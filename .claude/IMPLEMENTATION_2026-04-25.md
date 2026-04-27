# Orqest Implementation Plan — 2026-04-25

> **Anchors:** `.claude/VISION.md` (durable goal), `.claude/AUDIT_2026-04-25.md` (point-in-time state)
> **Detailed designs:** `.claude/designs/01-metacognition.md`, `.claude/designs/02-self-healing.md`, `.claude/designs/03-ui-and-procedural-memory.md`
> **Status:** ✅ **All three waves shipped on 2026-04-25 (same day this plan was written).** Test suite 360 → 612. All 360 pre-existing tests held green at every wave boundary. See `AUDIT_2026-04-25.md` § Resolution log for the per-finding outcome.

This is the executable bridge between *what Orqest needs to become* (the five novel features) and *what we ship next*. Three Plan agents deep-validated the audit's claims and produced concrete implementation designs. Their full output lives in the `designs/` subdirectory; this file is the cross-track synthesis with sequencing, conflict resolution, and the pre-flight checklist.

---

## Findings the deep-dive corrected from the audit

The audit's verdicts were broadly accurate, but the deep-dives surfaced six refinements worth flagging:

| # | Audit said | Code actually showed | Impact |
|---|---|---|---|
| 1 | `RefinementLoop.evaluator` accepts `BaseAgent` — half of agent-self-evaluation already wired | True, but the evaluator agent must be `BaseAgent[..., EvalResult]`. The same agent rating itself is **not** wired. | Audit overstated latency. True self-rating still requires `EnrichedOutput`. |
| 2 | (not flagged) | `MetaOrchestrator._find_or_spawn` already prompts spawned agents for a `confidence` number (`meta.py:267-272`) | **Latent capability the audit missed.** Use it: `_extract_confidence` should read this existing field shape. |
| 3 | "Hooks are fire-and-forget" → blocks self-healing | Annotation choice, not semantic constraint. `_safe_call` discards return value but adding a decision-returning protocol is additive. | Reframes self-healing path: extend the protocol, don't replace it. |
| 4 | (not flagged) | **`HookRunner` does NOT intercept pydantic-AI's internal tool dispatch.** Hooks fire only at `CompoundTool` / `run_with_retry` / `MetaOrchestrator._execute_subtask` boundaries. | **Load-bearing.** `Skip`/`Redirect` only affect compound flows we control. To extend to raw LLM-issued tool calls, future work needs to wrap each `Tool.function` at construction (`as_tool`, `MCPToolAdapter.adapt`). |
| 5 | `resolve_model` is single-shot | True; **also** runtime 5xx during `request()` is uncaught — pydantic-AI propagates errors directly. | `FallbackModel` must subclass pydantic-AI's `Model` (not wrap) so it can intercept `request()` failures, not just resolution. |
| 6 | `ExecutionPlan` is "the closest pattern to generative UI" | Confirmed; **and** Polymath's `useSidecar.ts` whitelist (line 21-45) means new event types require frontend whitelist updates today. | Generative UI must ship a manifest endpoint (`GET /event-types`) so frontends auto-build listener lists. |

These are durable findings — record them in design docs so future sessions don't re-derive.

---

## Cross-track conflict resolution

The three designs were produced independently. Two surface conflicts that need explicit resolution before implementation:

### Conflict A — Hook protocol semantics (metacognition vs self-healing)

- **Metacognition design** says: respect "fire-and-forget" semantics; `MetacognitionHook` returns `None`.
- **Self-healing design** upgrades the protocol so methods now return `HookDecision`.

**Resolution:** Self-healing's `_safe_call` auto-wraps `None` → `Continue()`. `MetacognitionHook` returns `None` and is auto-wrapped — the two designs compose cleanly. **No conflict.**

### Conflict B — `MetaOrchestrator._find_or_spawn` (metacognition vs procedural memory)

- **Metacognition design** uses `_find_or_spawn`'s existing `confidence` prompt to drive re-decomposition.
- **Procedural memory design** changes `_find_or_spawn` to dual-write episodic + procedural memory entries.

