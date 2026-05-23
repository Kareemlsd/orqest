# Benchmarks

Reproducible head-to-head benchmarks measuring what each Orqest battery
delivers over a baseline. Every subdirectory is **self-contained**:

- `run.py` — entry point. Accepts `--model`, `--trials`, `--problems`, etc.
- `README.md` — what the benchmark tests, how to reproduce, expected
  numbers (with stdev), cost estimate.
- Helper modules for problem fixtures, runners, scorers.

## Why benchmarks live in the repo

The framework ships rich primitives (`MetaOrchestrator`, `RuntimeTopologyDesigner`,
`DynamicToolFactory`, the optimization batteries) — but until you compose them
into a real working system on a real task with a real number, none of those
primitives is yet *proven*. Benchmarks are the evidence layer. Each entry
here is a measured win you can verify with one shell command + an API key.

## Convention for new benchmarks

If you're adding a benchmark for another battery (memory, metacognition,
healing, optimization, runtime topology, etc.):

1. New subdirectory `benchmarks/<name>/`.
2. `run.py` is the entry point. Argparse with sensible defaults (model,
   trials, problems). Loads `.env` at repo root.
3. `README.md` documents: what's tested, expected numbers (+ stdev), cost,
   how to reproduce, where the numbers come from.
4. A baseline (single-primitive, no-composition) MUST exist alongside the
   combo so the delta is honest.
5. Multi-trial averaging by default — the LLM variance is real and a
   single run can mislead by ±10pp.
6. Outputs land in the same directory as `run.py` (e.g.
   `benchmarks/<name>/trial_averages.json`) — easy to compare across runs.

## Current benchmarks

- [`coding/`](coding/) — test-driven refinement loop vs single-shot
  baseline on a 10-problem coding benchmark. The headline win: **+17pp
  pass@1 / +14pp test_pass_rate** with `gpt-4o-mini` (3-trial average).
