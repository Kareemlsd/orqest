# Self-Healing — reference

Compressed judgment layer over `orqest/healing/`. For full reference, read `docs/concepts/healing.md`.

## Three-layer split — what to keep distinct

| Layer | Type | Concern |
|---|---|---|
| Detection | `Watchdog` Protocol → `Detection` | Pure observation. What happened? |
| Intent | `RecoveryAction` (policy function) | What *should* happen? |
| Decision | `HookDecision` (`Continue`/`Skip`/`Redirect`/`Abort`) | What *will* happen at the next compound-flow boundary? |

Detectors are reusable; consumers swap the policy. Don't conflate detection and recovery.

## The three watchdogs

```python
from orqest.healing import StallDetector, LoopDetector, RegressionDetector

StallDetector(timeout_s=30.0)                                # open tool calls exceeding timeout
LoopDetector(threshold_k=3, window_n=10)                     # same (tool, args_hash) repeats
RegressionDetector(window_n=10, drop_threshold=0.2)          # head-half vs tail-half confidence mean
```

`RegressionDetector` subscribes to `metacognition.confidence` events. With no metacog feed → silently no-ops. By design.

## `RecoveryAction` — deliberately lean

```python
from orqest.healing import AbortRun, EscalateToUser
```

Two variants only:

| Action | Effect |
|---|---|
| `AbortRun(reason)` | Stops the compound flow with `HookAbortError` |
| `EscalateToUser(question)` | `Skip` carrying the question; consumer renders a takeover dialog |

Model-level recovery is `FallbackModel`. Tool-level recovery is `DiscoveryHook` (in `orqest.mcp`). Both are composable mechanisms, NOT `RecoveryAction` variants — earlier designs that conflated them produced unused payloads.

```python
from orqest.healing import default_policy
# default_policy maps every Detection → AbortRun. Override with a custom callable.
```

## Wire-up — `WatchdogHook` + `HealingRunner`

The convenience factory on `Workbench`:

```python
from orqest import Workbench
from orqest.healing import HealingConfig

wb = Workbench(user_id="alice", session_id="...", memory=memory_store)
healing = wb.with_healing(
    HealingConfig(
        stall_timeout_s=30.0,
        loop_threshold_k=3,
        loop_window_n=10,
        regression_window_n=10,
        regression_drop_threshold=0.2,
        poll_interval_s=1.0,
        fallback_models=("openai:gpt-4.1", "anthropic:claude-sonnet-4-6"),
    ),
    api_key={"openai": "sk-...", "anthropic": "sk-ant-..."},
)

async with healing as runner:
    # Inside: watchdogs subscribed to wb.event_bus, poll loop active,
    # FallbackModel available as runner.model
    agent = MyAgent(model=runner.model, hooks=[runner.hook], ...)
    await agent.run(state)
```

Manual wire-up if you don't want `Workbench`:

```python
from orqest.healing import WatchdogHook, StallDetector, LoopDetector, default_policy
from orqest.hooks import HookRunner

detectors = [StallDetector(timeout_s=30.0), LoopDetector(threshold_k=3, window_n=10)]
for d in detectors:
    d.subscribe(bus)
hook = WatchdogHook(watchdogs=detectors, policy=default_policy, bus=bus)
runner = HookRunner(hooks=[hook])
```

## `FallbackModel` — transparent provider failover

Sticky failover (advance only on transient failure; commit on success). Transient classifier: 5xx / timeout / rate-limit → fall back; auth / validation → propagate.

```python
from orqest.healing import resolve_model_with_fallback

model = resolve_model_with_fallback(
    ["openai:gpt-4.1", "anthropic:claude-sonnet-4-6", "google:gemini-2.5-pro"],
    api_key={"openai": "sk-...", "anthropic": "sk-ant-...", "google": "AIza..."},
    bus=bus,                                                 # emits healing.model_fallback / .model_chain_exhausted
)
agent = MyAgent(model=model, ...)                           # drops straight into any BaseAgent
```

Missing per-provider keys: chain shortens silently. Empty resolved chain raises `ValueError` at construction.

## Cross-feature handshake — metacognition → healing

```
agent.run_enriched(...)
    → MetacognitionHook emits `metacognition.confidence` on bus
    → RegressionDetector buffers → signals Detection
    → policy returns RecoveryAction (default: AbortRun)
    → WatchdogHook translates → HookDecision (Abort)
    → HookRunner aggregates → compound flow halts with HookAbortError
```

Each piece degrades gracefully. Metacognition without healing → events fire, nobody listens. Healing without metacognition → `Stall` and `Loop` work, `Regression` no-ops.

## Pitfalls

- **`default_policy` aborts on every detection.** Conservative. Override only when you've measured a recovery action that's actually safe.
- **Don't share `HealingRunner` across sessions.** It owns subscriptions + a poll task; lifecycle is per-run.
- **Don't catch `HookAbortError` in tools.** It's the framework's halt signal. Catch at the consumer's outermost boundary if you need to surface as HTTP error / message.
- **Don't subscribe two `MetacognitionHook` instances to the same bus.** Confidence events double-fire; regression detection triggers prematurely.
- **`FallbackModel` does not retry the current model on transient failure** — it advances. If you want intra-model retry first, wrap with `run_with_retry`; both compose.
- **`RegressionDetector` needs metacognition.** Enabling it without `metacognition.confidence` events flowing is a silent no-op. Wire both or disable the detector.

## Where to read more

- `docs/concepts/healing.md` — full reference (incl. `HealingConfig` field-by-field)
- `references/metacognition.md` — the signal source `RegressionDetector` consumes
- `docs/concepts/hooks-and-lifecycle.md` — `HookDecision` aggregation rules
- `notebooks/01_cognitive_substrate.ipynb` — `RegressionDetector` + `WatchdogHook` + `FallbackModel` end-to-end
