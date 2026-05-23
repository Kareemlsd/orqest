# Polymath Assessment vs Post-Wave-3 Orqest

> **Date:** 2026-04-25
> **Scope:** how Polymath uses Orqest today, what's missing after Waves 1–3, and how AI SDK Elements should slot in to prove the cognitive-substrate vision
> **Anchors:** `~/repos/orqest/.claude/VISION.md`, `~/repos/orqest/.claude/IMPLEMENTATION_2026-04-25.md`
> **Methodology:** two parallel Explore agents (backend + frontend code recon) + WebFetch of `elements.ai-sdk.dev` for the AI SDK component catalog

---

## TL;DR — the headline

Polymath was built before Waves 1–3 and **does not consume any of the new Orqest features**:

- ❌ **Wave 1.1 HookDecision** — `HookRunner` is constructed only with `EventBusPublishHook`; no Skip/Redirect/Abort flow demonstrated.
- ❌ **Wave 1.2 Procedural memory** — Polymath has its **own** Postgres `SubAgent` table that **duplicates** `MetaOrchestrator._find_or_spawn`'s now-procedural persistence (~150 LOC of redundant code).
- ❌ **Wave 1.3 Metacognition** — analyst output schema has no `confidence`/`uncertainty` fields; `MetacognitionHook` is not wired; `RefinementLoop.confidence_threshold`/`agent_self_eval` not used; `MetaOrchestrator(metacognition=...)` not plumbed.
- ❌ **Wave 2.C Healing** — no `HealingRunner`, no `Workbench.with_healing`, no `FallbackModel`. Sandbox tool failures crash sessions.
- ❌ **Wave 2.D MCP auto-wire** — `ToolRegistry.get_or_discover` not used; analyst tools are hand-listed.
- ❌ **Wave 3 Generative UI** — backend emits `artifact.created` only; no `ui.<type>.{init,delta}` events. Frontend has hand-coded `ChartsTab`/`ReportTab` that consume `/sessions/{sid}/artifacts` REST instead of typed component specs.

**The strategic move is "Wave 4 — Polymath consolidation"** (called out in `IMPLEMENTATION_2026-04-25.md`). Migrating Polymath to use the post-Wave-3 surface validates the substrate claim end-to-end and is the single most valuable thing left to do for the demo.

The frontend has **partial** AI SDK Elements adoption — four components copied via `npx ai-elements add` (`conversation.tsx`, `message.tsx`, `prompt-input.tsx`, `tool.tsx` under `src/components/ai-elements/`). Six more high-leverage Elements components fit cleanly: **Task, Sources, CodeBlock, Reasoning, Suggestions, Loader**.

---

## 1 · What Polymath uses from Orqest today

| Orqest module | Polymath usage | Citation |
|---|---|---|
| `Workbench` | `Workbench(memory + tracer + event_bus)` per session | `workbench_factory.py:47` |
| `LocalMemoryStore` | one SQLite DB per session under `cfg.MEMORY_DIR/{sid}.db` | `workbench_factory.py:43` |
| `JSONTracer` | per-session tracer | `workbench_factory.py:44` |
| `EventBus` + `sse_sidecar` | event fan-out + SSE stream over `/events` | `runtime.py:46`, `routers/events.py:35` |
| `EventBusPublishHook` | the only hook in `HookRunner` | `workbench_factory.py:48-50` |
| `ExecutionPlan`, `PlanTask`, `PlanSubtask`, `PlanStatus` | plan tracking via `tools/plan.py` | `state.py:30`, `tools/plan.py:51-67` |
| `ExecutionPlan.emit_init()` / `set_task_status()` | legacy `plan.init` / `plan.task.updated` events | `tools/plan.py:71`, `:97-103` |
| `AgentSpec`, `ToolSpec`, `AgentFactory.spawn`, `ToolRegistry`, `DynamicAgent` | analyst sub-agent spawning | `autonomy/analyst.py:54-100`, `tools/autonomy.py:50-156` |
| `MemoryEntry`, `MemoryFilter` | semantic + episodic recall via `tools/memory.py` | `tools/memory.py:34, 57` |
| `BaseSessionState`, `GlobalState` | per-session state + sub-agent invocation state | `state.py:19`, `tools/autonomy.py:155` |
| `web_search`, `web_fetch` from `orqest.tools.web` | research tools registered on the orchestrator | `agent.py:63-64`, `autonomy/analyst.py:19-20` |
| `load_sys_prompt` | loads `system_prompts/orchestrator.md` | `agent.py:47` |
| `resolve_model` | one-shot model resolution | implicitly via `pydantic_ai.Agent` |

