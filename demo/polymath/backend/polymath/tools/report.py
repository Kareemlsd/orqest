"""Figure + PDF generation tools. Artifacts land in the session sandbox
under ``/workspace/.polymath/artifacts/`` and are registered in the DB so
the ChartsTab / ReportTab / artifact list can surface them immediately.
"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import uuid4

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from orqest.ui import (
    ChartComponent,
    ChartComponentData,
    UIEmitter,
)

from polymath.artifacts.store import create_artifact
from polymath.runtime import emit, get_runtime
from polymath.sandbox.manager import SandboxError, get_manager
from polymath.state import PolymathState

_ARTIFACT_DIR = ".polymath/artifacts"


_CHART_WRAPPER = r"""
import sys, os, json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as _plt  # noqa

OUT_PATH = sys.argv[1]
os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)

# User snippet runs in its own namespace. Convention: the snippet builds a
# matplotlib figure (plot / subplots / etc.). If the user forgets to save,
# we call plt.savefig on the current figure.
user_code = sys.stdin.read()
_ns = {"plt": _plt, "__name__": "__polymath_chart__"}
exec(compile(user_code, "<chart>", "exec"), _ns)

if os.path.getsize(OUT_PATH) if os.path.exists(OUT_PATH) else 0 == 0:
    fig = _plt.gcf()
    fig.savefig(OUT_PATH, dpi=120, bbox_inches="tight")

print(json.dumps({"path": OUT_PATH, "size": os.path.getsize(OUT_PATH)}))
"""


_PDF_CSS = (
    "@page { size: A4; margin: 2cm; }\n"
    "body { font-family: 'Source Sans 3', Helvetica, sans-serif; "
    "font-size: 11pt; color: #222; line-height: 1.55; }\n"
    "h1, h2, h3 { font-family: 'Source Serif 4', Georgia, serif; "
    "color: #111; letter-spacing: -0.02em; }\n"
    "h1 { font-size: 22pt; margin-top: 0.5em; }\n"
    "h2 { font-size: 16pt; margin-top: 1.5em; }\n"
    "h3 { font-size: 13pt; margin-top: 1em; }\n"
    "p  { margin: 0.5em 0; }\n"
    "a  { color: #0f766e; text-decoration: none; }\n"
    "code { font-family: 'JetBrains Mono', Menlo, monospace; "
    "background: #f5f5f5; padding: 0.1em 0.3em; border-radius: 3px; "
    "font-size: 10pt; }\n"
    "pre code { display: block; padding: 0.75em; overflow-x: auto; }\n"
    "table { border-collapse: collapse; width: 100%; }\n"
    "th, td { border: 1px solid #ddd; padding: 6px 10px; font-size: 10pt; }\n"
    "th { background: #fafafa; text-align: left; }\n"
    "blockquote { border-left: 3px solid #0f766e; margin: 1em 0; "
    "padding-left: 1em; color: #555; }"
)

_PDF_WRAPPER = r"""
import sys, os, json, markdown
from weasyprint import HTML, CSS

OUT_PATH = sys.argv[1]
CSS_STR = sys.argv[2]
os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)

md = sys.stdin.read()
html_body = markdown.markdown(
    md, extensions=["fenced_code", "tables", "toc", "codehilite"]
)
doc = "<html><head><meta charset='utf-8'/></head><body>" + html_body + "</body></html>"
HTML(string=doc).write_pdf(OUT_PATH, stylesheets=[CSS(string=CSS_STR)])

