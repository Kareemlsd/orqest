"""Single-CoT SQL-generation baseline for BIRD-dev.

Mirrors :mod:`orqest.benchmarks.spider.baseline` but adapted for BIRD's
record shape (``SQL`` instead of ``query``, plus an ``evidence`` hint
that BIRD's design assumes is given to the model).

This is the floor for ADAS/GEPA-synthesized topologies. Vanilla prompt
on purpose — keeps room for the optimizer to add value.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.benchmarks.bird.dataset import (
    BIRDQuestion,
    db_path,
    extract_schema_ddl,
    load_dev,
    stratified_sample,
)
from orqest.benchmarks.spider.harness import EvalOutcome, rows_match

RESULTS_DIR = Path(__file__).resolve().parents[3] / "data" / "bird" / "results"

_PRICING: dict[str, tuple[float, float]] = {
    "openrouter:deepseek/deepseek-v3.2": (0.21, 0.79),
    "openrouter:deepseek/deepseek-chat-v3.1": (0.21, 0.79),
    "openrouter:deepseek/deepseek-r1": (0.50, 2.20),
    "anthropic:claude-haiku-4-5": (1.00, 5.00),
    "anthropic:claude-sonnet-4-6": (3.00, 15.00),
    "anthropic:claude-opus-4-7": (15.00, 75.00),
}


def _estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    rates = _PRICING.get(model_id)
    if rates is None:
        return 0.0
    in_per, out_per = rates
    return (input_tokens / 1_000_000.0) * in_per + (
        output_tokens / 1_000_000.0
    ) * out_per


class SQLOutput(BaseModel):
    """Structured output: just the SQL string."""

    model_config = ConfigDict(frozen=True)
    sql: str = Field(description="The SQL query that answers the question.")


_SYSTEM_PROMPT = """\
You are an expert SQL developer working with real-world dirty schemas.

Given a database schema, a natural-language question, and a hint
("evidence") clarifying the question, produce a single SQLite-compatible
SQL query that answers the question.

Hard rules:
- Output only the SQL query in the `sql` field — no explanation, no markdown.
- Use only tables and columns present in the provided schema.
- The schema may have unusual column names (spaces, mixed case, special
  characters) — quote them with backticks or double-quotes as needed.
- Use SQLite syntax. No PostgreSQL-only features.
- Apply the evidence hint when given — it usually contains domain-specific
  definitions you cannot guess from column names alone.
- Do NOT terminate with a semicolon.
"""


class SingleCoTBIRDAgent(BaseAgent[GlobalState, SQLOutput]):
    """Minimal one-shot SQL agent — the v1 BIRD baseline floor."""

    async def _run_implementation(self, state: GlobalState, **kwargs) -> SQLOutput:
        message = state.get_latest_message("user") or ""
        result = await self.call_model(message, state)
        return result.output


def _format_user_prompt(q: BIRDQuestion, schema_ddl: str) -> str:
    evidence = q.evidence or "(no evidence provided)"
    return (
        f"### Database schema\n```sql\n{schema_ddl}\n```\n\n"
        f"### Evidence (definitions / hints)\n{evidence}\n\n"
        f"### Question\n{q.question}\n\n"
        f"Produce the SQL query."
    )


def _execute_bird_sql(
    db_id: str,
    sql: str,
    *,
    timeout_s: float = 30.0,
) -> tuple[list[tuple] | None, str | None]:
    """BIRD's DBs are larger; we use a longer timeout than Spider."""
    path = db_path(db_id)
    if not path.exists():
        return None, f"db not found: {path}"
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout_s)
        con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    except sqlite3.Error as exc:
        return None, f"connect failed: {exc}"
    try:
        rows = con.execute(sql).fetchall()
        return rows, None
    except sqlite3.Error as exc:
        return None, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass


def evaluate_bird_candidate(q: BIRDQuestion, candidate_sql: str) -> EvalOutcome:
    """Execution-accuracy verdict for a BIRD example."""
    import re

    order_sensitive = bool(re.search(r"\border\s+by\b", q.SQL, re.IGNORECASE))
    t0 = time.monotonic()
    cand_rows, cand_err = _execute_bird_sql(q.db_id, candidate_sql)
    gold_rows, gold_err = _execute_bird_sql(q.db_id, q.SQL)
    elapsed = (time.monotonic() - t0) * 1000.0

    if gold_err or cand_err:
        passed = False
    else:
        passed = rows_match(cand_rows, gold_rows, order_sensitive=order_sensitive)

    return EvalOutcome(
        passed=passed,
        candidate_rows=len(cand_rows) if cand_rows is not None else 0,
        gold_rows=len(gold_rows) if gold_rows is not None else 0,
        candidate_error=cand_err,
        gold_error=gold_err,
        duration_ms=elapsed,
        order_sensitive=order_sensitive,
    )


