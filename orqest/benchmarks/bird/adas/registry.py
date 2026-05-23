"""Primitive registry — agents + callables ADAS composes over.

The meta-agent in :class:`MetaAgentSearch` can only reference names from
these registries. That's the load-bearing safety property: there's no
``eval``/``exec``, no code emission, only graph composition over a
known vocabulary.

Vocabulary exposed to the meta-agent:

agent_registry:
    * ``schema_linker`` — filters the schema to relevant tables/columns
    * ``question_classifier`` — labels complexity (simple/moderate/challenging)
    * ``decomposer`` — breaks complex questions into sub-questions
    * ``sql_generator`` — generates a candidate SQL
    * ``sql_critic`` — semantic check on candidate SQL before execution
    * ``error_explainer`` — reads execution_error → refinement_hint
    * ``voter`` — picks best from multiple candidate_sqls
    * ``terminal_finalizer`` — commits final_sql from the latest candidate

callable_registry:
    * ``execute_sql_call`` — runs state.candidate_sqls[-1] against the DB,
      sets state.execution_error on failure
    * ``is_complex`` — boolean predicate on state.complexity
    * ``has_error`` — boolean predicate on state.execution_error
    * ``promote_last_candidate`` — sets state.final_sql ← state.candidate_sqls[-1]

These are deliberately the smallest viable vocabulary. The meta-agent
will combine them via Pipeline / Parallel / Router / RefinementLoop.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.benchmarks.bird.adas.state import SQLTaskState
from orqest.benchmarks.bird.dataset import db_path
from orqest.orchestration.hydrate import CallableRegistry


# ── Agent base class ─────────────────────────────────────────────────


class _SQLDomainAgent(BaseAgent[GlobalState, SQLTaskState]):
    """All SQL-domain agents share this implementation.

    The agent reads the prior :class:`SQLTaskState` from the user message
    (JSON-serialized by :class:`AgentStep`), then emits a complete
    updated state. The system prompt is the only thing that varies
    between agents — that's exactly what GEPA later optimizes.
    """

    async def _run_implementation(
        self, state: GlobalState, **kwargs: Any
    ) -> SQLTaskState:
        message = state.get_latest_message("user") or ""
        result = await self.call_model(message, state)
        return result.output


# ── Per-agent prompts (the GEPA optimization surface) ────────────────


SCHEMA_LINKER_PROMPT = """\
You are a schema-linking expert for SQL generation.

Read the SQLTaskState JSON in the user message. Identify the subset of
tables and columns in `full_schema_ddl` that are relevant to answering
`question` (using `evidence` as a hint when present).

Emit a complete updated SQLTaskState where:
- `filtered_schema_ddl` is the CREATE statements for ONLY the relevant
  tables, with irrelevant columns optionally removed for clarity.
- All other fields are passed through unchanged.

Be aggressive about filtering — fewer tables/columns means a cleaner
SQL-generation prompt. If you can't decide, include the table.
"""

QUESTION_CLASSIFIER_PROMPT = """\
You are a SQL-complexity classifier.

Read the SQLTaskState JSON. Set `complexity` to one of:
- "simple" — single table, no JOINs, simple WHERE.
- "moderate" — 2-3 table JOIN, basic aggregation, simple subquery.
- "challenging" — multiple JOINs, nested subqueries, window functions, CTEs.

Pass through all other fields unchanged.
"""

DECOMPOSER_PROMPT = """\
You are a question-decomposition expert.

Read the SQLTaskState JSON. If the question is complex (multi-step,
multi-aggregate, or requires intermediate results), populate
`sub_questions` with the natural-language sub-questions whose individual
answers can be combined into the final SQL. Order matters — later
sub-questions may depend on earlier ones.

If the question is simple enough to answer directly, leave
`sub_questions` empty.

Pass through all other fields unchanged.
"""

SQL_GENERATOR_PROMPT = """\
You are an expert SQLite SQL author working with real-world dirty schemas.

Read the SQLTaskState JSON. Generate a single SQLite-compatible SQL query
that answers `question`. Use:
- `filtered_schema_ddl` if present, otherwise `full_schema_ddl`.
- `evidence` for domain definitions.
- `sub_questions` to structure the SQL (CTEs / nested SELECTs).
- `refinement_hint` if present — it's a repair hint from a prior error.

Append your candidate SQL to `candidate_sqls` (do not replace existing
entries). Set `final_sql` to the new candidate as well (this lets you
serve as a terminal agent if no further refinement is wired).

Quote unusual column names with backticks or double quotes. SQLite
syntax only. Do NOT terminate with a semicolon.

Pass through all other fields unchanged.
"""

SQL_CRITIC_PROMPT = """\
You are a SQL semantic reviewer.

Read the SQLTaskState JSON. Inspect the LAST entry in `candidate_sqls`
(or `final_sql` if `candidate_sqls` is empty). Check for:
- Logical mistakes (wrong aggregation, missing GROUP BY, JOIN on
  wrong columns, etc.).
- Reference to columns/tables not in the schema.
- Likely value mismatches (e.g., comparing string columns to integers).

If the SQL is correct, set `critique_passed=true` and pass through.
If the SQL is wrong, set `critique_passed=false`, append a corrected
SQL to `candidate_sqls`, and update `final_sql` to the corrected SQL.

