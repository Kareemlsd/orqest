"""GEPA prompt optimization on the ADAS-winning topology.

After Phase 3 (ADAS) selects a topology, this module runs Phase 4:
GEPA over the system prompts of the agents the topology references.
The topology stays fixed; only per-agent prompts mutate.

Why a dedicated evaluator: :class:`TopologyEvaluator` varies the topology
(reading it from the decoded genome). For prompt-only optimization we
want the opposite — fixed topology, varying prompts. The
:class:`PromptOnTopologyEvaluator` here holds the topology spec and
rebuilds a fresh agent_registry with the GEPA-proposed prompts per
evaluation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

from orqest.benchmarks.bird.adas.evaluator import _score_fn, bird_gold_examples
from orqest.benchmarks.bird.adas.registry import (
    build_agent_registry,
    build_callable_registry,
    default_prompts,
)
from orqest.benchmarks.bird.adas.state import SQLTaskState
from orqest.benchmarks.bird.dataset import load_dev, stratified_sample
from orqest.optimization.bundle import MetricBundle, MetricWeights
from orqest.optimization.config import OptimizationConfig
from orqest.optimization.evaluator import Evaluator, GoldExample
from orqest.optimization.genome import Genome, PromptGene
from orqest.optimization.runner import OptimizationRunner
from orqest.optimization.topology import _no_op_factory, unpack_topology_output
from orqest.orchestration.hydrate import topology_from_spec
from orqest.orchestration.spec import TopologySpec

RESULTS_DIR = Path(__file__).resolve().parents[4] / "data" / "bird" / "results"


class PromptOnTopologyEvaluator(Evaluator[SQLTaskState, SQLTaskState]):
    """Evaluate a FIXED topology with VARIABLE per-agent prompts.

    The decoded genome contains ``{agent_name: prompt_text}`` entries.
    Each evaluation rebuilds a fresh agent_registry using those prompts
    and hydrates the held topology against it.
    """

    def __init__(
        self,
        *,
        topology_spec: TopologySpec,
        task_model: str,
        task_api_key: str,
        callable_registry,
        active_agent_names: list[str],
    ) -> None:
        super().__init__(agent_factory=_no_op_factory, score_fn=_score_fn)
        self._topology_spec = topology_spec
        self._task_model = task_model
        self._task_api_key = task_api_key
        self._callable_registry = callable_registry
        self._active_agent_names = active_agent_names

    async def evaluate_one(
        self,
        decoded: dict[str, Any],
        example: GoldExample[SQLTaskState, SQLTaskState],
    ) -> MetricBundle:
        # Build prompts dict: only the ones GEPA proposed for active agents.
        prompts = {
            name: decoded[name]
            for name in self._active_agent_names
            if name in decoded and isinstance(decoded[name], str)
        }
        try:
            agent_registry = build_agent_registry(
                model_id=self._task_model,
                api_key=self._task_api_key,
                prompts=prompts,
            )
            topology = topology_from_spec(
                self._topology_spec,
                callable_registry=self._callable_registry,
                agent_registry=agent_registry,
            )
            start = time.monotonic()
            run_result = await topology.run(example.input)
            elapsed_ms = (time.monotonic() - start) * 1000.0
            output = unpack_topology_output(run_result)
            score = float(self._score_fn(output, example))
            return MetricBundle(
                accuracy=max(0.0, min(1.0, score)),
                latency_ms=elapsed_ms,
                raw={"n_agents": len(self._active_agent_names)},
            )
        except Exception as exc:  # noqa: BLE001
            return MetricBundle(
                accuracy=0.0,
                raw={"error": str(exc), "error_type": type(exc).__name__},
            )


def _agent_names_in_spec(spec: TopologySpec | dict | Any) -> set[str]:
    """Walk *spec* and collect every ``agent_name`` it references.

    Used to scope GEPA's mutation surface to only the agents the ADAS
    winner actually uses (optimizing prompts for unused agents is
    wasted compute).
    """
    if isinstance(spec, str):
        try:
            from pydantic import TypeAdapter
            spec = TypeAdapter(TopologySpec).validate_json(spec)
        except Exception:
            return set()
    names: set[str] = set()

    def walk(node: Any) -> None:
        if node is None:
            return
        kind = getattr(node, "kind", None)
        if kind == "agent_step":
            name = getattr(node, "agent_name", None)
            if name:
                names.add(name)
            return
        if kind == "function_step":
            return
        if kind == "pipeline":
            for entry in node.steps:
                walk(entry.operation)
            return
        if kind == "parallel":
            for s in node.steps:
                walk(s)
            return
        if kind == "router":
            for r in node.routes:
                walk(r.step)
            if hasattr(node, "fallback_step") and node.fallback_step is not None:
                walk(node.fallback_step)
            if isinstance(node.classifier, str):
                names.add(node.classifier)
            return
        if kind == "refinement_loop":
            walk(node.step)
            if isinstance(node.evaluator, str):
                names.add(node.evaluator)
            return

    walk(spec)
    return names


async def run_gepa(
    *,
    topology_json: str,
    task_model: str,
    task_api_key: str,
    reflection_model: str,
    reflection_api_key: str,
    n_train: int = 20,
    n_val: int = 20,
    max_metric_calls: int = 60,
    seed: int = 42,
    persist: bool = True,
) -> dict:
    """Run GEPA prompt optimization over the ADAS-winning topology.

    Args:
        topology_json: JSON-serialized TopologySpec (e.g., from ADAS result).
    """
    from pydantic import TypeAdapter

    spec = TypeAdapter(TopologySpec).validate_json(topology_json)
    active = sorted(_agent_names_in_spec(spec))
    defaults = default_prompts()
    print(f"[gepa] active agents in topology: {active}")

    if not active:
        raise RuntimeError(
            "GEPA cannot run — no agent_steps found in the topology"
        )

    # Build the genome — one PromptGene per active agent
    genes = [
        PromptGene(
            name=name,
            initial=defaults.get(name, ""),
            constraints=(
                "Keep the prompt focused on the agent's role within the "
                "SQL-domain pipeline (state input, state output). The "
                "agent's output_type is SQLTaskState — explicitly require "
                "the model to emit a complete SQLTaskState JSON."
            ),
        )
        for name in active
        if name in defaults
    ]
    genome = Genome(genes=genes)
    print(f"[gepa] genome: {len(genes)} prompt genes")

    # Sample train+val
    dev = load_dev()
    train_qs = stratified_sample(dev, n=n_train, seed=seed, by="difficulty")
    val_qs = stratified_sample(dev, n=n_val, seed=seed + 1, by="difficulty")
    train_ids = {q.question_id for q in train_qs}
    val_qs = [q for q in val_qs if q.question_id not in train_ids][:n_val]
    trainset = bird_gold_examples(train_qs)
    valset = bird_gold_examples(val_qs)

    callable_registry = build_callable_registry()
    evaluator = PromptOnTopologyEvaluator(
        topology_spec=spec,
        task_model=task_model,
        task_api_key=task_api_key,
        callable_registry=callable_registry,
        active_agent_names=active,
    )

    config = OptimizationConfig(
        max_metric_calls=max_metric_calls,
        reflection_model=reflection_model,
        minibatch_size=3,
        weights=MetricWeights(
            accuracy=10.0,
            cost_usd=-1.0,
            latency_ms=-0.0,
            confidence=0.0,
            robustness=0.0,
        ),
        seed=seed,
    )
    runner = OptimizationRunner(
        config, genome=genome, evaluator=evaluator, api_key=reflection_api_key
    )

    started = time.monotonic()
    result = await runner.optimize(trainset, valset=valset)
    wall = time.monotonic() - started

    summary = {
        "phase": "gepa",
        "task_model": task_model,
        "reflection_model": reflection_model,
        "active_agents": active,
        "best_score": result.best_score,
        "best_prompts": {
            k: v for k, v in result.best_candidate.items() if k in active
        },
        "wall_s": wall,
    }

    if persist:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        out = RESULTS_DIR / f"gepa_{ts}.json"
        out.write_text(json.dumps(summary, indent=2))
        print(f"[gepa] result → {out}")
        summary["persisted_path"] = str(out)

    print(f"[gepa] DONE — best_score={result.best_score:.3f}  wall={wall:.1f}s")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="GEPA prompt opt on ADAS winner")
    parser.add_argument("--adas-result", required=True, help="Path to ADAS result JSON")
    parser.add_argument("--n-train", type=int, default=20)
    parser.add_argument("--n-val", type=int, default=20)
    parser.add_argument("--max-metric-calls", type=int, default=60)
    parser.add_argument(
        "--task-model",
        default=os.environ.get(
            "SPIDER_TASK_MODEL", "openrouter:deepseek/deepseek-v3.2"
        ),
    )
    parser.add_argument(
        "--reflection-model",
        default=os.environ.get(
            "SPIDER_META_MODEL", "openrouter:deepseek/deepseek-r1"
        ),
    )
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    adas_payload = json.loads(Path(args.adas_result).read_text())
    topology_json = adas_payload["best_topology"]

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
            raise SystemExit(f"missing {env}")
        return k

    asyncio.run(
        run_gepa(
            topology_json=topology_json,
            task_model=args.task_model,
            task_api_key=_key_for(args.task_model),
            reflection_model=args.reflection_model,
            reflection_api_key=_key_for(args.reflection_model),
            n_train=args.n_train,
            n_val=args.n_val,
            max_metric_calls=args.max_metric_calls,
            persist=not args.no_persist,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