**Verdict: Polymath uses every shipped Orqest battery from before 2026-04-25 morning. Zero usage of anything from Waves 1–3 (afternoon-of-2026-04-25 features).**

---

## 2 · The big duplication — `SubAgent` table vs. procedural memory

This is the single highest-priority finding.

### What Polymath has today

Schema: `db/models.py:63-82` — a `SubAgent` SQLModel table with `(id, session_id, name, role, spec_json, created_at, updated_at)`.

Persistence layer: `autonomy/store.py:26-106` — `upsert_sub_agent`, `get_sub_agent`, `list_sub_agents`, `delete_sub_agent` — SQL CRUD over the table.

Tool wiring: `tools/autonomy.py:62-235` — three tools (`register_agent`, `invoke_agent`, `list_agents`) that hit the table.

### What Orqest now does natively

Per Wave 1.2 (shipped 2026-04-25): `MetaOrchestrator._find_or_spawn` dual-writes every spawned agent's `AgentSpec` as both an episodic memory mirror **and** a procedural `Skill` entry in `LocalMemoryStore`. Recall is procedural-first (matched on the trigger field) with episodic fallback. Cross-session reuse is automatic.

The `Skill` shape (`orqest/memory/store.py`) carries `name`, `description`, `trigger`, `tool_sequence: list[ToolCallSpec]`, `expected_outcome`, `success_examples`, `version`.

### Why these are the same thing

Both store an `AgentSpec` keyed by `(session_id, name)` and retrieve it by name. Polymath's "role" field maps to `Skill.description`. Polymath's name maps to `Skill.name` (and to the `trigger` if you want fuzzy invocation).

### Migration

1. **Rewrite** `tools/autonomy.py:_register_agent` to call `workbench.memory.store(MemoryEntry(memory_type="procedural", content=name, structured_content=Skill(name=name, description=role, trigger=name, ...).model_dump()))`.
2. **Rewrite** `_invoke_agent` to call `workbench.memory.recall(name, k=1, filters=MemoryFilter(memory_type="procedural", skill_name=name))` — the first hit hydrates the spec.
3. **Rewrite** `_list_agents` to call `recall(query="", k=50, filters=MemoryFilter(memory_type="procedural"))`.
4. **Delete** `db/models.py:63-82` (`SubAgent` table) and `autonomy/store.py` entirely.
5. **Delete** the `routers/sub_agents.py` HTTP routes if they're not consumed by the frontend (verify), or rewrite them to read memory.

**Net: ~250 LOC removed, ~80 LOC added. One fewer DB table. The frontend's Sub-Agents view (if any) keeps working; the data source flips from Postgres to SQLite memory store.**

---

## 3 · The five novel features × Polymath today

### 3.1 Vision feature #1 — Runtime agent design ✅ partially proven, not consolidated

Polymath shows runtime agent spawning end-to-end (analyst sub-agent via `MetaOrchestrator`-style flow, `register_agent`/`invoke_agent`/`list_agents` tools). But it does this **without** consuming Orqest's procedural-memory persistence (see §2).

**Action:** consolidate per §2 above.

### 3.2 Vision feature #2 — Cognitive memory typology 🟡 only semantic+episodic

Polymath uses `LocalMemoryStore` via the `remember`/`recall` tools — but only stores semantic memories. No procedural skills, no kind-aware retrieval strategy, no per-kind `PerKindConfig`.

**Action:** the consolidation in §2 implicitly proves procedural memory. Additionally:
- Add a Polymath demo prompt that exercises procedural recall: *"register a skill for benchmarking vector DBs, then on the next turn ask me to benchmark Pinecone — the agent should find and reuse the skill"*.
- Wire `MemoryConfig.PerKindConfig(version_on_edit=True)` for the procedural track so skill revisions accumulate.

### 3.3 Vision feature #3 — Metacognition ❌ not wired at all

Polymath's analyst output schema (`autonomy/analyst.py:31-51`) has fields `summary`, `findings`, `next_steps` — **no confidence**, no uncertainty_targets, no capability_boundary.

