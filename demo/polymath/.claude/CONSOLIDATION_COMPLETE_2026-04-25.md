# Polymath Consolidation Complete — 2026-04-25

> **Status:** ✅ All four phases (α, β, γ, δ) shipped on 2026-04-25 + post-consolidation stability fixes (BaseAgent migration, persistence, EventSource pool, ChatMessage memoization, recall + list_dir bug fixes).
> **Backend tests:** 91 → **120** (+29, all green).
> **Frontend:** typecheck + build clean throughout.
> **Consolidation plan:** `POLYMATH_ASSESSMENT_2026-04-25.md` (the "12 recommended changes" table in §7).
> **Implementation:** 8 parallel agents across 4 sequential rounds.

This document records what landed on top of the assessment, agent-by-agent, with the decisions each made on ambiguous interfaces.

---

## TL;DR — what changed

Polymath now demonstrates **all five novel Orqest features** end-to-end:

| Vision feature | How Polymath demonstrates it post-consolidation |
|---|---|
| **#1 Runtime agent design** | `register_agent` / `invoke_agent` / `list_agents` tools, now backed by `MetaOrchestrator`-style procedural-memory persistence (deleted the bespoke `SubAgent` Postgres table). |
| **#2 Cognitive memory typology** | Sub-agent persistence uses `memory_type="procedural"` with `Skill` payloads in `MemoryEntry.structured_content` and the embedded `AgentSpec` in `MemoryEntry.metadata["agent_spec"]`. Recall via `MemoryFilter(memory_type="procedural", skill_name=...)`. |
| **#3 Metacognition primitives** | Analyst output schema carries `self_confidence` / `uncertain_about` / `outside_my_capability`. `_invoke_agent` uses `agent.run_enriched`. `MetacognitionHook` registered alongside `EventBusPublishHook`. `metacognition.confidence` events flow on the SSE stream. |
| **#4 Self-healing primitives** | `Workbench.with_healing(HealingConfig(...))` constructs a `HealingRunner` per session. Watchdog hook in `HookRunner` chain. `FallbackModel` chain when `POLYMATH_FALLBACK_MODELS` env is set. **Takeover-as-Skip** — replaced router-side 409 with a `TakeoverGate` hook returning `HookDecision.Skip` from `before_tool`. |
| **#5 Generative UI** | Backend dual-emits `ui.plan.{init,delta}` (via `ExecutionPlan.enable_ui_events`) and `ui.chart.init` (via `UIEmitter` after chart artifact creation). New `GET /sessions/{sid}/ui/event-types` manifest endpoint. Frontend consumes typed events via the new `useUIComponents<T>(sessionId, componentType)` generic hook. `PlanHeader` rebuilt on `<Task>` AI Element. `ChartsTab` consumes `ui.chart.*`. New `TakeoverDialogModal` renders agent-initiated dialogs. AI Elements installed: `code-block`, `sources`, `reasoning`, `suggestion`, `task` + a hand-rolled `loader` (registry doesn't ship one). |

Plus backend additions for the demo polish layer: dynamic SSE event-type discovery (frontend fetches from the manifest, falls back to a static superset).

---

## Wave-by-wave landing log

### Round 1 — α + δ.11 (parallel, 2 agents)

**Agent A — Phase α (procedural memory + metacognition).** Backend.

- **SubAgent table consolidation:** deleted `db/models.py:SubAgent`, deleted `autonomy/store.py` entirely, deleted `routers/sub_agents.py` (verified zero frontend refs first). Rewrote `tools/autonomy.py` to use `workbench.memory.recall(filters=MemoryFilter(memory_type="procedural", skill_name=name))` for lookups and `workbench.memory.store(MemoryEntry(memory_type="procedural", content=name, structured_content=Skill(...).model_dump(), metadata={"agent_spec": spec.model_dump()}))` for persistence.
- **AgentSpec home:** chose `MemoryEntry.metadata["agent_spec"]` over `Skill.success_examples[0].outputs["agent_spec"]`. Reasoning: `success_examples` semantically represents *worked invocations*, not the agent contract; wedging the spec there pollutes the model. `metadata` is the natural home for protocol-defined free space.
- **Idempotent re-register:** SHA1-derived deterministic `MemoryEntry.id` from `(session_id, name)` so SQLite INSERT-OR-REPLACE upserts in place without read-then-update.
- **Metacognition wiring:** extended `_OUTPUT_SCHEMA` in `autonomy/analyst.py` with the three optional metacognition fields (`self_confidence` / `uncertain_about` / `outside_my_capability`); injected `StructuredOutputProtocol()` post-spawn (option (a) — `agent._confidence_protocol = ...`); switched `_invoke_agent` to `agent.run_enriched(state)` and lifted `enriched.{confidence,uncertainty_targets,capability_boundary}` into the returned JSON.
- **Hook registration:** `MetacognitionHook(workbench.event_bus, agent_name=...)` added to `HookRunner` alongside `EventBusPublishHook`.
- Test count: 93 → 91 (net -2: removed 3 sub-agents-route tests, added 1 metacognition test).

**Agent B — Phase δ.11 (AI Elements polish).** Frontend.

