# Orqest Metacognition Module — Implementation Design

> **Date:** 2026-04-25 · **Status:** ✅ **shipped (Wave 1.3, 2026-04-25)** · **Author:** Plan agent (deep-dive)
> **Anchors:** `.claude/VISION.md` § feature #3, `.claude/AUDIT_2026-04-25.md` § "Feature #3 — Metacognition primitives"
> **Sequencing:** Wave 1 (parallel with HookDecision protocol upgrade and procedural memory). All three Wave 1 tracks landed the same day this design was written.

## Audit-claim validation against actual source

Each audit assertion validated below with file:line evidence.

### Claim A: `BaseAgent.run` returns raw `OutputT` — no confidence/uncertainty/capability boundary
**CONFIRMED.** `orqest/agents/base_agent.py:326-328`. `OutputT` is `TypeVar("OutputT", bound=BaseModel)` (line 38). The abstract `_run_implementation` (line 330-337) returns the same `OutputT`. `call_model` (line 238-252) returns pydantic-ai's `AgentRunResult` (line 29) — also no confidence/uncertainty fields. **The keystone gap is real and at line 326.**

### Claim B: `RefinementLoop.evaluator` already accepts a `BaseAgent` — agent-self-evaluation half-built
**CONFIRMED with subtlety.** `orqest/orchestration/loop.py:51` types `Evaluator = Callable[..., Any] | BaseAgent`. `_call_evaluator` (lines 156-166) handles both branches, but when the evaluator is a `BaseAgent`, the loop expects the return value to be `EvalResult`. The evaluator agent must be `BaseAgent[GlobalState, EvalResult]`. **The audit overstated this.** What's wired today is "any agent whose output is `EvalResult` can serve as a critic." True self-rating (the same agent rates itself) is not wired and requires `EnrichedOutput`.

### Claim C: `SubAgentResult` cannot expose confidence — blocked on `BaseAgent`
**CONFIRMED.** `sub_agent_tool.py:36-58` defines `SubAgentResult[ResultT]` with fields `result, iterations, refined, exit_reason` — no confidence. `_build_refinement_prompt` is `Callable[[ResultT, str], str]` (line 99). Receives raw `ResultT`, no confidence input.

### Claim D: `ContextManager.compact` is token-count-driven, no salience signal
**CONFIRMED.** `context_manager.py:46-60` compares against `effective_budget * threshold`. `_summarize_old_turns` (62-112) decides what to drop purely by **age** (`recent_start = max(1, len(messages) - self.min_recent_turns)`). `_emergency_truncate` (114-142) walks backward from the end accumulating tokens — also age-based. **Zero signal flow from confidence/salience.**

### Claim E: `HookRunner` is fire-and-forget; `_safe_call` discards return values
**CONFIRMED.** `hooks.py:95-109`. `_safe_call` `await`s the method and discards whatever it produced. Hook protocol methods (lines 24-49) return `-> None`. **Important caveat:** "fire-and-forget" is an *annotation choice*, not a semantic constraint. The blocker for self-healing isn't fire-and-forget semantics — it's the absence of a separate decision-returning hook protocol.

### Claim F: `AgentEvent.data` is `dict[str, Any]` — extensible
**CONFIRMED.** `events.py:36`. `EventBus.emit` (line 85) dispatches by `event_type` string. We can add a new `metacognition.confidence` event type without protocol changes.

### Claim G: `MetaOrchestrator.solve` has no confidence-drop trigger for re-decomposition
**CONFIRMED with new finding.** `meta.py:113-146` runs subtasks sequentially with no inspection of result quality. **However, audit missed this:** `_find_or_spawn` (`meta.py:267-272`) **already adds a `confidence` field** to spawned generic agents' output schemas:

```python
"confidence": {"type": "number", "description": "Confidence 0-1"},
```

So spawned generic agents are *already prompted to emit a confidence number*, but it lands in `SubTaskResult.output` (an `Any` blob, line 52) and is **never inspected**. **Latent capability the audit missed** — the orchestrator already asks for confidence; it just doesn't read it.

### Audit mistakes flagged
1. **`RefinementLoop` "latent" overstated** — same agent can't rate itself today; only "another `BaseAgent[..., EvalResult]`" works. True self-rating requires `EnrichedOutput`.
2. **`_find_or_spawn` confidence prompt** — already half-built (meta.py:267-272), not flagged in audit.
3. **"Fire-and-forget" misframed** — annotation choice, not semantic constraint. The blocker is no decision-returning protocol exists.