**Resolution:** Both touch `_find_or_spawn` for orthogonal reasons (one reads confidence post-execution, the other writes spec persistence). They compose: write a `Skill`-shaped procedural entry containing the confidence prompt info, and read confidence on subtask completion via `_extract_confidence`. The procedural memory test rewrite (`test_meta.py:406`) is the one shared touchpoint. **Sequence: metacognition Wave 1, procedural memory Wave 1 — both can proceed in parallel since they touch different methods.**

### Cross-track event type unification

Three new event-type families land:
- `metacognition.confidence` (Wave 1)
- `healing.detection`, `healing.action`, `healing.model_fallback` (Wave 2)
- `ui.<component_type>.{init,delta,remove}`, `discovery.{requested,connected,denied,failed}`, `hook.conflict` (Wave 2-3)

**Single mechanism:** `Workbench` should expose a registry-of-known-event-types so frontends auto-build listener lists via `GET /event-types`. **Add a `Workbench.event_types(): list[str]` accessor that union-aggregates from registered hooks/watchdogs/UI registry.** Out of scope for this implementation plan; flagged for design-followup.

---

## Sequencing — three waves

Dependencies determine the wave grouping. Within a wave, work runs in parallel.

### Wave 1 — Foundations (parallel, ~7-9 days estimated; **all shipped 2026-04-25**)

| Track | Status | Outcome |
|---|---|---|
| **HookDecision protocol** (`02-self-healing` Track [B]) | ✅ shipped (Wave 1.1, +29 tests) | Hooks can now Skip / Redirect / Abort. Foundational for Wave 2. |
| **Metacognition** (`01-metacognition`) | ✅ shipped (Wave 1.3, +63 tests) | `EnrichedOutput[T]`, `ConfidenceProtocol` (3 strategies), `MetacognitionHook`, `BaseAgent.run_enriched`, `RefinementLoop`/`SubAgentTool`/`ContextManager`/`MetaOrchestrator` integration. |
| **Procedural memory** (`03-ui-and-procedural-memory` Track 2) | ✅ shipped (Wave 1.2, +23 tests) | `Literal["semantic","episodic","procedural"]`, `Skill`/`ToolCallSpec`/`SkillExample`, per-kind retrieval strategies, `MetaOrchestrator._find_or_spawn` dual-write migration. |

**Rationale:** all three are independent. `HookDecision` needs to ship first within Wave 2 dependencies but doesn't block other Wave 1 work — start it on day 1, finish ahead of metacognition completion. Procedural memory has the smallest blast radius.

### Wave 2 — Self-healing (after Wave 1, ~7-9 days estimated; **all shipped 2026-04-25**)

| Track | Status | Outcome |
|---|---|---|
| **Watchdog subsystem** (`02-self-healing` Track [C]) | ✅ shipped (Wave 2.C, +65 tests) | `Watchdog` Protocol, `StallDetector`, `LoopDetector`, `RegressionDetector`, `RecoveryAction`, `WatchdogHook`, `HealingRunner`, `FallbackModel` (subclass of `pydantic_ai.models.Model`), `resolve_model_with_fallback`, `Workbench.with_healing`. |
| **MCP auto-wire** (`02-self-healing` Track [D]) | ✅ shipped (Wave 2.D, +17 tests) | `ToolRegistry.get_or_discover`, `DiscoveryHook`, `PermissionGate` (`DenyAll` default), audit-log emission. *Note:* `factory.aspawn` deferred — sync `factory.spawn` remains the public API; auto-discovery hooks in via the `DiscoveryHook` opportunistic path. |

### Wave 3 — Generative UI (after Wave 1-2, ~5-7 days estimated; **shipped 2026-04-25**)

