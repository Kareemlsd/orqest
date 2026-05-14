# AGENT_HARNESS.md — Required Output Template

After building the harness, produce an `AGENT_HARNESS.md` at the consumer-project root (or `docs/agent_harness.md` if the project already has a `docs/` directory). This is the **extensibility playbook for the harness you just built** — the contract for the next session to extend without re-discovering the architecture.

Use this template. Fill every section. The file is a living doc — update it whenever the harness changes.

## Template

```markdown
# Agent Harness — <name>

## What the harness does

<one paragraph; tie back to Phase A discovery answers>

## Component selection

| Component | Used? | Why |
|-----------|-------|-----|
| BaseAgent | <YES/NO> | <Phase A answer that justifies it> |
| Pipeline / Parallel / Router | <YES/NO> | <...> |
| RefinementLoop | <YES/NO> | <...> |
| LocalMemoryStore (semantic) | <YES/NO> | <...> |
| LocalMemoryStore (episodic) | <YES/NO> | <...> |
| LocalMemoryStore (procedural) | <YES/NO> | <...> |
| MetaOrchestrator | <YES/NO> | <...> |
| MetacognitionHook + EnrichedOutput | <YES/NO> | <...> |
| with_healing | <YES/NO> | <...> |
| FallbackModel chain | <YES/NO> | <...> |
| Workbench | <YES/NO> | <...> |
| EventBus + sse_sidecar | <YES/NO> | <...> |
| UIEmitter + UIComponentSpec | <YES/NO> | <...> |
| MCPServerManager (MCP client) | <YES/NO> | <...> |

For omitted components, briefly note WHY they were rejected (e.g., "no cross-session memory in scope").

## Module layout

<where in the codebase; cite file paths>

- `<app>/agents/<name>.py` — the agent class + `build(...)` factory
- `<app>/agents/types.py` — Pydantic input/output shapes
- `<app>/agents/tools/<name>_tools.py` — tools wrapping existing app functions
- `<app>/api/agents.py:<line>` — the route handler that invokes the agent
- `<app>/runtime/workbench_factory.py` — per-session Workbench wiring (only if used)

## Configuration knobs

| Concern | Single source of truth |
|---------|------------------------|
| LLM model | `<settings.llm_model>` (env: `LLM_MODEL`) |
| API key | `<settings.llm_api_key>` (env: `LLM_API_KEY`) |
| User identity | `<Depends(get_current_user)>` |
| Memory backend | <if applicable> |
| Healing toggles | <if applicable> |
| ... | ... |

Every cross-cutting concern lives behind one config knob. Hard-coding a model id or API key inside a tool is a violation.

## Integration points

<where the existing app calls the agent — file:line references>

- `<app>/api/agents.py:<line>` — POST `/agents/<name>` builds and invokes the agent
- `<app>/agents/tools/<name>_tools.py:<line>` — the only place agents touch <existing data layer>
- `<app>/main.py:<line>` — `app.include_router(agents.router, prefix="/api")`

## Event flow

<what events the agent emits; where they're consumed>

If the harness uses `Workbench` + `EventBus`:

- `tool.before` / `tool.after` / `tool.error` — emitted by `EventBusPublishHook` on every tool call
- `metacognition.confidence` — emitted by `MetacognitionHook` after each `run_enriched` (if used)
- `healing.detection` / `.action` / `.model_fallback` — emitted by `HealingRunner` (if used)
- `ui.<componentType>.{init,delta,remove}` — emitted by `UIEmitter` (if used)

Subscribers:

- <existing observability layer> via `bus.subscribe_all(forward_to_logger)`
- <SSE sidecar route> at `/sessions/{sid}/events` if frontend listens

If the harness does NOT use `Workbench` (single BaseAgent path), explicitly note: "This harness emits no events. If observability is added later, mount an `EventBusPublishHook` on a `Workbench`."

## How to add a new tool

The canonical pattern for *this* harness:

1. Declare an `async def` function in `<app>/agents/tools/<name>_tools.py`. It takes typed parameters and returns a typed result. Reuse existing app primitives (DB queries, services, ...).
2. Add to the `tools=[...]` list in `<app>/agents/<name>.py::build`.
3. Add a one-liner pytest in `tests/agents/tools/test_<name>_tools.py` that mocks the underlying app primitive and verifies the tool wires correctly.

Concrete example:

```python
# Adding a tool to fetch user preferences
async def get_user_preferences(user_id: str) -> dict:
    """Return the user's stored preferences."""
    return await db.fetch_preferences(user_id=user_id)


