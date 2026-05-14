# Metacognition

Orqest treats *what an agent thinks of its own output* as first-class data, not prose. Every agent run can return an `EnrichedOutput[OutputT]` that pairs the structured output with a self-rated `confidence`, a list of `uncertainty_targets` (the assumptions the agent flagged as the bottleneck), and a `capability_boundary` flag (true when the task is outside what the agent can verify). Three pluggable `ConfidenceProtocol` strategies produce that enrichment with different cost/quality trade-offs.

## What problem does this solve?

An agent that says *"the answer is 42"* and one that says *"42, confidence 0.6, the bottleneck is whether assumption X holds"* are different products. The second one composes — downstream code can decide to retry, escalate, refine, or trust. The first one forces every consumer to babysit. Metacognition makes confidence a structured signal on the bus, so refinement loops, healing watchdogs, and UI surfaces can all act on it.

## EnrichedOutput

Generic over `OutputT`, so typing flows unchanged through `Pipeline`, `RefinementLoop`, `SubAgentTool`, etc.

| Field | Type | Description |
|-------|------|-------------|
| `output` | `OutputT` | What the agent produced (unchanged from `BaseAgent.run`) |
| `confidence` | `float \| None` (in `[0, 1]`) | Self-rated probability the output satisfies the task. `None` when no protocol ran or the protocol failed. |
| `uncertainty_targets` | `list[str]` | Free-text identifiers for assumptions the agent flagged as the bottleneck. |
| `capability_boundary` | `bool` | True iff the task is outside what the agent can verify. **Distinct from low confidence.** |
| `protocol_name` | `str \| None` | Which `ConfidenceProtocol` produced this enrichment. |
| `metadata` | `dict[str, Any]` | Protocol-defined free space (sample_count, rating_prompt_hash, protocol_error). Never load-bearing. |

All metacognitive fields are best-effort. A protocol that fails or returns ill-formed data falls back to `confidence=None` with `metadata["protocol_error"]` set.

## Three ConfidenceProtocols

Pick by cost. All implement the same `ConfidenceProtocol` Protocol — swap freely.

### `StructuredOutputProtocol` — zero extra cost

Lifts confidence directly off the agent's own `OutputT`. If your output type already has a `self_confidence` (or `uncertain_about`, or `outside_my_capability`) field, the protocol reads it. **Default recommended.**

```python
from pydantic import BaseModel, Field
from orqest.metacognition import StructuredOutputProtocol


class AnswerWithConfidence(BaseModel):
    answer: str
    self_confidence: float = Field(ge=0.0, le=1.0)
    uncertain_about: list[str] = []
    outside_my_capability: bool = False


protocol = StructuredOutputProtocol()  # field names overridable
```

### `LLMSelfRatingProtocol` — +1 LLM call

Spins up a rater agent that reads the original output and emits a JSON rating. Markdown-fence-tolerant parser. Use when the `OutputT` is fixed and you can't add a confidence field.

```python
from orqest.metacognition import LLMSelfRatingProtocol

protocol = LLMSelfRatingProtocol(
    rater_model="openai:gpt-4.1",
    api_key=config.llm_api_key,
)
```

### `EnsembleProtocol(k=N)` — +k–1 parallel calls

Runs the agent k times in parallel; confidence = pairwise agreement (`_default_agreement` over `model_dump`). Most expensive, but calibrated against actual variance.

```python
from orqest.metacognition import EnsembleProtocol

protocol = EnsembleProtocol(k=3)
```

## BaseAgent.run_enriched

The entry point. Additive — `run` is untouched; you opt in per call or via the agent's ctor.

```python
import asyncio
from pydantic import BaseModel
from orqest.agents import BaseAgent, GlobalState
from orqest.metacognition import StructuredOutputProtocol


class Answer(BaseModel):
    text: str
    self_confidence: float = 0.5
    uncertain_about: list[str] = []


class QAAgent(BaseAgent[GlobalState, Answer]):
    async def _run_implementation(self, state, **kwargs) -> Answer:
        result = await self.call_model(state.get_latest_message("user"), state)
        return result.output


async def main():
    agent = QAAgent(
        agent_name="qa",
        system_prompt="Answer the user's question. Set self_confidence in [0,1] "
        "and list assumptions in uncertain_about.",
        output_type=Answer,
        model="openai:gpt-4.1",
        api_key="sk-...",
        confidence_protocol=StructuredOutputProtocol(),
    )

    state = GlobalState()
    state.add_message("user", "Will it rain in Tokyo on 2030-01-01?")

    enriched = await agent.run_enriched(state)
    print(f"Answer: {enriched.output.text}")
    print(f"Confidence: {enriched.confidence}")
    print(f"Uncertain about: {enriched.uncertainty_targets}")
    print(f"Capability boundary: {enriched.capability_boundary}")


asyncio.run(main())
```

Per-call override:

```python
enriched = await agent.run_enriched(
    state, confidence_protocol=EnsembleProtocol(k=5)
)
```

