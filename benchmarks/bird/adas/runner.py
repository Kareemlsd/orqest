"""End-to-end runner for ADAS + GEPA on BIRD-dev.

Drives the two-phase Orqest-native optimization:

    Phase 3 (ADAS topology evolution):
        orqest.optimization.meta_agent.MetaAgentSearch.run(
            trainset, valset
        )
        → OptimizationResult (winning topology + scores + history)

    Phase 4 (GEPA prompt optimization on winner):
        orqest.optimization.runner.OptimizationRunner.optimize(
            trainset, valset
        )
        → OptimizationResult (optimized prompts for the topology's agents)

Both phases use the same BIRD evaluator + the same gold-example shape.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from .evaluator import (
    BIRDTopologyEvaluator,
    bird_gold_examples,
)
from .registry import (
    build_agent_registry,
    build_callable_registry,
)
from .seed import seed_topology
from ..dataset import load_dev, stratified_sample
from orqest.observability.events import AgentEvent, EventBus
from orqest.optimization.bundle import MetricWeights
from orqest.optimization.meta_agent import MetaAgentConfig, MetaAgentSearch
from orqest.optimization.topology import TopologyGene


def _wire_progress_bus() -> EventBus:
    """A live-progress bus that prints every meta_agent event to stdout.

    The subscriber is sync so output appears immediately, even when the
    main loop is mid-network-IO. Subscribers run inside `EventBus.emit`
    via `asyncio.create_task`, so they don't block the search loop.
    """
    bus = EventBus()

    def _on_iteration(event: AgentEvent) -> None:
        d = event.data
        phase = d.get("phase", "?")
        gen = d.get("generation", "?")
        score = d.get("score", 0.0)
        size = d.get("archive_size", 0)
        ts = time.strftime("%H:%M:%S")
        print(
            f"[{ts}] meta_agent.iteration: phase={phase} gen={gen} "
            f"score={score:.3f} archive={size}",
            flush=True,
        )

    def _on_debug(event: AgentEvent) -> None:
        d = event.data
        ts = time.strftime("%H:%M:%S")
        print(
            f"[{ts}] meta_agent.debug_retry: gen={d.get('generation','?')} "
            f"retry={d.get('retry','?')} "
            f"{d.get('error_type','?')}: {d.get('error','')[:200]}",
            flush=True,
        )

    bus.subscribe("meta_agent.iteration_completed", _on_iteration)
    bus.subscribe("meta_agent.debug_retry", _on_debug)
    return bus

RESULTS_DIR = Path(__file__).resolve().parents[4] / "data" / "bird" / "results"


async def run_adas(
    *,
    task_model: str,
    task_api_key: str,
    meta_model: str,
    meta_api_key: str,
    n_train: int = 30,
    n_val: int = 30,
    n_generations: int = 20,
    minibatch_size: int = 8,
    reflexion_passes: int = 1,
    seed: int = 42,
    persist: bool = True,
) -> dict:
    """Run Phase 3 — ADAS topology evolution on BIRD-dev.

    Returns a dict with the winning topology spec, the score history,
    and the persisted JSON path (when persist=True). Total LLM cost
    bounded by ``n_generations * (minibatch_size + 1 reflexion) * task_calls``
    plus the meta-agent's reflection calls.
    """
    # Sample train + val. Stratify by difficulty so each minibatch contains
    # questions across simple/moderate/challenging.
    dev = load_dev()
    train_qs = stratified_sample(dev, n=n_train, seed=seed, by="difficulty")
    val_qs = stratified_sample(
        dev, n=n_val, seed=seed + 1, by="difficulty"
    )
    # Make sure train and val don't overlap on question_id
    train_ids = {q.question_id for q in train_qs}
    val_qs = [q for q in val_qs if q.question_id not in train_ids][:n_val]

    print(
        f"[adas] train={len(train_qs)}  val={len(val_qs)}  "
        f"gens={n_generations}  minibatch={minibatch_size}  "
        f"task_model={task_model}  meta_model={meta_model}"
    )

    trainset = bird_gold_examples(train_qs)
    valset = bird_gold_examples(val_qs)

    agent_registry = build_agent_registry(
        model_id=task_model, api_key=task_api_key
    )
    callable_registry = build_callable_registry()

    evaluator = BIRDTopologyEvaluator(
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )

    gene = TopologyGene(
        name="main",
        initial=seed_topology(),
        constraints=(
            "DOMAIN: Text-to-SQL on BIRD-dev. State flows as SQLTaskState.\n"
            "\n"
            "GOAL: The topology MUST populate state.final_sql. If your "
            "terminal output's final_sql is empty, the score is 0.\n"
            "\n"
            "ALLOWED PRIMITIVES (v1 — anything else fails validation):\n"
            "  * PipelineSpec (sequential composition)\n"
            "  * ParallelSpec (concurrent, with merge='first_wins' OR "
            "    followed by a voter agent step)\n"
            "  * AgentStepSpec wrapping an agent_registry name\n"
            "  DO NOT emit RouterSpec or RefinementLoopSpec — they require "
            "  output shapes our agents don't produce.\n"
            "\n"
            "EXACT agent_registry names (use VERBATIM — case-sensitive — "
            "no other names exist):\n"
            "  schema_linker         — filter schema to relevant tables\n"
            "  question_classifier   — set state.complexity\n"
            "  decomposer            — break complex Q into sub-questions\n"
            "  sql_generator         — emit SQL into candidate_sqls + final_sql\n"
            "  sql_critic            — review the last candidate, refine if wrong\n"
            "  error_explainer       — read execution_error → refinement_hint\n"
            "  voter                 — pick best among candidate_sqls\n"
            "  terminal_finalizer    — copy last candidate into final_sql\n"
            "\n"
            "CALLABLES (rarely needed for v1 since we only use Pipeline+Parallel):\n"
            "  execute_sql_call, is_complex, has_error, promote_last_candidate\n"
            "\n"
            "TWO VALID EXAMPLE TOPOLOGIES:\n"
            "\n"
            "Example A — schema-linked, parallel-vote:\n"
            "{\n"
            "  \"kind\": \"pipeline\", \"name\": \"linked_parallel_vote\",\n"
            "  \"steps\": [\n"
            "    {\"operation\": {\"kind\": \"agent_step\", "
            "\"agent_name\": \"schema_linker\"}},\n"
            "    {\"operation\": {\"kind\": \"parallel\", \"merge\": "
            "\"collect_all\", \"steps\": [\n"
            "       {\"kind\": \"agent_step\", \"agent_name\": \"sql_generator\"},\n"
            "       {\"kind\": \"agent_step\", \"agent_name\": \"sql_generator\"},\n"
            "       {\"kind\": \"agent_step\", \"agent_name\": \"sql_generator\"}\n"
            "    ]}},\n"
            "    {\"operation\": {\"kind\": \"agent_step\", "
            "\"agent_name\": \"voter\"}},\n"
            "    {\"operation\": {\"kind\": \"agent_step\", "
            "\"agent_name\": \"terminal_finalizer\"}}\n"
            "  ]\n"
            "}\n"
            "\n"
            "Example B — decompose then generate with critique:\n"
            "{\n"
            "  \"kind\": \"pipeline\", \"name\": \"decompose_generate_critique\",\n"
            "  \"steps\": [\n"
            "    {\"operation\": {\"kind\": \"agent_step\", "
            "\"agent_name\": \"schema_linker\"}},\n"
            "    {\"operation\": {\"kind\": \"agent_step\", "
            "\"agent_name\": \"decomposer\"}},\n"
            "    {\"operation\": {\"kind\": \"agent_step\", "
            "\"agent_name\": \"sql_generator\"}},\n"
            "    {\"operation\": {\"kind\": \"agent_step\", "
            "\"agent_name\": \"sql_critic\"}},\n"
            "    {\"operation\": {\"kind\": \"agent_step\", "
            "\"agent_name\": \"terminal_finalizer\"}}\n"
            "  ]\n"
            "}\n"
            "\n"
            "SIZE BUDGET: total agent_step count ≤ 6. The metric bundle's "
            "cost weight penalizes spending tokens without lifting accuracy.\n"
            "\n"
            "DIVERSITY: Each generation should be STRUCTURALLY different "
            "from the archive — not just renamed steps."
        ),
        allowed_step_kinds=("agent_step",),  # No function_steps in v1
        max_depth=3,                          # Pipeline + Parallel only → depth 2 max
    )

    config = MetaAgentConfig(
        n_generations=n_generations,
        archive_strategy="top_k",
        archive_size=5,
        reflexion_passes=reflexion_passes,
        debug_max=3,
        minibatch_size=minibatch_size,
        seed=seed,
        weights=MetricWeights(
            accuracy=10.0,
            cost_usd=-2.0,
            latency_ms=-0.000001,
            confidence=0.0,
            robustness=0.0,
        ),
    )

    bus = _wire_progress_bus()
    search = MetaAgentSearch(
        config,
        gene=gene,
        evaluator=evaluator,
        meta_agent_model=meta_model,
        api_key=meta_api_key,
        bus=bus,
    )

    started = time.monotonic()
    result = await search.run(trainset, valset=valset)
    wall = time.monotonic() - started

    summary = {
        "phase": "adas",
        "task_model": task_model,
        "meta_model": meta_model,
        "n_train": len(trainset),
        "n_val": len(valset),
        "n_generations": n_generations,
        "minibatch_size": minibatch_size,
        "best_score": result.best_score,
        "wall_s": wall,
        "best_topology": result.best_candidate.get("main"),
        "history": result.history,
    }

    if persist:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out = RESULTS_DIR / f"adas_{ts}_gens{n_generations}.json"
        out.write_text(json.dumps(summary, indent=2))
        print(f"[adas] result → {out}")
        summary["persisted_path"] = str(out)

    print(
        f"[adas] DONE — best_score={result.best_score:.3f}  "
        f"wall={wall:.1f}s"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="ADAS topology evolution on BIRD-dev")
    parser.add_argument("--n-train", type=int, default=30)
    parser.add_argument("--n-val", type=int, default=30)
    parser.add_argument("--n-generations", type=int, default=20)
    parser.add_argument("--minibatch-size", type=int, default=8)
    parser.add_argument("--reflexion-passes", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--task-model",
        default=os.environ.get(
            "SPIDER_TASK_MODEL", "openrouter:deepseek/deepseek-v3.2"
        ),
    )
    parser.add_argument(
        "--meta-model",
        # Default: same as task model. R1 reasoning model can hang via
        # OpenRouter + pydantic-ai structured output (2026-05-15 finding).
        # Use V3.2 for both unless you explicitly switch.
        default=os.environ.get(
            "SPIDER_META_MODEL", "openrouter:deepseek/deepseek-v3.2"
        ),
    )
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    load_dotenv()

    def _key_for(model: str) -> str:
        provider = model.split(":", 1)[0]
        env_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GEMINI_API_KEY",
        }
        env = env_map.get(provider)
        if env is None:
            raise SystemExit(f"unknown provider {provider!r}")
        k = os.environ.get(env) or os.environ.get("LLM_API_KEY")
        if not k:
            raise SystemExit(f"missing {env} for {model}")
        return k

    asyncio.run(
        run_adas(
            task_model=args.task_model,
            task_api_key=_key_for(args.task_model),
            meta_model=args.meta_model,
            meta_api_key=_key_for(args.meta_model),
            n_train=args.n_train,
            n_val=args.n_val,
            n_generations=args.n_generations,
            minibatch_size=args.minibatch_size,
            reflexion_passes=args.reflexion_passes,
            seed=args.seed,
            persist=not args.no_persist,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