---

## `orqest.metacognition` design

### Module layout

```
orqest/metacognition/
├── __init__.py              # Re-exports
├── enriched.py              # EnrichedOutput[OutputT] — pure data model
├── protocol.py              # ConfidenceProtocol Protocol + 3 concrete strategies
├── hook.py                  # MetacognitionHook (a ToolHook)
├── config.py                # MetacognitionConfig — frozen dataclass
├── prompts/
│   └── self_rating.txt      # Default LLMSelfRatingProtocol prompt
└── salience.py              # confidence_salience for ContextManager integration
```

Tests under `tests/metacognition/` mirroring source.

No import-time side effects. No circular imports (enriched.py is leaf; protocol.py and hook.py depend on enriched; config.py is leaf; salience.py depends only on enriched).

### `EnrichedOutput[OutputT]`

```python
# orqest/metacognition/enriched.py
from __future__ import annotations
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, ConfigDict, Field

OutputT = TypeVar("OutputT", bound=BaseModel)


class EnrichedOutput(BaseModel, Generic[OutputT]):
    """Agent output paired with the agent's own self-assessment."""

    output: OutputT = Field(
        description="The agent's structured output — exactly what BaseAgent.run "
        "returned before enrichment."
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Self-rated probability that the output satisfies the "
        "agent's task. None when no protocol ran or the protocol failed. "
        "Calibration is protocol-defined.",
    )
    uncertainty_targets: list[str] = Field(
        default_factory=list,
        description="Free-text identifiers for assumptions/sub-claims the "
        "agent flagged as the bottleneck on confidence.",
    )
    capability_boundary: bool = Field(
        default=False,
        description="True iff the agent reports the task is outside what it "
        "can verify. Distinct from low confidence.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Protocol-defined free space (protocol_name, sample_count, "
        "rating_prompt_hash, etc.). Never load-bearing — UI/telemetry only.",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)
```

**Field justification:** `output` unmodified for backward compat. `confidence: float | None` distinguishes "didn't measure" from "measured zero." `uncertainty_targets` free-text by design (litmus test). `capability_boundary` separate from confidence — two-axis representation (confidence × boundary) is the minimum information set for re-decomposition rules ("try harder" vs "spawn different agent"). `metadata: dict[str, Any]` matches `AgentEvent.data` flexibility.

### `ConfidenceProtocol` — three pluggable strategies

```python
@runtime_checkable
class ConfidenceProtocol(Protocol):
    name: str

    async def enrich(
        self,
        agent: "BaseAgent",
        state: BaseModel,
        output: OutputT,
        **agent_kwargs: Any,
    ) -> EnrichedOutput[OutputT]:
        """Failures must be swallowed and surfaced as confidence=None — never raise."""
        ...
```

| Protocol | Extra LLM calls | Latency | Best for |
|---|---|---|---|
| `StructuredOutputProtocol` | 0 | ~0 (slightly larger output schema) | **Default.** Most agents. Lifts `confidence`/`uncertain_about`/`outside_my_capability` fields off the agent's own output. |
| `LLMSelfRatingProtocol` | +1 | +1 round-trip | Legacy agents whose `OutputT` cannot be modified. |
| `EnsembleProtocol` | +k–1 (parallel) | +k–1 round-trips | High-stakes one-shot decisions where calibration matters more than cost. |

Implementation skeletons in full design (see source agent output). `_coerce_confidence` and `_default_agreement` are private helpers.

### `MetacognitionHook` — bridges enriched output to EventBus

```python
class MetacognitionHook:
    """ToolHook that publishes enriched-output telemetry to an EventBus.

    Implements only after_tool: when the tool result is an EnrichedOutput,
    emits one 'metacognition.confidence' AgentEvent. Other tool results
    are ignored (best-effort: safe to register on any HookRunner).
    """

    def __init__(self, bus: EventBus, *, agent_name: str = "unknown") -> None:
        self._bus = bus
        self._agent_name = agent_name

    async def after_tool(
        self, tool_name: str, args: dict[str, Any], result: Any,
        state: Any, duration_ms: float,
    ) -> None:
        if not isinstance(result, EnrichedOutput):
            return
        await self._bus.emit(
            AgentEvent(
                event_type="metacognition.confidence",
                agent_name=self._agent_name,
                data={
                    "tool_name": tool_name,
                    "confidence": result.confidence,
                    "capability_boundary": result.capability_boundary,
                    "uncertainty_targets": list(result.uncertainty_targets),
                    "protocol": result.metadata.get("protocol"),
                    "duration_ms": round(duration_ms, 2),
                    **_state_meta(state),
                },
            )
        )
```

