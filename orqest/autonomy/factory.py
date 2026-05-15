"""Convert AgentSpec definitions into live BaseAgent instances.

The AgentFactory resolves tools from the ToolRegistry and constructs
Pydantic output models from JSON Schema at runtime using create_model.
DynamicAgent is the concrete agent type produced by the factory.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, create_model
from pydantic_ai.models import Model

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.autonomy.registry import ToolRegistry
from orqest.autonomy.spec import AgentSpec, ToolSpec


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
    ) -> None:
        """Initialize with an optional registry, default model, and API key."""
        self._registry = registry or ToolRegistry()
        self._default_model = default_model
        self._api_key = api_key

    def spawn(self, spec: AgentSpec, *, model: Model | None = None) -> DynamicAgent:
        """Hydrate an AgentSpec into a runnable DynamicAgent.

        Args:
            spec: The agent specification to hydrate.
            model: Optional pre-built Model instance. When provided, the
                factory uses it directly instead of resolving from spec.model.
                This is the recommended way to inject TestModel in tests.

        """
        output_type = self._schema_to_model(spec.name, spec.output_schema)
        tools = self._resolve_tools(spec.tools)

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

    def _resolve_tools(self, tool_specs: list[ToolSpec]) -> list:
        """Resolve ToolSpecs to pydantic-ai Tool instances from the registry.

        Specs that don't resolve are silently skipped — the LLM may
        request a tool the consumer hasn't registered yet, and the
        agent should still spawn with whatever does resolve.
        """
        tools = []
        for spec in tool_specs:
            if not self._registry:
                continue
            tool = self._registry.get(spec.name)
            if tool is not None:
                tools.append(tool)
        return tools
