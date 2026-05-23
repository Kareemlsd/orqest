"""Per-trial runners for the coding benchmark — private helpers used by `run.py`.

Two runners ship here:

- :func:`run_baseline_one` — single-shot agent emits code, scored against the
  problem's hidden tests. The floor the combo must beat.
- :func:`run_combo_one` — `BaseAgent` coder + `BaseAgent` fixer in a
  test-driven refinement loop. Each iteration runs the candidate via the
  `SubprocessSandbox` (Tier 1). Keep-best is applied across iterations on
  the visible-test score so the loop never returns a regression on what it
  can see.

Both runners take the same problem fixture (`codebench.PROBLEMS`) and share
the same scorer so the comparison is apples-to-apples. The only difference
is the orchestration around the LLM call.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv("/home/kareem/repos/orqest/.env")

from pydantic import BaseModel, Field

from orqest.agents import BaseAgent, GlobalState
from orqest.autonomy import DynamicToolFactory, GeneratedToolSpec
from orqest.sandbox import SubprocessSandbox

from codebench import PROBLEMS, Problem, score_candidate, aggregate, visible_examples_for


class CodeSolution(BaseModel):
    reasoning: str = Field(description="Short reasoning (one or two sentences).")
    code: str = Field(description="Complete Python function definition. No example calls, no markdown.")


class BaselineCoder(BaseAgent[GlobalState, CodeSolution]):
    def __init__(self, model: str, api_key: str):
        super().__init__(
            agent_name="baseline_coder",
            system_prompt=(
                "You are an expert Python programmer. Read the problem carefully and write "
                "a correct function definition. Pay attention to edge cases mentioned in the "
                "prompt. Return ONLY the function definition. Available stdlib: re, math, "
                "collections, itertools, string, bisect, heapq, functools, operator."
            ),
            output_type=CodeSolution,
            model=model,
            api_key=api_key,
            retries=2,
        )

    async def _run_implementation(self, state: GlobalState, **kwargs) -> CodeSolution:
        result = await self.call_model(state.get_latest_message("user"), state)
        return result.output


class CoderAgent(BaseAgent[GlobalState, CodeSolution]):
    def __init__(self, model: str, api_key: str):
        super().__init__(
            agent_name="combo_coder",
            system_prompt=(
                "You are an expert Python programmer in a test-driven loop. Write a clean "
                "first draft of the requested function. Your draft will be tested against "
                "the provided examples; if any fail, a fixer will revise it. Just write a "
                "solid attempt — do not include test cases. Return ONLY the function."
            ),
            output_type=CodeSolution,
            model=model,
            api_key=api_key,
            retries=2,
        )

    async def _run_implementation(self, state: GlobalState, **kwargs) -> CodeSolution:
        result = await self.call_model(state.get_latest_message("user"), state)
        return result.output


class FixerAgent(BaseAgent[GlobalState, CodeSolution]):
    def __init__(self, model: str, api_key: str):
        super().__init__(
            agent_name="fixer",
            system_prompt=(
                "You are a careful debugger. You see the previous code and which test cases "
                "passed vs failed (with expected and actual outputs). Diagnose the bug and "
                "emit a corrected COMPLETE function definition. PRESERVE everything that "
                "currently works — only change what is needed to fix the failing tests. "
                "Common stdlib available: re, math, collections, itertools, string, bisect, "
                "heapq, functools, operator."
            ),
            output_type=CodeSolution,
            model=model,
            api_key=api_key,
            retries=2,
        )

    async def _run_implementation(self, state: GlobalState, **kwargs) -> CodeSolution:
        result = await self.call_model(state.get_latest_message("user"), state)
        return result.output


ALLOWED_IMPORTS = {
    "re", "math", "collections", "itertools", "string",
    "bisect", "heapq", "functools", "operator",
}


async def run_one_test_in_sandbox(
    code: str,
    expression: str,
    tool_factory: DynamicToolFactory,
    test_index: int,
) -> tuple[bool, Any, str]:
    implementation = f"{code}\nreturn {expression}\n"
    spec = GeneratedToolSpec(
        name=f"candidate_{test_index}",
        description=f"Invoke candidate to compute {expression}",
        implementation=implementation,
        allowed_imports=ALLOWED_IMPORTS,
        timeout_s=4.0,
    )
    try:
        tool = await tool_factory.spawn(spec)
    except Exception as exc:  # noqa: BLE001
        return False, None, f"validation: {type(exc).__name__}: {str(exc)[:160]}"
    try:
        actual = await tool.function()
    except Exception as exc:  # noqa: BLE001
        return False, None, f"invoke: {type(exc).__name__}: {str(exc)[:160]}"
    if isinstance(actual, dict) and actual.get("stage") == "sandbox.execute":
        return False, None, f"sandbox: {str(actual.get('error', ''))[:160]}"
    return True, actual, ""


async def evaluate_in_sandbox(
    code: str,
    test_pairs: list[tuple[str, Any]],
    tool_factory: DynamicToolFactory,
) -> tuple[int, int, list[dict]]:
    n_pass = 0
    records = []
    for idx, (expression, expected) in enumerate(test_pairs):
        ran_ok, actual, err = await run_one_test_in_sandbox(code, expression, tool_factory, idx)
        if not ran_ok:
            records.append({"expr": expression, "passed": False,
                            "actual": f"<{err}>", "expected": repr(expected)[:100]})
            continue
        if actual == expected:
            n_pass += 1
            records.append({"expr": expression, "passed": True,
                            "actual": repr(actual)[:80], "expected": repr(expected)[:80]})
        else:
            records.append({"expr": expression, "passed": False,
                            "actual": repr(actual)[:140], "expected": repr(expected)[:140]})
    return n_pass, len(test_pairs), records


def format_feedback(records: list[dict]) -> str:
    lines = []
    for r in records:
        marker = "PASS" if r["passed"] else "FAIL"
        lines.append(f"  {marker}: {r['expr']}")
        if not r["passed"]:
            lines.append(f"         expected {r['expected']}")
            lines.append(f"         got      {r['actual']}")
    return "\n".join(lines)


async def run_baseline_one(problem: Problem, agent: BaselineCoder, k_visible: int) -> dict:
    """Baseline gets the SAME visible examples as the combo, for fairness.

    The only thing the combo has that the baseline doesn't is iteration with
    self-testing. Anything else and the comparison isn't apples-to-apples.
    """
    visible_tests = visible_examples_for(problem, k=k_visible)
    state = GlobalState()
    state.add_message(
        "user",
        f"PROBLEM:\n{problem.prompt}\n\nVisible examples:\n"
        + "\n".join(f"  {e} == {x!r}" for e, x in visible_tests),
    )
    t0 = time.monotonic()
    sol = await agent.run(state)
    elapsed = time.monotonic() - t0
    score = score_candidate(sol.code, problem)
    score["elapsed_s"] = elapsed
    score["code"] = sol.code
    return score


async def run_combo_one(
    problem: Problem,
    coder: CoderAgent,
    fixer: FixerAgent,
    tool_factory: DynamicToolFactory,
    *,
    max_iterations: int = 3,
    k_visible: int = 3,
) -> dict:
    """Combo V3 — keep-best strategy, visible-only tests, no test designer."""
    visible_tests = visible_examples_for(problem, k=k_visible)
    t0 = time.monotonic()

    # 1. Coder draft
    coder_state = GlobalState()
    coder_state.add_message(
        "user",
        f"PROBLEM:\n{problem.prompt}\n\nVisible examples:\n"
        + "\n".join(f"  {e} == {x!r}" for e, x in visible_tests),
    )
    initial_sol = await coder._run_implementation(coder_state)
    best_code = initial_sol.code
    best_pass, n_total, records = await evaluate_in_sandbox(best_code, visible_tests, tool_factory)

    iter_log = [{"iteration": 0, "n_pass": best_pass, "n_total": n_total, "source": "initial"}]

    # 2. Refinement — keep-best across iterations
    current_code = best_code
    current_records = records

    for it in range(1, max_iterations + 1):
        if best_pass == n_total:
            break  # already perfect on visible

        # Ask fixer for a revision based on current candidate's failures
        fixer_state = GlobalState()
        fixer_state.add_message(
            "user",
            f"PROBLEM:\n{problem.prompt}\n\n"
            f"PREVIOUS CODE:\n```python\n{current_code}\n```\n\n"
            f"TEST RESULTS ({best_pass}/{n_total} visible-tests passed; we are "
            f"on iteration {it}):\n{format_feedback(current_records)}\n\n"
            f"Diagnose ONLY what's needed to fix the failing tests. Re-emit the "
            f"COMPLETE corrected function. Preserve everything that already works.",
        )
        revised = await fixer._run_implementation(fixer_state)

        new_pass, _, new_records = await evaluate_in_sandbox(revised.code, visible_tests, tool_factory)
        iter_log.append({"iteration": it, "n_pass": new_pass, "n_total": n_total,
                         "improved": new_pass > best_pass})

        # KEEP BEST — only adopt the revision if it strictly improves
        if new_pass > best_pass:
            best_code = revised.code
            best_pass = new_pass
            current_code = revised.code  # iterate from the new best
            current_records = new_records
        else:
            # Keep current_code unchanged; we'll try another revision pass next iter
            # but feed the LATEST failed attempt's feedback so fixer can try differently
            current_code = revised.code  # iterate from the new (regressed) attempt for diversity
            current_records = new_records

    elapsed = time.monotonic() - t0
    score = score_candidate(best_code, problem)
    score["elapsed_s"] = elapsed
    score["code"] = best_code
    score["n_iterations"] = len(iter_log)
    score["best_pass_visible"] = best_pass
    score["visible_total"] = n_total
    score["iter_log"] = iter_log
    return score


# Public entry point for the benchmark is `benchmarks/coding/run.py` — that
# module imports the helpers above and orchestrates multi-trial averaging.
# This file deliberately ships no __main__ block to keep the entry-point story
# one-file (`python benchmarks/coding/run.py`).