**Action:**
1. Extend the analyst's output schema with `self_confidence: float | None`, `uncertain_about: list[str]`, `outside_my_capability: bool` (the field names `StructuredOutputProtocol` reads by default).
2. In `autonomy/analyst.py`, when constructing the `AgentSpec`, pass an `AgentFactory` whose spawned `DynamicAgent` has `confidence_protocol=StructuredOutputProtocol()`.
3. In `tools/autonomy.py:_invoke_agent`, replace `agent.run(state)` with `agent.run_enriched(state)` and lift `enriched.confidence` into the returned JSON.
4. Add `MetacognitionHook(workbench.event_bus, agent_name="analyst")` to `workbench_factory.py:HookRunner` alongside `EventBusPublishHook`. This emits `metacognition.confidence` events the frontend can render.
5. Pass `MetacognitionConfig(redecompose_threshold=0.5)` to any `MetaOrchestrator(metacognition=...)` Polymath spawns.

**Frontend follow-on:** add a `ConfidenceIndicator` component that subscribes to `metacognition.confidence` and renders a small badge on the relevant tool card / sub-agent row. AI SDK's `ToolHeader` `getStatusBadge` utility could host this.

### 3.4 Vision feature #4 — Self-healing ❌ not wired

Polymath has no `HealingRunner`, no `FallbackModel`, no watchdogs. A stuck `render_chart` (matplotlib timeout) just hangs the session. A 5xx from OpenAI fails the whole turn.

**Action:**
1. In `workbench_factory.py:build_workbench`, after constructing the `Workbench`, call `runner = wb.with_healing(HealingConfig(enable_loop=True, enable_stall=True, enable_regression=True, fallback_models=("openai:gpt-4.1", "anthropic:claude-sonnet-4-6")), api_key=cfg.llm_api_key)`. Store the runner alongside the workbench in `SessionRuntime`.
2. Start the runner via `async with runner:` in the chat-stream route (`routers/chat.py`). Stop on session close.
3. Register `runner.hook` on the `HookRunner` alongside `EventBusPublishHook` — watchdogs now influence compound flows via `HookDecision`.
4. Replace the `pydantic_ai.Agent(model=resolve_model(...))` construction in `agent.py` with `runner.model or resolve_model(cfg.LLM_MODEL, api_key=cfg.LLM_API_KEY)` — the agent now has a fallback chain when `fallback_models` is configured.
5. **Demo dividend:** kill the OpenAI key mid-session, watch Polymath fall back to Anthropic without a turn failure. Emit `healing.detection` and `healing.model_fallback` events show up in the chat UI as small "agent recovered" badges.

**Frontend follow-on:** add a `HealingTab` (or a banner on top of the existing tabs) that shows recent `healing.detection` and `healing.action` events.

### 3.5 Vision feature #5 — Generative UI ❌ not wired

Polymath's backend never emits `ui.*` events. Every artifact (chart, report) goes through the legacy `artifact.created` + REST `/sessions/{sid}/artifacts/{id}` fetch. The frontend's `ChartsTab` and `ReportTab` are hand-coded around this assumption.

**Action — backend:**

1. In `tools/plan.py:init_plan`, after constructing the `ExecutionPlan`, call `plan.enable_ui_events(component_id="plan")` so that `set_task_status` / `emit_init` dual-emit `ui.plan.{init,delta}`.
2. In `tools/report.py:render_chart`, after `create_artifact(...)`, also emit a `ChartComponent` via a `UIEmitter`:
   ```python
   from orqest.ui import ChartComponent, ChartComponentData, ChartSeries, UIEmitter
   emitter = UIEmitter(workbench.event_bus, agent_name="polymath")
   await emitter.init(ChartComponent(
       component_id=f"chart-{artifact.id}",
       data=ChartComponentData(
           chart_kind=detected_kind,  # the chart's kind, e.g. "bar" — the matplotlib snippet hint
           title=label,
           series=[ChartSeries(name="data", points=[{"x": ..., "y": ...}])],
       ),
   ))
   ```
