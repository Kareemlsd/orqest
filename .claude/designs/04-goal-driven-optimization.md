# Decision: Goal-Driven Optimization for Orqest

Date: 2026-05-16
Status: Proposed (post-adversarial-review v2)

## Problem Statement

Orqest ships two reflective-evolution batteries: GEPA (prompt evolution, `optimization/runner.py`) and MetaAgentSearch (ADAS-style topology evolution, `optimization/meta_agent.py`). Both currently require `list[GoldExample[InputT, OutputT]]` with `.expected` populated, threaded through a user-supplied `score_fn(output, example) -> float`.

The user friction we want to remove: developers typically arrive with a *domain* ("expert in protein folding, solves problems of type X"), not a *labeled dataset*. We want them to bootstrap an optimized multi-agent architecture from a goal description alone.

Constraints:
- Must compose with the existing `OptimizationRunner` / `MetaAgentSearch` / `Evaluator` / `MetricBundle` machinery (don't fork it).
- Honest about cost: ADAS is already expensive — `Inefficiencies of Meta Agents` (El et al., 2025) shows break-even at ~15k evaluations on MMLU/DROP.
- Honest about Goodhart: every proxy-for-truth signal degrades into reward-hacking under enough optimization pressure.

## Inputs to this analysis

- Codebase audit of `optimization/` and `autonomy/` (see prior conversation; bridge today is one wire — `RuntimeTopologyDesigner.seed_library`).
- Divergent brainstorm (Gemini, 7 strategies).
- Literature grounding (ADAS, GEPA, MaAS, AlphaEvolve, Self-Rewarding LM, Meta-Rewarding, uPRM, ProcessBench, DSPy BootstrapFewShot, LLM-judge bias studies).
- Adversarial review (Gemini, against the v1 "Tiered Verifier-First" proposal).

The adversarial pass surfaced a load-bearing argument that reshaped the recommendation — what I'm calling the **Unsupervised Evaluation Paradox**, below.

---

## The Unsupervised Evaluation Paradox

If the generator + judge + oracle are *competent enough at the domain* to produce valid synthetic problems and reliably score outputs without labels, then the domain is already solved by the base model — you don't need a multi-agent topology, one prompt to the oracle suffices.

If the domain is *hard enough to need a multi-agent topology*, then by definition the generator + judge + oracle are not competent at it, so the optimization loop will optimize the system to satisfy incompetent judges (Goodhart on a noisy proxy).

This is the central tension. It does not say unsupervised optimization is impossible — it says the viable design space is narrower than "any goal description." It splits into three regions:

1. **Verifier-decidable domains** (code, math, SQL, JSON schemas, regex, simulators, theorem provers). Truth has a cheap, deterministic checker. AlphaEvolve, FunSearch, AlphaProof, AlphaCode all live here. **Fully unsupervised is real and works.**
2. **Judge-aligned domains** (rubric-scorable writing, summarization, customer-support style, code style). Frontier judges agree well enough with humans that unsupervised iterative refinement converges. Self-Rewarding LM and Meta-Rewarding work here. **Unsupervised works with caveats.**
3. **Domain-expert-required tasks** (clinical reasoning, novel scientific synthesis, niche regulatory analysis, anything the base model is weak at). The paradox bites hard. **Unsupervised collapses.**

A useful framework must tell the user which region they're in, and behave differently in each.

---

## Options

### Option A: Pure Unsupervised Judge Council (the v1 proposal)

**Description:** Goal description → ProblemGenerator agent → MetaAgentSearch + GEPA driven by a hybrid score (RubricJudge + ConsistencyScore + SelfDistilledOracle, weighted). No labels at any point.

**Pros:**
- Maximally aligned with the user's stated friction ("no dataset").
- Closes the offline-runtime feedback loop via seed library.
- Conceptually clean — one entry point regardless of domain.

**Cons:**
- Falls into the Unsupervised Evaluation Paradox for region-3 domains (the cases where MAS optimization is most valuable).
- **Cost math is brutal**: ~22 LLM calls per evaluation × 15k evaluations × ~$0.01 = ~$3,300 per optimization run, before GEPA on top. Worse, the unit cost is now stochastic (judge noise), making convergence slower.
- ConsistencyScore actively penalizes correct-but-counter-intuitive outputs (Strawberry / Monty Hall failure: all siblings hallucinate the same wrong intuitive answer).
- SelfDistilledOracle treats "more compute" as truth, but multi-agent systems frequently *degrade* with more reflection (Huang et al. 2023, "LLMs Cannot Self-Correct Reasoning Yet").
- Three "independent" Tier-2 signals are correlated through the same base-model prior; the ensemble illusion.
- Adversarial curriculum collapses into prompt-injection on the judge, not real domain difficulty.

**Effort:** Medium. **Risk:** High. **Best when:** the domain is region-2 (judge-aligned) AND the user accepts a Goodhart-tolerant deployment workflow.

### Option B: Verifier-First Only

**Description:** Restrict the unsupervised optimization API to domains where the user can wire a deterministic verifier (sandbox execution, schema validation, regex, simulator). Reuses Orqest's existing `sandbox/` module. `score_fn` returns binary pass/fail or graded reward from the verifier. No judge LLMs in the loop.

**Pros:**
- Theoretically clean: the same reason AlphaEvolve and FunSearch work — there's an unbiased oracle.
- Goodhart-resistant: hard to game `assert result == expected_property(input)`.
- Cost-efficient: verifier runs are cheap and synchronous.
- Already partially built — `sandbox/` is shipped, `GeneratedToolSpec` already exercises this path.

**Cons:**
- Domain coverage is *narrow*. Many user goals don't admit a verifier (e.g., "research assistant for medical literature").
- Easy to game with trivial verifiers (`assert 1 == 1`). Requires verifier-quality scoring as a meta-check.
- Doesn't solve the user's primary problem (their stated goal was domain-general).
- Still needs the user to write the verifier — moves the labeling burden from "expected outputs" to "constraint specs," which is sometimes harder.

**Effort:** Low (mostly plumbing). **Risk:** Low. **Best when:** the goal is region-1 (verifier-decidable).

### Option C: Bootstrap-to-Supervised (recommended)

**Description:** Reframe the surface from "unsupervised optimization" to "labeled-set generator that lets you run normal supervised optimization." The framework's job is to turn 30 minutes of user attention into a 50-100 example labeled set; *that set* feeds the existing supervised pipeline unchanged.

Concrete flow:
1. User provides `GoalSpec`: domain, problem_kinds, success_principles, failure_modes_to_avoid, **5-10 seed example_problems** (no expected outputs needed at this stage), optional verifier hook.
2. `ProblemGenerator` agent expands seed examples to a candidate set of ~100 synthetic problems, diversified across `problem_kinds`. Cheap (~100 LLM calls).
3. `ReferenceProducer` runs a strong model (or a deliberate ensemble) once per problem to produce candidate expected outputs. Cheap (~100-300 LLM calls).
4. **Human-in-the-loop labeling UI** (notebook widget or simple CLI): user reviews ~50-100 (problem, candidate-output) pairs in 30-60 minutes, accepting / editing / rejecting. Rejected cases optionally feed back into the generator for hard-case mining.
5. Resulting `list[GoldExample]` feeds the standard `OptimizationRunner` / `MetaAgentSearch`. Existing code, existing cost profile.
6. **Optional second loop**: after optimization, the optimized system's wins on the labeled set become a richer seed for the next round of `ProblemGenerator` (curriculum drift).

**Pros:**
- Sidesteps the Unsupervised Evaluation Paradox entirely — the optimization runs on real labels.
- Cost is bounded and predictable: ~500 LLM calls for bootstrap + standard optimization budget.
- Hits the user's actual friction: "I don't have a dataset" → "you now have a dataset in 30 minutes."
- Composes with what's shipped — no changes to `Evaluator`, `MetricBundle`, `OptimizationRunner`, `MetaAgentSearch`. Adds a new `orqest/optimization/bootstrap/` namespace.
- Honest framing: the framework is upfront that labels matter, but radically lowers the cost of producing them.
- Human-in-the-loop is also a *learning experience* for the user — they discover what they actually want, which is usually different from their initial pitch.

**Cons:**
- Not "unsupervised" in the literal sense. The marketing story is "low-supervision," not "no-supervision."
- Requires building a labeling UI (or at least a notebook widget) — work outside Orqest's current frontiers.
- The bootstrap can drift if the `ProblemGenerator` is biased; mitigated by user review at step 4.

**Effort:** Medium. **Risk:** Low-Medium. **Best when:** region-2 or region-3 domains where the user has 30-60 minutes but not 30 hours.

### Option D: Joint Co-Optimization with Verifier or Labeled Set (no separate ADAS-then-GEPA phase)

**Description:** Independent of which evaluation signal is chosen (B, C, or future improvements), restructure the optimization composition itself. ADAS-then-GEPA sequencing kills complex topologies before their prompts have been tuned (Gemini's critique #6, supported by the MaAS paper's joint-optimization approach). Replace with interleaved or joint search.

Concrete flow:
- Outer loop: ADAS proposes N candidate topologies.
- Inner loop: a *budget-limited* GEPA pass tunes the prompts of each candidate topology to a reasonable baseline before evaluation.
- Pareto front survives both axes (topology shape + prompt quality).

This is independent of the "where does the signal come from" question — it can stack on top of Option B or Option C.

**Pros:**
- Fixes a real algorithmic flaw (sequenced search culls under-tuned complex shapes).
- Empirically supported by MaAS's results: joint optimization beats sequential.
- Modest reframing of existing pieces.

**Cons:**
- Multiplies cost (every candidate topology pays a GEPA tax before being scored).
- Cache invalidation interacts with `RuntimeTopologyDesigner.seed_library` reuse.
- Adds complexity to an already-complex search loop.

**Effort:** Medium. **Risk:** Medium. **Best when:** the user has enough compute budget for the inner GEPA tax.

---

## Comparison Matrix

| Criterion | A: Pure Unsupervised | B: Verifier-First | C: Bootstrap-to-Supervised | D: Joint Co-Opt |
|---|---|---|---|---|
| Solves user's stated friction | ✅ | ⚠️ narrow | ✅ (90%) | n/a (orthogonal) |
| Goodhart resistance | ❌ | ✅✅ | ✅ | n/a |
| Cost (per optimization run) | ~$3,300+ | ~$50-300 | ~$200-600 | +30-100% on baseline |
| Coverage of user goals | All (badly) | Region 1 only | Region 2 + 3 | All |
| Reversibility | Hard to walk back | Easy | Easy | Easy |
| Composes with shipped code | New eval path | New eval path | Zero changes to runner | Refactor of runner |
| Honest with the user | ❌ (oversells) | ✅ | ✅ | n/a |
| Engineering effort | Medium | Low | Medium | Medium |

---

## Recommendation

**Ship Option C as the primary path, Option B as the parallel sibling for verifier-decidable domains, and Option D as a stacked improvement on both.** Do not ship Option A — the cost math and reward-hacking risk make it net-negative against the alternatives even when it works.

Concretely, the user-facing API exposes one entry point that *dispatches* based on what the user provides:

```python
# Verifier-decidable: route to Option B (fully unsupervised)
runner = OptimizationRunner.from_goal(
    goal=GoalSpec(domain="...", problem_kinds=[...]),
    verifier=my_sandbox_verifier,  # → Option B
)

# Default: route to Option C (bootstrap-to-supervised)
runner = OptimizationRunner.from_goal(
    goal=GoalSpec(domain="...", problem_kinds=[...], seed_examples=[...]),
    # no verifier → triggers bootstrap UI
)

# Both paths: apply Option D's joint co-optimization under the hood
```

The frame to use with users is: *"Orqest doesn't pretend to optimize without supervision — it makes supervision cheap. Either you give us a verifier and we go fully autonomous (Option B), or you spend 30 minutes labeling 50 examples we generate and we run normal supervised optimization (Option C)."*

This is the honest version of the user's pitch. It's also more defensible to a senior MAS researcher (Khattab's likely critique — "you're compiling without a test suite" — has a real answer: "the test suite is generated and reviewed in 30 minutes").

---

## Reversibility Assessment

- **Option C** is highly reversible — it's additive (`orqest/optimization/bootstrap/`), changes no existing types, and the bootstrap output is just `list[GoldExample]` feeding existing machinery. If the bootstrap quality is poor, replace it without touching the optimizer.
- **Option B** is highly reversible — it's a new `Evaluator` subclass and a new `score_fn` signature. Walk-back cost is near zero.
- **Option D** is moderately reversible — it restructures the search loop's main flow. A refactor away if it underperforms.
- **Option A** is hard to reverse once shipped — users will build expectations around "no dataset needed," and unwinding that messaging is expensive. Avoiding it is the cheap option.

Cost of being wrong on C: ~2 weeks of work, mostly UI/widget. Cost of being wrong on A (which I almost recommended): user trust on optimization claims, plus a stack of unfixable bug reports about reward-hacked architectures.

---

## What the literature actually says (the bibliography that shaped this)

- **ADAS / Meta Agent Search** ([Hu et al. 2024](https://arxiv.org/abs/2408.08435), ICLR 2025) — the original. Already in Orqest as `MetaAgentSearch`.
- **GEPA** ([Agrawal et al. 2025](https://arxiv.org/abs/2507.19457), ICLR 2026 Oral) — already in Orqest. Outperforms RL with 35× fewer rollouts. Trajectory reflection doesn't strictly need gold answers, but the published version uses them.
- **MaAS — Agentic Supernet** ([Zhang et al. 2025](https://arxiv.org/abs/2502.04180), ICML 2025 Oral) — query-adaptive sampling from a probabilistic distribution of topologies. Closer to Orqest's `RuntimeTopologyDesigner` than ADAS is. Notable: jointly optimizes architecture and operators, *not* sequentially. Direct support for Option D.
- **Inefficiencies of Meta Agents** ([El, Yuksekgonul, Zou 2025](https://arxiv.org/abs/2510.06711), EMNLP Findings) — break-even at ~15k examples. The cost-math reality check that killed Option A.
- **AlphaEvolve** ([Google DeepMind 2025](https://arxiv.org/abs/2506.13131)) — verifier-driven code evolution. Proof of concept that Option B *can* be transformative in verifier-decidable domains.
- **Self-Rewarding Language Models** ([Yuan et al. 2024](https://arxiv.org/abs/2401.10020)) — iterative LLM-as-judge works for region-2 domains. Direct evidence Option A's spirit can succeed, but limited to alignment-style tasks.
- **Meta-Rewarding** ([Wu et al. 2024](https://arxiv.org/abs/2407.19594)) — adds a meta-judge to refine the judge itself. The technique that would make Option A *almost* viable, but doesn't address the cost or coverage problems.
- **Unsupervised Process Reward Models (uPRM)** ([2025](https://arxiv.org/abs/2605.10158v1)) — step-level rewards without labels, +15% over LLM-as-judge on ProcessBench. A possible *future* signal source for Option C's bootstrap step.
- **DSPy BootstrapFewShot** — the prior art for the bootstrap pattern. Uses a metric function to filter teacher-generated demos. Validates Option C's general shape; the metric is still required, but Option C generates the metric via user review rather than user authoring.
- **LLM-judge biases** ([Justice or Prejudice 2024](https://arxiv.org/abs/2410.02736), [Self-Preference 2024](https://arxiv.org/abs/2410.21819), [Position Bias 2024](https://arxiv.org/abs/2406.07791)) — frontier models fail 50%+ of bias tests as judges; perplexity drives self-preference. The empirical case against Option A's RubricJudge ensemble.
- **LLMs Cannot Self-Correct Reasoning Yet** ([Huang et al. 2023](https://arxiv.org/abs/2310.01798)) — the SelfDistilledOracle assumption ("more compute → better output") is empirically false in many MAS contexts.

---

## Next Steps

1. **Spike the bootstrap UI** (~1 week). Notebook widget that takes `GoalSpec`, runs `ProblemGenerator` + `ReferenceProducer`, displays pairs for review. Validate the 30-minute claim on one real domain (e.g., a known-shape task like math word problems, where we *do* have labels so we can A/B the bootstrap-generated set against ground truth).
2. **Build the `from_goal()` dispatcher** (~1 week). Routes to Option B if `verifier` is passed, Option C otherwise. Single entry point so the user API stays clean.
3. **Implement Option B verifier path** (~3 days). New `VerifierEvaluator` subclass of `Evaluator`. Wire to existing `sandbox/`.
4. **Implement Option C bootstrap path** (~1 week). `orqest/optimization/bootstrap/` namespace: `ProblemGenerator`, `ReferenceProducer`, `LabelingSession`, output is a standard `list[GoldExample]`.
5. **Spike Option D joint co-optimization on toy domain** (~3 days). Compare ADAS-then-GEPA vs interleaved on math word problems. If the win is real (+5% or more, supported by MaAS's results), schedule the bigger refactor. If not, defer indefinitely.
6. **Fix the deferred items the audit surfaced** (~3 days, can interleave with above):
   - Cost capture in `TopologyEvaluator` (`optimization/topology.py:172` — `cost_usd=0.0` default).
   - Semantic decay on `MemoryStoreCache` (W3.E, ROADMAP).
   - Structural `UnsupervisedScoreFn` typing where it actually applies (Option B's path).
7. **Document the framing publicly**. CHANGELOG entry + concept doc (`docs/concepts/goal_driven_optimization.md`) that names the Unsupervised Evaluation Paradox and explains the framework's stance. Users will respect the honesty more than the magic.

## What I changed from v1 (post-adversarial)

The v1 proposal led with the Tiered Judge Council (Option A). Gemini's adversarial pass killed it on cost math + the Unsupervised Evaluation Paradox + correlated-signals illusion. The current version:
- Demotes A from "the recommendation" to "the option we considered and rejected, here's why."
- Promotes the verifier and bootstrap paths from "implementation details" to first-class options.
- Adds Option D as a separable improvement that stacks on B or C.
- Frames the user pitch around honesty about supervision cost, not magic about removing it.