@dataclass
class RunSummary:
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
    per_difficulty_passed: dict[str, int] = field(default_factory=dict)
    per_difficulty_total: dict[str, int] = field(default_factory=dict)

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
    stratify_by: str = "difficulty",
) -> RunSummary:
    """Run BIRD single-CoT baseline on a stratified sample."""
    dev = load_dev()
    questions = stratified_sample(dev, n=n, seed=seed, by=stratify_by)
    print(
        f"[bird-baseline] model={model_id}  n={len(questions)}  seed={seed}  "
        f"stratify_by={stratify_by}"
    )

    summary = RunSummary(model_id=model_id, n_questions=len(questions))
    per_question = []

    started = time.monotonic()
    for idx, q in enumerate(questions, start=1):
        schema_ddl = extract_schema_ddl(q.db_id, with_samples=with_samples)
        agent = SingleCoTBIRDAgent(
            agent_name="bird_baseline",
            system_prompt=_SYSTEM_PROMPT,
            output_type=SQLOutput,
            model=model_id,
            api_key=api_key,
        )
        state = GlobalState()
        prompt = _format_user_prompt(q, schema_ddl)
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
            print(f"  [{idx}/{len(questions)}] LLM error: {exc}")

        latency = (time.monotonic() - call_start) * 1000.0
        outcome = evaluate_bird_candidate(q, cand_sql)
        cost = _estimate_cost_usd(model_id, in_tok, out_tok)

        summary.total_input_tokens += in_tok
        summary.total_output_tokens += out_tok
        summary.total_cost_usd += cost
        summary.per_db_total[q.db_id] = summary.per_db_total.get(q.db_id, 0) + 1
        summary.per_difficulty_total[q.difficulty] = (
            summary.per_difficulty_total.get(q.difficulty, 0) + 1
        )
        if outcome.passed:
            summary.n_passed += 1
            summary.per_db_passed[q.db_id] = (
                summary.per_db_passed.get(q.db_id, 0) + 1
            )
            summary.per_difficulty_passed[q.difficulty] = (
                summary.per_difficulty_passed.get(q.difficulty, 0) + 1
            )
        if outcome.candidate_error:
            summary.n_candidate_error += 1
        if outcome.gold_error:
            summary.n_gold_error += 1

        per_question.append(
            {
                "question_id": q.question_id,
                "db_id": q.db_id,
                "difficulty": q.difficulty,
                "question": q.question,
                "evidence": q.evidence,
                "gold_sql": q.SQL,
                "candidate_sql": cand_sql,
                "outcome": json.loads(outcome.model_dump_json()),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": cost,
                "latency_ms": latency,
            }
        )
        mark = "✓" if outcome.passed else "✗"
        print(
            f"  [{idx:3d}/{len(questions)}] {mark} {q.db_id[:22]:22s} "
            f"diff={q.difficulty[:6]:6s} in={in_tok:5d} out={out_tok:4d} "
            f"cost=${cost:.5f}"
        )

    summary.total_wall_s = time.monotonic() - started

    print(
        f"\n[bird-baseline] accuracy={summary.accuracy:.3f}  "
        f"passed={summary.n_passed}/{summary.n_questions}  "
        f"cand_err={summary.n_candidate_error}  gold_err={summary.n_gold_error}  "
        f"total_cost=${summary.total_cost_usd:.4f}  "
        f"wall={summary.total_wall_s:.1f}s"
    )
    print(f"  per-difficulty: {summary.per_difficulty_passed}/{summary.per_difficulty_total}")

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
                    "per_difficulty_passed": summary.per_difficulty_passed,
                    "per_difficulty_total": summary.per_difficulty_total,
                    "per_question": per_question,
                },
                indent=2,
            )
        )
        print(f"[bird-baseline] results → {out_path}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="BIRD-dev single-CoT SQL baseline")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "SPIDER_TASK_MODEL", "openrouter:deepseek/deepseek-v3.2"
        ),
    )
    parser.add_argument("--with-samples", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument(
        "--stratify-by", choices=["db_id", "difficulty"], default="difficulty"
    )
    args = parser.parse_args()

    load_dotenv()
    provider = args.model.split(":", 1)[0]
    key_env = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
    }.get(provider)
    api_key = os.environ.get(key_env) if key_env else None
    if not api_key:
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
            stratify_by=args.stratify_by,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