| Track | Status | Outcome |
|---|---|---|
| **Generative UI** (`03-ui-and-procedural-memory` Track 1) | ✅ shipped (Wave 3, +54 tests) | `orqest.ui` module: `UIComponentSpec[T]`, `UIDeltaEvent`, `ComponentRegistry` (per-Workbench), `UIEmitter`, 5 first-party components, `ExecutionPlan.enable_ui_events()` flag-gated dual emission, `Workbench.ui_registry` ctor kwarg with `default_registry()` auto-loaded first-party. |
| **Polymath UI consolidation** | ⏳ deferred | Polymath migrates `ChartsTab`/`ReportTab` to typed component specs; wires `HealingRunner`; consolidates Postgres `SubAgent` table onto `_find_or_spawn`'s procedural persistence. **Polymath consolidation, not Orqest core** — tracked as the next strategic move. |

**Why Wave 3 last:** generative UI is the most invasive *protocol* change (touches `AgentEvent.data` shape conventions). Letting Wave 1-2 settle the event-typing patterns first reduced churn.

### Wave 4 — Polymath consolidation ✅ shipped 2026-04-25

Eight parallel agents across four sequential rounds. Backend tests 91 → 109; frontend typecheck + build clean throughout. Full landing log: `~/repos/orqest/demo/polymath/.claude/CONSOLIDATION_COMPLETE_2026-04-25.md`.

