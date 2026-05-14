"""SubAgentTool — a reusable "agent → executor → evaluator → state update" primitive.

Many Orqest consumers build *compound tools*: LLM-facing callables that
(1) delegate to a stateless sub-agent for a structured decision,
(2) execute that decision against a real system (MCP, sandbox, etc.),
(3) update long-lived session state with the result,
(4) optionally evaluate the result and retry with a refined prompt when
it falls short of a quality threshold.

Before ``SubAgentTool`` this flow was hand-rolled in every compound
tool body — dozens of lines of ``try/except`` + manual refinement
loops + state-mutation bookkeeping. ``SubAgentTool`` captures the
pattern in one class so consumers only write the domain-specific
bits: the executor, the state updater, and the optional quality
evaluator.

For retry-with-enrichment on *exceptions* (not quality failures),
wrap a ``SubAgentTool.run(...)`` call with
:func:`orqest.agents.retry.run_with_retry` — the two primitives
compose cleanly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from orqest.agents.base_agent import BaseAgent

StateT = TypeVar("StateT")
ResultT = TypeVar("ResultT")


class SubAgentResult(BaseModel, Generic[ResultT]):
    """Outcome of a :meth:`SubAgentTool.run` invocation.

    Captures the final result plus a short history of refinement
    attempts so consumers (metrics, trace spans, LLM tool returns) can
    surface "how many passes it took" without re-instrumenting.
    """

    result: ResultT
    iterations: int = Field(
        default=1,
        description="Number of (agent + executor) cycles run, including the first.",
    )
    refined: bool = Field(
        default=False,
        description="True iff a refinement cycle produced a different result than the first attempt.",
    )
    exit_reason: str = Field(
        default="passed",
        description="'passed' | 'max_refinements' | 'refinement_failed_keep_original'",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Self-confidence reported by the underlying agent on "
        "the final iteration (after refinement). None when no "
        "confidence_protocol is configured. Best-effort.",
    )
    uncertainty_targets: list[str] = Field(
        default_factory=list,
        description="Free-text bottlenecks the agent flagged on its final "
        "iteration. Empty when no enrichment ran.",
    )
    capability_boundary: bool = Field(
        default=False,
        description="True iff the agent flagged the task as outside its "
        "verifiable capability on the final iteration.",
    )

    model_config = {"arbitrary_types_allowed": True}


class EvalResult(BaseModel):
    """Pass/fail signal from the optional evaluator."""

    passed: bool
    feedback: str = ""


class SubAgentTool(Generic[StateT, ResultT]):
    """Compose a stateless sub-agent with an executor and optional refinement.

    Usage — implement three domain functions and hand them to the tool:

    * ``executor(agent_output, state) -> Awaitable[ResultT]`` — turns
      the sub-agent's structured output into a real-world outcome
      (e.g. run the MCP pipeline and return a payload).
    * ``state_updater(result, state) -> None`` — mutates the long-
      lived session state with whatever needs to persist.
    * ``evaluator(result) -> EvalResult`` (optional) — decides whether
      the result is good enough or a refinement cycle should fire.

    If ``max_refinements > 0`` and the evaluator rejects the first
    result, the tool calls ``build_refinement_prompt(result, prompt)``
    to construct a new prompt and reruns the sub-agent + executor
    cycle. Refinement exceptions are caught and the best prior result
    is kept — matching numatics-ai v2's "best effort refinement" rule.

    The tool does NOT wrap retry-on-exception; for that, wrap the
    ``run`` call in :func:`orqest.agents.retry.run_with_retry`.
    """

    def __init__(
        self,
        agent: BaseAgent,
        executor: Callable[[Any, StateT], Awaitable[ResultT]],
        state_updater: Callable[[ResultT, StateT], None],
        *,
        evaluator: Callable[[ResultT], EvalResult] | None = None,
        max_refinements: int = 0,
        build_refinement_prompt: Callable[[ResultT, str], str] | None = None,
        name: str | None = None,
    ) -> None:
        """Configure the compound flow.

        Args:
            agent: A stateless :class:`~orqest.agents.base_agent.BaseAgent`
                whose ``.run()`` takes ``(state, **kwargs)`` and returns
                a structured output (typically a Pydantic model).
            executor: Async function that runs the real-world action
                using the sub-agent's output and returns a
                serializable result payload.
            state_updater: Synchronous mutator that writes the result
                back onto the state object.
            evaluator: Optional quality check. When provided with
                ``max_refinements > 0``, a failing evaluation triggers
                a refinement cycle.
            max_refinements: Number of refinement cycles allowed after
                the first pass. ``0`` disables refinement.
            build_refinement_prompt: ``(result, original_prompt) ->
                new_prompt``. Required when ``max_refinements > 0``.
            name: Optional tool name used in :class:`SubAgentResult`
                and error messages. Defaults to ``agent.agent_name``.

        Raises:
            ValueError: If ``max_refinements > 0`` but ``evaluator`` or
                ``build_refinement_prompt`` is ``None``.
        """
        if max_refinements > 0 and (
            evaluator is None or build_refinement_prompt is None
        ):
            raise ValueError(
                "SubAgentTool with max_refinements > 0 requires both "
                "evaluator and build_refinement_prompt."
            )

        self._agent = agent
        self._executor = executor
        self._state_updater = state_updater
        self._evaluator = evaluator
        self._max_refinements = max_refinements
        self._build_refinement_prompt = build_refinement_prompt
        self.name = name or getattr(agent, "agent_name", "sub_agent_tool")

    async def run(
        self,
        state: StateT,
        prompt: str,
        *,
        use_enriched: bool = False,
        **agent_kwargs: Any,
    ) -> SubAgentResult[ResultT]:
        """Execute one (agent + executor + state-update) cycle, then
        optionally refine up to ``max_refinements`` times.

        The first result is always committed to state before refinement
        begins — so a failed refinement leaves the original result in
        place (best-effort semantics). Extra keyword arguments are
        forwarded verbatim to ``agent.run``.

        Args:
            state: The agent's state object.
            prompt: The user-facing prompt for the sub-agent.
            use_enriched: When ``True``, runs the agent via
                :meth:`BaseAgent.run_enriched` and lifts the final-pass
                ``confidence`` / ``uncertainty_targets`` /
                ``capability_boundary`` onto the returned
                :class:`SubAgentResult`. The executor still receives the
                raw agent output (unwrapped from
                :class:`EnrichedOutput`). Default ``False`` preserves
                pre-metacognition behavior.
            **agent_kwargs: Forwarded to the agent.
        """

        async def _run_agent(state: StateT, **kw: Any) -> tuple[Any, dict[str, Any]]:
            """Returns ``(raw_output, enrichment_dict)``. The enrichment
            dict is empty when ``use_enriched`` is False or the agent
            has no protocol configured."""
            if use_enriched:
                enriched = await self._agent.run_enriched(state, **kw)
                return enriched.output, {
                    "confidence": enriched.confidence,
                    "uncertainty_targets": list(enriched.uncertainty_targets),
                    "capability_boundary": enriched.capability_boundary,
                }
            return await self._agent.run(state, **kw), {}

        # --- First pass ---
        # Deliver the prompt both ways: as a user message on `state` (the
        # universal BaseAgent channel, when supported) and as a `note=`
        # kwarg (legacy — agents that read it directly still work).
        if hasattr(state, "add_message"):
            state.add_message("user", prompt)
        call_kwargs = {"note": prompt, **agent_kwargs}
        agent_output, last_enrichment = await _run_agent(state, **call_kwargs)
        first_result = await self._executor(agent_output, state)
        self._state_updater(first_result, state)

        iterations = 1
        current_result = first_result
        refined = False
        exit_reason = "passed"

        if (
            self._max_refinements > 0
            and self._evaluator is not None
            and self._build_refinement_prompt is not None
        ):
            eval_result = self._evaluator(current_result)
            while (
                not eval_result.passed
                and iterations <= self._max_refinements
            ):
                next_prompt = self._build_refinement_prompt(current_result, prompt)
                try:
                    if hasattr(state, "add_message"):
                        state.add_message("user", next_prompt)
                    refined_output, last_enrichment = await _run_agent(
                        state, note=next_prompt,
                    )
                    refined_result = await self._executor(
                        refined_output, state,
                    )
                    self._state_updater(refined_result, state)
                    current_result = refined_result
                    refined = True
                    iterations += 1
                    eval_result = self._evaluator(current_result)
                except Exception:
                    # Best-effort refinement: exception keeps prior result.
                    exit_reason = "refinement_failed_keep_original"
                    break
            else:
                if not eval_result.passed:
                    exit_reason = "max_refinements"

        return SubAgentResult(
            result=current_result,
            iterations=iterations,
            refined=refined,
            exit_reason=exit_reason,
            confidence=last_enrichment.get("confidence"),
            uncertainty_targets=last_enrichment.get("uncertainty_targets") or [],
            capability_boundary=bool(last_enrichment.get("capability_boundary", False)),
        )