`MetacognitionHook` returns `None` from all methods → auto-wraps to `Continue` under the new `HookDecision` protocol (see `02-self-healing.md`). Backward compatible.

### `BaseAgent.run_enriched` — additive, NOT replacing `run`

**Critical decision:** `run_enriched` is **additive**; `run` stays untouched. Reasoning:

1. **360 existing tests** call `agent.run(state)` and assert on `OutputT` shape. Rewriting `run` to wrap-and-unwrap risks subtle type-narrowing failures.
2. **Unwrap path is opinionated.** "What does `run` return when no protocol is configured?" Either always-wraps (breaks every caller) or call-and-unwrap (breaks the "minimal overhead" contract).
3. **Litmus test:** "Could a coding-assistant builder use this *without* knowing about metacognition?" Yes — they ignore `run_enriched`.
4. **Pragmatic Programmer ETC:** new behavior belongs in a composable piece.

```python
# orqest/agents/base_agent.py — additive

async def run_enriched(
    self,
    state: StateT,
    *,
    confidence_protocol: ConfidenceProtocol | None = None,
    **kwargs: Any,
) -> EnrichedOutput[OutputT]:
    output: OutputT = await self._run_implementation(state, **kwargs)

    protocol = confidence_protocol or self._confidence_protocol
    if protocol is None:
        return EnrichedOutput(output=output)

    try:
        return await protocol.enrich(self, state, output, **kwargs)
    except Exception as exc:
        logger.debug(
            "ConfidenceProtocol {p} failed: {e}",
            p=getattr(protocol, "name", type(protocol).__name__),
            e=str(exc),
        )
        return EnrichedOutput(
            output=output,
            metadata={"protocol_error": type(exc).__name__},
        )
```

Constructor change: keyword-only `confidence_protocol: ConfidenceProtocol | None = None` parameter, stored as `self._confidence_protocol`. All 360 tests pass unchanged.

### `RefinementLoop` integration

Add **two** keyword-only ctor params:
- `confidence_threshold: float | None = None` — exit with `exit_reason="confident"` once `score ≥ threshold`
- `agent_self_eval: BaseAgent | None = None` — when set, loop uses `agent_self_eval.run_enriched(state)` to produce per-iteration confidence; synthesises `EvalResult(passed=False, score=enriched.confidence)`

`Evaluator` typing unchanged. `_call_evaluator` byte-identical when neither new param is set. New exit reason `"confident"` doesn't break existing assertions (verified — no test asserts the complete set is exactly the four current values).

### `SubAgentResult` integration

Three additive optional fields: `confidence: float | None`, `uncertainty_targets: list[str]`, `capability_boundary: bool`.

`SubAgentTool.run(use_enriched: bool = False)` keyword-only. When `True`, replaces `_agent.run` with `_agent.run_enriched`, executor still receives raw `agent_output`, final `SubAgentResult` lifts the enrichment.

Migration: v0.1.0 ships `use_enriched=False` default; v0.2.0 flips to `True` if `_agent._confidence_protocol is not None`.

### `ContextManager` salience hook

**Decision:** add optional `salience_fn` to `__init__`, NOT to `compact()`. Reason: `compact()` is registered as a history processor (`base_agent.py:212`); pydantic-AI calls it with `(messages,)` only — we can't widen the call signature.

```python
class ContextManager:
    def __init__(
        self, ..., *,
        salience_fn: "Callable[[ModelMessage], float] | None" = None,
    ):
        self._salience_fn = salience_fn
```

When `None`, existing flow unchanged. When set, `_summarize_old_turns`/`_emergency_truncate` consult salience for drop *order*.

`orqest/metacognition/salience.py` provides `confidence_salience(message, *, floor=0.3, metadata_key="metacognition_confidence")` — returns 1.0 for un-tagged messages (backward compat).

**Known wrinkle:** pydantic-AI's `ModelResponse` is frozen — can't mutate. Pragmatic path: side-table cache on `ContextManager` keyed by `id(message)`, populated by a tag-confidence history processor. Alternative: ride on `ToolReturnPart.metadata` if available in the pinned pydantic-AI version. **Open question 7 below.**