- ✅ Polymath sub-agent roster migrated to procedural-memory persistence — `tools/autonomy.py` rewritten to use `workbench.memory` with `Skill` payloads in `structured_content` and `AgentSpec` in `metadata["agent_spec"]`. `db/models.py:SubAgent` table + `autonomy/store.py` + `routers/sub_agents.py` all deleted.
- ✅ Polymath agent runs `agent.run_enriched(state)` so analyst output carries `confidence` / `uncertainty_targets` / `capability_boundary`. `MetacognitionHook` registered alongside `EventBusPublishHook`. `metacognition.confidence` events flow on the SSE stream.
- ✅ Polymath frontend `PlanHeader` rebuilt on AI Elements `<Task>` consuming `ui.plan.{init,delta}` events. `ChartsTab` rebuilt on a new generic `useUIComponents<T>(sessionId, componentType)` hook consuming `ui.chart.*` events; PNG round-trip via `metadata.artifact_id`. New `TakeoverDialogModal` for agent-initiated dialogs. Five new AI Elements installed (code-block, sources, reasoning, suggestion, loader hand-rolled).
- ✅ Polymath wires `HealingRunner` via `Workbench.with_healing(...)` with `enable_regression=True`. `FallbackModel` chain when `POLYMATH_FALLBACK_MODELS` env is set. Watchdog hook integrates into the `HookRunner` chain.
- ✅ Polymath router-side 409 takeover block replaced with a `TakeoverGate` hook returning `HookDecision.Skip` from `before_tool` — demonstrates the cross-feature hook-decision flow.
- ✅ Polymath frontend uses `GET /sessions/{sid}/ui/event-types` manifest endpoint (per the audit's correction #6); the SSE listener whitelist auto-builds from `Workbench.ui_registry.list_types()`. Static `_FALLBACK_EVENT_TYPES` superset preserved for graceful degradation.

Outstanding (out of scope for the consolidation, deferred):
- Backend `POST /sessions/{sid}/takeover/respond` endpoint to land user responses back into the agent loop. The frontend modal POSTs to it forward-compat.
- `DocumentComponent` in `orqest.ui` core for `markdown_to_pdf` typed emission (assessment §6 Option B). Polymath emits the legacy `artifact.created` for PDFs in the meantime.
- `ClientChart` renderer for when `tools/report.py:_render_chart` starts forwarding structured plot data instead of just matplotlib PNG.
- Concept docs `docs/concepts/{metacognition,healing,generative_ui}.md`.

---

## Pre-flight implementation checklist

Before any Wave 1 implementation begins, do these:

1. **Open-question resolution.** The three designs flag 22 open questions total (8 metacog, 8 healing, 6 UI/memory). Most have explicit "leans" — accept the leans by default. The four that genuinely fork:
   - `confidence_protocol` field placement on `EnrichedOutput` (top-level vs metadata) — **accept lean: top-level `protocol_name: str | None`**
   - `RefinementLoop.agent_self_eval` × `evaluator` interaction — **accept lean: mutually exclusive, explicit error**
   - `EnsembleProtocol` output replacement — **accept lean: keep original**
   - `MetaOrchestrator + Abort` semantics — **accept lean: subtask-fail default; `abort_halts_run: bool = False`**

2. **Pydantic-AI version pin verification.** `FallbackModel` subclasses `pydantic_ai.models.Model`. Confirm the pinned version's `Model` ABC surface (`request`, `request_stream`, `model_name`, `system`) matches design assumptions. Add a smoke test: `assert isinstance(FallbackModel([m]), Model)`.

3. **Test infrastructure.** Set up `pydantic_ai.TestModel` fixtures for metacognition + healing tests. No real API keys required for the CI-blocking suite.

4. **Spec immutability surface.** Confirm `MetacognitionConfig`, `HealingConfig`, `PerKindConfig` follow the existing frozen-dataclass pattern (`config.py`, `memory/config.py`).

5. **Module re-export rules.** Per CLAUDE.md, root `orqest/__init__.py` stays small. Only `EnrichedOutput`, `MetacognitionConfig`, `HealingConfig` reach the root. Everything else is submodule-only.

---

## Backward compatibility — single inviolable invariant

**All 360 existing tests must stay green after each wave.**

Mechanism per track:
- **HookDecision:** legacy `None` returns auto-wrap to `Continue`. `EventBusPublishHook`, `MetacognitionHook` need zero changes.
- **Metacognition:** every new ctor param keyword-only with safe defaults (`None` / `False`). `BaseAgent.run` untouched. `MetaOrchestrator`'s `for subtask in subtasks` rewritten as `while i < len(subtasks)` — structurally equivalent when no mutation.
- **Procedural memory:** `Literal` extension is superset; new `structured_content` field defaults None; SQL `ALTER TABLE` best-effort. **One test rewrite required:** `tests/autonomy/test_meta.py:406` loosens from "memory_type=='episodic'" to "any episodic AND any procedural."
- **Generative UI:** `emit_ui_events: bool = False` default flag on `ExecutionPlan` keeps event counts unchanged. Wave 3 is opt-in until Polymath validates.

---

## What this enabled (post-implementation)

After Wave 1: agents return enriched output with confidence; refinement loops use agent self-confidence; salience-aware compaction is wired; sub-agent persistence uses procedural-memory semantics; security hooks Skip/Redirect/Abort tool calls.

After Wave 2: watchdogs detect stalls/loops/confidence-regression; provider fallback is automatic; missing capabilities trigger MCP discovery (with `DenyAll` default permission gate). Cross-feature handshake validated: metacognition's `metacognition.confidence` events feed `RegressionDetector` cleanly.

After Wave 3: agents emit typed UI component specs; the frontend hot-loads them via a discriminator-based resolver; Polymath migration (deferred) will turn it into a thin demo of a generic substrate.

**Vision feature status (final, 2026-04-25 end of day):**

| Feature | Before | After all 3 waves |
|---|---|---|
| #1 Runtime agent design | ✅ shipped | ✅ shipped + procedural-memory consolidation in `_find_or_spawn` |
| #2 Cognitive memory typology | 🟡 half | ✅ shipped (procedural + per-kind retrieval) |
| #3 Metacognition primitives | ❌ gap | ✅ shipped |
| #4 Self-healing primitives | ❌ gap | ✅ shipped |
| #5 Generative UI | ❌ gap | ✅ shipped |

All five novel features ship. Orqest's strategic positioning has moved from "LangGraph + good batteries" to a substrate with *all five* category-defining vectors. Test count: 360 → 612.

---

## When this plan goes stale

If the implementation stretches past 6 weeks, redo the audit (`AUDIT_<date>.md`) and revisit this plan. The five-feature framing is durable; the sequencing isn't.

If pydantic-AI ships a confidence-adjacent feature mid-flight (logprobs accessor, output enrichment), fold it into `ConfidenceProtocol` as a fourth strategy (`LogprobsProtocol`) rather than working around it.

If a sixth novel feature emerges (e.g., agent-to-agent direct messaging beyond `MetaOrchestrator`'s spawn pattern), update VISION.md before adding implementation tracks.
