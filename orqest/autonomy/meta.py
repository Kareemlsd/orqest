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
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.hooks import HookRunner


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

        """
        self._planner = planner
        self._factory = factory
        self._registry = registry
        self._memory = memory
        self._hooks = hooks or HookRunner()
        self._max_subtasks = max_subtasks
        self._max_spawn_depth = max_spawn_depth
        self._spawned_agents: dict[str, BaseAgent] = {}

    async def solve(self, goal: str) -> ExecutionResult:
        """Decompose a goal into subtasks, spawn agents, and execute."""
        start = time.monotonic()

        decomposition = await self._decompose(goal)
        subtasks = decomposition.subtasks[: self._max_subtasks]

        results: list[SubTaskResult] = []
        context: dict[str, Any] = {}

        for subtask in subtasks:
            result = await self._execute_subtask(subtask, context)
            results.append(result)
            if result.success:
                context[subtask.name] = result.output

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

        try:
            agent, was_spawned = await self._find_or_spawn(subtask)

            state = GlobalState()
            state.add_message("user", prompt)

            await self._hooks.fire_before(
                f"meta:{subtask.name}",
                {"subtask": subtask.name},
                state,
            )

            output = await agent.run(state)
            duration = (time.monotonic() - start) * 1000

            await self._hooks.fire_after(
                f"meta:{subtask.name}",
                {"subtask": subtask.name},
                output,
                state,
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

        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.warning(
                "Subtask {name} failed: {err}",
                name=subtask.name,
                err=str(exc),
            )
            await self._hooks.fire_error(
                f"meta:{subtask.name}",
                {"subtask": subtask.name},
                exc,
                GlobalState(),
            )
            return SubTaskResult(
                subtask_name=subtask.name,
                success=False,
                error=str(exc),
                agent_used=subtask.agent_name or "unknown",
                was_spawned=False,
                duration_ms=duration,
            )

    async def _find_or_spawn(
        self, subtask: SubTask
    ) -> tuple[BaseAgent, bool]:
        """Find an existing agent or spawn a new one for the subtask."""
        # Check cache of previously spawned agents
        if subtask.agent_name and subtask.agent_name in self._spawned_agents:
            return self._spawned_agents[subtask.agent_name], False

        # Check memory for a previously successful spec
        if self._memory and subtask.agent_name:
            try:
                from orqest.memory.store import MemoryFilter

                memories = await self._memory.recall(
                    subtask.agent_name,
                    k=1,
                    filters=MemoryFilter(
                        memory_type="episodic", min_reliability=0.5
                    ),
                )
                if memories:
                    from orqest.autonomy.spec import AgentSpec

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

        # Persist the spec to memory for future reuse (best-effort)
        if self._memory:
            try:
                from orqest.memory.store import MemoryEntry

                await self._memory.store(
                    MemoryEntry(
                        content=spec.model_dump_json(),
                        memory_type="episodic",
                        source_agent="meta_orchestrator",
                        metadata={"subtask": subtask.name},
                    )
                )
            except Exception:
                logger.debug("Failed to persist agent spec to memory")

        return agent, True

    @property
    def spawned_agents(self) -> dict[str, BaseAgent]:
        """Access the cache of dynamically spawned agents."""
        return dict(self._spawned_agents)