### `MetaOrchestrator` re-decomposition

Add keyword-only `metacognition: MetacognitionConfig | None = None` ctor param. When set, after each successful subtask, inspect confidence; if below threshold and within `max_redecompositions` budget, call new private `_redecompose(...)` returning rewritten remaining subtasks.

`_extract_confidence(output)` static helper handles three shapes:
- `EnrichedOutput.confidence`
- `getattr(output, "confidence", None)` ← **the latent shape `_find_or_spawn` already prompts for**
- `output.metadata.get("confidence")` for dict outputs

The `for subtask in subtasks` loop becomes `i = 0; while i < len(subtasks)` so the list can mutate mid-iteration. Structurally equivalent to the for-loop when no mutation happens — existing test outputs byte-identical.

### `MetacognitionConfig`

```python
@dataclass(frozen=True)
class MetacognitionConfig:
    redecompose_threshold: float = 0.5
    max_redecompositions: int = 2
    confidence_floor: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.redecompose_threshold <= 1.0:
            raise ValueError("redecompose_threshold must be in [0, 1]")
        if self.max_redecompositions < 0:
            raise ValueError("max_redecompositions must be >= 0")
```

Frozen dataclass matches `OrqestConfig` and `MemoryConfig` style.

### Backward compat — every existing test stays green

| Test file | Survives because |
|---|---|
| `tests/agents/test_base_agent.py` | `run()` unchanged; new ctor param keyword-only with `None` default. |
| `tests/orchestration/test_loop.py` | New params (`confidence_threshold`, `agent_self_eval`) keyword-only with `None` default. New exit reason `"confident"` doesn't appear in existing assertions. |
| `tests/compound/test_sub_agent_tool.py` | New `SubAgentResult` fields optional with `None`/empty defaults. `use_enriched` keyword-only with `False` default. |
| `tests/test_context_manager.py` | `salience_fn` keyword-only with `None` default; existing path verbatim. |
| `tests/autonomy/test_meta.py` | `metacognition` keyword-only with `None` default. While-loop structurally equivalent to for-loop when no mutation. |

### Test strategy — ~30 new tests

`tests/metacognition/{test_enriched.py, test_protocol.py, test_hook.py, test_config.py, test_salience.py, test_integration.py}`

Mocking the model layer per CLAUDE.md convention (use `pydantic_ai.TestModel`). No real API keys required.

### Concept doc outline

`docs/concepts/metacognition.md` — 10-section TOC covering: the four concepts, quickstart, choosing a protocol, wiring into orchestration, the metacognition.confidence event, failure semantics, trade-offs, what's next, reference.

### Module re-exports

`orqest/__init__.py` adds: `EnrichedOutput`, `MetacognitionConfig` only. Protocols and hook stay submodule-only access (matching `EventBusPublishHook` precedent — CLAUDE.md line 88).

### Open design questions

1. Should `confidence_protocol` be a top-level field on `EnrichedOutput`, or stay in `metadata["protocol"]`? **Lean: top-level `protocol_name: str | None`.**
2. Pydantic-AI native confidence (logprobs)? — verify before implementation. **v1.1 if exists; not blocking.**
3. `RefinementLoop`'s `agent_self_eval` interaction with existing `evaluator`? **Lean: mutually exclusive; explicit error if both set.**
4. `EnsembleProtocol`: keep original output or replace with majority? **Lean: keep original.** Confidence is signal, not output replacement.
5. `BaseAgent.run_enriched` auto-emit `metacognition.confidence`? **Lean: no auto-emit; hook is canonical site.**
6. `_build_refinement_prompt` signature inspection — v1 or v2? **Lean: defer to v0.2.**
7. `ContextManager` salience side-table on `id(message)` vs pydantic-AI metadata? **Lean: ship side-table, mark TODO.**
8. `DecisionHook` (out of scope here) — flagged for self-healing track. `MetacognitionHook` is shaped to sit on either protocol; promotion is trivial.

### Critical files for implementation
- `orqest/agents/base_agent.py`
- `orqest/orchestration/loop.py`
- `orqest/compound/sub_agent_tool.py`
- `orqest/agents/context_manager.py`
- `orqest/autonomy/meta.py`
- New: `orqest/metacognition/*`
