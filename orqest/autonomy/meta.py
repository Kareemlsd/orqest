"""Self-spawning orchestrator that decomposes goals into subtasks.

The MetaOrchestrator is the core of orqest's autonomy layer. It takes a
high-level goal, uses a planner agent to decompose it into subtasks,
finds or creates agents for each subtask, executes them sequentially,
and collects the results. Successful agent specs can be persisted to
memory for reuse in future runs.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.hooks import HookAbortError, HookRunner, Redirect, Skip
from orqest.observability import AgentEvent, EventBus


class SubTask(BaseModel):
    """A single subtask derived from goal decomposition."""

    name: str = Field(description="Short name for this subtask")
    description: str = Field(description="What needs to be done")
    requires_agent: bool = Field(
        description="Whether this needs an agent or is a simple function"
    )
    agent_name: str | None = Field(
        default=None, description="Name of existing agent if known"
    )


class TaskDecomposition(BaseModel):
    """Output of the goal decomposition step."""

    goal: str = Field(description="The original high-level goal")
    subtasks: list[SubTask] = Field(
        description="Ordered list of subtasks to achieve the goal"
    )
    reasoning: str = Field(description="Why these subtasks are needed")


class SubTaskResult(BaseModel):
    """Result of a single subtask execution."""

    subtask_name: str
    success: bool
    output: Any = None
    error: str | None = None
    agent_used: str
    was_spawned: bool
    duration_ms: float


class ExecutionResult(BaseModel):
    """Result of executing the full goal."""

    goal: str
    success: bool
    subtask_results: list[SubTaskResult]
    summary: str
    total_duration_ms: float


class MetaOrchestrator:
    """Orchestrator that decomposes goals and spawns agents as needed.

    The MetaOrchestrator:
    1. Takes a high-level goal from the user
    2. Uses a planner agent to decompose it into subtasks
    3. For each subtask, finds an existing agent or spawns a new one
    4. Executes the subtasks sequentially (v1)
    5. Collects results and produces a summary
    6. Optionally persists successful agent specs to memory
    """

    def __init__(
        self,
        planner: BaseAgent,
        factory: Any,
        registry: Any,
        *,
        memory: Any | None = None,
        hooks: HookRunner | None = None,
        max_subtasks: int = 10,
        max_spawn_depth: int = 3,
        metacognition: Any = None,
        bus: EventBus | None = None,
    ) -> None:
        """Initialize the MetaOrchestrator.

        Args:
            planner: Agent that decomposes goals into TaskDecomposition.
            factory: AgentFactory that spawns agents from AgentSpec.
            registry: ToolRegistry for tool lookup.
            memory: Optional MemoryStore for persisting learned specs.
            hooks: Optional HookRunner for lifecycle events.
            max_subtasks: Upper bound on subtasks per goal.
            max_spawn_depth: Maximum nesting depth for spawned agents.
            metacognition: Optional :class:`MetacognitionConfig`. When
                set, after each successful subtask the orchestrator
                inspects the result's confidence; if it falls below
                ``redecompose_threshold`` (and the re-decomposition
                budget remains), the planner is re-invoked to rewrite
                the remaining subtasks. ``None`` preserves the legacy
                straight-through behavior.

        """
        self._planner = planner
        self._factory = factory
        self._registry = registry
        self._memory = memory
        self._hooks = hooks or HookRunner()
        self._max_subtasks = max_subtasks
        self._max_spawn_depth = max_spawn_depth
        self._metacognition = metacognition
        self._bus = bus
        self._spawned_agents: dict[str, BaseAgent] = {}

    async def solve(self, goal: str) -> ExecutionResult:
        """Decompose a goal into subtasks, spawn agents, and execute.

        When :class:`MetacognitionConfig` is configured, low-confidence
        subtask results trigger re-decomposition of the remaining
        subtasks (bounded by ``max_redecompositions``).
        """
        start = time.monotonic()

        decomposition = await self._decompose(goal)
        subtasks = list(decomposition.subtasks[: self._max_subtasks])

        results: list[SubTaskResult] = []
        context: dict[str, Any] = {}
        redecomposition_count = 0

        i = 0
        while i < len(subtasks):
            subtask = subtasks[i]
            result = await self._execute_subtask(subtask, context)
            results.append(result)
            if result.success:
                context[subtask.name] = result.output

                # Confidence-driven re-decomposition.
                conf = _extract_confidence(result.output)
                if (
                    self._metacognition is not None
                    and conf is not None
                    and conf < self._metacognition.redecompose_threshold
                    and redecomposition_count
                    < self._metacognition.max_redecompositions
                ):
                    # Surface the cognitive moment — when configured with
                    # an event bus, emit a typed event so consumers
                    # (Polymath's metacognition badge / healing log) can
                    # render "the orchestrator just re-planned because
                    # confidence dropped to X". Best-effort; bus failures
                    # are logged but never propagate.
                    if self._bus is not None:
                        try:
                            await self._bus.emit(
                                AgentEvent(
                                    event_type="metacognition.redecomposition_triggered",
                                    agent_name=self._planner.agent_name,
                                    timestamp=datetime.now(UTC),
                                    data={
                                        "subtask_name": subtask.name,
                                        "confidence": conf,
                                        "threshold": self._metacognition.redecompose_threshold,
                                        "attempt": redecomposition_count + 1,
                                        "max_attempts": self._metacognition.max_redecompositions,
                                        "remaining_subtasks": [
                                            s.name for s in subtasks[i + 1 :]
                                        ],
                                    },
                                )
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "metacognition redecomposition emit failed: {e}",
                                e=exc,
                            )

                    new_remaining = await self._redecompose(
                        original_goal=goal,
                        completed=results,
                        remaining=subtasks[i + 1 :],
                        triggering_result=result,
                        triggering_confidence=conf,
                    )
                    subtasks = subtasks[: i + 1] + list(new_remaining)
                    redecomposition_count += 1
            i += 1

        total_ms = (time.monotonic() - start) * 1000
        all_success = all(r.success for r in results)

        summary_parts = []
        for r in results:
            status = "OK" if r.success else "FAILED"
            summary_parts.append(
                f"  [{status}] {r.subtask_name} (via {r.agent_used})"
            )
        summary = f"Goal: {goal}\n" + "\n".join(summary_parts)

        return ExecutionResult(
            goal=goal,
            success=all_success,
            subtask_results=results,
            summary=summary,
            total_duration_ms=total_ms,
        )

    async def _decompose(self, goal: str) -> TaskDecomposition:
        """Use the planner agent to break a goal into subtasks."""
        state = GlobalState()
        state.add_message("user", goal)
        return await self._planner.run(state)

    async def _execute_subtask(
        self, subtask: SubTask, context: dict[str, Any]
    ) -> SubTaskResult:
        """Execute a single subtask — find or spawn an agent."""
        start = time.monotonic()

        prompt = subtask.description
        if context:
            context_str = json.dumps(
                {k: str(v)[:500] for k, v in context.items()},
                indent=2,
            )
            prompt += f"\n\nContext from previous steps:\n{context_str}"

        agent: BaseAgent | None = None
        was_spawned = False
        try:
            agent, was_spawned = await self._find_or_spawn(subtask)

            state = GlobalState()
            state.add_message("user", prompt)

            hook_args = {"subtask": subtask.name}
            before_decision = await self._hooks.run_before(
                f"meta:{subtask.name}", hook_args, state,
            )

            # Skip → synthetic success with stub_result.
            if isinstance(before_decision, Skip):
                duration = (time.monotonic() - start) * 1000
                stub = before_decision.stub_result
                await self._hooks.run_after(
                    f"meta:{subtask.name}", hook_args, stub, state, duration,
                )
                return SubTaskResult(
                    subtask_name=subtask.name,
                    success=True,
                    output=stub,
                    agent_used=agent.agent_name,
                    was_spawned=was_spawned,
                    duration_ms=duration,
                )

            # Redirect → mutate prompt via new_args["prompt"], if provided.
            if isinstance(before_decision, Redirect):
                if before_decision.new_args and "prompt" in before_decision.new_args:
                    new_prompt = str(before_decision.new_args["prompt"])
                    state = GlobalState()
                    state.add_message("user", new_prompt)

            output = await agent.run(state)
            duration = (time.monotonic() - start) * 1000

            await self._hooks.run_after(
                f"meta:{subtask.name}", hook_args, output, state, duration,
            )

            return SubTaskResult(
                subtask_name=subtask.name,
                success=True,
                output=output,
                agent_used=agent.agent_name,
                was_spawned=was_spawned,
                duration_ms=duration,
            )

        except HookAbortError as abort:
            duration = (time.monotonic() - start) * 1000
            logger.warning(
                "Subtask {name} aborted by hook: {reason}",
                name=subtask.name,
                reason=abort.reason,
            )
            return SubTaskResult(
                subtask_name=subtask.name,
                success=False,
                error=f"aborted: {abort.reason}",
                agent_used=subtask.agent_name or "unknown",
                was_spawned=False,
                duration_ms=duration,
            )

        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.warning(
                "Subtask {name} failed: {err}",
                name=subtask.name,
                err=str(exc),
            )
            try:
                error_decision = await self._hooks.run_error(
                    f"meta:{subtask.name}",
                    {"subtask": subtask.name},
                    exc,
                    GlobalState(),
                )
            except HookAbortError as abort:
                return SubTaskResult(
                    subtask_name=subtask.name,
                    success=False,
                    error=f"aborted: {abort.reason}",
                    agent_used=subtask.agent_name or "unknown",
                    was_spawned=False,
                    duration_ms=duration,
                )

            retried = await self._retry_subtask_on_redirect(
                decision=error_decision,
                agent=agent,
                was_spawned=was_spawned,
                subtask=subtask,
                prompt=prompt,
                start=start,
            )
            if retried is not None:
                return retried

            return SubTaskResult(
                subtask_name=subtask.name,
                success=False,
                error=str(exc),
                agent_used=subtask.agent_name or "unknown",
                was_spawned=False,
                duration_ms=duration,
            )

    async def _retry_subtask_on_redirect(
        self,
        *,
        decision: Any,
        agent: BaseAgent | None,
        was_spawned: bool,
        subtask: SubTask,
        prompt: str,
        start: float,
    ) -> SubTaskResult | None:
        """Honor an ``on_error`` :class:`Redirect` with one bounded agent retry.

        Returns the success :class:`SubTaskResult` when the retry ran and
        succeeded, or ``None`` when no retry applies (the decision is not a
        :class:`Redirect`, or no agent was spawned) or the retry itself
        raised — in which case the caller reports the original failure.
        """
        if not isinstance(decision, Redirect) or agent is None:
            return None
        retry_state = GlobalState()
        retry_prompt = prompt
        if decision.new_args and "prompt" in decision.new_args:
            retry_prompt = str(decision.new_args["prompt"])
        retry_state.add_message("user", retry_prompt)
        try:
            output = await agent.run(retry_state)
        except Exception:
            return None
        duration = (time.monotonic() - start) * 1000
        await self._hooks.run_after(
            f"meta:{subtask.name}",
            {"subtask": subtask.name},
            output,
            retry_state,
            duration,
        )
        return SubTaskResult(
            subtask_name=subtask.name,
            success=True,
            output=output,
            agent_used=agent.agent_name,
            was_spawned=was_spawned,
            duration_ms=duration,
        )

    async def _find_or_spawn(
        self, subtask: SubTask
    ) -> tuple[BaseAgent, bool]:
        """Find an existing agent or spawn a new one for the subtask.

        Memory-recall path is procedural-first: a stored ``Skill`` whose
        ``trigger`` matches ``subtask.name`` is used preferentially.
        Falls back to the legacy episodic recall on miss. Stores into
        BOTH episodic (legacy mirror) and procedural (the cognitively-
        correct kind) for forward compat.
        """
        # Check cache of previously spawned agents
        if subtask.agent_name and subtask.agent_name in self._spawned_agents:
            return self._spawned_agents[subtask.agent_name], False

        # Check memory for a previously successful spec — procedural first
        if self._memory and subtask.agent_name:
            from orqest.autonomy.spec import AgentSpec
            from orqest.memory.store import MemoryFilter

            try:
                proc_memories = await self._memory.recall(
                    subtask.agent_name,
                    k=1,
                    filters=MemoryFilter(
                        memory_type="procedural", min_reliability=0.5
                    ),
                )
                if proc_memories and proc_memories[0].structured_content:
                    spec_payload = proc_memories[0].structured_content.get("spec")
                    if spec_payload:
                        spec = AgentSpec.model_validate(spec_payload)
                        agent = self._factory.spawn(spec)
                        self._spawned_agents[spec.name] = agent
                        return agent, True
            except Exception:
                logger.debug("No usable procedural skill in memory")

            # Fallback: episodic recall (legacy path)
            try:
                memories = await self._memory.recall(
                    subtask.agent_name,
                    k=1,
                    filters=MemoryFilter(
                        memory_type="episodic", min_reliability=0.5
                    ),
                )
                if memories:
                    spec = AgentSpec.model_validate_json(memories[0].content)
                    agent = self._factory.spawn(spec)
                    self._spawned_agents[spec.name] = agent
                    return agent, True
            except Exception:
                logger.debug("No usable agent spec found in memory")

        # Spawn a new generic agent for this subtask
        from orqest.autonomy.spec import AgentSpec

        spec = AgentSpec(
            name=subtask.name.replace(" ", "_"),
            system_prompt=(
                f"You are a specialist agent for: {subtask.description}\n"
                "Produce clear, structured output. Be thorough and precise."
            ),
            output_schema={
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "The result of the task",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence 0-1",
                    },
                },
                "required": ["result", "confidence"],
            },
        )

        agent = self._factory.spawn(spec)
        self._spawned_agents[spec.name] = agent

        # Persist the spec to memory for future reuse (best-effort).
        # Dual-write: episodic mirror (legacy) + procedural Skill (new).
        if self._memory:
            from orqest.memory.store import MemoryEntry, Skill, ToolCallSpec

            try:
                await self._memory.store(
                    MemoryEntry(
                        content=spec.model_dump_json(),
                        memory_type="episodic",
                        source_agent="meta_orchestrator",
                        metadata={"subtask": subtask.name},
                    )
                )
            except Exception:
                logger.debug("Failed to persist agent spec to episodic memory")

            try:
                skill_payload = Skill(
                    name=spec.name,
                    description=subtask.description,
                    trigger=subtask.name,
                    tool_sequence=[
                        ToolCallSpec(tool_name=t.name, arguments={})
                        for t in spec.tools
                    ],
                    expected_outcome="Spawn-and-run agent for matching subtask.",
                ).model_dump()
                # Embed the AgentSpec inside the skill payload so
                # _find_or_spawn can rehydrate without a second lookup.
                skill_payload["spec"] = spec.model_dump()
                await self._memory.store(
                    MemoryEntry(
                        content=subtask.name,
                        structured_content=skill_payload,
                        memory_type="procedural",
                        source_agent="meta_orchestrator",
                        metadata={"subtask": subtask.name},
                    )
                )
            except Exception:
                logger.debug("Failed to persist agent spec to procedural memory")

        return agent, True

    @property
    def spawned_agents(self) -> dict[str, BaseAgent]:
        """Access the cache of dynamically spawned agents."""
        return dict(self._spawned_agents)

    async def _redecompose(
        self,
        *,
        original_goal: str,
        completed: list[SubTaskResult],
        remaining: list[SubTask],
        triggering_result: SubTaskResult,
        triggering_confidence: float,
    ) -> list[SubTask]:
        """Re-invoke the planner with the partially-completed context.

        Builds a re-planning prompt with the original goal, the completed
        subtask outputs (clipped), the triggering low-confidence result,
        and the remaining subtasks for context. Returns the planner's
        rewritten remaining subtasks. On any failure, returns
        ``remaining`` unchanged — best-effort behavior.
        """
        try:
            completed_summary = "\n".join(
                f"- {r.subtask_name}: success={r.success} agent={r.agent_used}"
                for r in completed
            )
            remaining_summary = "\n".join(f"- {s.name}: {s.description}" for s in remaining)
            prompt = (
                f"Original goal: {original_goal}\n\n"
                f"Completed subtasks:\n{completed_summary}\n\n"
                f"The most recent subtask '{triggering_result.subtask_name}' "
                f"reported low confidence ({triggering_confidence:.2f}). "
                "Re-plan the REMAINING subtasks given what we've learned.\n\n"
                f"Currently remaining:\n{remaining_summary}\n\n"
                "Return a fresh TaskDecomposition for ONLY the remaining steps."
            )
            state = GlobalState()
            state.add_message("user", prompt)
            new_decomp = await self._planner.run(state)
            return list(new_decomp.subtasks)[: self._max_subtasks]
        except Exception as exc:
            logger.warning("Re-decomposition failed: {e}", e=exc)
            return list(remaining)


def _extract_confidence(output: Any) -> float | None:
    """Best-effort extraction of a confidence number from a subtask output.

    Tries (in order):
      1. ``output.confidence`` — covers EnrichedOutput and the
         existing structured-output pattern that ``_find_or_spawn``
         already prompts spawned agents to emit.
      2. ``output.metadata["confidence"]`` — for dict outputs.

    Returns ``None`` when no confidence is discoverable.
    """
    direct = getattr(output, "confidence", None)
    if direct is None and isinstance(output, dict):
        direct = output.get("confidence")
        if direct is None:
            md = output.get("metadata")
            if isinstance(md, dict):
                direct = md.get("confidence")
    if direct is None:
        return None
    try:
        f = float(direct)
    except (TypeError, ValueError):
        return None
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f
