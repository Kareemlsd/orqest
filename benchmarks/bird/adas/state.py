"""The uniform state object every BIRD-domain agent consumes and produces.

All agents in the BIRD :func:`build_agent_registry` accept and return a
:class:`SQLTaskState`. This uniform input/output contract is what lets
the ADAS meta-agent freely compose them via Pipeline / Parallel / Router
/ RefinementLoop without any per-agent shape adapters.

Each agent reads the current state, focuses on the fields the topology
positioned it to populate (per its system prompt), and emits an updated
state — fields it didn't touch pass through unchanged.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SQLTaskState(BaseModel):
    """Per-question state that flows through every topology node.

    Original input fields (set once at topology entry):
        question, db_id, evidence, full_schema_ddl

    Decorated fields (populated by upstream agents):
        filtered_schema_ddl, sub_questions, complexity, candidate_sqls,
        execution_error, refinement_hint, critique_passed

    Terminal field (the topology's final output):
        final_sql — what the evaluator extracts and runs against the DB.

    Every agent's ``output_type`` is :class:`SQLTaskState`. The pipeline
    flow IS the state — upstream agents enrich it; the terminal agent
    decides ``final_sql``.
    """

    model_config = ConfigDict(frozen=False)  # mutable; agents return updated copies

    # ── Original inputs ──────────────────────────────────────────────
    question: str = Field(description="The natural-language question to answer.")
    db_id: str = Field(description="The target database identifier.")
    evidence: str | None = Field(
        default=None,
        description="BIRD's per-question hint with domain definitions.",
    )
    full_schema_ddl: str = Field(
        description="Complete schema CREATE statements for the DB."
    )

    # ── Decorated fields (set by upstream agents) ────────────────────
    filtered_schema_ddl: str | None = Field(
        default=None,
        description=(
            "Schema restricted to the tables/columns relevant to this "
            "question — set by schema_linker. Downstream agents should "
            "prefer this when present; fall back to full_schema_ddl otherwise."
        ),
    )
    sub_questions: list[str] = Field(
        default_factory=list,
        description=(
            "Decomposed sub-questions — set by decomposer. Each can be "
            "answered with a simpler SQL whose results feed the final SQL."
        ),
    )
    complexity: str | None = Field(
        default=None,
        description=(
            "Question complexity label set by question_classifier — one "
            "of 'simple' | 'moderate' | 'challenging'."
        ),
    )
    candidate_sqls: list[str] = Field(
        default_factory=list,
        description=(
            "Candidate SQL queries — set by sql_generator (1 per call) "
            "or multiple parallel generators. Voter picks the best."
        ),
    )
    execution_error: str | None = Field(
        default=None,
        description=(
            "SQLite error message from a prior execution attempt — set "
            "by execute_sql callable. Triggers refinement loops."
        ),
    )
    refinement_hint: str | None = Field(
        default=None,
        description=(
            "Natural-language repair hint — set by error_explainer "
            "reading execution_error."
        ),
    )
    critique_passed: bool | None = Field(
        default=None,
        description=(
            "Whether sql_critic accepted the candidate SQL before "
            "execution. None = not yet reviewed."
        ),
    )

    # ── Terminal output ──────────────────────────────────────────────
    final_sql: str | None = Field(
        default=None,
        description=(
            "The SQL the topology commits to. Set by the terminal "
            "agent in the topology. The evaluator extracts this and "
            "runs it on the DB for execution-accuracy scoring."
        ),
    )


def extract_final_sql(state: SQLTaskState | dict | str | None) -> str:
    """Pull a SQL string out of whatever shape the topology returned.

    Resilient to ParallelResult.merged shapes (list of states), to dicts,
    and to bare strings (in case the meta-agent wires a terminal step
    that emits SQL directly).
    """
    if state is None:
        return ""
    if isinstance(state, SQLTaskState):
        return (state.final_sql or "").strip() or (
            state.candidate_sqls[0].strip() if state.candidate_sqls else ""
        )
    if isinstance(state, dict):
        sql = state.get("final_sql") or ""
        if not sql:
            cands = state.get("candidate_sqls") or []
            if cands:
                sql = cands[0]
        if not sql:
            sql = state.get("sql") or ""
        return str(sql).strip()
    if isinstance(state, str):
        return state.strip()
    if isinstance(state, list) and state:
        # Parallel.collect_all → list[SQLTaskState]; pick the first with final_sql
        for item in state:
            sql = extract_final_sql(item)
            if sql:
                return sql
    return ""


__all__ = ["SQLTaskState", "extract_final_sql"]
