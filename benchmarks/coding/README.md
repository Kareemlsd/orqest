# Coding benchmark

Test-driven refinement loop vs single-shot baseline on a 10-problem coding
benchmark. Same model both sides; only the orchestration differs. The combo
demonstrates the architecture-driven win Orqest was built for.

## Headline result

Averaged over 3 trials with `openrouter:openai/gpt-4o-mini`:

| Metric | Baseline (single-shot) | Combo (this benchmark) | Δ |
|---|---|---|---|
| `pass@1` | 73% (±6%) | **90%** (±10%) | **+17pp** |
| `test_pass_rate` | 80% (±6%) | **94%** (±9%) | **+14pp** |

Per-problem highlights:
- `parse_csv_row`: 23% → 73% (+50pp)
- `word_ladder_length`: 38% → 100% (+62pp)
- `parse_roman`: 55% → 79% (+24pp)
- six other problems are 100%/100% — combo correctly doesn't regress.

Zero regressions across the 30 trial-problem pairs.

## What's being measured

10 small (but tricky) coding problems with hidden test cases — Roman parsing,
RFC-4180 CSV, text justification, regex matching, monotonic-stack
histograms, word ladder BFS, edit distance, subarray-sum DP, palindrome
partitioning. Each has 5-14 hidden tests targeting edge cases that
frontier LLMs commonly miss in one-shot generation.

The baseline is a single `BaseAgent` that sees the problem prompt + the first
4 visible examples and emits a function definition in one shot.

The combo is a test-driven refinement loop:
1. **Coder** (a `BaseAgent` spawned via `AgentFactory.spawn(AgentSpec)`) writes a draft.
2. **Evaluator** runs the draft against the 4 visible tests in a `SubprocessSandbox`,
   spawning a fresh `GeneratedToolSpec` per (iteration × test) via `DynamicToolFactory`.
3. **Fixer** (another spawned `BaseAgent`) revises based on test failures.
4. Keep-best across iterations on the visible-test score — never returns a
   regression on what it can see.
5. Final code scored against ALL tests (visible + hidden) — same metric as baseline.

Three Orqest pillars compose: declarative agent spawning, dynamic tool generation
via the sandbox, iterative refinement with the new `keep_best=True` safety property.

## Reproducing

Requires:
- An `OPENROUTER_API_KEY` in `.env` at the repo root (or another provider key
  + `--api-key-env`).
- The optional `dotenv` dependency (already pulled in by `uv sync`).

```bash
# Smoke test — 1 trial, 2 problems, ~$0.005, ~30s
python benchmarks/coding/run.py --trials 1 --problems 2

# Full headline reproduction — 3 trials, 10 problems, ~$0.05, ~5-10 min
python benchmarks/coding/run.py --trials 3 --problems 10
```

Alternate models:
```bash
# Switch models; pick the env var holding the key:
python benchmarks/coding/run.py \
  --model "anthropic:claude-3-5-haiku-20241022" \
  --api-key-env ANTHROPIC_API_KEY
```

Output: per-trial per-problem detail on stdout + a `trial_averages.json` file
next to `run.py` with full per-trial breakdown.

## Honest caveats

- **LLM variance is real.** Single trials swing ±10pp. The "+17pp pass@1" claim
  rests on the 3-trial average. Your run-to-run numbers will differ; the
  *direction* of the win holds, the exact magnitude won't.
- **Stronger models leave less headroom.** With `gpt-5.2` baseline already
  scores 100% on these problems — the combo can't beat 100%. The combo's
  value is biggest where the baseline has room to fail.
- **Combo costs 2-9× baseline latency.** ~5s per problem for baseline, 5-50s
  for combo depending on iterations. Acceptable for verifier-decidable
  domains where correctness matters more than throughput; not a free lunch.
- **Combo only iterates on visible-test failures.** Edge cases in hidden
  tests that aren't represented in the 4 visible examples slip through.
  Increasing `--k-visible` trades fairness against coverage.

## Files

- `codebench.py` — 10-problem fixture + `score_candidate()` + `aggregate()`.
- `_runners.py` — `BaselineCoder` / `CoderAgent` / `FixerAgent` and the
  per-trial runners. Private helpers; entry is `run.py`.
- `run.py` — multi-trial driver. Single shell command produces the head-to-head.
- `trial_averages.json` — written by `run.py`, full per-trial detail.

The original source for these numbers is `notebooks/12_combo_autonomous_coder.ipynb`,
which walks the architecture end-to-end with cells you can step through.
