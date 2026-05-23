"""Run the coding benchmark — baseline (single-shot) vs combo (test-driven
refinement loop) on a small set of tricky coding problems, averaged over N
trials.

The combo demonstrates the architecture-driven win the framework was built
for: same model both sides, only the orchestration differs. Per-problem +
aggregate numbers report on stdout; a `trial_averages.json` file lands next
to the entry point with full per-trial detail.

Usage:
    python benchmarks/coding/run.py --trials 3 --problems 10 \\
        --model openrouter:openai/gpt-4o-mini

Cost estimate: ~$0.05 for a 3-trial / 10-problem run with `gpt-4o-mini`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Allow loading repo-root .env when invoked directly (`python benchmarks/coding/run.py`)
# AND allow sibling-module imports (codebench, _runners) regardless of cwd.
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
load_dotenv(_REPO_ROOT / ".env")
sys.path.insert(0, str(_HERE))

from _runners import (  # noqa: E402  — sys.path edit above is intentional
    BaselineCoder,
    CoderAgent,
    FixerAgent,
    run_baseline_one,
    run_combo_one,
)
from codebench import PROBLEMS, aggregate  # noqa: E402

from orqest.autonomy import DynamicToolFactory  # noqa: E402
from orqest.sandbox import SubprocessSandbox  # noqa: E402


async def one_trial(model: str, api_key: str, n_problems: int, k_visible: int, max_iter: int):
    problems = PROBLEMS[:n_problems]
    sandbox = SubprocessSandbox()
    tool_factory = DynamicToolFactory(sandbox=sandbox)

    baseline_agent = BaselineCoder(model=model, api_key=api_key)
    coder = CoderAgent(model=model, api_key=api_key)
    fixer = FixerAgent(model=model, api_key=api_key)

    baseline_results = []
    for p in problems:
        try:
            r = await run_baseline_one(p, baseline_agent, k_visible)
        except Exception as exc:  # noqa: BLE001
            r = {"problem": p.name, "passed": 0, "total": len(p.tests),
                 "errors": [{"crash": str(exc)}], "compile_error": str(exc),
                 "elapsed_s": 0.0, "code": ""}
        baseline_results.append(r)

    combo_results = []
    for p in problems:
        try:
            r = await run_combo_one(p, coder, fixer, tool_factory,
                                    max_iterations=max_iter, k_visible=k_visible)
        except Exception as exc:  # noqa: BLE001
            r = {"problem": p.name, "passed": 0, "total": len(p.tests),
                 "errors": [{"crash": str(exc)}], "compile_error": str(exc),
                 "elapsed_s": 0.0, "code": "", "n_iterations": 0,
                 "best_pass_visible": 0, "visible_total": 0, "iter_log": []}
        combo_results.append(r)

    return baseline_results, combo_results


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("COMBO_MODEL", "openrouter:openai/gpt-4o-mini"))
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--problems", type=int, default=10)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--k-visible", type=int, default=4)
    parser.add_argument("--max-iter", type=int, default=3)
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Missing API key in env var {args.api_key_env}")

    print(f"Model: {args.model}  |  Problems: {args.problems}  |  Trials: {args.trials}  |  "
          f"k_visible: {args.k_visible}  |  max_iter: {args.max_iter}\n")

    all_trials = []
    for trial in range(1, args.trials + 1):
        print(f"--- Trial {trial}/{args.trials} ---")
        t0 = time.monotonic()
        baseline, combo = await one_trial(args.model, api_key, args.problems, args.k_visible, args.max_iter)
        b_agg = aggregate(baseline)
        c_agg = aggregate(combo)
        elapsed = time.monotonic() - t0
        print(f"  baseline pass@1: {b_agg['pass_at_1']:.0%}  test_rate: {b_agg['test_pass_rate']:.0%}")
        print(f"  combo    pass@1: {c_agg['pass_at_1']:.0%}  test_rate: {c_agg['test_pass_rate']:.0%}")
        print(f"  trial elapsed:   {elapsed:.0f}s\n")
        all_trials.append({"baseline": baseline, "combo": combo, "elapsed_s": elapsed})

    # Aggregate across trials
    print("=" * 70)
    print(f"AVERAGED OVER {args.trials} TRIALS")
    print("=" * 70)

    baseline_pass1 = [aggregate(t["baseline"])["pass_at_1"] for t in all_trials]
    baseline_rate = [aggregate(t["baseline"])["test_pass_rate"] for t in all_trials]
    combo_pass1 = [aggregate(t["combo"])["pass_at_1"] for t in all_trials]
    combo_rate = [aggregate(t["combo"])["test_pass_rate"] for t in all_trials]

    def fmt(vals):
        mean = statistics.mean(vals)
        if len(vals) > 1:
            stdev = statistics.stdev(vals)
            return f"{mean:.0%} (±{stdev:.0%})"
        return f"{mean:.0%}"

    print(f"  pass@1          baseline: {fmt(baseline_pass1)}  combo: {fmt(combo_pass1)}  "
          f"Δ: {statistics.mean(combo_pass1)-statistics.mean(baseline_pass1):+.0%}")
    print(f"  test_pass_rate  baseline: {fmt(baseline_rate)}  combo: {fmt(combo_rate)}  "
          f"Δ: {statistics.mean(combo_rate)-statistics.mean(baseline_rate):+.0%}")

    # Per-problem averages
    print("\n--- Per-problem (averaged across trials) ---")
    print(f"{'Problem':40s} {'Baseline test%':>18s} {'Combo test%':>18s} {'Δ':>8s}")
    for i in range(args.problems):
        pname = all_trials[0]["baseline"][i]["problem"]
        b_pcts = [t["baseline"][i]["passed"] / t["baseline"][i]["total"] for t in all_trials]
        c_pcts = [t["combo"][i]["passed"] / t["combo"][i]["total"] for t in all_trials]
        b_mean = statistics.mean(b_pcts)
        c_mean = statistics.mean(c_pcts)
        delta = c_mean - b_mean
        marker = "  ✓" if delta > 0.05 else ("  ✗" if delta < -0.05 else "   ")
        print(f"  {pname:40s} {b_mean:>16.0%}     {c_mean:>16.0%}  {delta:+6.0%}{marker}")

    out = {
        "config": vars(args),
        "summary": {
            "baseline_pass1_mean": statistics.mean(baseline_pass1),
            "baseline_pass1_stdev": statistics.stdev(baseline_pass1) if len(baseline_pass1) > 1 else 0,
            "combo_pass1_mean": statistics.mean(combo_pass1),
            "combo_pass1_stdev": statistics.stdev(combo_pass1) if len(combo_pass1) > 1 else 0,
            "baseline_rate_mean": statistics.mean(baseline_rate),
            "combo_rate_mean": statistics.mean(combo_rate),
        },
        "trials": [{
            "baseline_results": t["baseline"],
            "combo_results": t["combo"],
            "elapsed_s": t["elapsed_s"],
        } for t in all_trials],
    }
    out_path = _HERE / "trial_averages.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