print(json.dumps({"path": OUT_PATH, "size": os.path.getsize(OUT_PATH)}))
"""


async def _render_chart(
    ctx: RunContext[PolymathState],
    code: Annotated[
        str,
        "Python snippet that builds a matplotlib figure. Use `plt` for the "
        "pyplot API. Save is auto-applied to the current figure if you "
        "don't call savefig yourself.",
    ],
    label: Annotated[str, "Short human label for the artifact list."] = "chart",
) -> str:
    """Run a matplotlib snippet in the sandbox and save as a PNG artifact."""
    sid = ctx.deps.session_id
    fname = f"{_ARTIFACT_DIR}/chart-{uuid4().hex[:8]}.png"
    await emit(sid, "tool.report.render_chart.started", {"label": label})
    try:
        await get_manager().exec(sid, ["mkdir", "-p", f"/workspace/{_ARTIFACT_DIR}"])
        # matplotlib wrapper reads user code from stdin via bash heredoc-less echo.
        # We pass user code as an env var to avoid shell-quoting the script.
        wrapped = (
            "printf '%s' \"$POLYMATH_USER_CODE\" | python3 -c "
            + _shell_quote(_CHART_WRAPPER)
            + " "
            + _shell_quote(f"/workspace/{fname}")
        )
        code_exit, stdout, stderr, _ = await get_manager().exec(
            sid,
            ["bash", "-lc", wrapped],
            env={"POLYMATH_USER_CODE": code},
            timeout_s=60,
        )
        if code_exit != 0:
            raise SandboxError((stderr or stdout).strip() or "chart render failed")
        payload = _last_json(stdout)
        size = int(payload.get("size") or 0)
    except SandboxError as exc:
        await emit(sid, "tool.report.render_chart.error", {"error": str(exc)})
        return json.dumps({"error": str(exc)})
    artifact = await create_artifact(
        session_id=sid,
        kind="chart",
        mime="image/png",
        label=label,
        path=fname,
        size_bytes=size,
    )
    # Phase β: also emit the typed ``ui.chart.init`` event so the
    # frontend can resolve a renderer through the generative-UI channel
    # in addition to the legacy artifact list. Matplotlib produces a
    # binary PNG (not structured series data), so we leave ``series``
    # empty and stash the artifact pointer in metadata — the frontend
    # fetches the PNG via the existing ``/sessions/{sid}/artifacts``
    # endpoint.
    #
    # TODO(polymath): when we extend ``_render_chart`` to optionally
    # accept structured plot data (e.g. a list of (x, y) points), pass
    # those through into ``ChartComponentData.series`` so the typed
    # channel can render charts client-side without the PNG roundtrip.
    bus = get_runtime(sid).workbench.event_bus
    emitter = UIEmitter(bus, agent_name=f"polymath[{sid}]")
    await emitter.init(
        ChartComponent(
            component_id=f"chart-{artifact.id}",
            data=ChartComponentData(
                chart_kind="line",
                title=label,
                series=[],
            ),
            metadata={
                "artifact_id": str(artifact.id),
                "artifact_path": fname,
                "mime": "image/png",
            },
        )
    )
    await emit(
        sid,
        "tool.report.render_chart.completed",
        {"artifact_id": str(artifact.id), "label": label, "size": size},
    )
    return json.dumps(
        {"artifact_id": str(artifact.id), "path": fname, "size_bytes": size}
    )


async def _markdown_to_pdf(
    ctx: RunContext[PolymathState],
    markdown_text: Annotated[str, "Markdown source of the report."],
    label: Annotated[str, "Short human label for the artifact list."] = "report",
) -> str:
    """Render markdown → PDF via weasyprint in the sandbox."""
    sid = ctx.deps.session_id
    fname = f"{_ARTIFACT_DIR}/report-{uuid4().hex[:8]}.pdf"
    await emit(sid, "tool.report.markdown_to_pdf.started", {"label": label})
    try:
        await get_manager().exec(sid, ["mkdir", "-p", f"/workspace/{_ARTIFACT_DIR}"])
        wrapped = (
            "printf '%s' \"$POLYMATH_USER_MD\" | python3 -c "
            + _shell_quote(_PDF_WRAPPER)
            + " "
            + _shell_quote(f"/workspace/{fname}")
            + " "
            + _shell_quote(_PDF_CSS)
        )
        code_exit, stdout, stderr, _ = await get_manager().exec(
            sid,
            ["bash", "-lc", wrapped],
            env={"POLYMATH_USER_MD": markdown_text},
            timeout_s=60,
        )
        if code_exit != 0:
            raise SandboxError((stderr or stdout).strip() or "pdf render failed")
        payload = _last_json(stdout)
        size = int(payload.get("size") or 0)
    except SandboxError as exc:
        await emit(sid, "tool.report.markdown_to_pdf.error", {"error": str(exc)})
        return json.dumps({"error": str(exc)})
    artifact = await create_artifact(
        session_id=sid,
        kind="report",
        mime="application/pdf",
        label=label,
        path=fname,
        size_bytes=size,
    )
    # TODO(orqest): emit a typed ``ui.document.init`` event here once
    # ``DocumentComponent`` lands in ``orqest.ui``. PDFs are a generic
    # document shape — see assessment §6 Option B. For now the frontend
    # consumes ``artifact.created`` for the PDF preview tab and the
    # generative-UI channel doesn't carry the report.
    await emit(
        sid,
        "tool.report.markdown_to_pdf.completed",
        {"artifact_id": str(artifact.id), "label": label, "size": size},
    )
    return json.dumps(
        {"artifact_id": str(artifact.id), "path": fname, "size_bytes": size}
    )


def _shell_quote(s: str) -> str:
    """POSIX single-quote for safe bash -lc interpolation."""
    return "'" + s.replace("'", "'\\''") + "'"


def _last_json(stdout: str) -> dict:
    line = stdout.strip().splitlines()[-1] if stdout.strip() else "{}"
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {}


render_chart = Tool(_render_chart, name="render_chart")
markdown_to_pdf = Tool(_markdown_to_pdf, name="markdown_to_pdf")