## MetacognitionHook — confidence on the EventBus

Wire the hook on a `HookRunner` (or pass through `Workbench`); whenever a tool result is an `EnrichedOutput`, a `metacognition.confidence` event fires on the bus. This is the seam that lets the healing layer's `RegressionDetector` act on confidence drops without depending on the metacognition module directly.

```python
from orqest.metacognition import MetacognitionHook
from orqest.observability import EventBus

bus = EventBus()
hook = MetacognitionHook(bus=bus)
# Pass to HookRunner, then to your CompoundTool / SubAgentTool / agent
```

Event payload includes `confidence`, `uncertainty_targets`, `capability_boundary`, `protocol_name`, `agent_name`.

## Integration points

Confidence flows automatically through the rest of the framework:

- **`RefinementLoop(confidence_threshold=0.85)`** — exit reason `"confident"` when score ≥ threshold; saves iterations once the agent is sure
- **`RefinementLoop(agent_self_eval=critic_agent)`** — mutually-exclusive scoring path that synthesises an `EvalResult(passed=False, score=enriched.confidence)` from the agent's own self-rating
- **`MetaOrchestrator(metacognition=MetacognitionConfig(redecompose_threshold=0.5))`** — re-decomposes remaining subtasks when a subtask's confidence drops below threshold, bounded by `max_redecompositions`
- **`ContextManager(salience_fn=confidence_salience)`** — emergency truncation rescues high-confidence old messages on top of the recency window
- **`SubAgentTool.run(use_enriched=True)`** — lifts the final-iteration enrichment onto the result so callers see `SubAgentResult.confidence`

## Cross-feature handshake — metacognition → healing

The `RegressionDetector` watchdog subscribes to `metacognition.confidence` events. When confidence drops sliding-window-over-window, it signals a `Detection`, which the policy maps to a `RecoveryAction`. Metacognition produces the signal; healing acts on it. This is the cognitive substrate's most distinctive feature: an agent that knows it's getting worse, and a system that does something about it.

```python
from orqest.healing import RegressionDetector

detector = RegressionDetector(
    window_n=10,        # rolling window size
    drop_threshold=0.2, # head-mean − tail-mean ≥ 0.2 fires
)
detector.subscribe(bus)
```

## MetacognitionConfig

Frozen dataclass for orchestration policy:

```python
from orqest.metacognition import MetacognitionConfig

config = MetacognitionConfig(
    redecompose_threshold=0.5,   # MetaOrchestrator triggers re-decomposition below this
    max_redecompositions=2,      # bounds re-decomposition recursion
    confidence_floor=0.3,        # below this, return enriched.output but flag in metadata
)
```

## Best practices

- **Default to `StructuredOutputProtocol`.** Zero cost. Add `self_confidence: float` to your `OutputT` and you're done. Only graduate to `LLMSelfRating` or `Ensemble` when you've measured a calibration gap.
- **`capability_boundary` is not low confidence.** "I don't know" (capability boundary) and "I'm 0.4 sure" (low confidence) compose to different recovery actions. Treat them as distinct signals.
- **Confidence is calibration-defined, not absolute.** A `StructuredOutputProtocol`'s 0.7 isn't comparable to an `EnsembleProtocol(k=10)`'s 0.7. Treat confidence as a within-protocol ranking signal; never compare across protocols.
- **`run_enriched` is opt-in.** `run` stays as-is for callers who don't care. Don't force enrichment into call paths that don't consume it.

## Pitfalls

- **Don't propagate `confidence=None` as if it were 0.** `None` means "no protocol ran or failed" — distinct from "the agent is confident this is wrong."
- **Don't read `metadata["protocol_error"]` as a diagnostic in production logic.** It's UI/telemetry only. If you need the failure to be load-bearing, use a hook that returns `Abort`.
- **Don't subscribe `RegressionDetector` to a bus that doesn't carry `metacognition.confidence` events.** It silently no-ops (graceful degradation), but you'll be wondering why nothing fires.

## What's happening under the hood

1. `BaseAgent.run_enriched(state)` calls `BaseAgent.run(state)` to produce `OutputT`
2. The configured `ConfidenceProtocol.score(output, state)` runs, producing `(confidence, uncertainty_targets, capability_boundary, metadata)` (or fails, in which case `confidence=None`)
3. `EnrichedOutput[OutputT]` is constructed
4. If a `MetacognitionHook` is wired to a bus, the `metacognition.confidence` event is emitted
5. Downstream consumers (`RefinementLoop`, `RegressionDetector`, `ContextManager`, UI) read whatever shape they need

## Related Concepts

- [Agents](agents.md) — `BaseAgent` and the `run_enriched` extension point
- [Orchestration](orchestration.md) — `RefinementLoop` integration
- [Healing](healing.md) — `RegressionDetector` consuming `metacognition.confidence`
- [Observability](observability.md) — events on the bus
- [Hooks & Lifecycle](hooks-and-lifecycle.md) — `MetacognitionHook` + `HookRunner`