3. Same pattern for `tools/report.py:markdown_to_pdf` — emit a `DocumentComponent` (which doesn't exist in Orqest yet — see §6 below).
4. New router `routers/ui.py` exposing `GET /sessions/{sid}/ui/event-types` (returns `Workbench.ui_registry.list_types()` mapped to `["ui.plan.init", "ui.plan.delta", "ui.plan.remove", "ui.chart.init", ...]`) — eliminates the frontend's hardcoded `EVENT_TYPES` list.
5. New router exposing `GET /sessions/{sid}/ui/snapshot` that reconstructs each known `component_id`'s current state from the recent-events ring buffer (generalises Polymath's existing `/sessions/{sid}/plan` endpoint).

**Action — frontend:** see §5 below.

---

## 4 · Hook usage — the most under-exercised feature

Polymath constructs `HookRunner([EventBusPublishHook(bus)])` and never uses anything else. After Wave 1.1, `HookDecision` enables four meaningful flows that Polymath could demonstrate:

| Flow | Hook | Behaviour | Demo value |
|---|---|---|---|
| **Takeover-as-Skip** | A `TakeoverGate` hook returns `Skip(reason="user has control", stub_result={"deferred": True})` from `before_tool` while `runtime.takeover_active` is True | Today the chat router (`routers/chat.py:37-41`) blocks chat streams with HTTP 409, but tool calls inside an in-flight turn still execute. Move the gate to a hook so it fires uniformly. | Cleaner architecture; demonstrates `Skip` |
| **Sanitiser** | A `ShellSanitiser` hook returns `Redirect(new_args={"command": sanitised})` when `tools/shell.run_command` would run `rm -rf` | Inject a security policy without forking the tool | Demonstrates `Redirect` |
| **Watchdog** | `HealingRunner.hook` (covered in §3.4) | Returns `Continue`/`Redirect`/`Abort` based on detector signals | Demonstrates `HookDecision` × healing |
| **Confidence-aware abort** | A `ConfidenceGate` hook reads the last `metacognition.confidence` event and returns `Abort(reason="low confidence ladder")` if confidence has dropped below a threshold | Only safe once metacognition is wired | Demonstrates the metacognition × hooks × healing handshake |

**Action:** start with the Takeover-as-Skip — it's a refactor of existing logic, not a new feature, and proves the protocol with low risk.

---

## 5 · AI SDK Elements — fit assessment

Polymath has 4/29 elements installed (shadcn-copy style):

```
demo/polymath/frontend/src/components/ai-elements/
├── conversation.tsx        # custom thin wrapper around StickToBottom
├── message.tsx             # message + content + avatar
├── prompt-input.tsx        # PromptInput suite
└── tool.tsx                # Tool/ToolHeader/ToolContent/ToolInput/ToolOutput
```

The remaining 25 elements are unused. After research against Polymath's needs, **six more should ship**:

### 5.1 `Task` — replace `PlanHeader.tsx` ⭐ highest leverage

> *"A collapsible task list component for displaying AI workflow progress, with status indicators and optional descriptions."* — `elements.ai-sdk.dev/components/task`

Component family: `Task`, `TaskTrigger`, `TaskContent`, `TaskItem`, `TaskItemFile`. Maps directly to Orqest's `PlanComponentData.tasks: list[PlanTask]`.

**Why now:** the existing `PlanHeader.tsx` is hand-rolled (~95 lines) and consumes the legacy `Plan` type from `usePlan` hook. Migrating it to (a) consume `ui.plan.{init,delta}` events from `useSidecar` and (b) render via `<Task>`/`<TaskItem>` would:
- Replace ~95 LOC of bespoke checklist UI with the AI Elements primitive (themable, accessible, file-references via `TaskItemFile` for tool outputs).
- Validate `ExecutionPlan.enable_ui_events()` end-to-end — the keystone Wave 3 demo.
- Drop the dependency on `/sessions/{sid}/plan` REST hydration.

**Cost:** 1-2 days. Adds ~50 LOC to consume events + the `<Task>` import.

### 5.2 `Sources` + `Source` — citation rendering for `web_search` ⭐ high leverage

> Renders message parts with `type: "source-url"` as a collapsible list of citations.

Polymath's `web_search` tool returns a JSON envelope rendered as opaque text inside the bespoke `ToolCard`. Adopting `Sources` requires the backend to:
1. Emit web_search results as `source-url` parts on the assistant message (per AI SDK convention).
2. Or — more in-keeping with Orqest patterns — emit a custom `SourcesComponent` (a new Orqest first-party component) that the frontend wraps with `<Sources>` rendering.

