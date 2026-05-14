# Self-Healing

Orqest treats failure recovery as composable primitives, not retry loops scattered across handlers. Three watchdogs (`StallDetector`, `LoopDetector`, `RegressionDetector`) observe an agent's runtime, raise `Detection` records, a policy maps each to a `RecoveryAction`, and `WatchdogHook` translates intent into a `HookDecision` that takes effect at the next compound-flow boundary. Plus `FallbackModel` for transparent provider failover. Wire once, every agent inherits robustness.

## What problem does this solve?

Production agents fail constantly: rate limits, model outages, infinite loops on bad prompts, silent quality regressions. Most frameworks let the developer rebuild this from scratch. Orqest's healing layer is the substrate's "immune system" — three observation primitives, a small intent vocabulary, and one decision protocol that hooks into the existing `HookRunner`. Combined with metacognition, this is what makes Orqest agents survivable in production without a human pager.

## The three-layer split

The architecture is intentional: detection, intent, and decision are different concerns.

| Layer | Type | Concern |
|-------|------|---------|
| Detection | `Watchdog` Protocol → `Detection` | Pure observation. What happened? |
| Intent | `RecoveryAction` (policy function) | What *should* happen? |
| Decision | `HookDecision` (Continue/Skip/Redirect/Abort) | What *will* happen at the next boundary? |

Detectors are reusable across consumers. A different consumer may want a different policy; both reuse the same detectors and the same `HookDecision` plumbing.

## The three watchdogs

### `StallDetector`

Flags open tool calls that exceed `timeout_s`. Idempotent subscribe; suppresses double-fire on the same call.

```python
from orqest.healing import StallDetector

detector = StallDetector(timeout_s=30.0)
```

### `LoopDetector`

Sliding window over `(tool_name, args_hash)` pairs. Fires when the same pair appears more than `threshold_k` times in the last `window_n`. Suppression resets when the pair changes.

```python
from orqest.healing import LoopDetector

detector = LoopDetector(threshold_k=3, window_n=10)
```

### `RegressionDetector`

