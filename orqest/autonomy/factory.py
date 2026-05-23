"""Convert AgentSpec definitions into live BaseAgent instances.

The AgentFactory resolves tools from the ToolRegistry and constructs
Pydantic output models from JSON Schema at runtime using create_model.
DynamicAgent is the concrete agent type produced by the factory.

When an AgentSpec carries a :class:`GeneratedToolSpec` (a tool the LLM
defines at runtime, with implementation included), the factory delegates
to a :class:`DynamicToolFactory` to materialize it through a sandbox.
The dispatch is by isinstance — :class:`ToolSpec` → registry lookup,
:class:`GeneratedToolSpec` → ``tool_factory.spawn(spec)``.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field, create_model
from pydantic_ai.models import Model

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.autonomy.registry import ToolRegistry
from orqest.autonomy.spec import AgentSpec, GeneratedToolSpec, ToolSpec

if TYPE_CHECKING:
    from orqest.autonomy.tool_factory import DynamicToolFactory


class DynamicAgent(BaseAgent[GlobalState, BaseModel]):
    """An agent created at runtime from an AgentSpec.

    Unlike user-defined agents, DynamicAgent's _run_implementation
    is generic: it takes the latest user message and calls call_model.
    """

    async def _run_implementation(
        self, state: GlobalState, **kwargs: Any
    ) -> BaseModel:
        user_message = state.get_latest_message("user")
        result = await self.call_model(user_message or "", state)
        return result.output


class AgentFactory:
    """Creates live agents from AgentSpec definitions.

    The factory resolves tools from the ToolRegistry and constructs
    Pydantic output models from JSON Schema at runtime.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        default_model: str = "openai:gpt-4.1",
        api_key: str = "",
        *,
        tool_factory: "DynamicToolFactory | None" = None,
    ) -> None:
        """Initialize with an optional registry, default model, and API key.

        Args:
            registry: Optional :class:`ToolRegistry` for resolving
                :class:`ToolSpec` references. Created empty if omitted.
            default_model: Fallback model when ``spec.model`` is empty.
            api_key: API key used when spawning agents from a model string.
            tool_factory: Optional :class:`DynamicToolFactory` for
                materializing :class:`GeneratedToolSpec` entries inside
                ``AgentSpec.tools``. When ``None``, generated tool specs
                are logged + dropped (matches the existing graceful-skip
                behavior for unknown registry names).

        """
        self._registry = registry or ToolRegistry()
        self._default_model = default_model
        self._api_key = api_key
        self._tool_factory = tool_factory

    def spawn(self, spec: AgentSpec, *, model: Model | None = None) -> DynamicAgent:
        """Hydrate an AgentSpec into a runnable DynamicAgent.

        Args:
            spec: The agent specification to hydrate. ``spec.tools`` may
                mix :class:`ToolSpec` (registry lookup) and
                :class:`GeneratedToolSpec` (sandbox-spawned). Generated
                tools require a ``tool_factory`` configured at construction.
            model: Optional pre-built Model instance. When provided, the
                factory uses it directly instead of resolving from spec.model.
                This is the recommended way to inject TestModel in tests.

        """
        # Dispatch on whichever output-shape declaration the spec carries.
        # The AgentSpec validator already enforced exactly-one-of, so we can
        # branch cleanly here.
        if spec.output_type is not None:
            output_type = spec.output_type
        else:
            # JSON Schema path — synthesise a Pydantic model at runtime.
            assert spec.output_schema is not None  # validator guarantee
            output_type = self._schema_to_model(spec.name, spec.output_schema)
        # Pass agent_id (= spec.name) so Tier-2 sandbox routes execution into
        # the agent's per-agent subfolder + .venv. Tier-0 / Tier-1 ignore.
        tools = self._resolve_tools(spec.tools, agent_id=spec.name)

        prompt = spec.system_prompt
        if spec.constraints:
            constraint_text = "\n".join(f"- {c}" for c in spec.constraints)
            prompt += f"\n\nConstraints (you MUST follow these):\n{constraint_text}"

        if model is not None:
            return DynamicAgent(
                agent_name=spec.name,
                system_prompt=prompt,
                output_type=output_type,
                model=model,
                tools=tools if tools else None,
            )

        return DynamicAgent(
            agent_name=spec.name,
            system_prompt=prompt,
            output_type=output_type,
            model=spec.model or self._default_model,
            api_key=self._api_key,
            tools=tools if tools else None,
        )

    def _schema_to_model(
        self, agent_name: str, schema: dict[str, Any]
    ) -> type[BaseModel]:
        """Convert a JSON Schema dict to a Pydantic model at runtime."""
        fields: dict[str, Any] = {}
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        for field_name, field_schema in properties.items():
            field_type = self._resolve_type(field_schema)
            description = field_schema.get("description", "")

            if field_name in required:
                fields[field_name] = (field_type, Field(description=description))
            else:
                default = field_schema.get("default")
                fields[field_name] = (
                    field_type,
                    Field(default=default, description=description),
                )

        model_name = f"{agent_name}_Output"
        return create_model(model_name, **fields)

    def _resolve_type(self, field_schema: dict[str, Any]) -> type:
        """Map JSON Schema types to Python types."""
        json_type = field_schema.get("type", "string")
        type_map: dict[str, type] = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        if json_type == "array":
            items = field_schema.get("items", {})
            item_type = self._resolve_type(items)
            return list[item_type]  # type: ignore[valid-type]

        return type_map.get(json_type, str)

    def _resolve_tools(
        self,
        tool_specs: list[ToolSpec | GeneratedToolSpec],
        *,
        agent_id: str | None = None,
    ) -> list:
        """Resolve a mixed list of tool specs to pydantic-ai Tool instances.

        :class:`ToolSpec` → registry lookup (existing behavior; missing names
        logged and dropped). :class:`GeneratedToolSpec` → ``tool_factory.spawn``
        if a factory is configured, otherwise logged and dropped.

        Spawning is async; we run it inline via :func:`asyncio.run` (no running
        loop) or a worker thread (loop already running, e.g. Jupyter / async
        consumers). Mirrors the bridge pattern in
        :class:`OrqestGEPAAdapter._run_async`.

        Args:
            tool_specs: Mixed list of registered + generated tool specs.
            agent_id: The agent identifier (typically the AgentSpec name).
                Forwarded to ``tool_factory.spawn`` so Tier-2 sandbox can
                route into per-agent venvs. ``None`` (default) is fine for
                Tier-0 / Tier-1.

        """
        tools = []
        for spec in tool_specs:
            if isinstance(spec, GeneratedToolSpec):
                if self._tool_factory is None:
                    logger.warning(
                        "AgentFactory: GeneratedToolSpec {n!r} requires a "
                        "tool_factory; dropping (configure DynamicToolFactory "
                        "to materialize runtime-generated tools).",
                        n=spec.name,
                    )
                    continue
                try:
                    tool = self._spawn_generated(spec, agent_id=agent_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "AgentFactory: failed to spawn generated tool {n!r}: {e}; "
                        "dropping.",
                        n=spec.name,
                        e=exc,
                    )
                    continue
                tools.append(tool)
                continue

            # Existing ToolSpec path
            if not self._registry:
                continue
            tool = self._registry.get(spec.name)
            if tool is not None:
                tools.append(tool)
        return tools

    def _spawn_generated(
        self,
        spec: GeneratedToolSpec,
        *,
        agent_id: str | None = None,
    ) -> Any:
        """Sync adapter over ``DynamicToolFactory.spawn`` with the standard
        async-bridge: ``asyncio.run`` when no loop is running; worker thread
        when one is. Mirrors :meth:`OrqestGEPAAdapter._run_async`.
        """
        assert self._tool_factory is not None  # narrowed by caller
        spawn_fn = self._tool_factory.spawn

        async def _do_spawn():
            return await spawn_fn(spec, agent_id=agent_id)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_do_spawn())

        # Already in a loop — run on a worker thread so we don't deadlock.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _do_spawn()).result()
