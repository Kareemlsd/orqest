# Optimization

Orqest already produces every signal a multi-objective optimizer needs (accuracy via output validation, confidence via `EnrichedOutput`, latency via `Tracer.Span`, cost via `pydantic_ai.usage.RunUsage`, robustness via `HealingRunner` detector firings) — but those signals never close the loop back into the prompts that drive the agents. This battery wires [GEPA](https://github.com/gepa-ai/gepa) (Genetic-Pareto reflective evolution, Agrawal et al., ICLR 2026 Oral) into the existing signal stream so the prompts driving your agents evolve from real traces.

## What problem does this solve?

Prompts are code that no one tests. Hand-tuning is expensive and gets worse as the system grows; reinforcement-learning fine-tuning is overkill for most apps; GEPA's reflective textual evolution is the right granularity. A separate "reflection" LLM reads execution trajectories in natural language, proposes targeted prompt mutations, and a Pareto frontier prevents collapse into local optima. Reported wins on the original benchmarks: **+6% over GRPO with 35× fewer rollouts; +10% over MIPROv2.**

The Orqest fit is unusually clean because the framework already produces multi-dimensional fitness signals out of the box. The optimizer doesn't need new instrumentation — it consumes `EnrichedOutput`, `RunUsage`, `Tracer.Span`, and `EventBus` events that were always going to be there.

## Optional install

GEPA pulls litellm + datasets + tiktoken transitively (~50–80 MB). It's not a core Orqest dependency:

```bash
uv sync --group optimization
```

`from orqest.optimization import OptimizationRunner` raises a friendly `ImportError` with this same instruction when the dep isn't installed.

## The three-layer split

| Layer | Files | Responsibility |
|---|---|---|
| **Encoding** | `orqest/optimization/genome.py` | Turn Orqest's typed surface into GEPA's `dict[str, str]` candidate format |
| **Evaluation** | `orqest/optimization/evaluator.py`, `bundle.py` | Run a candidate against a `GoldExample`, produce a `MetricBundle` |
| **Adaptation** | `orqest/optimization/adapter.py`, `runner.py`, `apply.py`, `_compat.py` | Bridge GEPA's `GEPAAdapter` Protocol → Orqest, drive the loop, write the winner back |

## Genes — what's evolvable

A `Genome` is an ordered list of typed genes. Three kinds today:

- `PromptGene` — a string prompt slot. The bread-and-butter of W1.
- `ScalarGene` — a bounded float with optional quantization grid. Wired but gated by `OptimizationConfig.enable_scalar_genes`.
- `CategoricalGene` — a fixed-set string choice. Same gating story.

```python
from orqest.optimization import Genome, PromptGene

genome = Genome(genes=[
    PromptGene(
        name="researcher.system_prompt",
        initial="You are a careful research assistant.",
        constraints="Always cite the source paragraph; abstain when unsure.",
    ),
])
```

The `name` is the slot identifier — it must match the key your `agent_factory` reads to construct the agent. The `constraints` field is surfaced verbatim to the reflection LLM in `make_reflective_dataset`; use it to pin invariants the optimizer must not break.

Decode is **resilient by design**: a malformed reflection (missing key, unparseable scalar, out-of-set categorical) falls back to the gene's `initial` rather than raising. We'd rather lose one iteration than crash the run.

## The MetricBundle contract

`MetricBundle` is the per-example fitness payload:

| Dimension | Type | Source | Direction |
|---|---|---|---|
| `accuracy` | `[0, 1]` | your `score_fn` | higher is better |
| `confidence` | `[0, 1]` \| None | `EnrichedOutput.confidence` | higher is better |
| `cost_usd` | `>= 0` | optional `cost_estimator(usage)` | lower is better |
| `latency_ms` | `>= 0` | wall-clock per example | lower is better |
| `robustness` | `[0, 1]` \| None | (consumer-defined) | higher is better |

Two views on the same bundle, both consumed by GEPA:

- `MetricBundle.scalarize(weights)` — a single weighted sum used by GEPA's acceptance test (the per-example float in `EvaluationBatch.scores`).
- `MetricBundle.to_per_instance_scores(weights)` — an unweighted per-dimension dict used by GEPA's `EvaluationBatch.objective_scores`. With `OptimizationConfig.frontier_type="hybrid"` (the default), GEPA's native Pareto frontier discovers tradeoffs across both example-instances and objective dimensions.

```python
from orqest.optimization import MetricBundle, MetricWeights

weights = MetricWeights(accuracy=1.0, cost_usd=-0.1, latency_ms=-0.001)
bundle = MetricBundle(accuracy=0.8, cost_usd=0.5, latency_ms=1200.0)
scalar = bundle.scalarize(weights)               # 0.65
dims = bundle.to_per_instance_scores(weights)    # {'accuracy': 0.8, 'cost_usd': 0.5, ...}
```

`None` dimensions (an absent `confidence` or `robustness` signal) are *skipped* in scalarize, never zero-filled — a missing signal must not penalize a candidate that simply didn't surface it.

## The Evaluator pattern

The evaluator wraps the bits a GEPA-adapter needs to score a candidate against your gold set. The user supplies:

- An `agent_factory(decoded) -> BaseAgent` that constructs a **fresh** agent from a decoded genome. Freshness matters: mutating an existing agent's `system_prompt` is unsafe because the cached `pydantic_ai.Agent` keeps the old prompt.
- A `score_fn(output, example) -> float in [0, 1]` (sync or async).

Optional:

- `confidence_protocol` — when set, the evaluator reads `output.confidence` / `output.self_confidence` / `output.metadata['confidence']` to fill `MetricBundle.confidence`.
- `cost_estimator(usage) -> float` — translates `pydantic_ai.usage.RunUsage` to USD. Without it, `cost_usd` stays 0 (token totals still surface in `MetricBundle.raw`).

```python
from orqest.optimization import Evaluator, GoldExample
from orqest.metacognition import StructuredOutputProtocol

def factory(decoded):
    return ResearchAgent(system_prompt=decoded["researcher.system_prompt"], ...)

def score(output, example):
    return 1.0 if example.expected.answer in output.answer else 0.0

evaluator = Evaluator(
    agent_factory=factory,
    score_fn=score,
    confidence_protocol=StructuredOutputProtocol(),
    cost_estimator=lambda usage: 1e-6 * (usage.input_tokens + 3 * usage.output_tokens),
)
```

Per the GEPA Protocol contract, the evaluator **never raises** for per-example failures. An exception during agent construction or `score_fn` is captured as `accuracy=0.0` with the error in `MetricBundle.raw["error"]`. GEPA proceeds to the next example.

## Running an optimization

```python
from orqest.optimization import (
    OptimizationConfig, OptimizationRunner, Genome, PromptGene, GoldExample,
)

config = OptimizationConfig(
    max_metric_calls=150,                          # rollout budget
    reflection_model="anthropic:claude-opus-4-7",  # the optimizer's brain
    task_model="openai:gpt-4.1-mini",              # what we're optimizing for
)

runner = OptimizationRunner(
    config,
    genome=genome,
    evaluator=evaluator,
    bus=workbench.event_bus,                       # optional: emits iteration events
)

result = await runner.optimize(trainset, valset)
print(f"Best score: {result.best_score:.3f}")
print(f"Pareto frontier size: {len(result.pareto_candidates)}")
```

## The Pareto frontier

`result.pareto_candidates` is the **real** output, not just `result.best_candidate`. With `frontier_type="hybrid"`, GEPA returns the set of distinct candidates that win on *some* example or *some* objective dimension. Inspect it to see tradeoffs the aggregate scalar winner doesn't surface:

```python
for cand in result.pareto_candidates:
    print(cand)
```

The accuracy-king on the frontier might also be the latency-loser. The cheap candidate might score 5% lower but cost 80% less. Pareto reasoning makes that visible.

## Apply: dry-run by default

`apply_result` defaults to `dry_run=True`. It builds and returns the unified diffs but does not mutate your agent. Flip `dry_run=False` to commit:

```python
from orqest.optimization import apply_result

diffs = apply_result(result, target=my_agent, dry_run=True)
for d in diffs:
    if d.changed:
        print(d.unified)

# Happy with it? Commit.
apply_result(result, target=my_agent, dry_run=False)
```

**Critical gotcha:** when committing, `apply_result` resets the agent's cached `pydantic_ai.Agent` (`target._agent = None`). Without that reset, the new prompt is silently invisible at runtime — the cached Agent keeps the old prompt baked in. The default commit path handles this; if you bypass `apply_result` and write `agent.system_prompt = ...` manually, remember to clear the cache yourself.

The target can also be a plain `dict` (e.g., a settings store) — values are written by key, no cache reset needed.

## Cost reasoning

`max_metric_calls` is the only knob that really moves the cost needle. Rough scaling:

```
total LLM calls ≈ max_metric_calls × |minibatch|
                  + ~max_metric_calls / minibatch_size  (reflection calls)
```

For 150 metric_calls × 3 minibatch + ~50 reflection calls on a typical 10–20 example gold set, expect **~$1–$3 end-to-end** depending on the task and reflection model. The reflection model dominates the cost — use the strongest model you can afford for reflection, not the task. The task model can stay cheap.

## What's next

These are wired-in extension points, not work that's done. They live in the architecture as future seams:

- **W1.5 — Model-as-gene.** Mutating `BaseAgent.model` mid-optimization is gated until we've measured single-model variance and have a Pareto-comparison story across providers.
- **W2 — Synthetic gold (`synthetic_gold.py`).** Bootstrap a 10–20-example eval set from a strong model. The single biggest adoption blocker for any optimizer is "I don't have a labeled eval set." This module solves it.
- **W2 — Scalar/categorical gene activation.** Flip `enable_scalar_genes` / `enable_categorical_genes` defaults; wire scalar/categorical decode into the runner. The types ship in W1; the wiring is what's deferred.
- **W3 — Topology evolution.** ✅ Shipped — see [Topology Optimization](topology_optimization.md). The orchestration IR (`PipelineSpec` / `RouterSpec` / `ParallelSpec` / `RefinementLoopSpec`) plus an ADAS-style `MetaAgentSearch` loop. Same `MetricBundle` Pareto contract, different mutation engine.

## Related Concepts

- [Topology Optimization](topology_optimization.md) — evolves the *topology* (Pipeline / Parallel / Router compositions) rather than the prompts. Two-phase composition with this battery is the recommended way to evolve both axes.
- [Metacognition](metacognition.md) — `EnrichedOutput.confidence` is the primary signal that fills `MetricBundle.confidence`.
- [Self-Healing](healing.md) — healing detector firings can populate `MetricBundle.robustness`; the optimizer can then evolve prompts that are less likely to trigger watchdogs.
- [Workbench](workbench.md) — pass `workbench.event_bus` to the runner to surface `optimization.iteration_completed` events alongside the rest of your observability stream.
- [Observability](observability.md) — the `EventBus` and `Tracer` already capture everything the optimizer feeds GEPA's reflection LLM.

## Runnable demos

- [`notebooks/06_optimization_basic.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/06_optimization_basic.ipynb) — evolve a research summariser's prompt against a 15-example gold set
- [`notebooks/07_optimization_compound.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/07_optimization_compound.ipynb) — evolve the planner inside `MetaOrchestrator`