Subscribes to `metacognition.confidence` events. Fires when `head_half_mean − tail_half_mean ≥ drop_threshold`. Silently no-ops when no confidence events flow (graceful degradation when metacognition isn't wired).

```python
from orqest.healing import RegressionDetector

detector = RegressionDetector(window_n=10, drop_threshold=0.2)
```

## RecoveryAction discriminated union

| Action | When | Effect |
|--------|------|--------|
| `RetrySameTool(note)` | Transient failure (timeout, 5xx) | Re-issue the same tool call |
| `RetryDifferentModel(model)` | Persistent failure with current model | Re-issue with `provider:model_id` |
| `EscalateToUser(question)` | Ambiguity that needs human input | Surface as a takeover dialog (consumer-side rendering) |
| `AbortRun(reason)` | Unrecoverable | Stop the compound flow with `HookAbortError` |
| `DiscoverAndRetry(capability)` | Tool not found | Search MCP for the capability, register, retry |

Default policy maps every detection to `AbortRun` — conservative. Consumers override with a custom callable.

## WatchdogHook — the bridge into HookDecision

Wire detectors + policy + bus into a `WatchdogHook`. Returned `HookDecision` flows through the same `HookRunner` aggregation as security/policy hooks.

```python
import asyncio
from orqest.healing import (
    LoopDetector,
    StallDetector,
    WatchdogHook,
    default_policy,
)
from orqest.observability import EventBus
from orqest.hooks import HookRunner


async def main():
    bus = EventBus()

    detectors = [
        StallDetector(timeout_s=30.0),
        LoopDetector(threshold_k=3, window_n=10),
    ]
    for d in detectors:
        d.subscribe(bus)

    hook = WatchdogHook(
        watchdogs=detectors,
        policy=default_policy,
        bus=bus,
    )

    runner = HookRunner(hooks=[hook])
    # Pass `runner` to your CompoundTool / SubAgentTool / agent.

asyncio.run(main())
```

## FallbackModel — transparent provider failover

Subclasses `pydantic_ai.models.Model`. Sticky failover (advance only on transient failure; commit to the current model on success). Transient classifier: 5xx / timeout / rate-limit fall back; auth / validation propagate.

```python
from orqest.healing import resolve_model_with_fallback

model = resolve_model_with_fallback(
    ["openai:gpt-4.1", "anthropic:claude-sonnet-4-6", "google:gemini-2.5-pro"],
    api_key={
        "openai": "sk-...",
        "anthropic": "sk-ant-...",
        "google": "AIza...",
    },
    bus=bus,  # emits healing.model_fallback / healing.model_chain_exhausted
)

# Use exactly like a regular model
agent = MyAgent(model=model, ...)
```

Missing per-provider keys are skipped gracefully (chain shortens). Empty resolved chain raises `ValueError` at construction (crash early).

## HealingRunner — the lifecycle

Async context manager that wires watchdogs to a bus, runs the poll loop, emits `healing.detection` events, and owns the `WatchdogHook` plus the optional `FallbackModel`. Use as the spine of a healing-enabled agent run.

```python
import asyncio
from orqest.workbench import Workbench
from orqest.healing import HealingConfig


async def main():
    workbench = Workbench(memory=...)  # your memory store

    healing = workbench.with_healing(
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
        # Inside this block: watchdogs are wired to workbench.event_bus,
        # poll loop is running, FallbackModel is available as runner.model
        agent = MyAgent(model=runner.model, hooks=[runner.hook], ...)
        await agent.run(state)


asyncio.run(main())
```

## HealingConfig

Frozen dataclass; one config knob per cross-cutting concern.

| Field | Default | Effect |
|-------|---------|--------|
| `stall_timeout_s` | `30.0` | StallDetector timeout |
| `loop_threshold_k` | `3` | LoopDetector match count threshold |
| `loop_window_n` | `10` | LoopDetector sliding window |
| `regression_window_n` | `10` | RegressionDetector sliding window |
| `regression_drop_threshold` | `0.2` | RegressionDetector head-vs-tail mean delta |
| `poll_interval_s` | `1.0` | Poll loop tick interval |
| `fallback_models` | `()` | Tuple of `provider:model_id` strings |
| `enable_stall` / `enable_loop` / `enable_regression` | `True` | Flag-gate per-detector |

## Cross-feature handshake — metacognition → healing

`RegressionDetector` consumes `metacognition.confidence` events from a `MetacognitionHook`. Wire both for trustworthy agents:

```
agent.run_enriched(...)
    → MetacognitionHook emits metacognition.confidence on bus
    → RegressionDetector buffers → signals Detection
    → policy returns RetryDifferentModel(...)
    → WatchdogHook returns Redirect(new_args=...)
    → HookRunner aggregates → CompoundTool re-issues with the new model
```

The whole chain is composable. Drop in metacognition without healing → events fire, nobody listens. Drop in healing without metacognition → `RegressionDetector` no-ops, `Stall`/`Loop` still work. Each piece degrades gracefully.

## MCP auto-discovery (DiscoverAndRetry)

When a runtime "tool not found" error fires, `DiscoveryHook` searches MCP for the missing capability. Gated by `PermissionGate` (default `DenyAll` — opt-in). Recovery action `DiscoverAndRetry(capability=name)` returns `Redirect(new_tool=name)` after registration.

```python
from orqest.mcp import DiscoveryHook, AllowList

hook = DiscoveryHook(
    discovery=MCPDiscovery(),
    manager=MCPServerManager(),
    permission=AllowList([r"web\..*", r"git\..*"]),
    audit_bus=bus,  # emits discovery.requested / .connected / .denied / .failed
)
```

## Best practices

- **Start with the default policy.** `default_policy` aborts on every detection. Override only when you've measured a recovery action that's actually safe in your domain.
- **Wire `RegressionDetector` only if metacognition is on.** It's cheap when no events flow (no-op), but the *intent* is clearer if you only enable it where confidence signals exist.
- **`FallbackModel` does not retry transient failures on the *current* model** — it advances. If you want intra-model retry first, use `run_with_retry` around the agent and `FallbackModel` underneath; both compose.
- **Set conservative thresholds first.** A stall timeout that's too aggressive aborts every slow tool. Tune from telemetry.

## Pitfalls

- **Don't override the policy with arbitrary `Redirect(new_args=...)` payloads.** The `_action_to_decision` mapping translates each `RecoveryAction` to a structured `HookDecision`; ad-hoc redirects bypass the contract.
- **Don't share a `HealingRunner` across sessions.** It owns subscriptions and a poll task; lifecycle is per-run.
- **Don't catch `HookAbortError` in tools.** It's the framework's signal to halt the compound flow. Catch it at the consumer's outermost boundary if you need to surface it as an HTTP error / message.
- **Don't subscribe two `MetacognitionHook` instances to the same bus** — confidence events double-fire, regression detection triggers prematurely.

## What's happening under the hood

1. `HealingRunner.__aenter__` subscribes each watchdog to the bus, starts the poll task
2. Each tool call fires `tool.before` / `tool.after` / `tool.error` events (via `EventBusPublishHook`)
3. Watchdogs observe the event stream, buffer state in their windows
4. Periodically (`poll_interval_s`), `HealingRunner` polls each watchdog's `signal()` for a fresh `Detection`
5. On detection: emit `healing.detection` event, then the policy returns a `RecoveryAction`
6. `WatchdogHook` translates the action to a `HookDecision`, emits `healing.action`
7. The next compound-flow boundary (`CompoundTool.run`, `run_with_retry`, `MetaOrchestrator._execute_subtask`) consumes the decision
8. `__aexit__` cancels the poll task, drains pending detections

## Related Concepts

- [Hooks & Lifecycle](hooks-and-lifecycle.md) — `HookDecision` discriminated union, `HookRunner` aggregation
- [Metacognition](metacognition.md) — confidence events that feed `RegressionDetector`
- [Observability](observability.md) — `EventBus` underlying everything
- [Workbench](workbench.md) — `with_healing(...)` convenience factory
