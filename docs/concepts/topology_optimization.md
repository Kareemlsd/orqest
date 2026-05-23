# Topology optimization

GEPA evolves the prompts inside a fixed topology ([Optimization](optimization.md)). This battery evolves the *topology itself* — discovers Pipeline / Parallel / Router compositions from real traces against a small gold set. **Same Pareto frontier contract; different mutation engine.**

The implementation is ADAS-inspired ([Hu, Lu, Clune 2024, arXiv 2408.08435](https://arxiv.org/abs/2408.08435)) — Meta Agent Search with archive-based reflective evolution — but **diverges deliberately on the search surface**: the meta agent emits typed `TopologySpec` JSON, not raw Python. There is no `exec()`, no sandbox, no code-execution failure modes. Expressivity is capped to compositions of registered primitives; the cap is the deliberate price of safety.

## What problem does this solve?

Two complementary failure modes in the GEPA-only world:

1. **Wrong structure.** A single CoT agent can't compete with a CoT → Verifier Pipeline on inferential tasks; no amount of prompt evolution recovers what a missing structural step costs.
2. **Wrong specialization.** A Router with an abstain-classifier in front handles off-topic inputs cleanly; a single agent with "abstain when unsure" baked into its prompt is unreliable at it.

This battery surfaces those structural axes as evolvable. The meta agent designs combinations of `AgentStep` / `FunctionStep` over `Pipeline` / `Parallel` / `Router` / `RefinementLoop`, evaluates each candidate against your gold set, and keeps the top-K on a Pareto frontier of accuracy / cost / latency / `n_agents` / `depth`.

## The two-layer split

| Layer | Files | Responsibility |
|---|---|---|
| **Orchestration IR** | `orqest/orchestration/spec.py`, `orqest/orchestration/hydrate.py` | Pydantic models + spec→runtime hydration. Independently useful (closes the audit-named "LLM cannot emit topology at runtime" gap regardless of search). |
| **Search engine** | `orqest/optimization/topology.py`, `orqest/optimization/meta_agent.py` | TopologyGene + TopologyEvaluator + MetaAgentSearch loop (design → reflexion → evaluate → archive). |

Both ship together but the IR is the load-bearing piece — once `TopologySpec` exists, any search engine (MetaAgentSearch today, MCTS / GA / RL tomorrow) is a plug-in.

## TopologySpec instead of raw Python — the deliberate cap

ADAS's public repo ([`ShengranHu/ADAS`](https://github.com/ShengranHu/ADAS)) calls `exec(forward_str, globals(), namespace)` directly in the search process — the paper claims "containerized execution," but the public code is in-process `exec` with try/except. This is fine for research, **unacceptable for a library shipped to consumers.**

Orqest takes the [AFlow](https://arxiv.org/abs/2410.10762) approach instead: meta agent emits a typed JSON document validated by Pydantic. The hydrator looks up agent and callable references against explicit registries — there is no `eval`, no `exec`, no name forgery. The emission surface is *names from a user-controlled allowlist*, nothing more.

The cap: candidates are restricted to compositions of *registered* primitives. Novel reasoning blocks (the kind ADAS occasionally discovers) are not expressible. We earn that expressivity back later (W3.C — `orqest/sandbox/` + raw-Python codegen behind a `Sandbox` Protocol) only if users prove they need it.

## The CallableRegistry contract

```python
from orqest.orchestration.hydrate import CallableRegistry

cr = CallableRegistry()
cr.register("is_long", lambda x: len(str(x)) > 200)
cr.register("first_wins_priority", custom_merge)
cr.register("propose_next", state_updater)
print(cr.names())   # ['first_wins_priority', 'is_long', 'propose_next']
```

The meta agent receives `cr.names()` in its design prompt as the *only* legal callable references. Hydrating a spec that names `"unknown_fn"` raises `KeyError` — the search loop catches that, feeds the error back to the meta agent as debug feedback, and retries up to `MetaAgentConfig.debug_max` times.

The same pattern applies to the agent registry — a `dict[str, Callable[[], BaseAgent]]` of factories (not instances; factories avoid cached-`_agent` problems when the same agent appears in multiple candidates).

## The MetaAgentSearch loop

```python
from orqest.optimization import (
    MetaAgentConfig, MetaAgentSearch, TopologyGene, TopologyEvaluator,
)
from orqest.orchestration.spec import PipelineSpec, AgentStepSpec, PipelineStepEntry

seed = PipelineSpec(steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="cot"))])
gene = TopologyGene(
    name="main",
    initial=seed,
    constraints="Must end with an agent capable of abstaining for off-topic inputs.",
)

search = MetaAgentSearch(
    MetaAgentConfig(n_generations=10, archive_strategy="top_k", archive_size=5),
    gene=gene,
    evaluator=TopologyEvaluator(
        score_fn=score_fn,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    ),
    meta_agent_model="openai:gpt-4.1",
    api_key=api_key,
)
result = await search.run(trainset=gold_set)
```

Each generation:

1. **Design** — the meta agent emits a `TopologyDesign(thought, spec)` given the archive view (strategy-dependent), the TopologySpec JSON schema, the agent / callable allowlists, and any `TopologyGene.constraints`.
2. **Reflexion** — `MetaAgentConfig.reflexion_passes` rounds of "critique your own design and revise" (ADAS uses 2 by default).
3. **Evaluate** — hydrate the spec, run on a deterministically-sampled `minibatch_size`-sized subset of the valset, score with `TopologyEvaluator`. On Pydantic ValidationError or hydration KeyError, the error is fed back as debug feedback (analogue of ADAS's traceback retry) and the design step retries.
4. **Archive** — append the `(spec, bundles, aggregate_score, thought)` entry. The next generation sees a strategy-dependent archive view in its prompt.

After `n_generations`, the loop returns an `OptimizationResult` shaped identically to the GEPA path — same `best_candidate` / `best_decoded` / `pareto_candidates` / `history` / `raw` fields. Downstream consumers (`apply_result`, notebook visualizations) work without dispatch.

## Archive strategies

| Strategy | What the meta agent sees on the next design | Use case |
|---|---|---|
| `top_k` (default) | Top `archive_size` entries by aggregate score | Strongest signal-to-noise per the [2510.06711 critique](https://arxiv.org/abs/2510.06711). Recommended. |
| `cumulative` | Every entry seen so far | ADAS-paper-faithful. Tends to overflow context after ~20 entries and dilute strong signals. Use for reproducing the original paper. |
| `parallel` | Nothing | Each generation designs from scratch; selection is end-only. Surprisingly competitive per the same critique. Useful when archive context is biasing the meta agent toward incremental tweaks. |

All entries are retained in storage (so `pareto()` and `best()` see the full history); the strategy only affects what's *shown* to the next design step.

## Two-phase composition with GEPA — never nest

Naive nesting (running GEPA inside each MetaAgentSearch iteration) compounds cost multiplicatively: `O(N_topology × N_prompts × N_eval × |val_set|)` LLM calls — four-to-five-figure dollar bills per discovery. Worse, topology mutations invalidate GEPA-learned prompts (a prompt evolved for `LLM_debate(roles=[A,B,C])` does not transfer to `Router(abstain | CoT-then-Verifier)`), so the inner GEPA run wastes compute on a structure about to change.

**Always two-phase:** find topology with a fixed strong-prompt template; tune prompts on the winner.

```python
# Phase 1: topology
topology_result = await MetaAgentSearch(...).run(gold_set)
winning_topology = topology_result.best_decoded["main"]

# Phase 2: prompts on the winner
prompt_genes = [PromptGene(name=f"{a}.system_prompt", initial=SEED[a]) for a in agents_in(winning_topology)]
prompt_runner = OptimizationRunner(
    OptimizationConfig(...),
    genome=Genome(genes=prompt_genes),
    evaluator=Evaluator(agent_factory=evolved_topology_factory(winning_topology), score_fn=score_fn),
    api_key=api_key,
)
final_result = await prompt_runner.optimize(trainset=gold_set)
```

Notebook `09_topology_with_gepa.ipynb` demonstrates the full ablation with concrete numbers.

## MetricBundle dimensions for topology

`TopologyEvaluator` reuses [the standard MetricBundle](optimization.md#the-metricbundle-contract) with two extra structural dimensions in `bundle.raw`:

| Dimension | What it measures | Direction |
|---|---|---|
| `n_agents` | Total `AgentStepSpec` count in the hydrated topology | lower is better (cost ceiling proxy) |
| `depth` | Maximum nesting depth | lower is better (latency ceiling proxy) |

These flow through to `MetricBundle.to_per_instance_scores()` automatically when surfaced; the optimizer's Pareto frontier prefers smaller / shallower topologies on accuracy ties without any further wiring.

**Cost limitation (honest).** Today, `cost_usd=0.0` for topology evaluations because we don't aggregate `Usage` across multiple agents in the hydrated topology — each agent's `Usage` is local to its own `BaseAgent.call_model` invocation. Consumers wanting cost-as-fitness should pass a `cost_estimator` callable that walks the topology and sums per-agent token usage; the `MetricBundle.raw` extension point is the seam. This is a known limitation; per-step cost capture is on the future seams list below.

## Apply: dry-run-by-default again

The same `apply_result` from the GEPA path handles topology values via the dict-target case:

```python
from orqest.optimization import apply_result

topology_registry = {"main": seed_topology}
diffs = apply_result(result, target=topology_registry, dry_run=True)
for d in diffs:
    if d.changed:
        print(d.unified)   # JSON pretty-printed diff for Pydantic values
# When ready, commit:
apply_result(result, target=topology_registry, dry_run=False)
# topology_registry["main"] is now the evolved TopologySpec
```

Dry-run is the default; commit is opt-in. Object-target and dict-target paths both work.

## Cost reasoning

```
total_cost ≈ (n_generations × (1 + reflexion_passes) × meta_call_cost)        # meta agent calls
            + (n_generations × minibatch_size × candidate_eval_cost)            # candidate evaluations
            + (full_valset × candidate_eval_cost)                               # seed + final winner re-eval
```

Worked example with `gpt-4o-mini` ($0.15 per 1M input tokens, $0.60 per 1M output tokens), 10 generations, 2 reflexion passes, 5-example minibatch, 9-example full set, ~3 agents per candidate, ~500 tokens per call:

- Meta-agent design + reflexion: 10 × 3 × ~$0.005 ≈ **$0.15**
- Candidate evaluation (each runs ~3 agents × 500 tokens): 10 × 5 × ~$0.0075 ≈ **$0.40**
- Seed + winner full-set eval: 2 × 9 × ~$0.0075 ≈ **$0.15**
- **Total: ~$0.70 per search.**

Notebook `08_topology_search_basic.ipynb` runs at this scale (~$1–2 with `gpt-4.1`).

## Runtime topology design

`MetaAgentSearch` discovers topologies *offline* against a fixed gold set. `RuntimeTopologyDesigner` + `TopologyOrchestrator` complete the picture: the LLM designs a topology *per request*, hydrates it on the fly, runs it. Same `TopologySpec` IR, same `topology_from_spec()` hydrator — the only difference is *when* synthesis happens.

The framework already does runtime LLM-driven planning via `MetaOrchestrator`, but that planner emits a flat `TaskDecomposition` (a sequential list of `SubTask`s) — it can't produce branching, parallelism, refinement loops, or routing. `TopologyOrchestrator` is the topology-shaped sibling.

### When to use which

| Setting | Use search-time `MetaAgentSearch` | Use runtime `TopologyOrchestrator` |
|---|---|---|
| Workload shape | Stable — the same kind of task over and over | Variable — every request is meaningfully different |
| Latency budget | Generous (offline batch) | Tight (each request waits for synthesis or cache) |
| Compute per design | High (~\$1–5 per discovery) | Low (single LLM call + cache hit) |
| Output | One winning topology to deploy | Per-request topology |
| Output shape vs. `MetaOrchestrator` | (n/a) | Richer (full topology IR vs. flat subtask list) |

The two compose: offline search produces a Pareto-front library of validated topologies; runtime designer is *seeded* with that library and primarily picks or specializes from it, falling back to fresh design only on novel requests.

### When NOT to use `RuntimeTopologyDesigner` — just hand-write a Pipeline

Worth saying out loud: the runtime designer adds a per-request LLM call. That cost is real (~1-3 s + a few cents). It's only worth paying when there's *genuine structural variability* across requests that the designer can exploit. If every request takes the same shape — same agents in the same order, same refinement loop, same routing logic — **hand-writing the `Pipeline` is the right answer**.

Three honest tests for "should I reach for this primitive":

| Test | Hand-write a Pipeline | Use `RuntimeTopologyDesigner` |
|---|---|---|
| **Shape variability:** how often does the optimal structure differ between requests? | Rarely; one structure handles 90%+ of the workload | Often — short questions want one shape, complex multi-step asks want another |
| **Cache hit ratio (target):** what fraction of requests will be similar enough to reuse a cached design? | N/A (no design) | >50% (otherwise the designer LLM call dominates latency) |
| **Cost per request budget:** how many cents can you spend on orchestration overhead? | ~free | ~$0.001–0.01 in extra LLM cost per cold request |

A simple rule: **`MetaOrchestrator`'s flat decomposition + a hand-written `Pipeline` covers most production workloads**. Only escalate to `RuntimeTopologyDesigner` when you have measured evidence (or strong prior) that different request shapes need different orchestration shapes. The notebook 10 demo is *deliberately* a domain (mixed factual-QA + summarisation + verification requests) where this variability is real; not every consumer is in that situation.

Don't reach for `RuntimeTopologyDesigner` because it's the most sophisticated tool in the box. Reach for it because your workload has *measured* structural variability and you've ruled out simpler answers.

### Where it lives — and an honest framing note

`RuntimeTopologyDesigner` lives in **`orqest.autonomy.runtime`**, alongside `MetaOrchestrator` (`orqest.autonomy.meta`) and `TopologyOrchestrator` (`orqest.autonomy.topology_orchestrator`). All three are **runtime planners** — they decide what to do for each incoming request.

The runtime designer **is not an optimizer in the classical sense.** There's no loss function, no per-request scoring, no Pareto archive — the cache's "online learning" is exception-driven invalidation (a topology that crashes during execution decays in reliability), not optimization over a quality signal. It shares the `TopologySpec` IR with `MetaAgentSearch` (which *is* an optimizer) because the IR is provenance-agnostic — but the relationship is shared infrastructure, not shared algorithm. Closing the loop into real online optimization requires the deferred **W3.E** (output-quality reliability signal) item below.

### The four design calls

1. **Designer-as-agent.** The designer is a user-provided `BaseAgent[GlobalState, TopologyDesign]`, not a class that constructs its own `pydantic_ai.Agent`. Mirrors `MetaOrchestrator(planner: BaseAgent, ...)`. Lets you plug in your preferred model / hooks / reasoning effort. Pydantic-AI handles the `TopologySpec` JSON schema automatically via the structured-output mechanism — saves ~2-3k tokens per design call vs. the search-time path (which embeds the schema in the prompt).

2. **Cache pluggable behind a Protocol.** `TopologyCache` is a Protocol with three concrete implementations: `NoCache` (default, zero state), `InMemoryLRU` (exact-match goal string, demos and tests), and `MemoryStoreCache` (production — backed by `LocalMemoryStore` with semantic recall + reliability decay).

3. **`TopologyOrchestrator` is parallel to `MetaOrchestrator`, not a mode flag.** `MetaOrchestrator`'s flat-subtask shape is well-tested, has live consumers, and maps cleanly to `ExecutionPlan` UI. New sibling class for the topology-shaped runtime; both ship.

4. **`verify_on_hit=True` by default; runtime design failure raises (no debug-retry).** Cache hits validate the cached spec against current registries before returning (catches stale agent / callable references). Design failures raise immediately — runtime is latency-sensitive; the search-time debug-retry pattern is wrong here. Optional `fallback_spec` lets you provide a safe default.

### `MemoryStoreCache` — online learning over topologies

The interesting piece. Discovered topologies become `MemoryEntry(memory_type="semantic", source_agent="topology_cache")` rows — one per goal — with the `TopologySpec` JSON in `structured_content`. Lookup uses `LocalMemoryStore.recall()` semantic similarity on the goal embedding; hit returns the prior spec.

```python
from orqest.memory import LocalMemoryStore
from orqest.autonomy.runtime import MemoryStoreCache

store = LocalMemoryStore("topology_cache.db", embedder=my_embedder)
cache = MemoryStoreCache(store, threshold=0.85, namespace="topology_cache")
```

**Embedder requirement (loud).** Without an embedder configured on the backing store, recall falls back to FTS5 / LIKE — brittle for free-text goal similarity. The class still constructs and works (lookups just return `None` more often) so test wiring without an embedder doesn't crash, but production deployments should configure one.

**Online learning is automatic.** On `TopologyOrchestrator.execute(goal)`:

* On success → `cache.store(goal, spec, success=True)` adds (or refreshes) the entry.
* On execution exception → `cache.store(goal, spec, success=False)` calls `MemoryStore.update_reliability(entry_id, success=False)`, which decays the reliability score via the existing `PerKindConfig.decay_on_failure` machinery. With `MemoryStoreCache(min_reliability=0.3)`, chronically-failing entries drop below the floor and stop surfacing.

**Why `semantic` memory_type and not `procedural`?** Procedural memory's `_validate_procedural_shape` validator requires `structured_content` to be `Skill`-shaped — `TopologySpec` doesn't fit that shape and we'd be abusing the schema. Semantic with a namespaced `source_agent` keeps things clean; reliability decay still applies. If a future need surfaces (versioning topology library entries), revisit by relaxing the validator.

### Seed-library bootstrap

Tying offline + runtime together:

```python
# Once, offline (notebook 08):
search_result = await MetaAgentSearch(...).run(gold_set)
seed_library = [entry.spec for entry in search_result.raw.pareto()]
# Persist seed_library to disk: json.dump([s.model_dump() for s in seed_library], ...)

# At deploy time:
designer = RuntimeTopologyDesigner(
    designer_agent=designer_agent,
    callable_registry=callable_registry,
    agent_registry=agent_registry,
    seed_library=seed_library,
    cache=MemoryStoreCache(memory_store, ...),
)
orchestrator = TopologyOrchestrator(designer, ...)

# Per request:
result = await orchestrator.execute(goal=incoming_goal)
```

The seed library is rendered into the design prompt as: *"Library of validated topologies — prefer composing or specializing one of these; only design from scratch when none fit."* That gives the designer a strong inductive bias toward proven structures while still allowing novel composition for genuinely-different requests. YAGNI today is "list of `TopologySpec` inline in the prompt"; when libraries grow past ~20 entries, a `RetrievalPolicy` Protocol layer (W3.D, deferred) becomes worthwhile.

### Honest tradeoffs

* **Per-request latency tax.** A cold design call adds the meta-agent LLM round-trip (typically 1-3 s) before execution. `MemoryStoreCache` is the production answer — embedded recall is fast (single cosine pass over a few hundred entries) and a hit short-circuits the design call entirely. The break-even is roughly: "if cache hit ratio > 50%, runtime topology design beats fresh-design-every-time on average latency."
* **Cost compounds.** Designer cost stacks on top of execution cost. For workloads where every request is similar (e.g., the same kind of QA over a fresh paragraph), `MetaOrchestrator`'s flat-subtask path is cheaper and good enough. Use `TopologyOrchestrator` when the structural variation across requests is real enough to pay for the design cost.
* **Decay only fires on exceptions, not bad outputs.** Today reliability decay is exception-driven. A topology that runs cleanly but produces a wrong answer won't decay automatically. Wiring an `output_judge` callable into `TopologyOrchestrator.execute` is the W3.E item that fixes this.
* **Asymmetry with `MetaAgentSearch`.** Search-time uses `pydantic_ai.Agent` directly; runtime uses `BaseAgent`. Acceptable because search-time is internal-only (no consumer-side composition) while runtime is consumer-facing.

Notebook `10_runtime_topology.ipynb` walks through cold design, cache hit reuse, the `TopologyOrchestrator` loop, seed-library bootstrap, and the online-learning failure decay end-to-end.

## Caveat: LLM-generated tests as evaluator feedback

A pattern that looks attractive but reliably misfires on imperfect models: have an LLM **generate additional test cases** for the candidate code at evaluation time, then score the candidate against both the gold tests AND the LLM-generated ones. The intuition is appealing — "the designer agent knows the spec, it should be able to write good edge-case tests" — and we tried exactly this in V2 of the coding benchmark (`benchmarks/coding/`). It made the combo WORSE than the baseline.

Failure mode: the test-designer LLM hallucinates *wrong expected values* for its proposed tests. Whatever the test designer's confidence, on weaker models (gpt-4o-mini-tier) ~10–20% of generated tests have an incorrect expected output. The downstream fixer agent — which can't tell hallucinated tests from real ones — then "fixes" code that was actually correct, rewriting it to pass the wrong tests. The aggregate accuracy regresses.

This is the **Unsupervised Evaluation Paradox** (named in `.claude/designs/04-goal-driven-optimization.md`) applied to a runtime evaluator: if the LLM is competent enough to generate reliable test labels, it's competent enough to solve the task one-shot — so the test generation adds noise without adding signal. If the LLM isn't competent enough to solve the task one-shot, then any test labels it generates are equally unreliable, and using them as ground truth poisons the loop.

Where LLM-generated tests *can* work:

* **As advisory feedback that doesn't gate exit.** Surface them in the fixer's prompt as "consider these potential cases" without scoring against them — the fixer can take them as hints rather than ground truth.
* **With cross-validation across diverse models.** Generate tests with model A, score with B, only trust agreed-upon tests. Adds significant cost; only worth it for high-stakes domains.
* **With explicit per-test confidence + filtering.** Designer outputs a confidence; only tests above a high threshold (>0.9) are scored against. Discards most generated tests.
* **When the candidate must produce a verifiable artifact** (executable code, proof, schema) — the verifier IS the ground truth, the LLM-generated "tests" are just inputs to it.

What worked in `benchmarks/coding/`:

* Drop the test designer entirely.
* Score the candidate only against the **visible examples shipped with the problem** (the first `k` real test cases — labels the user wrote, not the LLM).
* Use keep-best ([`RefinementLoop(keep_best=True)`](orchestration.md#keep-best-safety-default-on)) so a regression on visible tests never makes the final answer worse.

This is the conservative-but-correct shape. The combo wins because the agent gets to *iterate* using real-but-limited test feedback — not because new feedback got synthesized. If you find yourself reaching for "let an LLM generate the test labels," step back: you're probably dressing up unsupervised evaluation in a different costume.

## What's next (deferred)

- **W3.C — `orqest/sandbox/`.** A `Sandbox` Protocol (subprocess + e2b implementations) so the meta agent can emit raw Python `forward()` for tasks where compositions of registered primitives are too constrained. This is the original ADAS surface; we ship it later only if users prove the expressivity ceiling matters.
- **MCTS search.** AFlow-style MCTS over the same `TopologySpec` IR — a one-strategy swap inside `MetaAgentSearch` once a `SearchStrategy` Protocol abstraction lands.
- **Per-step cost capture.** Walk the topology, hook `BaseAgent.call_model`, sum `Usage` across all agents. Plumbs `cost_usd` through to the optimizer's Pareto front.
- **`Pipeline.to_spec()` round-trip.** The inverse of `topology_from_spec` — lets users round-trip a hand-built `Pipeline` into the IR for evolution.
- **Cross-task topology transfer.** Discovered topologies as warm-starts for new tasks; requires a topology-similarity metric.

## Runnable demos

- [`notebooks/08_topology_search_basic.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/08_topology_search_basic.ipynb) — ADAS-style offline topology search
- [`notebooks/09_topology_with_gepa.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/09_topology_with_gepa.ipynb) — two-phase: discover topology, then evolve prompts
- [`notebooks/10_runtime_topology.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/10_runtime_topology.ipynb) — per-request synthesis with semantic cache