# Then in build():
return MyAgent(..., tools=[..., get_user_preferences])
```

## How to add a new agent (peer)

When the app needs a second agent for a different task:

1. Mirror this harness structure — `types.py`, `<new_name>.py`, `tools/<new_name>_tools.py`
2. Mount a new route in `<app>/api/agents.py` (or a new router file if it warrants separation)
3. Update the "Module layout" + "Integration points" sections of *this* doc

Decide composition vs peer:
- **Peer** (separate agent, separate route) when the new task is independent
- **Composition** via `Pipeline` / `Parallel` / `as_tool` when the new task depends on the existing agent's output

## How to add memory later

If a future PR adds cross-session memory (e.g., "remember user's stylistic preferences"):

1. Build a `Workbench(memory=LocalMemoryStore("/var/app/agent-memory.db"))`
2. Pass `workbench=workbench` to the agent (or just the memory directly to tools)
3. The agent's tools recall via `workbench.memory.recall(query, k, filters)` filtered by `user_id`
4. Persist learnings via `workbench.memory.store(MemoryEntry(...))` — semantic for facts, episodic for events, procedural for skills

Update the "Component selection" table above to flip the memory rows to YES with the new justification.

## How to add healing later

If the agent moves to mission-critical paths:

1. Compose `Workbench.with_healing(HealingConfig(...))` — see `references/recipes.md` R7
2. Wrap the agent run in `async with healing as runner` and pass `model=runner.model`, `hook_runner=runner.hook_runner`
3. Add fallback model chain via `fallback_models=("openai:gpt-4.1", "anthropic:claude-sonnet-4-6")`

## How to add metacognition later

If output quality matters and you want confidence-aware behavior:

1. Add a `self_confidence: float` field to the agent's output type (zero extra LLM cost — `StructuredOutputProtocol`)
2. Pass `confidence_protocol=StructuredOutputProtocol()` to the agent ctor
3. Wire `MetacognitionHook(bus=bus)` on the `HookRunner`
4. Optionally: wrap in `RefinementLoop(confidence_threshold=0.85)` for quality-gated iteration

## How to add generative UI later

If the frontend gains SSE support and we want streaming chart / table / form output:

1. Add `Workbench(event_bus=bus, ui_registry=default_registry())`
2. Use `UIEmitter(bus)` from inside tools to emit typed components
3. Mount `sse_sidecar(bus)` as a route; frontend subscribes per `references/ai_sdk_integration.md`
4. Custom components: subclass `UIComponentSpec[T]`, register on `Workbench.ui_registry`

## Testing strategy

- **Unit tests:** mock the underlying app primitives + use pydantic-ai's `TestModel`. No real LLM in CI.
  - Location: `tests/agents/test_<name>.py`
  - Fixtures: reuse existing `tests/conftest.py` + add agent-specific fixtures only if needed
- **Integration tests:** the existing app test framework, with a real test DB and a `TestModel` agent.
  - Location: `tests/api/test_agents_integration.py`
- **Golden trajectory tests** (optional): record a session of agent calls + the expected output sequence. Replay deterministically with `TestModel` returning canned responses.

## Operational concerns

- **Cost:** <typical tokens per request; LLM cost ceiling>
- **Rate limits:** <how the harness handles upstream rate limits — if no healing, the request fails; if healing, fallback chain advances>
- **Logging:** <how agent activity surfaces in the existing log stream>
- **Monitoring:** <which existing dashboards / alerts cover the agent>
- **Cancellation:** <can the agent be cancelled mid-run? — usually yes via the framework's request lifecycle>

---

**This file is a living doc.** Update it whenever the harness changes. The next session reads it first to extend the harness without re-discovering the architecture.
```

## Filling-in tips

- **Cite Phase A answers.** Don't write "we don't use memory because we don't need it." Write "no cross-session memory because Phase A answer 12: 'each invocation stands alone.'"
- **Cite file paths with line numbers.** `app/api/agents.py:18` is a precise integration point. "the route handler" is not.
- **Be honest about what's NOT used.** The "rejected components" rationale is as useful as the "selected components" rationale — both prevent future drift.
- **Update when extending.** Adding a new tool requires updating "Module layout" and possibly "Integration points." Adding healing flips the table row from NO to YES.
