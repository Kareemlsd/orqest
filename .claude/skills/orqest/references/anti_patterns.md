# Anti-patterns + Pragmatic Programmer Discipline

## Pragmatic Programmer rules (load-bearing)

These rules govern every line of agent harness code. Source: `~/repos/orqest/.claude/PRINCIPLES.md`.

### Orthogonality

- Agent code does not entangle with route handlers, DB access, or business logic.
- The agent module *imports* app primitives; app code does not import agent internals.
- Constructor arguments fully determine an agent's behavior. Two agents in the same process with different providers must coexist.

### DRY

- One source of truth per fact. If the existing app already has a `User` model, the agent reuses it; never re-declare.
- State fields have non-overlapping responsibilities. No duplicate fields with subtly different semantics.

### YAGNI

- Implement only what discovery surfaced. No "we might need this later" Workbench, healing config, or memory store.
- Memory / healing / metacognition / generative UI / orchestration are each opt-in.

### ETC (Easy to Change)

- Every cross-cutting concern (model selection, API key, memory backend, hook config) lives behind a single configuration knob.
- Hard-coding `"openai:gpt-4.1"` deep in a tool is a violation. Read it from the agent's config.
- Provider/strategy selection uses mappings, not if/elif chains. Adding a new option means editing data, not control flow.

### Tracer bullets

- Land the smallest end-to-end working slice first; iterate from there.
- Don't design the whole abstraction upfront. Get two agents talking through minimal wiring, then extract the pattern.

### Shy code (Tell, Don't Ask)

- Don't reach through objects. Chains of `obj.x.y.z` more than one level deep are a smell.
- An agent doesn't know how a provider constructs its model — it receives a ready-to-use model.
- Expose operations, not structure.

### Crash early

- Validate at construction; trust internally. Missing API key surfaces at startup, not deep in `call_model`.
- Never silently return `None` to hide a failure. Raise, log, and let the caller decide recovery.

### Design by contract

- Pydantic models for every state / input / output / config boundary.
- Document invariants in docstrings (the WHY, not the WHAT).

### Async-first

- Every agent path is `async def`.
- Bridge to sync only at framework boundaries (CLI handlers, sync HTTP frameworks like Django without `flask[async]`).

### Pydantic everywhere

- State, output, configs (frozen dataclass), memory entries — all Pydantic.
- Frozen dataclass for runtime-immutable config (avoids Pydantic validation overhead).

### Generic typing

- `BaseAgent[StateT, OutputT]`, `Pipeline[InputT, OutputT]`, `SubAgentTool[StateT, ResultT]` — always parameterized.
- Returns of `Any` are usually a bug.

### Inheritance tax

- One level of inheritance is fine: `BaseAgent → ConcreteAgent`.
- Beyond that, prefer Protocols and composition.
- If a feature tempts a second level, use delegation or a hook.

### Reversibility

- Never mutate input data. Processors return new structures, not modified originals.
- History processors are pure functions chained.

### Pragmatic paranoia

- Defensive at boundaries, trusting internally.
- External inputs (env vars, API responses, user state) are validated.
- Internal function calls between validated layers can trust their inputs.

## Anti-patterns — what NOT to do

The do-NOT list. Each one has been the source of a real failure mode.

### Process

- **Don't skip the discovery phase.** SKIPPING DISCOVERY IS THE #1 FAILURE MODE. Without Phase A answers, you'll over-engineer (MetaOrchestrator + memory + healing) where a single BaseAgent would do.
- **Don't add features the application doesn't need.** Every Orqest battery is opt-in. If discovery didn't surface a reason for it, leave it out.
- **Don't violate the consumer's existing conventions** to match Orqest's. If the host app uses Pylint, use Pylint. If it has its own logging convention, route Orqest events through it. Orqest is the library; the host is the application.
- **Don't ship without `AGENT_HARNESS.md`.** It's the contract for the next session to extend the harness without re-discovering the architecture.
- **Don't update docs lazily.** `AGENT_HARNESS.md` is a living doc — update it whenever the harness changes.

### Imports

- **Don't import from `orqest.internal.*`.** No such module exists. Stay on the documented public surface (the 18 root re-exports + the documented submodule paths).
- **Don't reach into pydantic-ai internals** (`msg.parts[0].content` chains, Agent's private attrs). Wrap, compose, bridge; never re-implement what pydantic-ai already provides.

### Composition

- **Don't sync-call `async def` paths.** Every agent path is async; bridge at the framework boundary (sync HTTP handler) — not inside Orqest calls.
- **Don't bypass `HookRunner`.** Every tool call goes through it for observability + healing. Side-channel tool invocation breaks the audit trail.
- **Don't skip the `as_tool` wrapper for sub-agents.** Calling `inner_agent.run(...)` inside a parent agent's tool implementation works but loses hook integration. Use `as_tool(inner_agent)` and pass it to `tools=[...]`.

### State