**Why now:** transforms web_search from "raw JSON" to "named, clickable citations" — matches the visual quality bar of Manus/Devin demos.

**Cost:** 2 days (backend emission contract + frontend wiring).

### 5.3 `CodeBlock` + `CodeBlockCopyButton` — code rendering everywhere ⭐ medium-high leverage

Polymath currently renders code through `react-markdown`'s `<pre>` fallback (no syntax highlighting beyond basic CSS). `CodeBlock` ships:
- Shiki-powered syntax highlighting with bundled language packs
- Light/dark theme automation via CSS variables
- One-click copy with timeout-driven confirmation state

**Slots into:**
- `ChatMessage.tsx` — replace `<pre>` Markdown renderer when language is detected.
- `EditorTab.tsx` — read-only file preview (Monaco for editing, but `CodeBlock` for "agent just wrote this" inline preview in chat).
- `ToolOutput` for tool calls returning code (`run_python_snippet` results).

**Cost:** 0.5-1 day (small wiring, CSS vars need verification).

### 5.4 `Reasoning` + `ReasoningTrigger` + `ReasoningContent` — agent thinking display ⭐ medium leverage (depends on backend)

> Collapsible thinking-content panel that auto-opens during streaming, auto-closes when finished. Reads message parts with `type: "reasoning"`.

**Today:** Polymath does not surface chain-of-thought. If the orchestrator runs Claude with extended thinking, those reasoning blocks are discarded.

**Action if adopted:**
1. Configure pydantic-AI to forward reasoning parts (Claude extended thinking, OpenAI o1 reasoning summaries).
2. Wire `<Reasoning>` into `ChatMessage.tsx` to render those parts.

**Why now:** signals to demo viewers that Polymath surfaces *how* the agent decided, not just *what* it decided — a trust affordance directly aligned with the metacognition vision.

**Cost:** 1-2 days (backend forwarding + frontend rendering). May require pydantic-AI version bump for reasoning-part exposure.

### 5.5 `Suggestions` + `Suggestion` — empty-state prompt chips ⭐ low leverage but high polish

The empty state (`ChatPane.tsx`) currently shows three example prompts as static text. `Suggestions` renders them as click-to-send chips that dispatch `useChat.sendMessage(...)` on click.

**Cost:** half a day. Cosmetic but matches user expectations from Vercel demos.

### 5.6 `Loader` + streaming indicators — replace `animate-slide-bar` ⭐ low leverage

Polymath has a custom `animate-slide-bar` keyframe in `ToolCard.tsx` for the "tool is streaming" state. AI Elements' `Loader` provides this consistently. Drop the custom keyframe.

**Cost:** half a day. Pure cleanup.

### 5.7 `Branch` — *deferred*

`Branch` enables branching conversations (alternate replies). Polymath is single-thread today. Could be revisited if the demo wants to showcase "what if I asked the analyst differently" — but nothing in the current design pushes for it.

### Components NOT recommended for adoption

| Element | Reason to skip |
|---|---|
| `Attachments` family | Polymath's tools don't take user-uploaded files (everything goes through the sandbox). Re-evaluate if a "file upload to /workspace" UX lands. |
| `WebPreview` | Browser tab already shows the full noVNC iframe — a small URL-card preview is redundant. |
| `Image` | Charts are emitted as full ChartComponents, not standalone images. |
| `Artifact` (if Vercel ships one) | Polymath's right-pane tabs are richer than a generic artifact viewer. |

---

## 6 · One missing first-party Orqest component — `DocumentComponent`

The frontend audit flagged that `ReportTab.tsx` (PDF preview iframe) has no Orqest equivalent. Two options:

**Option A — leave Report as a Polymath-domain component.** PDFs are output of `tools/report.py:markdown_to_pdf`; Polymath-specific. Frontend stays hand-coded; consumed via `ui.<custom>.init` registered against Polymath's `Workbench.ui_registry`.

**Option B — add `DocumentComponent` to `orqest.ui`.** Generic shape:
```python
class DocumentComponentData(BaseModel):
    title: str = ""
    mime: Literal["application/pdf", "text/markdown", "text/html"]
    artifact_id: str | None = None       # if served via the artifact registry
    content: str | None = None           # inline (for short markdown)
    download_url: str | None = None
```

