"""Serializable agent and tool definitions for runtime agent spawning.

An LLM produces an AgentSpec as structured output. The AgentFactory
hydrates it into a live BaseAgent. ToolSpec describes a tool an agent needs,
resolved from the ToolRegistry by name. GeneratedToolSpec carries an
implementation string and is hydrated by DynamicToolFactory through a
:class:`Sandbox`.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolSpec(BaseModel):
    """Description of a tool an agent needs.

    The ``name`` is resolved against :class:`ToolRegistry` at spawn time.
    ``parameters`` is a JSON-Schema-shaped dict carried for the LLM's
    benefit (it never reaches the registered tool — that contract lives
    on the tool itself).
    """

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class GeneratedToolSpec(BaseModel):
    """A tool the LLM defines AT RUNTIME — implementation included.

    The companion to :class:`ToolSpec` for cases where the agent needs a
    capability that does NOT yet exist in :class:`ToolRegistry`. The
    ``implementation`` string is the body of the tool function:

    * It receives a single ``args`` dict (matching ``parameters``)
    * It must ``return`` a JSON-serializable value
    * It executes inside the configured :class:`orqest.sandbox.Sandbox`

    Hydration is performed by :class:`orqest.autonomy.DynamicToolFactory`,
    which validates the implementation (AST check + allowed-imports
    allowlist) before producing the runnable ``pydantic_ai.Tool``.

    The presence of ``implementation`` is the structural discriminator that
    distinguishes :class:`GeneratedToolSpec` from :class:`ToolSpec` in the
    :attr:`AgentSpec.tools` smart-union — Pydantic v2 picks this variant
    when ``implementation`` is present in the input dict.
    """

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    implementation: str
    """Python source — the body of a function that takes ``args`` (dict)
    and returns a JSON-serializable value. Use ``return`` for the result.

    Example::

        "import re\\n"
        "matches = re.findall(r'\\\\d+', args['text'])\\n"
        "return {'matches': matches}\\n"
    """

    allowed_imports: set[str] = Field(default_factory=set)
    """Top-level module names the implementation may import. Empty set
    rejects any ``import`` statement at validate time. Use sparingly —
    every entry is a safety surface."""

    dependencies: list[str] = Field(default_factory=list)
    """Optional pip specifiers (e.g. ``["pandas>=2.0", "httpx"]``) required
    by the implementation. Tier-2 :class:`DockerSandbox` installs them
    into the agent's per-agent ``.venv`` on first invocation, gated by the
    sandbox's ``allowed_packages`` allowlist (default-deny). Tier-0 / Tier-1
    sandboxes ignore — they have no per-agent venv concept. Empty default
    keeps the field backward-compatible."""

    timeout_s: float = Field(default=5.0, gt=0.0)
    """Per-invocation wall-clock cap inside the sandbox."""

    memory_mb: int = Field(default=128, gt=0)
    """Per-invocation memory cap (RLIMIT_AS on POSIX). Ignored on Windows."""


class AgentSpec(BaseModel):
    """Everything needed to spawn an agent at runtime.

    An LLM produces this as structured output. The AgentFactory hydrates it
    into a live BaseAgent.

    Output shape is declared via **exactly one** of:

    - ``output_schema``: a JSON Schema dict (the wire-format option — LLMs can
      emit this, and it survives serialization/persistence).
    - ``output_type``: a Pydantic ``BaseModel`` subclass (the code-side
      ergonomic option — terser than authoring JSON Schema by hand; not
      serializable, so use this for in-process construction).

    A validator enforces "exactly one of" — neither raises, both raises.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    system_prompt: str
    output_schema: dict[str, Any] | None = None
    """JSON Schema dict describing the agent's structured output. Use this
    when the spec is emitted by an LLM or persisted across processes. Pair
    with the ``properties``/``required`` shape that
    :meth:`AgentFactory._schema_to_model` expects."""
    output_type: type[BaseModel] | None = None
    """A Pydantic ``BaseModel`` subclass. Use this when constructing the spec
    in code — it's terser than authoring JSON Schema by hand and you get
    static-typing of the output. Not serializable; the JSON Schema path is
    the wire-format option."""
    tools: list[ToolSpec | GeneratedToolSpec] = Field(default_factory=list)
    """Mixed list — pre-registered tool references (:class:`ToolSpec`) and
    runtime-generated tools (:class:`GeneratedToolSpec`). Pydantic v2
    smart-union dispatches by structure: the ``implementation`` field
    on :class:`GeneratedToolSpec` is the disambiguator."""
    model: str = "openai:gpt-4.1"
    constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exactly_one_output_shape(self) -> "AgentSpec":
        has_schema = self.output_schema is not None
        has_type = self.output_type is not None
        if has_schema and has_type:
            raise ValueError(
                f"AgentSpec '{self.name}': pass exactly one of `output_schema` "
                f"(JSON Schema dict, LLM-emittable) or `output_type` (Pydantic "
                f"BaseModel subclass, code-side). Both are set."
            )
        if not has_schema and not has_type:
            raise ValueError(
                f"AgentSpec '{self.name}': must declare output shape via either "
                f"`output_schema=<dict>` or `output_type=<PydanticModel>`. "
                f"Neither is set."
            )
        if has_type and not (
            isinstance(self.output_type, type)
            and issubclass(self.output_type, BaseModel)
        ):
            raise ValueError(
                f"AgentSpec '{self.name}': `output_type` must be a Pydantic "
                f"BaseModel subclass; got {self.output_type!r}."
            )
        return self
