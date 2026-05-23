# Optimization — reference

Compressed judgment layer over `orqest/optimization/`. For full reference, read `docs/concepts/optimization.md`.

## What this battery does

Wires [GEPA](https://github.com/gepa-ai/gepa) (Genetic-Pareto reflective evolution, Agrawal et al., ICLR 2026) into Orqest's existing signal stream so prompts evolve from real traces. Reported wins: **+6% over GRPO with 35× fewer rollouts; +10% over MIPROv2.** Orqest fits cleanly because the framework already produces every multi-objective signal — `EnrichedOutput`, `RunUsage`, `Tracer.Span`, `EventBus` events.

**When to reach for it:** you have ≥10 labeled gold examples + a `score_fn`, your prompts are hand-tuned, and you want to evolve them. **When not:** stable production prompts with no measurement loop. Hand-tune until you have a real eval set.

## Optional install

```bash
uv sync --group optimization                              # pulls gepa[full] + litellm + datasets (~50-80 MB)
```

`from orqest.optimization import OptimizationRunner` raises `ImportError` with this instruction if missing.

## The three-layer split

| Layer | Files | Responsibility |
|---|---|---|
| **Encoding** | `genome.py` | Turn typed surface → GEPA's `dict[str, str]` candidate format |
| **Evaluation** | `evaluator.py`, `bundle.py` | Run a candidate vs `GoldExample`, produce `MetricBundle` |
| **Adaptation** | `adapter.py`, `runner.py`, `apply.py`, `_compat.py` | Bridge GEPA Protocol → Orqest; drive the loop; write the winner back |

## Genes — what's evolvable

```python
from orqest.optimization import Genome, PromptGene, ScalarGene, CategoricalGene

genome = Genome(genes=[
    PromptGene(
        name="researcher.system_prompt",                     # MUST match the agent_factory's read key
        initial="You are a careful research assistant.",
        constraints="Always cite the source paragraph; abstain when unsure.",
    ),
])
```

- `PromptGene` — string prompt slot. **The bread-and-butter.**
- `ScalarGene` — bounded float with optional quantization grid. Gated by `enable_scalar_genes` (off by default).
- `CategoricalGene` — fixed-set string choice. Same gating.

Decode is **resilient by design**: a malformed reflection (missing key, unparseable scalar, out-of-set categorical) falls back to the gene's `initial` rather than raising. Lose one iteration, not the whole run.

## `MetricBundle` — per-example fitness payload

| Dimension | Type | Source | Direction |
|---|---|---|---|
| `accuracy` | `[0, 1]` | your `score_fn` | ↑ |
| `confidence` | `[0, 1]` \| None | `EnrichedOutput.confidence` | ↑ |
| `cost_usd` | `>= 0` | optional `cost_estimator(usage)` | ↓ |
| `latency_ms` | `>= 0` | wall-clock per example | ↓ |
| `robustness` | `[0, 1]` \| None | consumer-defined (e.g. healing detector fires) | ↑ |

```python
from orqest.optimization import MetricBundle, MetricWeights

weights = MetricWeights(accuracy=1.0, cost_usd=-0.1, latency_ms=-0.001)
bundle = MetricBundle(accuracy=0.8, cost_usd=0.5, latency_ms=1200.0)
scalar = bundle.scalarize(weights)                         # → 0.65 (used by GEPA acceptance test)
dims = bundle.to_per_instance_scores(weights)              # → per-dimension (used by GEPA Pareto frontier)
```

`None` dimensions are **skipped**, never zero-filled — a missing signal must not penalize a candidate that didn't surface it.

## `Evaluator` — wraps what GEPA needs

```python
from orqest.optimization import Evaluator, GoldExample
from orqest.metacognition import StructuredOutputProtocol

def factory(decoded):
    # MUST return a FRESH agent. Mutating an existing agent's system_prompt is
    # unsafe because the cached pydantic_ai.Agent keeps the old prompt baked in.
    return ResearchAgent(system_prompt=decoded["researcher.system_prompt"], ...)

def score(output, example):
    return 1.0 if example.expected.answer in output.answer else 0.0

evaluator = Evaluator(
    agent_factory=factory,
    score_fn=score,                                          # sync or async, returns float in [0, 1]
    confidence_protocol=StructuredOutputProtocol(),          # optional — fills MetricBundle.confidence
    cost_estimator=lambda usage: 1e-6 * (usage.input_tokens + 3 * usage.output_tokens),  # optional
)
```

Per GEPA contract, the evaluator **never raises** for per-example failures. Exception → `accuracy=0.0` with the error in `MetricBundle.raw["error"]`. GEPA proceeds to next example.

## Running an optimization

```python
from orqest.optimization import OptimizationConfig, OptimizationRunner, GoldExample

config = OptimizationConfig(
    max_metric_calls=150,                                    # the rollout budget (the cost-dominant knob)
    reflection_model="anthropic:claude-opus-4-7",            # the optimizer's brain — use the strongest you can afford
    task_model="openai:gpt-4.1-mini",                        # what we're optimizing for — can stay cheap
)

runner = OptimizationRunner(
    config,
    genome=genome,
    evaluator=evaluator,
    bus=workbench.event_bus,                                 # optional: emits optimization.iteration_completed
)

result = await runner.optimize(trainset, valset)
print(f"Best score: {result.best_score:.3f}")
print(f"Pareto frontier size: {len(result.pareto_candidates)}")
```

## The Pareto frontier — the real output

`result.pareto_candidates` is the set of distinct candidates that win on *some* example or *some* objective dimension. The accuracy-king may be the latency-loser. The cheap candidate may score 5% lower but cost 80% less. Inspect the frontier, not just `best_candidate`.

## Apply — dry-run by default

```python
from orqest.optimization import apply_result

diffs = apply_result(result, target=my_agent, dry_run=True)  # default
for d in diffs:
    if d.changed:
        print(d.unified)

# Happy with it? Commit:
apply_result(result, target=my_agent, dry_run=False)
```

**Critical gotcha:** when committing, `apply_result` resets the agent's cached `pydantic_ai.Agent` (`target._agent = None`). Without that reset, the new prompt is **silently invisible at runtime** — the cached Agent keeps the old prompt. The default commit path handles this; if you bypass `apply_result` and write `agent.system_prompt = ...` manually, clear the cache yourself.

Target can also be a plain `dict` (e.g., a settings store) — values written by key, no cache reset needed.

## Cost reasoning

`max_metric_calls` is the only knob that moves the cost needle. Rough scaling:

```
total LLM calls ≈ max_metric_calls × |minibatch|
                  + ~max_metric_calls / minibatch_size  (reflection calls)
```

For 150 metric_calls × 3 minibatch + ~50 reflection calls on a 10-20 example gold set: **~$1-$3 end-to-end** depending on task + reflection model. **The reflection model dominates the cost.** Use a strong reflection model; task model can stay cheap.

## Topology evolution — `MetaAgentSearch`

For evolving the *structure* (Pipeline / Parallel / Router compositions), not prompts:

```python
from orqest.optimization import MetaAgentSearch, MetaAgentConfig
```

ADAS-style search loop. Same `MetricBundle` Pareto contract; different mutation engine. See `docs/concepts/topology_optimization.md` for the full picture — out of scope for this reference.

## Pitfalls

- **`agent_factory` MUST return a fresh agent.** Mutating an existing agent's `system_prompt` is unsafe because the cached pydantic-ai Agent keeps the old prompt baked in. The factory pattern is load-bearing.
- **`apply_result(dry_run=False)` resets `target._agent`.** If you bypass `apply_result`, clear the cache yourself — otherwise the optimization is invisible at runtime.
- **None-valued metric dimensions are skipped, not zero-filled.** Don't infer "missing = failed."
- **`max_metric_calls` is the cost knob.** Tuning anything else without measuring is a waste. Use the strongest reflection model, the cheapest task model.
- **Don't optimize without an eval set.** Without ≥10 gold examples + a real `score_fn`, you're tuning to noise. The W2 `synthetic_gold` module is the deferred unblocker — bootstrap an eval set from a strong model.

## Where to read more

- `docs/concepts/optimization.md` — full reference
- `docs/concepts/topology_optimization.md` — `MetaAgentSearch` evolving topologies
- `references/metacognition.md` — `EnrichedOutput.confidence` populating `MetricBundle.confidence`
- `notebooks/06_optimization_basic.ipynb` — evolve a research summariser's prompt against a 15-example gold set
- `notebooks/07_optimization_compound.ipynb` — evolve the planner inside `MetaOrchestrator`