**Recommendation: Option B.** Documents are a generic shape — any agent producing a PDF/markdown/HTML artifact wants this. Adding it to core completes the first-party catalog (Plan/Chart/Table/Form/TakeoverDialog/**Document**) without violating the litmus test ("could a coding-assistant builder use this without knowing what numatics-ai is?" — yes, code-assistant agents emit markdown plans / PDFs / HTML reports all the time).

---

## 7 · Recommended changes — prioritized by leverage

| # | Change | Files touched | Effort | Demo value |
|---|---|---|---|---|
| **1** | **Consolidate SubAgent table → procedural memory.** Delete the table; rewrite `tools/autonomy.py` to call `workbench.memory`. | `db/models.py`, `autonomy/store.py` (delete), `tools/autonomy.py`, `routers/sub_agents.py` | 2 d | Closes the audit's flagged duplication; demonstrates Wave 1.2. |
| **2** | **Wire metacognition** — add confidence fields to analyst output schema, switch to `run_enriched`, register `MetacognitionHook`. | `autonomy/analyst.py`, `tools/autonomy.py`, `workbench_factory.py` | 2 d | Demonstrates Wave 1.3; unblocks #6 below. |
| **3** | **Backend: `ui.plan.{init,delta}` dual emission.** Call `plan.enable_ui_events()` in `tools/plan.py:init_plan`. | `tools/plan.py` | 0.5 d | Frontend-side migration becomes possible. |
| **4** | **Backend: `ui.chart.init` emission for charts.** Wrap `tools/report.py:render_chart` with `UIEmitter.init(ChartComponent(...))`. | `tools/report.py`, possibly new `orqest.ui.DocumentComponent` if §6 Option B taken | 1 d | Validates Wave 3 end-to-end. |
| **5** | **Backend: `GET /sessions/{sid}/ui/event-types` manifest endpoint.** Returns `workbench.ui_registry.list_types()` × `{init,delta,remove}`. | new `routers/ui.py` | 0.5 d | Unblocks frontend dynamic-listener migration. |
| **6** | **Wire `HealingRunner` into `Workbench`.** Add `with_healing(...)` call in `workbench_factory.py`. | `workbench_factory.py`, `runtime.py`, `routers/chat.py` (lifecycle) | 1.5 d | Demonstrates Wave 2; the "agent recovers when OpenAI 5xx" demo. |
| **7** | **Refactor takeover from router-block to `HookDecision.Skip`.** | `routers/takeover.py`, `workbench_factory.py` (new hook), `routers/chat.py` (drop the manual 409 block) | 1 d | Demonstrates `HookDecision` Skip pattern. |
| **8** | **Frontend: dynamic event-type fetching.** Replace hardcoded `EVENT_TYPES` array in `useSidecar.ts` with `GET /ui/event-types` on mount. | `frontend/src/hooks/useSidecar.ts` | 0.5 d | Removes the maintenance bottleneck. |
| **9** | **Frontend: migrate `PlanHeader.tsx` to `<Task>` + `ui.plan.*` events.** Install `Task` element via `npx ai-elements@latest add task`. | `frontend/src/components/chat/PlanHeader.tsx`, `frontend/src/hooks/usePlan.ts` (deprecate) | 1.5 d | Validates Wave 3 frontend; visible polish. |
| **10** | **Frontend: migrate `ChartsTab.tsx` to consume `ui.chart.*` events.** Render via Plotly directly from `ChartComponentData.series`. | `frontend/src/components/computer/ChartsTab.tsx`, possibly `useArtifacts.ts` | 1.5 d | Validates Wave 3 end-to-end; eliminates artifact-fetch roundtrip. |
| **11** | **Frontend: install `CodeBlock`, `Sources`, `Reasoning`, `Suggestions`, `Loader`.** Wire each into the existing components per §5. | `frontend/src/components/ai-elements/*` (new files), `chat/ChatMessage.tsx`, `chat/ToolCard.tsx`, empty-state in `chat/ChatPane.tsx` | 2 d | Visual polish + matches Vercel-demo bar. |
| **12** | **Frontend: takeover modal.** Listen for `ui.takeover_dialog.init`; render with the existing `TakeoverButton.tsx` component family. | `frontend/src/components/computer/TakeoverButton.tsx` | 1 d | Demonstrates dynamic UI components. |

**Total estimated effort:** ~14 days of focused work.

**Suggested phasing:**
- **Phase α (3 days):** items 1, 2 — back-end alignment with Waves 1.2 + 1.3. Closes the duplication and unblocks confidence-driven flows.
- **Phase β (4 days):** items 3, 4, 5, 6, 7 — back-end Wave 2/3 wiring.
- **Phase γ (5 days):** items 8, 9, 10 — front-end Wave 3 migration.
- **Phase δ (2 days):** items 11, 12 — polish + AI Elements polish layer.

---

## 8 · What this proves for Orqest's vision

Today Polymath is a **pre-Wave-1 demo** that happens to live in the post-Wave-3 repo. It demonstrates only feature #1 (runtime agent design) and a clean usage of Phase 1–5 batteries.

After the prescribed changes, Polymath demonstrates **all five novel features** end-to-end in one coherent demo:

1. **Runtime agent design** — `register_agent` / `invoke_agent` / `list_agents`, now backed by procedural memory (item 1).
2. **Cognitive memory typology** — Polymath demonstrates procedural recall on a follow-up turn (item 1, plus a demo prompt).
3. **Metacognition** — analyst sub-agents emit `metacognition.confidence` events; the chat UI shows confidence badges; low-confidence subtasks trigger orchestrator re-decomposition (item 2).
4. **Self-healing** — kill the LLM provider mid-turn, watch fallback to the next; watchdogs detect a stuck shell command and abort cleanly (item 6, item 7).
5. **Generative UI** — every visible piece of the right pane (plan, charts, takeover dialog) is rendered from `UIComponentSpec` events; new component types can be registered without frontend redeploy (items 3-5, 8-10, 12).

**That's the screenshot.** A single user turn — *"benchmark the top 3 vector DBs and write me a PDF report"* — that demonstrates every novel feature at once, from a single-screen UI.

---

## 9 · Open questions to resolve before starting

1. **`DocumentComponent` location** — does Orqest core gain a first-party `DocumentComponent` (Option B in §6), or does Polymath register a Polymath-domain `ReportComponent` against its own `Workbench.ui_registry`?
2. **AI SDK Elements vs hand-coded — is there a future where Polymath drops the bespoke `Conversation`/`Message`/`PromptInput` and uses the registry-installed `npx ai-elements add` versions verbatim?** Polymath's design language is currently a custom statement; standardising on Vercel's defaults would lose that distinctness. Worth a design call.
3. **Polymath frontend domain extraction** — should `events.ts` separate Orqest-core event types from Polymath-domain event types into two unions, so a third-party Orqest consumer can reuse the core hook layer? Current shape is monolithic (the audit's cross-cutting issue #1).
4. **`run_enriched` vs `run` — should the orchestrator's main `Agent` (not just sub-agents) run with `run_enriched`?** This would surface the orchestrator's own confidence to the user, which is powerful but potentially noisy.
5. **MetaOrchestrator vs the analyst pattern** — Polymath uses a hand-rolled "analyst as a tool" pattern (`tools/autonomy.py:_invoke_agent`). After consolidation onto procedural memory, would the proper move be to instantiate `orqest.MetaOrchestrator` directly and call `solve(goal)`? That would replace the analyst tool with an orchestrator tool. Decision deferred until item 1 ships.

---

## Sources

- [AI Elements registry](https://elements.ai-sdk.dev/) — full component catalog
- [AI Elements changelog announcement](https://vercel.com/changelog/introducing-ai-elements) — 20+ production-ready React components
- [vercel/ai-elements GitHub](https://github.com/vercel/ai-elements) — source + shadcn registry
- [AI SDK 6 docs](https://ai-sdk.dev/docs/ai-sdk-ui) — useChat / UIMessage shape
- Component pages fetched: [Conversation](https://elements.ai-sdk.dev/components/conversation), [Message](https://elements.ai-sdk.dev/components/message), [Tool](https://elements.ai-sdk.dev/components/tool), [CodeBlock](https://elements.ai-sdk.dev/components/code-block), [Reasoning](https://elements.ai-sdk.dev/components/reasoning), [PromptInput](https://elements.ai-sdk.dev/components/prompt-input), [Sources](https://elements.ai-sdk.dev/components/sources), [Task](https://elements.ai-sdk.dev/components/task), [Attachments](https://elements.ai-sdk.dev/components/attachments)
