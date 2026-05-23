"""Single-CoT SQL-generation baseline for Spider.

The baseline is a single BaseAgent that takes (question + schema_ddl)
and emits a SQL string. This is the floor that ADAS-synthesized
topologies must beat. The deliberately vanilla prompt also leaves
room for GEPA to add value on top of any topology that wraps it.

Cost accounting:
    * input_tokens / output_tokens are read from pydantic-ai's RunUsage.
    * cost_usd is computed via :func:`_estimate_cost_usd` against a
      provider-aware pricing table. DeepSeek V3.2 pricing per
      https://openrouter.ai/deepseek/deepseek-v3.2 (May 2026).

Use ``python -m orqest.benchmarks.spider.baseline --n 5`` for a smoke run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from .dataset import (
    SpiderQuestion,
    extract_schema_ddl,
    load_dev,
    stratified_sample,
)
from .harness import (
    BaselineRunResult,
    evaluate_candidate,
)

RESULTS_DIR = Path(__file__).resolve().parents[3] / "data" / "spider" / "results"

# Pricing table (USD per 1M tokens). Update when models change.
# Verify current numbers at https://openrouter.ai/models before treating
# the cost figures as authoritative.
_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_mtok, output_per_mtok)
    "openrouter:deepseek/deepseek-v3.2": (0.21, 0.79),
    "openrouter:deepseek/deepseek-chat-v3.1": (0.21, 0.79),
    "openrouter:deepseek/deepseek-r1": (0.50, 2.20),
    "anthropic:claude-haiku-4-5": (1.00, 5.00),
    "anthropic:claude-sonnet-4-6": (3.00, 15.00),
    "anthropic:claude-opus-4-7": (15.00, 75.00),
}


def _estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Best-effort USD cost; returns 0.0 if the model isn't in the pricing table."""
    rates = _PRICING.get(model_id)
    if rates is None:
        return 0.0
    in_per_mtok, out_per_mtok = rates
    return (input_tokens / 1_000_000.0) * in_per_mtok + (
        output_tokens / 1_000_000.0
    ) * out_per_mtok


class SQLOutput(BaseModel):
    """Structured output from the single-CoT agent."""

    model_config = ConfigDict(frozen=True)

    sql: str = Field(description="The SQL query that answers the question.")


_SYSTEM_PROMPT = """\
You are an expert SQL developer. Given a database schema and a natural-language
question, produce a single SQLite-compatible SQL query that answers the question.

Hard rules:
- Output only the SQL query in the `sql` field — no explanation, no markdown.
- Use only tables and columns present in the provided schema.
- Prefer simple JOINs over subqueries when both work.
- Use SQLite syntax. No PostgreSQL-only features.
- Do NOT terminate with a semicolon.
"""


class SingleCoTSQLAgent(BaseAgent[GlobalState, SQLOutput]):
    """Minimal one-shot SQL-generation agent — the v1 baseline floor.

    No tools, no refinement, no schema-linking step. This is intentionally
    the simplest possible thing that produces SQL, so we can quantify how
    much lift any topology adds.
    """

    async def _run_implementation(
        self, state: GlobalState, **kwargs
    ) -> SQLOutput:
        # Single-CoT prompt — state already carries (question, schema_ddl) text.
        message = state.get_latest_message("user") or ""
        result = await self.call_model(message, state)
        return result.output


def _format_user_prompt(q: SpiderQuestion, schema_ddl: str) -> str:
    return (
        f"### Database schema\n```sql\n{schema_ddl}\n```\n\n"
        f"### Question\n{q.question}\n\n"
        f"Produce the SQL query."
    )


@dataclass
class RunSummary:
    """Aggregate metrics for one baseline run."""

    model_id: str
    n_questions: int
    n_passed: int = 0
    n_candidate_error: int = 0
    n_gold_error: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_wall_s: float = 0.0
    per_db_passed: dict[str, int] = field(default_factory=dict)
    per_db_total: dict[str, int] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.n_passed / self.n_questions if self.n_questions else 0.0