- Installed via `npx ai-elements@latest add`: `code-block`, `sources`, `reasoning`, `suggestion` (singular — registry doesn't have plural). `loader` not in registry → hand-rolled a 25-line `Loader` component using `Loader2Icon` + `animate-spin` themed via `text-accent`.
- **CodeBlock:** wired into `chat/Message.tsx`'s Markdown override — fenced code blocks render via `<CodeBlock>` with `<CodeBlockCopyButton>`. Inline `<code>` keeps the original Polymath accent/mono styling.
- **Sources:** registered as a built-in renderer in `ToolCard.tsx`'s `BUILTIN_RENDERERS` table for the `web_search` tool. Defensive `extractWebSearchResults` shape-checks; falls back to JSON dump on mismatch.
- **Reasoning:** added a render path for `part.type === "reasoning"` in `Message.tsx`. Refactored the original parts `.map` into an indexed `while` loop so consecutive reasoning parts collapse into one `<Reasoning>` block. Dormant when no reasoning parts arrive.
- **Suggestions:** replaced the static empty-state shortcut row in `ChatPane.tsx` with a `<Suggestions>` chip row of three prompts wired to `sendMessage({ text })`.
- **Loader:** replaced the `animate-slide-bar` keyframe block in `ToolCard.tsx` with the hand-rolled spinner (an accent strip showing "streaming…").
- typecheck + build: PASS.

### Round 2 — β.3-5 + β.6-7 (parallel, 2 agents)

**Agent C — Phase β.3-5 (UI emission + manifest).** Backend.

- `tools/plan.py:_init_plan` calls `plan.enable_ui_events(component_id="plan")` before `emit_init` — dual-emits `plan.init` AND `ui.plan.init` (and same for `set_task_status` deltas).
- `tools/report.py:_render_chart` emits a `ChartComponent` via `UIEmitter` after `create_artifact`. PNG-backed contract: `series=[]`, metadata carries `{artifact_id, artifact_path, mime: "image/png"}` so the frontend can round-trip back to the legacy `/artifacts/{id}` endpoint for the bytes. `component_id = f"chart-{artifact.id}"`.
- `_markdown_to_pdf`: deferred (PDFs need a `DocumentComponent` in `orqest.ui` core — assessment §6 Option B); left a `# TODO(orqest):` comment near the success path.
- New `routers/ui.py`: `GET /sessions/{sid}/ui/event-types` returns static base + dynamic `ui.<type>.{init,delta,remove}` from `Workbench.ui_registry.list_types()`. `GET /sessions/{sid}/ui/component-types` returns the component-type list.
- 8 new tests: 3 in `test_tools_plan.py`, 3 in `test_ui_routes.py`, 2 in `test_tools_report.py`.

**Agent D — Phase β.6-7 (Healing + takeover-as-Skip).** Backend.

- `config.py`: `ENABLE_HEALING: bool = True` + `FALLBACK_MODELS: tuple[str, ...] = ()` with env loading (`POLYMATH_ENABLE_HEALING`, `POLYMATH_FALLBACK_MODELS` comma-separated).
- `workbench_factory.py`: conditional `wb.with_healing(HealingConfig(fallback_models=cfg.FALLBACK_MODELS, enable_regression=True), api_key=cfg.LLM_API_KEY)`. New `TakeoverGate(session_id)` hook reading `polymath.runtime._runtimes[session_id].takeover_active` (constructor-injection style mirrors `EventBusPublishHook`).
- **Hook ordering:** `EventBusPublishHook → MetacognitionHook → TakeoverGate → WatchdogHook`. TakeoverGate runs before WatchdogHook so a user-driven session's tool deferrals beat any watchdog `Abort` (semantically correct: the user is intentionally not running tools).
- **Lazy lifecycle:** `get_runtime` stays sync; `routers/chat.py` calls `await runtime.ensure_started()` before the first turn (idempotent). `drop_runtime` becomes async; only callers (DELETE session + test fixtures) already await.
- `routers/chat.py`: dropped the explicit 409 takeover block. Tool deferral now happens at the hook layer (TakeoverGate → Skip), not the router.
- `_reset_config_and_runtimes` per-test fixture in `test_healing_integration.py` `cache_clear()`s config and `await drop_runtime(sid)`s every cached runtime — keeps env-mutation tests hermetic.
- 7 new healing tests + 4 new takeover-gate tests = 11 new tests.

### Round 3 — γ.8 + γ.9 + γ.10 (parallel, 3 agents)

**Agent E — Phase γ.8 (dynamic event-type fetching).** Frontend.

- Renamed `EVENT_TYPES` → `_FALLBACK_EVENT_TYPES` (24 entries, full pre-Phase-β superset including `metacognition.confidence`).
- New `useEventTypes(sessionId)` exported helper — fetches `/sessions/{sid}/ui/event-types` with `AbortController` (so unmount/sessionId change aborts the fetch), validates payload via runtime `isEventTypesResponse` type guard, returns `readonly string[]`, falls back on any error/malformed response.
- `useSidecar` deps on resolved `eventTypes`. **Trade-off:** when manifest resolves (typically <100ms after mount, before any agent activity), the EventSource closes and reopens once with the new list. Reconnects for *real* network errors during a session don't re-fetch the manifest (`eventTypes` is stable after first resolution).

**Agent F — Phase γ.9 (PlanHeader → Task element).** Frontend.

- Installed `<Task>` AI Element via `npx ai-elements@latest add task`. Built on shadcn `Collapsible`.
- `usePlan.ts`: added `ui.plan.init` / `ui.plan.delta` handlers in parallel with the legacy `plan.init` / `plan.task.updated`. Pure `applyDelta(state, delta)` helper handles `op: "replace"` at `tasks.<i>.status` and `tasks.<i>.subtasks.<j>.status`. Other ops/paths log debug + return state unchanged.
- `PlanHeader.tsx` rewritten on `<Task>` / `<TaskTrigger>` / `<TaskContent>` / `<TaskItem>`. Top-level summary trigger: `Plan (N/M complete)`. Tasks with subtasks render as nested `<Task>` (per-task collapse preserved). Status icons: lucide `Check` / `LoaderCircle` (animate-spin) / `X` / `Slash` / `Circle` keyed off existing accent / destructive / muted-foreground tokens.
- **Signature decision:** kept `<PlanHeader plan={plan}>` rather than `<PlanHeader sessionId={...}>` — `ChatPane.tsx` already calls `usePlan(sessionId)` and threads the result down; refactoring would either duplicate the SSE subscription or cascade-touch unrelated code. Minimal change won.
- Added `ui.plan.{init,delta}` to the static `_FALLBACK_EVENT_TYPES`.

**Agent G — Phase γ.10 (ChartsTab → `ui.chart.*`).** Frontend.

- New `useUIComponents<T>(sessionId, componentType)` generic hook. Returns `{components, byId}` (memoised array sorted newest-first by `created_at`; underlying `Map` for O(1) lookup). Handles `ui.<type>.init` (upsert), `delta` (apply per op), `remove` (delete). Pure exported `applyDelta` for unit-testability.
- **Delta op semantics:** `replace` (set value at path), `merge` (shallow object merge), `append` (push onto array), `remove` (delete key from object). Empty path targets `data` itself.
- **Defensive parsing:** delta with unresolvable path → spec unchanged; remove without `component_id` → silently ignored. Matches "fire-and-forget never breaks" Orqest convention.
- `ChartsTab.tsx`: drops `useArtifacts` for charts; consumes `useUIComponents<ChartData>(sessionId, "chart")`. PNG fetched via `metadata.artifact_id` round-trip to `/artifacts/{id}`. Auto-selects newest on first arrival. Empty state preserved verbatim. Future `ClientChart` branch wired with TODO for when the backend forwards structured plot data (per `tools/report.py` TODO from β.4).
- **No REST hydration in v1** — relies on SSE replay from the recent-events ring buffer.
- `useArtifacts.ts` left untouched — `ReportTab` / `FilesTab` / `EditorTab` still consume it.

### Round 4 — δ.12 (single agent)

**Agent H — Phase δ.12 (TakeoverDialog modal).** Frontend.

- New `TakeoverDialogModal.tsx` (~190 LOC). Subscribes via `useUIComponents<TakeoverDialogData>(sessionId, "takeover_dialog")`, renders the newest non-dismissed dialog as a Radix Dialog (existing shadcn wrapper at `src/components/ui/dialog.tsx`). Three kind dispatchers: `ConfirmBody` / `InputBody` / `ChoiceBody`.
- **Response shape:** discriminated union `{type: "confirm"|"cancel"|"input"|"choice", value?: string}`. POSTs to `/sessions/{sid}/takeover/respond` with `{component_id, response}`.
- **Optimistic dismissal:** local `dismissedIds: Set<string>` set *before* the await — modal closes even if the endpoint 404s. Forward-compat — the response endpoint doesn't exist yet (TODO documented).
- **Esc/overlay click → `{type: "cancel"}`** — modal cannot be silently dismissed.
- **Empty `choices` for `kind="choice"`** falls back to a confirm-only layout so a malformed payload never traps the user.
- Mounted at `src/app/sessions/[id]/page.tsx` page-shell level (sibling to header), so the Radix portal overlays both `ChatPane` and `ComputerPane`.
- Added `ui.takeover_dialog.{init,delta,remove}` to `_FALLBACK_EVENT_TYPES`.
- The existing `TakeoverButton.tsx` button affordance is **untouched** — modal is strictly additive (agent-initiated path; button stays as user-initiated path).

---

## Aggregate test outcomes

- **Backend tests: 91 → 109** (+18 net; one rewritten test for the dual-write migration assertion).
- **Frontend typecheck + build: clean** through every round.
- **Zero pre-existing tests broken.** Every test that needed to be rewritten was an explicit acceptance — `tests/test_takeover.py::test_chat_blocked_during_takeover` (asserted 409, replaced with hook-level Skip tests + a router-no-longer-409 sanity test).

---

## What this proves

A single user turn now demonstrates all five novel Orqest features end-to-end:

```
"benchmark the top 3 vector DBs and write me a PDF report"
    ↓
[orchestrator emits init_plan]                      → Plan rendered via <Task> from ui.plan.init
[orchestrator calls register_agent("analyst", ...)]  → Procedural memory entry persisted (Wave 1.2)
[orchestrator calls invoke_agent("analyst", ...)]    → run_enriched → metacognition.confidence event (Wave 1.3)
                                                     → confidence < threshold ⇒ MetaOrchestrator re-decomposes
[orchestrator calls render_chart(matplotlib)]        → ui.chart.init event → ChartsTab renders via useUIComponents
[provider 5xx mid-call]                              → FallbackModel advances chain; healing.model_fallback event (Wave 2)
[stuck shell command]                                → StallDetector → Abort decision (HookDecision)
[user clicks Takeover]                               → next tool call returns Skip stub (Wave 1.1 + 2.7)
[orchestrator emits TakeoverDialogComponent("approve discovery?")] → TakeoverDialogModal renders (Wave 3)
```

That's the screenshot.

---

## Outstanding work (out of scope for this consolidation)

1. **Backend `POST /sessions/{sid}/takeover/respond` endpoint** — currently the modal POSTs into the void; the endpoint translates the body into a `takeover.responded` event for the agent loop. Small, deferred.
2. **`DocumentComponent` in `orqest.ui` core** — for `markdown_to_pdf` to emit a typed UI event. Per assessment §6 Option B. Deferred until at least one consumer needs it.
3. **`ClientChart` renderer** — when `tools/report.py:_render_chart` starts forwarding structured plot data (`series`/`points` instead of just the matplotlib PNG), `ChartsTab` can render client-side via Plotly/Recharts. TODO comments in both files.
4. **Concept docs** — `docs/concepts/{metacognition,healing,generative_ui}.md` in Orqest core (still outstanding from the Wave 1-3 ship; Polymath consolidation didn't add to this list).

---

## Files changed at a glance

### Backend (Polymath)

```
DELETED:
  backend/polymath/autonomy/store.py
  backend/polymath/routers/sub_agents.py
  backend/polymath/db/models.py:SubAgent class

ADDED:
  backend/polymath/routers/ui.py
  backend/tests/test_healing_integration.py
  backend/tests/test_tools_plan.py
  backend/tests/test_ui_routes.py

MODIFIED (substantively):
  backend/polymath/agent.py (uses runtime.healing_runner.model when present)
  backend/polymath/autonomy/analyst.py (+3 metacognition fields)
  backend/polymath/config.py (+2 healing knobs)
  backend/polymath/runtime.py (lazy-start lifecycle, async drop)
  backend/polymath/server.py (-/+ routers)
  backend/polymath/tools/autonomy.py (full rewrite onto procedural memory)
  backend/polymath/tools/plan.py (enable_ui_events)
  backend/polymath/tools/report.py (UIEmitter for chart)
  backend/polymath/workbench_factory.py (MetacognitionHook + HealingRunner + TakeoverGate)
  backend/polymath/routers/chat.py (drop 409, ensure_started)
  backend/polymath/routers/sessions.py (await drop_runtime)
  backend/tests/test_runtime.py (await drop_runtime)
  backend/tests/test_takeover.py (hook-level Skip tests)
  backend/tests/test_tools_autonomy.py (full rewrite onto procedural-memory mocks)
  backend/tests/test_tools_report.py (+2 ui.chart.init tests)
```

### Frontend (Polymath)

```
ADDED:
  frontend/src/components/ai-elements/code-block.tsx (+ select.tsx)
  frontend/src/components/ai-elements/sources.tsx (+ collapsible.tsx)
  frontend/src/components/ai-elements/reasoning.tsx (+ shimmer.tsx)
  frontend/src/components/ai-elements/suggestion.tsx (+ scroll-area.tsx)
  frontend/src/components/ai-elements/loader.tsx (hand-rolled — registry doesn't ship one)
  frontend/src/components/ai-elements/task.tsx
  frontend/src/components/computer/TakeoverDialogModal.tsx
  frontend/src/hooks/useEventTypes.ts (or useSidecar.ts containment — agent's choice)
  frontend/src/hooks/useUIComponents.ts

MODIFIED (substantively):
  frontend/src/app/sessions/[id]/page.tsx (mount TakeoverDialogModal)
  frontend/src/components/chat/ChatPane.tsx (Suggestions in empty state)
  frontend/src/components/chat/Message.tsx (CodeBlock + Reasoning render paths)
  frontend/src/components/chat/PlanHeader.tsx (rewritten on <Task>)
  frontend/src/components/chat/ToolCard.tsx (Sources for web_search + Loader for streaming)
  frontend/src/components/computer/ChartsTab.tsx (consumes useUIComponents)
  frontend/src/hooks/usePlan.ts (ui.plan.init / delta handlers + applyDelta)
  frontend/src/hooks/useSidecar.ts (dynamic event-type fetch + fallback superset)
```

---

**Polymath consolidation complete. The flagship demo now runs on the post-Wave-3 Orqest substrate.**

---

## Post-consolidation stability + perf fixes (2026-04-25, late)

User-reported pain points after the consolidation:

1. Polymath wasn't using Orqest's `BaseAgent` — constructed raw `pydantic_ai.Agent` directly.
2. History wasn't persisted across page refresh — the agent forgot the conversation.
3. Some tools failed (`recall`, `list_dir`).
4. Frontend slowed down dramatically as the conversation grew.

Three parallel implementation agents + one direct fix landed in a single round.

### Bug fixes

| # | Bug | Root cause | Fix |
|---|---|---|---|
| 1 | `recall` tool failed | `tools/memory.py:58` called `store.recall(query, k=k, filter=mfilter)` — wrong kwarg name. `LocalMemoryStore.recall` signature is `(query, *, k, filters)` (plural). | One-line edit. `filter=` → `filters=`. |
| 2 | `list_dir` returned empty `{entries: []}` for *missing path*, *path-is-a-file*, AND *legitimately empty directory* — all three indistinguishable. Agent's POV: tool empty → workspace empty (instead of "the path is wrong"). | Manager's Python script in `sandbox/manager.py:list_dir` did `entries = os.listdir(p) if os.path.isdir(p) else []` and emitted the same shape for every case. | Tag stdout with `status` field (`ok` / `missing` / `not_a_directory`); manager raises `SandboxError` with a clear message for the two failure modes. `/workspace` root missing still returns `[]` (legitimately empty until first write to a fresh volume). 7 new tests at the manager + tool level. |
| 3 | Chat history not persisted across page refresh | `routers/chat.py:on_complete` was `logger.info(...)` only (a Phase-0 stub, "to implement in Phase 1"). `list_messages` returned hardcoded `{messages: []}`. | Implemented full message persistence. User message persisted **before** `VercelAIAdapter.dispatch_request` (crash-safe — prompt survives a mid-run crash). Assistant message persisted in `on_complete` by walking `result.new_messages()` for `ModelResponse`s and concatenating every `TextPart.content`. `list_messages` returns ordered rows; projection prefers `content_json.text`, falls back to parts, last-resort JSON-stringifies (forward-compat with future parts-only persistence). 4 new persistence tests. |
| 4a | N EventSources per session | `useSidecar(sid, cb)` opened a fresh `EventSource` every time it was called. With `usePlan` + `useArtifacts` + `useTakeover` + `useUIComponents` all calling it, each session held 4-6 simultaneous SSE connections; every event fanned out N times; every fanout triggered React re-renders in N hooks. | New `<SidecarProvider sessionId>` context owns ONE `EventSource` per session, dispatches via `Map<eventType, Set<handler>>` + a `subscribeAll` set. `useSidecar` becomes a thin context consumer; signature unchanged. Manifest-fetch + fallback + exponential-backoff reconnect semantics preserved. Subscriber sets independent of the connection effect — handlers survive reconnects without consumer involvement. |
| 4b | `ChatMessage` re-rendered every token for every history message; each re-render rebuilt `<ReactMarkdown>` + Shiki `<CodeBlock>` from scratch. | (a) `ChatMessage` not memoized; (b) `toolRenderers` default `{}` was a fresh object reference every parent render, defeating any memoization downstream; (c) heavy parts-loop ran inline in the component body, no `useMemo`. | `React.memo(ChatMessage)` shallow-compares props. `toolRenderers` stabilized via frozen module-level `EMPTY_RENDERERS` (`Object.freeze({})`) + `useMemo` in `ChatPane.tsx`. Parts-rendering loop pulled into `buildRenderables(message, toolRenderers)` and memoized via `useMemo` keyed on `[message, toolRenderers]`. AI SDK v6's `useChat` already keeps past-message references stable; only the streaming message gets a new ref each token. Combined: only the actively-streaming message re-renders; history is bailed out. |
| 5 | Polymath used raw `pydantic_ai.Agent` instead of `orqest.BaseAgent` | `agent.py:get_agent()` constructed `Agent(model=..., tools=[...])` directly. | New `orchestrator.py` defines `PolymathAgent(BaseAgent[PolymathState, str])` with `ContextManager()` for token-aware compaction (per-model budget table — 128k for OpenAI families, 200k for Claude families) and `confidence_protocol=StructuredOutputProtocol()` for forward-compat metacognition. `routers/chat.py` dispatches via `polymath_agent.agent` (the `BaseAgent.agent` property exposing the underlying `pydantic_ai.Agent`) — verified `get_agent() is get_polymath_agent().agent`, so no double-construction. `agent.py` kept as a back-compat shim re-exporting `get_agent` for any external script / MCP integration. |

### Verification

- Backend: 109 → **120** (+11 net new tests; 4 persistence + 6 sandbox manager `list_dir` + 1 fs tool error-shape).
- Frontend: typecheck + build clean.
- Live observable wins:
  - Browser devtools Network tab shows exactly **one** `/sessions/{id}/events` connection per session (was 4-6).
  - React DevTools profiler shows only the actively-streaming `<ChatMessage>` re-rendering per token (was every message in history).
  - Page refresh restores the full transcript including any in-progress turn's user prompt.
  - `list_dir` on a missing path now returns `{entries: [], error: "..."}` so the agent realises its path is wrong rather than concluding the workspace is empty.
  - `recall("...")` works.

### Files added / modified (stability fixes)

```
ADDED:
  backend/polymath/orchestrator.py
  frontend/src/hooks/SidecarProvider.tsx

MODIFIED:
  backend/polymath/agent.py (now back-compat shim re-exporting from orchestrator)
  backend/polymath/routers/chat.py (persistence + dispatches via polymath_agent.agent)
  backend/polymath/sandbox/manager.py (status-tagged list_dir Python script)
  backend/polymath/tools/fs.py (error shape preserves entries:[])
  backend/polymath/tools/memory.py (filter→filters typo)
  backend/tests/test_chat.py (4 persistence tests)
  backend/tests/test_tools_fs.py (1 error-shape test)
  backend/tests/test_sandbox_manager.py (6 list_dir tests)
  backend/tests/test_healing_integration.py (cosmetic docstring)
  frontend/src/hooks/useSidecar.ts (now a context consumer)
  frontend/src/components/chat/Message.tsx (React.memo + buildRenderables + useMemo)
  frontend/src/components/chat/ChatPane.tsx (stabilized toolRenderers via frozen EMPTY_RENDERERS)
  frontend/src/app/sessions/[id]/page.tsx (mount SidecarProvider over the session shell)
```

**Test count after consolidation + stability: 120.**

---

## Addendum — post-consolidation work (2026-04-25 same day)

The consolidation above was the foundation. Several follow-on rollouts shipped
on the same date and aren't reflected upstream in the body of this doc:

### 1. Browser feature gate (default off)

`POLYMATH_ENABLE_BROWSER` (default `False`) gates the browser tools on the
agent and the noVNC `BrowserTab` on the frontend. The Chromium + noVNC stack
is heavy; demos that don't exercise browser automation skip it. Sandboxed
HTML (`POLYMATH_ENABLE_SANDBOXED_HTML`) defaults **on** so the Layer 3
escape hatch is available without env tweaking.

### 2. Generative UI — 3-layer architecture

12 new typed `UIComponentSpec` classes shipped in `orqest/ui/components/`:
**Layer 1** (compositional): `layout`, `text`, `markdown`, `image`, `badge`,
`button`, `input`. **Layer 2** (declarative grammars): `vega_chart`, `mermaid`,
`latex`, `json_viewer`. **Layer 3** (escape hatch): `sandboxed_html` (iframe
with `sandbox="allow-scripts"` + strict CSP). Plus three Polymath-side tools
(`emit_component` / `update_component` / `remove_component`) and 12 matching
frontend renderers in `frontend/src/components/ui-renderers/` registered via a
side-effect barrel.

### 3. Right-pane tab manifest (persistent + dynamic)

Replaces the old hard-coded seven-tab strip with a Postgres-backed `Tab` table
(soft-close, 24 h tombstones, drag-reorder, focus persistence). Backend ships
**`backend/polymath/routers/tabs.py`** (REST), **`tools/tabs.py`** (agent
tools `open_tab` / `update_tab` / `close_tab`), and **`tab_respawn.py`** (an
EventBus subscriber that lazily ensures system tabs — Shell / Files / Editor
per-path / Browser / Report / Charts — exist on first relevant tool activity).
`emit_component` honors `metadata.target_tab_id` to group multiple components
in one tab.

### 4. Dockview migration

The hand-rolled tab strip + drag-reorder (Radix Tabs + dnd-kit) was replaced
with **dockview-react** (`dockview-core` + `dockview-react`). Files:
- **`frontend/src/components/computer/DockviewWorkspace.tsx`** — `<DockviewReact>` wrapper, `position: relative` + `absolute inset-0` so panels have a defined bounding box
- **`frontend/src/components/computer/panels/`** — one adapter per `Tab["kind"]` (Shell / Files / Browser / Editor / ChartGallery / Report / ComponentTab)
- **`frontend/src/styles/dockview-polymath.css`** — maps Polymath design tokens onto dockview's CSS variables (mono font, accent underline on active, hairline borders)
- **`frontend/src/hooks/useTabs.ts`** — rewritten as a SSE↔dockview↔REST bridge with three-way echo suppression (`ignoreNextFocus`, `ignoreNextClose`, `ignoreNextLayoutChange`)
- **Removed:** `DynamicTabStrip.tsx`, `DynamicTabContent.tsx`, `@dnd-kit/*`

Two bugs found and fixed via headless playwright verification:
- **Group splitting** — every `addPanel(...)` defaults to "new group". Fixed by passing `position: { referenceGroup: api.activeGroup ?? api.groups[0] }` on every call after the first.
- **SSE→panel race** — `TabComponentRenderer` ran `useAllUIComponents` inline, so its subscription mounted *after* the matching `ui.<type>.init` event was dispatched. Fixed by adding **`frontend/src/hooks/UIComponentsProvider.tsx`** at session-page level so the wildcard subscription is always live; `TabComponentRenderer` now reads from `useUIComponentsContext()`.

### 5. Tools registered on the agent

Final tool list on `PolymathAgent.__init__` (`backend/polymath/orchestrator.py`):
research (`web_search`, `web_fetch`), plan (`init_plan`, `update_plan`),
memory (`remember`, `recall`), sandbox (`read_file`, `write_file`, `edit_file`,
`list_dir`, `run_command`, `run_python_snippet`), browser (`browser_*`,
gated), reports (`render_chart`, `markdown_to_pdf`), autonomy (`register_agent`,
`invoke_agent`, `list_agents`, `spawn_analyst`), generative UI (`emit_component`,
`update_component`, `remove_component`), tabs (`open_tab`, `update_tab`,
`close_tab`).

### Test count

**170 backend tests** passing as of dockview-migration verification (was 120
post-consolidation: +18 tabs router, +11 tab_respawn, +9 tab tools, +12
generative UI tools, +2 ui router additions = +52 minus a couple
restructured cases). Frontend `tsc --noEmit` clean. Visual regression
verified via headless playwright (chart actually renders inside the
component tab, single tab strip across the workspace).

---

## Addendum — cognitive-backbone surfacing + chat-UX polish (2026-04-26)

Two waves shipped on this date, both surface-layer (no architectural
changes to the substrate underneath):

### Wave 1 — surfacing the cognitive backbone

Made the four "invisible" Orqest features visible in the chrome:

* **Per-message confidence badge** (`src/components/chat/ConfidenceBadge.tsx`)
  — driven by a new post-turn `LLMSelfRatingProtocol` invocation in
  `chat.py:on_complete` that emits a synthetic `metacognition.confidence`
  event keyed to the assistant message id. Gated on
  `POLYMATH_ENABLE_SELF_RATING` (default on, +1 LLM call per turn).
* **Healing toasts** (bottom-left stack via `HealingToasts.tsx` +
  `useHealingEvents.ts`) — surfaces all five `healing.*` events.
  Two new framework events added for richer payloads:
  `healing.retry_initiated` from `recovery.py`,
  `healing.model_chain_exhausted` from `fallback.py`.
* **Memory tab** (`kind='memory'`, auto-spawns on first `memory.*`
  event) — three-section semantic / episodic / procedural browser via
  `routers/memory.py` + `useMemory.ts` + `MemoryBrowser.tsx`. New
  `LocalMemoryStore.list_recent()` method on the framework. Procedural
  entries render their `Skill.steps` tool sequences inline. Recent
  recalls footer shows query → hit count.
* **Agents tab** (`kind='agents'`, auto-spawns on first `agent.*`
  event) — runtime sub-agent roster via `routers/autonomy.py` +
  `useAgentRoster.ts` + `AgentRoster.tsx`. Reads procedural memory
  entries that carry an `agent_spec` payload. Reuses the
  `ConfidenceBadge` primitive for per-invocation confidence display.

Backend infra: `Tab.kind` Literal extended with `memory` + `agents`;
`tab_respawn.py` adds memory + agent event-family rules; nine new event
types added to `_STATIC_EVENT_TYPES`.

Framework additions:
- `MetaOrchestrator(bus=...)` — optional EventBus injection so
  `metacognition.redecomposition_triggered` fires when low confidence
  triggers re-planning.

### Wave 2 — chat-UX polish (anti-AI-slop, AI Elements adoption)

Three-stream rollout that ditched the "template-flat" feel:

* **Per-turn metadata strip** below assistant messages
  (`12.3s · 4 tools · 1.2k tokens`) driven by new `chat.turn.completed`
  event + `useChatMetrics.ts`. Backend ships
  `polymath/session_metrics.py` aggregator (in-memory, per session).
* **Cumulative session token-usage ring** in the page header
  (`SessionContext.tsx` wrapping AI Elements `<Context>`) hydrated
  from `GET /sessions/{sid}.cumulative_usage`.
* **Inline confidence badge** moved into the assistant role-label row
  (was previously stacked above the body, took its own row).
* **Hover-revealed message actions** — Copy + Regenerate via AI
  Elements `<Actions>`. Regenerate walks back to the prior user
  prompt and re-`sendMessage`s.
* **Inline citations** — `[1]`/`[2]` markers in assistant prose render
  as `<InlineCitation>` hover-cards with title/url/snippet, falling
  back to the collapsed Sources tray when no markers present.
  System-prompt updated to teach the agent to emit numeric citation
  markers tied to fetched sources (otherwise the surface stays silent).
* **CodeBlock headers** with always-visible language label + copy
  button (was hover-only).
* **`<ChainOfThought>` for ≥2-tool turns** — `ToolStrip.tsx` adapter
  replaces the stacked `ToolCard`s when an assistant message has
  multiple tool calls.
* **Reasoning skim mode** — collapsed Reasoning blocks now show the
  first sentence (~80 chars) of the reasoning text below the trigger.
* **Composer toolbar** — refactored onto AI Elements `<PromptInput>`
  primitives; keyboard hints moved from below the form into the
  toolbar's left slot.
* **Checkpoint dividers** between turns where the plan-state hash
  changed (`CheckpointDivider.tsx`); visual + hover "Restore here"
  affordance, restore wiring deferred.
* **Tool error states** — single muted `Tool {name} failed · ...`
  line with hover-revealed Retry, replaces the raw JSON dump.
* **Density**: `gap-4` between messages (was `gap-6`); user-bubble
  padding `px-3 py-2` (was `px-3.5 py-2.5`); assistant `pl-2.5`
  (was `pl-3`).

AI Elements installed in this wave: `actions`, `inline-citation`,
`context`, `chain-of-thought`, `checkpoint`, `prompt-input` (full
primitives, replacing the Phase-0 placeholder).

Anti-slop discipline held throughout: no avatars, no bubbles with
tails, no rainbow gradients, one accent (teal), hover-revealed actions
only, mono 10–11px chrome, no "AI is thinking..." prose.

### Test count

**178 backend tests** passing (was 170 pre-Wave-2: +6 session metrics).
Orqest core 655 tests passing. Frontend `tsc --noEmit` clean across
both waves. End-to-end visually verified via headless playwright
during dockview migration; both Wave-1 and Wave-2 changes are
incremental on that verified surface.

---

## Addendum 2 — Wave-2 visual-bug fixes (2026-04-26)

The first headless-playwright visual inspection of the chat polish
flagged three blockers that source-side `tsc --noEmit` had passed.
All three fixed in the same session.

### Bug 1 — Composer collapsed to a 38px sliver

The AI Elements `<PromptInputBody>` wrapper applies `display: contents`,
which defeats its parent `<InputGroup>`'s `:has(>textarea)` and
`:has(>[data-align=block-end])` direct-child selectors. Result: the
input never flipped to `flex-col` + auto-height; submit button and kbd
hint were invisible.

Fix in `frontend/src/components/chat/Composer.tsx`: dropped the
`<PromptInputBody>` wrapper. `<PromptInputTextarea>` and
`<PromptInputFooter>` now render as direct children of `<PromptInput>`
(which mounts `<InputGroup>`), so the layout selectors fire.

### Bug 2 — Confidence badge + per-turn metadata strip never rendered

Both `useChatMetrics` and `useMetacognition` were keying their event-
attribution by the backend's `ModelResponse.id` (extracted from
pydantic-ai's `result.new_messages()`). The frontend's AI-SDK
`UIMessage.id` is generated client-side and does not match the
backend's id, so the join always missed.

Fix: both hooks now ignore the backend message id and attribute every
incoming event to whatever `currentAssistantId` the caller passes in
*at event-receive time* — captured in a ref so the SSE handler closure
always sees the latest value. Removes the `chatStatus`-transition
freeze pattern from `useMetacognition` (it was firing before the
post-turn `metacognition.confidence` event arrived from
`on_complete`'s self-rating).

Files: `frontend/src/hooks/useChatMetrics.ts`,
`frontend/src/hooks/useMetacognition.ts`,
`frontend/src/components/chat/ChatPane.tsx` (passes
`currentAssistantId` into `useChatMetrics`).

### Bug 3 — Missing prose on tool-heavy turns

Multi-tool turns rendered the chain-of-thought tool list but ended on
a tool call instead of a closing prose answer.

Fix: appended a *Behaviour* bullet to
`backend/polymath/system_prompts/orchestrator.md` instructing the
agent to **always end with a short prose answer** even when the heavy
lifting happened in tool calls or component emits. Reads better and
makes the chain-of-thought feel intentional rather than truncated.

### Bonus fix — Tooltip-provider error from `<Checkpoint>`

The AI Elements `<Checkpoint>` primitive uses Radix `<Tooltip>` without
mounting its own `<TooltipProvider>`. Each component that needed a
tooltip (`Actions`, `TakeoverButton`) had its own local provider,
which `<Checkpoint>` didn't.

Fix: mounted `<TooltipProvider delayDuration={200}>` at the session
root in `app/sessions/[id]/page.tsx`, wrapping
`<SidecarProvider>` + `<UIComponentsProvider>` + `<SessionShell>`.
Nested providers are fine in Radix — local ones inside `<Actions>` /
`<TakeoverButton>` continue to work.

---

## Addendum 3 — Wave-3 claude.ai/design editorial redesign (2026-04-26)

A full visual identity shift, ported from a claude.ai/design handoff
bundle (`/tmp/polymath-design/polymath/`). The handoff contained a
README + chat transcript + six JSX files: a design-system page, six
pixel-grade screens, three motion moments, plus a primitives library.
Implementation ran as three parallel streams after a foundational
tokens pass.

### The big bet — the Cognitive Gutter

Instead of an inline confidence pill, every assistant turn now renders
with a **24px-wide left rail** ("the column the message stands on"):

- Spine: 1px hairline running the full message height.
- Confidence bar: top-anchored, fills proportional to confidence, in
  one of four amber/muted/warn stops (`--color-conf-{high,mid,low,doubt}`).
- Event ticks at proportional positions: tool calls (squares),
  memory writes (violet dots), sub-agent spawns (cyan ticks).
- Live indicator: amber pulse pinned to the bottom while the turn is
  streaming.

This replaces the old per-message `<ConfidenceBadge>` row and ties the
chat thread to the workspace as one continuous through-line.

File: `frontend/src/components/chat/CognitiveGutter.tsx`.

### Stream A — Foundational tokens (`globals.css`)

Replaced cool teal `#0f766e` + cold dark `#0a0a0f` with **warm-neutral
oklch** + **amber signal accent**. Replaced Source Serif 4 + Source
Sans 3 with **Newsreader** (display serif) + **Inter Tight** (body
grotesk). Added new variable families for downstream surfaces:

```css
.dark {
  --color-background:        oklch(0.165 0.006 60);
  --color-foreground:        oklch(0.965 0.005 90);
  --color-surface-card:      oklch(0.205 0.006 60);
  --color-surface-elevated:  oklch(0.245 0.006 60);
  --color-muted-foreground:  oklch(0.78 0.008 80);
  --color-accent:            oklch(0.78 0.14 75);   /* amber, was teal */
  --color-accent-subtle:     oklch(0.78 0.14 75 / 0.16);
  --color-border-subtle:     rgba(255,255,255,0.06);
  --color-border-default:    rgba(255,255,255,0.10);
  --color-border-strong:     rgba(255,255,255,0.18);

  /* New families for Memory + Agents + healing surfaces */
  --color-kind-semantic:     oklch(0.78 0.06 220);  /* cyan */
  --color-kind-episodic:     oklch(0.72 0.10 290);  /* violet */
  --color-kind-procedural:   oklch(0.78 0.10 150);  /* good-green */
  --color-warn:              oklch(0.7 0.16 30);

  /* Confidence stops drive gutter + ConfidenceBadge + AgentRoster bars */
  --color-conf-high:  oklch(0.78 0.14 75);   /* ≥ 0.85 */
  --color-conf-mid:   oklch(0.62 0.13 65);   /* 0.65 – 0.85 */
  --color-conf-low:   oklch(0.58 0.008 80);  /* 0.45 – 0.65 */
  --color-conf-doubt: oklch(0.7 0.16 30);    /* < 0.45 */
}
```

The dockview tab strip's accent underline + active fill picked up the
new tokens automatically (the `dockview-polymath.css` theme references
the same `--color-*` variables).

### Stream B — Cognitive Gutter + Chat editorial polish

- `Message.tsx` rewritten — assistant messages now render as `flex`
  with the gutter on the left and the body on the right. Editorial
  header `POLYMATH · TURN NN · HH:MM:SS · tools`. Footer strip
  carries `conf · 0.78 · N tools · M tokens · K sources` plus a
  right-aligned `⌘+r retry · ⌘+f fork · ⌘+m memorize` mono kbd row.
  The old above-body `<ConfidenceBadge>` row is gone; the
  `ConfidenceBadge` component file is preserved (still consumed by
  `AgentRoster`).
- `useCognitiveGutterEvents.ts` — derives the gutter's event array
  from the message's own `parts` (MVP: spread tool-* parts evenly
  across `0..1`).
- Editorial empty state in `ChatPane.tsx` — "What should we /
  *think through* today?" (italic amber on `think through`),
  date-stamped masthead row, "continuing memory" three-thread list
  driven by `useRecentMemory`, commands legend (`/plan`, `/recall`,
  `/branch`, `/spawn`).
- `Composer.tsx` — placeholder `Pick up a thread, or start a new
  one.`, focus ring `0 0 0 3px oklch(0.78 0.14 75 / 0.08)`, kbd hint
  chips moved into the toolbar's left slot.
- `PlanHeader.tsx` — full visual rework. Serif title + chevron header,
  mono `4 of 7 · running` meta on the right. Each task row: zero-
  padded mono number + amber check / amber pulse-dot / muted dot
  status glyph + sans 12.5px label + optional mono tool name pinned
  right.

Files added: `CognitiveGutter.tsx`, `useCognitiveGutterEvents.ts`,
`useRecentMemory.ts`. Files modified: `Message.tsx`, `ChatPane.tsx`,
`Composer.tsx`, `PlanHeader.tsx`, `ConfidenceBadge.tsx`.

### Stream C — Memory + Agents + Top bar

- `app/sessions/[id]/page.tsx` — 40px editorial top bar. Diamond glyph
  (1px-bordered rounded square + amber clip-path diamond) + serif
  Polymath wordmark + slug session id (`XXX-XXXXXX` shape) +
  plan-derived context label + `model · opus 4.1` mono + the existing
  `<SessionContext>` token-usage ring (now amber by token swap) +
  `live`/`idle` indicator dot.
- `MemoryBrowser.tsx` rewritten — top half is a `460px × 1fr` grid
  with `<MemoryGalaxy>` SVG on the left (14-node constellation in
  cyan/violet/green with an amber dashed cluster ring) and a
  three-kind serif tagline + count cells on the right. Below: filter
  row + flat list of `<MemoryItem>` rows with kind-tinted left rails,
  serif italic titles for episodic entries, recalled-amber pills.
- `AgentRoster.tsx` rewritten as a roster table. Hero row with
  `roster` mono label + serif headline like "3 minds, one task." +
  4 summary cells (`depth · max`, `merged conf.`, `in flight`,
  `returned`). Column headers + rows: status dot (amber pulse for
  running, check for returned, muted for queued, × for failed) +
  serif italic name (italic on every row, not just episodic) +
  `↳` indent for `depth > 0` + model pill + inline confidence bar +
  status mono + tasks count + more-icon.
- Empty workspace state (`EmptyWorkspaceState.tsx`) — grid-line
  texture + `workspace · awaiting task` mono + serif italic line
  "Tabs appear when I reach for tools…" + row of muted kind pills.
  Mounted by `DockviewWorkspace.tsx` when `panels.length === 0`.

Files added: `MemoryGalaxy.tsx`, `MemoryItem.tsx`, `EmptyWorkspaceState.tsx`.
Files modified: `app/sessions/[id]/page.tsx`, `MemoryBrowser.tsx`,
`AgentRoster.tsx`, `DockviewWorkspace.tsx`,
`styles/dockview-polymath.css` (1 → 2px active-tab underline + fill
matching panel for "attached" feel).

### Anti-slop discipline (preserved throughout)

- No avatars, no bubble tails, no `rounded-2xl`, no rainbow gradients
- One amber accent + neutral grayscale; saturated color used at most
  once per visible region
- Hover-revealed actions only — no always-on toolbars
- Mono 10–11px chrome, sans 13–14px body, serif headings/quotes/
  agent-names
- No "AI is thinking..." prose; one Shimmer max per streaming turn
- No emoji in default UI strings
- No marketing copy in the empty state — "What should we / *think
  through* today?" + remembered threads, nothing greets the user

### Architectural compromises documented

- Galaxy SVG is mocked: backend doesn't yet emit topology data
  (`topology · N nodes · M edges` shows the live total node count but
  mocks edges as `2× nodes`).
- "Used in current turn" flag for memory entries is hardcoded false
  pending a backend signal.
- Agent depth is hardcoded — backend doesn't emit `parent_run_id`.
  Top-level rows render at depth 1, the implicit Polymath orchestrator
  at depth 0.
- Plan-title for the top bar context falls back to the active task's
  title (the `Plan` schema doesn't carry a top-level `title`).
- Empty-state overlay uses `pointer-events: none` so dockview drag/
  drop targets stay interactive while the overlay is showing.

### Test count

**178 backend tests** still passing post-redesign (no backend changes
in this addendum besides the orchestrator system prompt). Orqest core
**655 tests** still passing. Frontend `tsc --noEmit` clean.
Source-level audit confirms every redesign element is present in the
tree and dev-server-served at `HTTP 200`.