- **Don't create module-level `Workbench` / `EventBus` / `Tracer` singletons.** They're per-session. A module-level Workbench leaks subscribers across users.
- **Don't share `MetaOrchestrator` across requests.** It owns `_spawned_agents` for the run; reuse leaks state across users.
- **Don't share `MCPServerManager` across processes.** Each connection holds OS-level handles; cross-process sharing breaks cleanup.

### Memory

- **Don't store untyped data in `MemoryEntry.metadata`.** It's a free-form `dict[str, Any]` for *non-load-bearing* metadata. Load-bearing structured data goes in `structured_content` (procedural memory only).
- **Don't trust the memory subsystem for transactional consistency.** It's best-effort; SQLite errors are swallowed and logged.
- **Don't reach into `LocalMemoryStore`'s SQLite directly.** Use the `MemoryStore` Protocol methods.

### Metacognition

- **Don't propagate `confidence=None` as if it were 0.** `None` means "no protocol ran or failed" — distinct from "the agent is confident this is wrong."
- **Don't compare confidence across protocols.** A `StructuredOutputProtocol`'s 0.7 isn't comparable to an `EnsembleProtocol(k=10)`'s 0.7. Treat as within-protocol ranking only.

### Healing

- **Don't override the policy with arbitrary `Redirect(new_args=...)` payloads.** The `_action_to_decision` mapping translates each `RecoveryAction` to a structured `HookDecision`; ad-hoc redirects bypass the contract.
- **Don't share a `HealingRunner` across sessions.** It owns subscriptions and a poll task; lifecycle is per-run.
- **Don't catch `HookAbortError` in tools.** It's the framework's signal to halt the compound flow. Catch at the outermost consumer boundary if you need to surface it.
- **Don't subscribe two `MetacognitionHook` instances to the same bus.** Confidence events double-fire; regression detection triggers prematurely.

### Generative UI

- **Don't propose a Polymath-shaped UI on top of an existing Vue/Svelte/HTMX app.** Generative UI fits where the frontend already supports SSE-driven typed components; otherwise return text/structured data and let the existing UI render it.
- **Don't share `ComponentRegistry` across consumers** that need different schemas. The per-Workbench design is intentional.
- **Don't emit `init` for the same `component_id` twice in a session.** That's a re-mount; the frontend may flicker. Use a `delta(replace, "", new_data)` instead.
- **Don't trust the frontend to validate.** The registry's `validate_payload` runs at the backend boundary; the frontend just renders.
- **Don't open a separate `EventSource` per hook on the frontend.** Browsers cap concurrent connections per origin. Use a `SidecarProvider` at the session root.

### MCP

- **Don't ship `PermissionGate.AllowAll` in production.** That's "remote code execution as a service." Use `AllowList(patterns)` with anchored regexes (`^web\.` not `web`).
- **Don't trust the tool description from a discovered MCP server.** A malicious server can advertise misleading descriptions. Combine `PermissionGate` with name-based allowlisting.
- **Don't auto-register dynamic-discovery into spawned agents' rosters.** Discovery is a registry-level decision, not a per-agent one.

### AI SDK Frontend

- **Don't key metacognition events by backend message id.** It does not match the AI SDK's `UIMessage.id`. Key by the frontend message id at event-arrival time.
- **Don't expose `sse_sidecar` without auth.** Cognitive backbone events can include tool input/output previews. Gate the route by the same auth as the chat endpoint.

### Comments

- **Don't write what-comments.** Bad: `# call the model`. Good: `# Truncate to 16k tokens to fit messages.text NOT NULL ≤ 64k constraint.`
- **Don't restate code in English.** No `# Add message to list` above `list.append()`.
- **Don't reference current task / fix / callers** ("used by X", "added for Y flow", "handles case from issue #123"). Those belong in the PR description.

### Existing app integration

- **Don't duplicate the existing app's logging / tracing / DB layer.** Orqest emits events; route them into the existing observability stream via a `bus.subscribe_all` handler.
- **Don't replicate the app's `User` / `Session` / `Order` models inside the agent module.** Import them from where they live.
- **Don't add a parallel auth path.** The agent inherits the existing auth (`Depends(get_current_user)` in FastAPI; `request.user` in Django; etc.).

## Pre-merge checklist

Before declaring the harness done:

- [ ] Every Orqest component imported can be traced to a Phase A discovery answer
- [ ] No module-level `Workbench` / `EventBus` / `Tracer` instances
- [ ] No imports from `orqest.internal.*` (this is a sanity check; the module doesn't exist)
- [ ] Every cross-cutting concern (model, API key, memory path, healing toggle) lives behind one config knob
- [ ] Existing app conventions match (lint, log, error envelope, async posture)
- [ ] `AGENT_HARNESS.md` exists and is filled in
- [ ] Tests use `TestModel`; no real LLM in CI
- [ ] No what-comments
- [ ] No `confidence=None` treated as `0`
- [ ] If `PermissionGate` used: not `AllowAll`
- [ ] If frontend wired: one `EventSource` per session, not per-hook
