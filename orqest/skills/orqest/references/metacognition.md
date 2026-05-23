# Metacognition — reference

Compressed judgment layer over `orqest/metacognition/`. For full reference, read `docs/concepts/metacognition.md`.

## The shape — `EnrichedOutput[OutputT]`

Generic over `OutputT`, so types flow unchanged through `Pipeline`, `RefinementLoop`, `SubAgentTool`, etc.

| Field | Type | Meaning |
|---|---|---|
| `output` | `OutputT` | What the agent produced (unchanged from `BaseAgent.run`) |
| `confidence` | `float \| None` in `[0, 1]` | Self-rated probability the output satisfies the task. `None` = no protocol ran or it failed. |
| `uncertainty_targets` | `list[str]` | Free-text identifiers for assumptions the agent flagged as the bottleneck |
| `capability_boundary` | `bool` | True iff the task is outside what the agent can verify. **Distinct from low confidence.** |
| `protocol_name` | `str \| None` | Which protocol produced this |
| `metadata` | `dict` | Protocol-defined free space (never load-bearing) |

All metacognitive fields are best-effort. Protocol failure → `confidence=None` with `metadata["protocol_error"]` set.

## Three `ConfidenceProtocol`s — pick by cost

```python
from orqest.metacognition import (
    StructuredOutputProtocol,            # 0 cost — default recommended
    LLMSelfRatingProtocol,               # +1 LLM call
    EnsembleProtocol,                    # +k-1 parallel calls
    ConfidenceProtocol,                  # the Protocol — implement your own
)
```

### `StructuredOutputProtocol` — zero extra cost

Lifts confidence off the agent's own `OutputT`. If your output type has `self_confidence` (or `uncertain_about`, or `outside_my_capability`), the protocol reads it. **Always reach for this first.**

```python
from pydantic import BaseModel, Field

class Answer(BaseModel):
    text: str
    self_confidence: float = Field(ge=0.0, le=1.0)
    uncertain_about: list[str] = []
    outside_my_capability: bool = False
```

### `LLMSelfRatingProtocol` — +1 LLM call

Rater agent reads the output and emits a JSON rating. Use when `OutputT` is fixed and you can't add a confidence field.

```python
protocol = LLMSelfRatingProtocol(rater_model="openai:gpt-4.1", api_key="sk-...")
```

### `EnsembleProtocol(k=N)` — most expensive, best calibrated

Runs the agent k times in parallel; confidence = pairwise agreement.

```python
protocol = EnsembleProtocol(k=3)
```

## Wire-up — `run_enriched`

`run_enriched` is additive — `run` stays as-is for callers who don't care.

```python
from orqest.agents import BaseAgent, GlobalState
from orqest.metacognition import StructuredOutputProtocol

agent = QAAgent(
    agent_name="qa",
    system_prompt="Answer the user's question. Set self_confidence in [0,1] and list assumptions in uncertain_about.",
    output_type=Answer,
    model="openai:gpt-4.1",
    api_key="sk-...",
    confidence_protocol=StructuredOutputProtocol(),         # agent-level default
)

enriched = await agent.run_enriched(state)                  # → EnrichedOutput[Answer]
# Per-call override:
enriched = await agent.run_enriched(state, confidence_protocol=EnsembleProtocol(k=5))
```

## `MetacognitionHook` — confidence on the EventBus

Whenever a tool result is an `EnrichedOutput`, a `metacognition.confidence` event fires. This is the seam healing's `RegressionDetector` subscribes to.

```python
from orqest.metacognition import MetacognitionHook
from orqest.observability import EventBus
from orqest.hooks import HookRunner

bus = EventBus()
hook = MetacognitionHook(bus=bus)
runner = HookRunner(hooks=[hook])
# Pass `runner` to CompoundTool / SubAgentTool / agent
```

## Integration points (confidence flows automatically)

| Consumer | How it uses confidence |
|---|---|
| `RefinementLoop(confidence_threshold=0.85)` | Exit reason `"confident"` when score ≥ threshold |
| `RefinementLoop(agent_self_eval=critic)` | Synthesises `EvalResult(score=enriched.confidence)` from the agent's self-rating |
| `MetaOrchestrator(metacognition=...)` | Re-decomposes remaining subtasks when subtask confidence < `redecompose_threshold` |
| `ContextManager(salience_fn=confidence_salience)` | Emergency truncation rescues high-confidence old messages on top of recency window |
| `SubAgentTool.run(use_enriched=True)` | Lifts final-iteration enrichment onto `SubAgentResult.confidence` |
| `RegressionDetector` (healing) | Subscribes to `metacognition.confidence` for confidence-drop detection |
| `MetricBundle.confidence` (optimization) | Filled from `EnrichedOutput.confidence` — optimizer evolves calibration |

## `MetacognitionConfig` — orchestration policy

```python
from orqest.metacognition import MetacognitionConfig

MetacognitionConfig(
    redecompose_threshold=0.5,     # MetaOrchestrator: re-decompose remaining below this
    max_redecompositions=2,        # bound re-decomposition recursion
    confidence_floor=0.3,          # below this, return enriched.output but flag in metadata
)
```

## `confidence_salience` / `recency_salience` — for ContextManager

```python
from orqest.metacognition import confidence_salience, recency_salience

# Plug into a ContextManager to rescue high-confidence old messages
ctx = ContextManager(salience_fn=confidence_salience)
```

## Pitfalls

- **`confidence=None` is not 0.** It means "no protocol ran or it failed" — distinct from "the agent is confident this is wrong." Don't propagate as zero.
- **`capability_boundary` is not low confidence.** "I don't know" (capability boundary) vs "I'm 0.4 sure" (low confidence) compose to different recovery actions. Distinct signals.
- **Confidence is calibration-defined, not absolute.** A `StructuredOutputProtocol` 0.7 isn't comparable to an `EnsembleProtocol(k=10)` 0.7. Treat as within-protocol ranking only — never compare across protocols.
- **Don't read `metadata["protocol_error"]` as production logic.** It's UI/telemetry only. If you need the failure to be load-bearing, use a hook that returns `Abort`.
- **`run_enriched` is opt-in.** Don't force enrichment into call paths that don't consume it.
- **`RefinementLoop(agent_self_eval=…)` requires `confidence_protocol` on the agent.** Validated at construction. Without one, `run_enriched` yields `confidence=None` and the loop could never exit `"confident"`.

## Where to read more

- `docs/concepts/metacognition.md` — full reference
- `references/healing.md` — `RegressionDetector` consuming `metacognition.confidence`
- `references/orchestration.md` — `RefinementLoop` confidence-driven exit
- `references/autonomy.md` — `MetaOrchestrator` confidence-driven re-decomposition
- `notebooks/01_cognitive_substrate.ipynb` — `run_enriched` + `StructuredOutputProtocol` + `MetacognitionHook` end-to-end with healing