async def run_baseline(
    *,
    model_id: str,
    api_key: str,
    n: int = 100,
    seed: int = 42,
    persist: bool = True,
    with_samples: bool = False,
) -> RunSummary:
    """Run the single-CoT baseline on a stratified sample of dev questions.

    Args:
        model_id: ``provider:model_id`` (e.g. ``openrouter:deepseek/deepseek-v3.2``).
        api_key: The provider API key.
        n: Number of questions to sample (stratified across the 20 dev DBs).
        seed: Sampling determinism.
        persist: Write results to ``data/spider/results/baseline_<...>.json``.
        with_samples: Include ~3 sample rows per table in the schema prompt.
    """
    dev = load_dev()
    questions = stratified_sample(dev, n=n, seed=seed)
    print(f"[baseline] model={model_id}  n={len(questions)}  seed={seed}")

    summary = RunSummary(model_id=model_id, n_questions=len(questions))
    per_question: list[BaselineRunResult] = []

    started = time.monotonic()
    for idx, q in enumerate(questions, start=1):
        schema_ddl = extract_schema_ddl(q.db_id, with_samples=with_samples)
        agent = SingleCoTSQLAgent(
            agent_name="spider_baseline",
            system_prompt=_SYSTEM_PROMPT,
            output_type=SQLOutput,
            model=model_id,
            api_key=api_key,
        )
        state = GlobalState()
        prompt = _format_user_prompt(q, schema_ddl)
        # GlobalState.app_messages is dual-layer (see CLAUDE.md); we don't
        # need history, just push the user message so the agent reads it.
        state.add_message(role="user", content=prompt)

        call_start = time.monotonic()
        in_tok = out_tok = 0
        cand_sql = ""
        try:
            result = await agent.call_model(prompt, state)
            cand_sql = result.output.sql.strip()
            usage = result.usage()
            in_tok = getattr(usage, "input_tokens", 0) or 0
            out_tok = getattr(usage, "output_tokens", 0) or 0
        except Exception as exc:  # noqa: BLE001
            cand_sql = ""
            print(f"  [{idx}/{len(questions)}] LLM error: {exc}")

        latency = (time.monotonic() - call_start) * 1000.0
        outcome = evaluate_candidate(q.db_id, cand_sql, q.query)
        cost = _estimate_cost_usd(model_id, in_tok, out_tok)

        summary.total_input_tokens += in_tok
        summary.total_output_tokens += out_tok
        summary.total_cost_usd += cost
        summary.per_db_total[q.db_id] = summary.per_db_total.get(q.db_id, 0) + 1
        if outcome.passed:
            summary.n_passed += 1
            summary.per_db_passed[q.db_id] = (
                summary.per_db_passed.get(q.db_id, 0) + 1
            )
        if outcome.candidate_error:
            summary.n_candidate_error += 1
        if outcome.gold_error:
            summary.n_gold_error += 1

        per_question.append(
            BaselineRunResult(
                db_id=q.db_id,
                question=q.question,
                gold_sql=q.query,
                candidate_sql=cand_sql,
                outcome=outcome,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
                latency_ms=latency,
            )
        )
        mark = "✓" if outcome.passed else "✗"
        print(
            f"  [{idx:3d}/{len(questions)}] {mark} {q.db_id:20s} "
            f"in={in_tok:5d} out={out_tok:4d} cost=${cost:.5f}"
        )

    summary.total_wall_s = time.monotonic() - started

    print(
        f"\n[baseline] accuracy={summary.accuracy:.3f}  "
        f"passed={summary.n_passed}/{summary.n_questions}  "
        f"cand_err={summary.n_candidate_error}  gold_err={summary.n_gold_error}  "
        f"total_cost=${summary.total_cost_usd:.4f}  "
        f"wall={summary.total_wall_s:.1f}s"
    )

    if persist:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out_path = RESULTS_DIR / f"baseline_{ts}_n{len(questions)}.json"
        out_path.write_text(
            json.dumps(
                {
                    "model_id": model_id,
                    "n_questions": summary.n_questions,
                    "n_passed": summary.n_passed,
                    "accuracy": summary.accuracy,
                    "n_candidate_error": summary.n_candidate_error,
                    "n_gold_error": summary.n_gold_error,
                    "total_input_tokens": summary.total_input_tokens,
                    "total_output_tokens": summary.total_output_tokens,
                    "total_cost_usd": summary.total_cost_usd,
                    "total_wall_s": summary.total_wall_s,
                    "per_db_passed": summary.per_db_passed,
                    "per_db_total": summary.per_db_total,
                    "per_question": [
                        json.loads(r.model_dump_json()) for r in per_question
                    ],
                },
                indent=2,
            )
        )
        print(f"[baseline] results → {out_path}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Spider single-CoT SQL baseline")
    parser.add_argument(
        "--n", type=int, default=100, help="Stratified sample size (default 100)"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Sampling seed"
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "SPIDER_TASK_MODEL", "openrouter:deepseek/deepseek-v3.2"
        ),
        help="provider:model_id (defaults to SPIDER_TASK_MODEL env or DeepSeek V3.2)",
    )
    parser.add_argument(
        "--with-samples",
        action="store_true",
        help="Include ~3 sample rows per table in the schema prompt (doubles size)",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Don't write results JSON (useful for quick smokes)",
    )
    args = parser.parse_args()

    load_dotenv()
    # Pick the right key for the model's provider prefix.
    provider = args.model.split(":", 1)[0]
    key_env = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
    }.get(provider)
    if not key_env:
        print(f"unknown provider {provider!r}; cannot pick API key env var")
        return 1
    api_key = os.environ.get(key_env)
    if not api_key:
        # Fall back to generic LLM_API_KEY (used by some examples)
        api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        print(f"missing API key — set {key_env} (or LLM_API_KEY) in .env")
        return 2

    asyncio.run(
        run_baseline(
            model_id=args.model,
            api_key=api_key,
            n=args.n,
            seed=args.seed,
            persist=not args.no_persist,
            with_samples=args.with_samples,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
