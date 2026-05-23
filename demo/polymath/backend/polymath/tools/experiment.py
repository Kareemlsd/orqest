"""Experiment-runner tool — the "actual discovery" piece for the research engine.

A research engine that only synthesises literature is a sophisticated summariser.
A research engine that can ALSO run small numerical experiments — train tiny NNs
on toy dynamical systems, fit Koopman approximations, compute prediction-error
curves — is something fundamentally different: it can verify or falsify claims
the literature makes, surface contradictions empirically, and build intuition
the user can carry forward.

This tool is the bridge. It wraps a structured "experiment" abstraction over
the existing sandbox surface (``run_python_snippet``):

* Input: a self-contained Python program that prints a final JSON line with
  metrics (the contract: last line of stdout MUST be valid JSON).
* Backend: per-session Docker sandbox (already running; provides ``numpy``,
  ``scipy``, ``matplotlib``, ``pytorch`` if image includes it).
* Output: structured ``{metrics, stdout_tail, plot_b64?, success, error?}``
  the agent can reason about, plus matplotlib plots saved into ``/workspace/
  experiments/`` for the user to inspect.

Use this when the question shifts from "what does the literature say?" to
"does this method actually work on this system?". Pair with the
``RefinementLoop`` pattern: design → run → critique → refine.
"""

from __future__ import annotations

import json
import re
from typing import Annotated

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from polymath.runtime import emit
from polymath.sandbox.manager import SandboxError, get_manager
from polymath.state import PolymathState


# How many chars of stdout/stderr to surface back to the agent. Enough to read
# loss curves + error messages; small enough not to blow the context budget.
_STDOUT_TAIL_CHARS = 4_000


_FINAL_JSON_LINE_RE = re.compile(r"^(\{.*\})\s*$", re.MULTILINE)


def _extract_final_json(stdout: str) -> dict | None:
    """Pull the last JSON object the program printed to stdout.

    The contract is "the final line of stdout is a JSON object with metrics."
    We're forgiving — search backwards through lines for the first parseable
    JSON object. Returns None if no JSON line found.
    """
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


async def _experiment_run(
    ctx: RunContext[PolymathState],
    program: Annotated[
        str,
        "A self-contained Python program that runs the experiment and prints "
        "a final JSON object to stdout with metrics. The last JSON object "
        "printed is parsed as the experiment's result. Use numpy/scipy/"
        "matplotlib (pre-installed); pytorch is available if needed. "
        "Save any plots to /workspace/experiments/<name>.png so the user "
        "can inspect them. The program should COMPLETE in under timeout_s "
        "seconds; otherwise it's killed.",
    ],
    label: Annotated[
        str,
        "Short human-readable name for this experiment, e.g. "
        "'edmd_lorenz_horizon_sweep' or 'deep_koopman_oscillator_baseline'. "
        "Used in event payloads and to disambiguate when several experiments "
        "run per session.",
    ],
    timeout_s: Annotated[
        int,
        "Wall-clock cap in seconds. Default 180 (3 min) — long enough for "
        "training a small NN for a few hundred epochs on a CPU; short enough "
        "to prevent runaway. Max 600.",
    ] = 180,
) -> str:
    """Run a small numerical experiment in the sandbox; return parsed metrics JSON.

    The contract:
    * The program runs to completion in the per-session sandbox.
    * The LAST JSON object printed to stdout is parsed as the experiment's
      "result" — typically ``{accuracy, loss, prediction_error_curve, ...}``.
    * Plots saved to ``/workspace/experiments/<name>.png`` are listed in the
      response so the agent can ``read_file`` or ``open_tab(kind='image')``.
    * On crash / timeout, the response captures the failure mode for the
      agent to diagnose.
    """
    sid = ctx.deps.session_id
    await emit(
        sid,
        "tool.experiment_run.started",
        {"label": label, "timeout_s": timeout_s, "program_chars": len(program)},
    )
    timeout_s = max(10, min(600, timeout_s))

    try:
        # Same pattern as run_python_snippet — python3 -c <program> in the
        # per-session sandbox via manager.exec().
        exit_code, stdout, stderr, truncated = await get_manager().exec(
            sid, ["python3", "-c", program], timeout_s=timeout_s,
        )
    except SandboxError as exc:
        await emit(
            sid,
            "tool.experiment_run.error",
            {"label": label, "error": str(exc), "stage": "sandbox"},
        )
        return json.dumps({
            "error": f"experiment_run sandbox error: {exc}",
            "label": label,
        })
    except Exception as exc:  # noqa: BLE001
        await emit(
            sid,
            "tool.experiment_run.error",
            {"label": label, "error": str(exc), "stage": "manager"},
        )
        return json.dumps({
            "error": f"experiment_run failed before execution: {type(exc).__name__}: {exc}",
            "label": label,
        })

    duration_ms = None  # manager.exec doesn't surface duration; could time around it

    metrics = _extract_final_json(stdout)
    success = exit_code == 0 and metrics is not None

    # Tail-truncate so the agent doesn't see all of a long training log
    stdout_tail = stdout[-_STDOUT_TAIL_CHARS:] if stdout else ""
    stderr_tail = stderr[-_STDOUT_TAIL_CHARS:] if stderr else ""

    payload = {
        "label": label,
        "success": success,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "metrics": metrics,  # may be None if no JSON line found
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail if not success else "",
        "hint": (
            "metrics extracted from final JSON line of stdout. Save plots to "
            "/workspace/experiments/<name>.png and the user / a follow-up tool "
            "can read them."
        )
        if success
        else (
            "experiment FAILED. Diagnose from stderr_tail + last lines of "
            "stdout_tail. Common causes: missing import (check stderr), wrong "
            "JSON shape (the metrics field is None), runtime > timeout."
        ),
    }

    if success:
        await emit(
            sid,
            "tool.experiment_run.completed",
            {
                "label": label,
                "duration_ms": duration_ms,
                "metric_keys": list(metrics.keys()) if metrics else [],
            },
        )
    else:
        await emit(
            sid,
            "tool.experiment_run.error",
            {"label": label, "exit_code": exit_code, "metrics_parsed": metrics is not None},
        )

    return json.dumps(payload, ensure_ascii=False)


experiment_run = Tool(_experiment_run, name="experiment_run")