Pass through all other fields unchanged.
"""

ERROR_EXPLAINER_PROMPT = """\
You are a SQLite error diagnostician.

Read the SQLTaskState JSON. If `execution_error` is present, write a
short natural-language repair hint into `refinement_hint` explaining
what likely went wrong and how to fix the SQL on the next attempt
(e.g., "column 'state' doesn't exist; the schema uses 'State_Abbr'").

If no `execution_error`, leave `refinement_hint` unset (or null).

Pass through all other fields unchanged.
"""

VOTER_PROMPT = """\
You are a SQL candidate-voter.

Read the SQLTaskState JSON. Among the entries in `candidate_sqls`, pick
the single best one that most likely answers `question`. Set `final_sql`
to that candidate verbatim.

Pass through all other fields unchanged.
"""

TERMINAL_FINALIZER_PROMPT = """\
You are a terminal commit agent.

Read the SQLTaskState JSON. If `final_sql` is unset, set it to the last
entry in `candidate_sqls` (or any other available SQL field).

Pass through all other fields unchanged.
"""


# ── Agent registry builder ──────────────────────────────────────────


def build_agent_registry(
    *,
    model_id: str,
    api_key: str,
    prompts: dict[str, str] | None = None,
) -> dict[str, Callable[[], BaseAgent[Any, Any]]]:
    """Construct the agent-name → factory map ADAS draws from.

    Args:
        model_id: ``provider:model_id`` for ALL agents in the topology.
            Single-model is the v1 simplification — GEPA can per-agent
            override later.
        api_key: The provider API key.
        prompts: Optional override map ``{agent_name: system_prompt_text}``.
            When set, replaces the default prompt for that agent. Used by
            GEPA: apply_result writes optimized prompts here, then a fresh
            agent_registry rebuilds.
    """
    p = dict(_DEFAULTS)
    if prompts:
        p.update(prompts)

    def _factory(name: str, prompt: str) -> Callable[[], BaseAgent[Any, Any]]:
        def _build() -> BaseAgent[Any, Any]:
            return _SQLDomainAgent(
                agent_name=name,
                system_prompt=prompt,
                output_type=SQLTaskState,
                model=model_id,
                api_key=api_key,
            )

        return _build

    return {name: _factory(name, prompt) for name, prompt in p.items()}


_DEFAULTS: dict[str, str] = {
    "schema_linker": SCHEMA_LINKER_PROMPT,
    "question_classifier": QUESTION_CLASSIFIER_PROMPT,
    "decomposer": DECOMPOSER_PROMPT,
    "sql_generator": SQL_GENERATOR_PROMPT,
    "sql_critic": SQL_CRITIC_PROMPT,
    "error_explainer": ERROR_EXPLAINER_PROMPT,
    "voter": VOTER_PROMPT,
    "terminal_finalizer": TERMINAL_FINALIZER_PROMPT,
}


def default_prompts() -> dict[str, str]:
    """The shipped per-agent system prompts. Surface for GEPA to mutate."""
    return dict(_DEFAULTS)


# ── Callable registry builder ───────────────────────────────────────


async def _execute_sql_call(state: SQLTaskState) -> SQLTaskState:
    """Run the LAST candidate SQL against the DB; populate state.execution_error.

    On success, leaves execution_error as None. On failure, sets it to the
    SQLite error message. Does NOT modify final_sql — that's the topology's
    job (e.g. via a RefinementLoop or a Pipeline followup).
    """
    sql = (state.candidate_sqls[-1] if state.candidate_sqls else state.final_sql) or ""
    if not sql:
        return state.model_copy(update={"execution_error": "no candidate SQL to execute"})
    path = db_path(state.db_id)
    if not path.exists():
        return state.model_copy(update={"execution_error": f"db not found: {path}"})
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
        con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    except sqlite3.Error as exc:
        return state.model_copy(update={"execution_error": f"connect failed: {exc}"})
    try:
        con.execute(sql).fetchall()
        return state.model_copy(update={"execution_error": None})
    except sqlite3.Error as exc:
        return state.model_copy(
            update={"execution_error": f"{type(exc).__name__}: {exc}"}
        )
    except Exception as exc:  # noqa: BLE001
        return state.model_copy(
            update={"execution_error": f"{type(exc).__name__}: {exc}"}
        )
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass


def _is_complex(state: SQLTaskState) -> bool:
    """Router predicate: True when complexity is moderate or challenging."""
    return (state.complexity or "").lower() in {"moderate", "challenging"}


def _has_error(state: SQLTaskState) -> bool:
    """Router/loop predicate: True when execution_error is set."""
    return bool(state.execution_error)


def _promote_last_candidate(state: SQLTaskState) -> SQLTaskState:
    """State-updater: copy last candidate_sqls entry into final_sql."""
    if state.candidate_sqls:
        return state.model_copy(update={"final_sql": state.candidate_sqls[-1]})
    return state


def build_callable_registry() -> CallableRegistry:
    """The callable-name → fn map ADAS draws from for FunctionStep + predicates."""
    reg = CallableRegistry()
    reg.register("execute_sql_call", _execute_sql_call)
    reg.register("is_complex", _is_complex)
    reg.register("has_error", _has_error)
    reg.register("promote_last_candidate", _promote_last_candidate)
    return reg


__all__ = [
    "build_agent_registry",
    "build_callable_registry",
    "default_prompts",
]
