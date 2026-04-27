# Orqest Self-Healing Primitives — Implementation Design

> **Date:** 2026-04-25 · **Status:** ✅ **shipped (Wave 1.1 + Wave 2, 2026-04-25)** · **Author:** Plan agent (deep-dive)
> **Anchors:** `.claude/VISION.md` § feature #4, `.claude/AUDIT_2026-04-25.md` § "Feature #4 — Self-healing primitives"
> **Sequencing:** three composable tracks — Track [B] HookDecision (Wave 1.1, +29 tests), Tracks [C] Watchdog/Healing (Wave 2.C, +65 tests) + [D] MCP auto-wire (Wave 2.D, +17 tests)
> **Dependencies:** [B] foundational (also unblocks Wave 2); [C] depends on [B] and on metacognition (for `RegressionDetector`'s confidence event consumption); [D] depends on [B] indirectly.

## Audit-claim re-validation (claim-by-claim)

### B-1: `ToolHook` methods return `None` — **CONFIRMED**
`hooks.py:24-49`. All three protocol methods typed `-> None`. `_safe_call` (`hooks.py:95-109`) `await`s and discards.

### B-2: Hooks are fire-and-forget — **CONFIRMED with nuance**
`hooks.py:102-109`: `_safe_call` wraps in `try/except Exception` and only logs WARN. **Implication:** the `HookDecision` upgrade must preserve this isolation. A *hook that crashes while computing a decision* must default to `Continue`, not propagate.

### B-3: Hooks see (state, agent, tool args) — **PARTIALLY CONFIRMED**
Hooks see `tool_name`, `args`, `state`, plus on `after_tool` `result + duration_ms`, plus on `on_error` the `Exception`. **They do NOT see the agent.** `state` is `Any`; introspection via `getattr` (the `EventBusPublishHook` pattern at `event_bus_hook.py:146-155`).

### B-4: `HookRunner` does NOT intercept pydantic-AI tool dispatch — **CONFIRMED, LOAD-BEARING**
**Most consequential finding.** `HookRunner.run_before/after/error` is invoked by:
- `CompoundTool.run` (`compound_tool.py:65-73`)
- `run_with_retry` (`retry.py:69, 99, 108`)
- `MetaOrchestrator._execute_subtask` (`meta.py:174-189, 207-212`)

It is **NOT invoked** when pydantic-AI's `Agent.run` dispatches a tool internally. There is no integration point at `BaseAgent.call_model` (`base_agent.py:238-252`).

**Implication for Skip/Redirect/Abort semantics:** hook decisions can only affect compound flows we control. To make Skip/Redirect meaningful for raw LLM-issued tool calls, we'd need a tool-level wrapping (e.g., wrap each `Tool.function` with a `HookRunner`-aware shim at construction time — `as_tool`, `MCPToolAdapter.adapt`). **Track [B] focuses on the compound surface for now** — sufficient for watchdog-driven recovery, which fires at compound-flow boundaries.

### C-1: `run_with_retry` is exception-axis only — **CONFIRMED**
`retry.py:75-96`. Iterates on `Exception`, checks `is_retryable` predicate. Non-exception failure modes (low-confidence output, regression) have no path.

### C-2: `resolve_model` is single-shot — **CONFIRMED + new finding**
`utils/llm_model.py:62-94`. Single string signature; raises `ValueError` on miss. **`_build_registry()` is not cached** (small inefficiency). **Crucially: only handles failure at *resolution* time. A 5xx during a model `request()` happens inside pydantic-AI and doesn't trip any orqest fallback today.**

### D-1: `MCPDiscovery → adapt → register` chain fully built — **CONFIRMED**
- `MCPDiscovery.search` (`discovery.py:94-131`)
- `DiscoveredServer.to_config` (`discovery.py:44-51`)
- `MCPServerManager.connect` (`client.py:148-166`)
- `MCPServerManager.discover_and_connect` (`client.py:182-223`) — already a one-shot helper
- `MCPToolAdapter.adapt_many` (`adapter.py:57-82`)

**Missing wiring:** `ToolRegistry.get(name) is None` → trigger discovery → register. `ToolRegistry.get` (`registry.py:45-47`) silently returns `None` — no signal.

### D-2: `MetaOrchestrator` does not auto-discover on tool miss — **CONFIRMED**
`MetaOrchestrator._find_or_spawn` (`meta.py:222-295`) only looks in `_spawned_agents` and `memory`. Does not consult `MCPDiscovery`.

### EventBus is watchdog-ready — **CONFIRMED**
`observability/events.py:54-83`. Both `subscribe(event_type, handler)` and `subscribe_all`. Handlers can be sync or async (`_safe_call` swallows exceptions).

### `tool.before/after/error` events flow via `EventBusPublishHook` — **CONFIRMED**
Watchdogs can subscribe to these today — no protocol change needed for them. The `HookDecision` upgrade is only required to let watchdog-issued recovery actions take effect.

---

## Track [B] — `HookDecision` Protocol Upgrade

### Module layout

`orqest/hooks.py` upgraded in place (additive). `HookDecision` lives alongside `ToolHook`.

### `HookDecision` discriminated union

Pydantic chosen (over frozen dataclass) — hooks may construct decisions from LLM output; we want validation; v2 has best discriminated-union support.

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, Any

class _DecisionBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class Continue(_DecisionBase):
    kind: Literal["continue"] = "continue"

class Skip(_DecisionBase):
    kind: Literal["skip"] = "skip"
    reason: str
    stub_result: Any = ""

class Redirect(_DecisionBase):
    kind: Literal["redirect"] = "redirect"
    new_args: dict[str, Any] | None = None
    new_tool: str | None = None
    reason: str = ""

    def model_post_init(self, _ctx: Any) -> None:
        if self.new_args is None and self.new_tool is None:
            raise ValueError("Redirect requires new_args or new_tool (or both)")

class Abort(_DecisionBase):
    kind: Literal["abort"] = "abort"
    reason: str

HookDecision = Continue | Skip | Redirect | Abort

class HookAbortError(RuntimeError):
    def __init__(self, reason: str, source_hook: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.source_hook = source_hook
```

### `ToolHook` protocol upgrade

```python
@runtime_checkable
class ToolHook(Protocol):
    """Methods may return None (legacy) or a HookDecision (new).
    HookRunner auto-wraps None into Continue so legacy hooks remain unchanged.
    """
    async def before_tool(self, tool_name, args, state) -> HookDecision | None: ...
    async def after_tool(self, tool_name, args, result, state, duration_ms) -> HookDecision | None: ...
    async def on_error(self, tool_name, args, error, state) -> HookDecision | None: ...
```

`after_tool` returning `Skip` is meaningless (already executed); runner treats post-execution `Skip` as `Continue` and logs WARN. `Abort` from any phase aborts.

### Aggregation rule (multiple hooks)

**First-non-Continue-wins, with Abort short-circuiting.**

1. Iterate hooks in registration order.
2. If any hook returns `Abort`, stop iterating immediately and propagate.
3. Otherwise, the first non-`Continue` decision (`Skip` or `Redirect`) is the active decision. Subsequent hooks still run (observers may want to log), but their decisions are recorded as "shadowed" in the AgentEvent metadata, not acted on.
4. If multiple hooks issue `Redirect` with conflicting `new_tool`, first wins; the conflict is emitted as `hook.conflict` AgentEvent.

**Rationale:** symmetric "all-must-continue" creates ordering bugs. First-wins with shadowing is deterministic and auditable.

### `HookRunner` execution flow

```python
async def _aggregate(self, method_name: str, *args: Any) -> HookDecision:
    active: HookDecision = Continue()
    shadowed: list[tuple[str, HookDecision]] = []
    for hook in self._hooks:
        decision = await self._safe_call(hook, method_name, *args)
        if isinstance(decision, Abort):
            raise HookAbortError(decision.reason, type(hook).__name__)
        if isinstance(active, Continue) and not isinstance(decision, Continue):
            active = decision
        elif not isinstance(decision, Continue):
            shadowed.append((type(hook).__name__, decision))
    if shadowed:
        logger.info("Hook decisions shadowed: {s}", s=shadowed)
    return active

async def _safe_call(self, hook, method_name, *args) -> HookDecision:
    method = getattr(hook, method_name, None)
    if method is None:
        return Continue()
    try:
        ret = await method(*args)
    except Exception:
        logger.warning("Hook {h}.{m} failed; defaulting to Continue", h=type(hook).__name__, m=method_name)
        return Continue()
    if ret is None:
        return Continue()
    if isinstance(ret, _DecisionBase):
        return ret
    logger.warning("Hook returned non-decision; treating as Continue")
    return Continue()
```

### Compound-flow integration

`CompoundTool.run` wraps `_executor` invocation: if `run_before` returns `Skip`, return `decision.stub_result`; if `Redirect`, mutate `effective_args`/`effective_name`; `Abort` raises `HookAbortError` which propagates. `after_tool` returning `Redirect` triggers bounded re-execution (max 1 redirect to prevent loops).

`run_with_retry`: `Skip` short-circuits; `Redirect` mutates `note`/`args`; `Abort` propagates (the helper only catches `Exception`, so `HookAbortError` flows through).

`MetaOrchestrator._execute_subtask`: `Skip` → synthetic `SubTaskResult(success=True, output=stub_result)`; `Abort` → failed `SubTaskResult` with `error=str(HookAbortError)`. **`Abort` does NOT halt the whole `solve()` loop by default** (configurable via new `abort_halts_run: bool = False`).

### Migration

`EventBusPublishHook` returns `None` from all methods → `_safe_call` auto-wraps to `Continue()`. Zero changes needed.

`MetacognitionHook` (from `01-metacognition.md`) also returns `None` → auto-wraps. Zero coupling.

### Tests for Track [B]

New `tests/test_hook_decision.py` (~20 cases). Existing `tests/test_hooks.py` stays green because legacy hooks return `None` → `Continue()`.

Test fixtures: `ContinueHook`, `SkipBeforeHook`, `RedirectArgsHook`, `AbortHook`, `CrashyDecisionHook`. Cases: single-hook variants, multi-hook aggregation, shadowing, bounded re-execution, partial implementations, return value coercion.

---

## Track [C] — `orqest.healing` Module

### Module layout

```
orqest/healing/
├── __init__.py
├── config.py              # HealingConfig (frozen dataclass)
├── watchdog.py            # Watchdog Protocol + Detection model
├── stall.py               # StallDetector
├── loop.py                # LoopDetector
├── regression.py          # RegressionDetector (graceful no-op without metacognition)
├── recovery.py            # RecoveryAction union + WatchdogHook (ToolHook)
├── fallback.py            # resolve_model_with_fallback + FallbackModel
└── runner.py              # HealingRunner
```

### `Watchdog` protocol + `Detection` model

```python
class Detection(BaseModel):
    detector: str
    severity: float = Field(ge=0.0, le=1.0, default=0.5)
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

@runtime_checkable
class Watchdog(Protocol):
    name: str
    def subscribe(self, bus: EventBus) -> None:
        """Wire event handlers idempotently."""
        ...
    async def signal(self) -> Detection | None:
        """Polled by HealingRunner. Inline-firing detectors return cached detection."""
        ...
```

### Three concrete watchdogs

**StallDetector** — tracks open tool calls; raises Detection if `now - started_at > timeout_s`. Subscribes to `tool.before`/`tool.after`/`tool.error`. Signals via `signal()` (polled).

**LoopDetector** — sliding window of recent `(tool_name, args_hash)`. If same `(name, hash)` appears > `threshold_k` times in last `window_n` events, raise. Subscribes to `tool.before`. Signals inline (cached in `_latest_detection`).

**RegressionDetector** — depends on metacognition. Subscribes to `metacognition.confidence` events. Computes head-tail mean over a window; if drop ≥ `drop_threshold`, raise. **If metacognition isn't loaded, no events fire and detector silently no-ops** (graceful degradation).

`_hash_args` uses SHA256 of JSON-sorted args. Default `default=str` for unhashable types — documented limitation.

### `RecoveryAction` discriminated union

```python
class RetrySameTool(_RecoveryBase):
    kind: Literal["retry_same"] = "retry_same"
    note: str = ""

class RetryDifferentModel(_RecoveryBase):
    kind: Literal["retry_diff_model"] = "retry_diff_model"
    model: str

class EscalateToUser(_RecoveryBase):
    kind: Literal["escalate"] = "escalate"
    question: str

class AbortRun(_RecoveryBase):
    kind: Literal["abort"] = "abort"
    reason: str

class DiscoverAndRetry(_RecoveryBase):
    kind: Literal["discover"] = "discover"
    capability: str

RecoveryAction = RetrySameTool | RetryDifferentModel | EscalateToUser | AbortRun | DiscoverAndRetry
```

### `WatchdogHook` — bridge to HookDecision

```python
class WatchdogHook:
    def __init__(self, watchdogs, *, policy=None, bus=None):
        self._watchdogs = watchdogs
        self._policy = policy or _default_policy
        self._bus = bus

    async def before_tool(self, tool_name, args, state) -> HookDecision:
        for wd in self._watchdogs:
            det = await wd.signal()
            if det is None: continue
            action = self._policy(det)
            if self._bus is not None:
                await self._bus.emit(AgentEvent(
                    event_type="healing.action",
                    data={"detection": det.model_dump(), "action": action.model_dump()},
                ))
            return _action_to_decision(action, tool_name, args)
        return Continue()
```

Default policy translation table:
- `StallDetector + RetrySameTool` → `Continue` (let timeout strategy retry)
- `StallDetector + AbortRun` → `Abort`
- `LoopDetector + RetryDifferentModel` → `Redirect(new_args={"_model": ...})`
- `LoopDetector + AbortRun` → `Abort(reason="loop")`
- `RegressionDetector + AbortRun` → `Abort`
- `RegressionDetector + DiscoverAndRetry` → `Redirect(new_tool=...)` after discovery

### `resolve_model_with_fallback` + `FallbackModel`

**Critical:** `FallbackModel` SUBCLASSES `pydantic_ai.models.Model` (not wraps). pydantic-AI's `Agent` calls `model.request()` directly; wrapping returns a non-`Model` object that fails `isinstance(model, Model)` checks (`base_agent.py:179`). `Model` ABC has small surface (`request`, `request_stream`, `model_name`, `system`).

```python
def resolve_model_with_fallback(
    models: list[str],
    *,
    api_key: str | dict[str, str],
    bus: EventBus | None = None,
    transient_predicate: Callable[[Exception], bool] | None = None,
) -> Model:
    """Resolve a chain. First successful resolve becomes primary;
    subsequent entries are fallbacks. Resolution failures (unknown
    provider, missing SDK) logged + skipped.
    """
    resolved: list[Model] = []
    for spec in models:
        provider = spec.split(":", 1)[0]
        key = api_key if isinstance(api_key, str) else api_key.get(provider, "")
        if not key:
            continue
        try:
            resolved.append(resolve_model(spec, api_key=key))
        except Exception as exc:
            logger.debug("resolve_model({s}) failed: {e}; skipping", s=spec, e=exc)
    if not resolved:
        raise ValueError(f"No model in {models!r} could be resolved")
    return FallbackModel(resolved, bus=bus, transient_predicate=transient_predicate)


class FallbackModel(Model):
    def __init__(self, models, *, bus=None, transient_predicate=None):
        self._models = models
        self._bus = bus
        self._is_transient = transient_predicate or _default_transient_predicate
        self._idx = 0

    @property
    def model_name(self) -> str:
        return f"fallback({','.join(m.model_name for m in self._models)})"

    @property
    def system(self) -> str:
        return self._models[self._idx].system

    async def request(self, messages, model_settings, model_request_parameters):
        last_exc = None
        for i in range(self._idx, len(self._models)):
            try:
                return await self._models[i].request(messages, model_settings, model_request_parameters)
            except Exception as exc:
                last_exc = exc
                if not self._is_transient(exc):
                    raise
                if self._bus is not None:
                    await self._bus.emit(AgentEvent(
                        event_type="healing.model_fallback",
                        data={"from": self._models[i].model_name, ...},
                    ))
                self._idx = i + 1
        raise RuntimeError(f"All fallback models exhausted; last error: {last_exc}")

    async def request_stream(self, *args, **kwargs) -> AsyncIterator[Any]:
        # Same logic but yields. Mid-stream errors propagate (not retried).
        ...
```

`_default_transient_predicate`: True for httpx connection/timeout, anthropic/openai rate-limit + 5xx, pydantic-AI's `ModelHTTPError`. False for `ValidationError`, `AuthenticationError`.

`_idx` is sticky — once advanced to model #2, doesn't try #1 again. Configurable via `reset_on_success: bool = False`.

### `HealingConfig`

```python
@dataclass(frozen=True)
class HealingConfig:
    stall_timeout_s: float = 60.0
    loop_threshold_k: int = 3
    loop_window_n: int = 10
    regression_window_n: int = 5
    regression_drop_threshold: float = 0.2
    poll_interval_s: float = 1.0
    fallback_models: tuple[str, ...] = ()
    enable_stall: bool = True
    enable_loop: bool = True
    enable_regression: bool = False  # off by default — needs metacognition
    abort_on_unresolved_loop: bool = True
```

### Wiring: `HealingRunner` (recommended) + `Workbench.with_healing` convenience

**Decision: explicit `HealingRunner` (not `Workbench.with_healing` as primary API).** Reasoning: keeps `Workbench` stable; composable; matches `MetaOrchestrator` / `HookRunner` precedent.

`Workbench.with_healing(config)` is a one-liner factory that returns a configured `HealingRunner` for ergonomics.

```python
class HealingRunner:
    """Wires watchdogs to a bus, runs poll loop, exposes a WatchdogHook.

    async with runner:  # starts poll loop
        hooks = HookRunner([runner.hook, EventBusPublishHook(bus)])
        ...
    """
    def __init__(self, config, *, bus, api_key=None, watchdogs=None):
        # Auto-construct enabled watchdogs from config
        # Subscribe each to the bus
        # Build WatchdogHook
        # If config.fallback_models: build FallbackModel
        ...

    async def __aenter__(self): await self.start(); return self
    async def __aexit__(self, *a): await self.stop()

    async def start(self):
        # asyncio.create_task(_poll_loop)
        ...
    async def stop(self):
        # cancel poll task
        ...
```

Poll loop swallows exceptions and continues — failure isolation per `PRINCIPLES.md`.

### Tests for Track [C] — ~22 tests

Watchdog tests (11): per-detector signal/no-signal cases, sliding window correctness, graceful degradation when metacognition absent.

Fallback tests (7): mocked Models, no real API calls. Resolution failures, transient vs non-transient errors, all-exhausted, event emission.

Integration tests (4): `HealingRunner` lifecycle, poll task swallowing exceptions, `Workbench.with_healing` round-trip.

---

## Track [D] — MCPDiscovery → ToolRegistry Auto-wire

### Two strategies — ship BOTH

**D-α: `ToolRegistry.get_or_discover(name, *, discovery=None, manager=None, audit_bus=None, permission=None)`** — for *deliberate* lookup paths (e.g., `factory.spawn`).

**D-β: `DiscoveryHook` (a `ToolHook`)** — for *opportunistic* recovery from runtime tool-not-found errors raised by an LLM that imagined a capability.

They compose: `factory.spawn` calls `get_or_discover` first (eager); if that fails and the LLM still hallucinates the tool, `DiscoveryHook` is the safety net. Both route through the same `PermissionGate`.

### `PermissionGate` — security boundary

```python
class PermissionGate(Protocol):
    async def allow(self, tool_name: str) -> bool: ...

class AllowAll(PermissionGate): ...   # opt-in via explicit choice
class DenyAll(PermissionGate): ...    # default
class AllowList(PermissionGate):       # regex allowlist
    def __init__(self, patterns: list[str]) -> None: ...
```

**Default policy: `DenyAll`** — discovery is opt-in. Documented loudly; remote MCP server is a code-execution surface.

Audit-log emission: every discovery attempt emits `discovery.requested` (before search) → `discovery.connected` (per registered tool) OR `discovery.denied` OR `discovery.failed`.

### `factory.spawn` integration

`AgentFactory.spawn` is sync today. To call `await get_or_discover`, add sister `aspawn` async method. `MetaOrchestrator._find_or_spawn` migrates to `aspawn`. Sync `spawn` stays for backward compat (skips discovery).

### Tests for Track [D] — ~12 tests

Coverage: existing tool returns directly; None when discovery is None; calls discovery + registers all from server; connect failure on #1 → tries #2; permission denial → emits `discovery.denied`; `AllowList` match/no-match; `DiscoveryHook` Continue/Redirect paths.

---

## Backward compatibility

Every existing test stays green. Touched test files survive because:
- Legacy hooks return `None` → wrapped to `Continue()` → behavior identical
- New ctor params keyword-only with safe defaults
- `factory.spawn` stays sync; new `aspawn` lives alongside
- `Workbench` lazy-imports healing inside the `with_healing` method — workbench tests unaffected

**Public API surface change (one line):** `HookRunner.run_before/after/error` now return `HookDecision` instead of `None`. All call sites are internal — no public consumer relies on the return type today.

## Open design questions

1. Hook scope expansion to raw LLM tool dispatch — wrap each `Tool.function` at construction (`as_tool`, `MCPToolAdapter.adapt`) with a hook-runner-aware shim. Out of scope; flagged.
2. `FallbackModel._idx` sticky vs ephemeral — ship sticky default with `reset_on_success: bool = False`.
3. `MetaOrchestrator` + `Abort` — default fails subtask but `solve()` continues. Add `abort_halts_run: bool = False`.
4. `StallDetector` poll vs push — polling simpler; flag for revisit if latency-sensitive.
5. `LoopDetector` arg-equality — SHA256 of JSON-sorted with `default=str`. Document limitation.
6. Permission gate persistence — persist learned allowlist? Out of scope.
7. `FallbackModel` and pydantic-AI `Model` interface stability — pin minimum version, smoke test `isinstance(Model)`.
8. `request_stream` mid-stream failure — only fall back if stream errors before first yielded chunk; mid-stream errors propagate.

## Concept docs

`docs/concepts/hook_protocol.md` and `docs/concepts/healing.md` — full TOCs in source design.

## Implementation sequencing

```
Sprint 1 — Track [B]: HookDecision + tests + integration (~3 days)
Sprint 2 — Track [C] core: watchdogs + RecoveryAction + WatchdogHook + HealingRunner + FallbackModel + tests (~4-5 days)
Sprint 3 — Track [C] regression + Track [D]: RegressionDetector wired to metacog events; ToolRegistry.get_or_discover + DiscoveryHook + PermissionGate + factory.aspawn (~3-4 days)
```

Each sprint ships independently. Sprint 1 alone unlocks security/policy hooks for any consumer. Sprint 2 alone gives stall/loop watchdogs and model fallback. Sprint 3 closes the loop on regression-detection and capability discovery.

## Critical files for implementation
- `orqest/hooks.py`
- `orqest/agents/compound_tool.py`
- `orqest/agents/retry.py`
- `orqest/utils/llm_model.py`
- `orqest/autonomy/meta.py`
- `orqest/autonomy/factory.py`
- `orqest/autonomy/registry.py`
- `orqest/mcp/{discovery,client,adapter}.py`
- New: `orqest/healing/*`
