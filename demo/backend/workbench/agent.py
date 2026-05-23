"""Workbench agent — a single pydantic-ai Agent backed by real Orqest primitives.

This is what an Orqest-powered app actually looks like: the agent stays lean
(pydantic-ai does what pydantic-ai is good at), and Orqest supplies the
infrastructure — memory, tracing, events, hooks — around it.

Tools available to the agent:
  - get_time:   return the current time
  - calculate:  evaluate an arithmetic expression
  - web_search: mock web search returning citations
  - remember:   persist a fact to LocalMemoryStore
  - recall:     retrieve matching memories
  - plan:       emit a structured plan (rendered as a task tree)
  - artifact:   emit a code/SVG/HTML artifact (rendered in the side panel)
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, Tool

from demo.backend._config import MODEL
from demo.backend.tools import web_search as _mock_search
from demo.backend.workbench.state import event_bus, memory, tracer
from orqest.memory import MemoryEntry, MemoryFilter
from orqest.observability import AgentEvent


# --- Tool implementations ---------------------------------------------------


async def _emit(event_type: str, data: dict[str, Any]) -> None:
    """Emit an event on the bus (and into the ring buffer)."""
    await event_bus.emit(
        AgentEvent(
            event_type=event_type,
            agent_name="workbench",
            data=data,
        )
    )


async def get_time() -> str:
    """Return the current local date and time."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await _emit("tool:get_time", {"result": now})
    return now


async def calculate(expression: str) -> str:
    """Evaluate a simple arithmetic expression."""
    allowed = set("0123456789+-*/().% ")
    if not all(c in allowed for c in expression):
        return "Invalid expression"
    try:
        value = eval(expression)  # noqa: S307
        await _emit("tool:calculate", {"expression": expression, "value": str(value)})
        return f"{expression} = {value}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


async def web_search(query: str) -> str:
    """Search the web for current information. Returns JSON list of sources."""
    result = await _mock_search(query)
    await _emit("tool:web_search", {"query": query, "hits": len(json.loads(result))})
    return result


async def remember(content: str, category: str = "general") -> str:
    """Persist a fact to long-term memory. Use for user preferences, names, plans, etc."""
    entry = MemoryEntry(
        content=content,
        memory_type="episodic",
        source_agent="workbench",
        metadata={"category": category},
    )
    try:
        await memory.store(entry)
        await _emit("memory:stored", {"id": entry.id, "content": content, "category": category})
        return f"Stored memory: {content}"
    except Exception as exc:  # noqa: BLE001
        return f"Failed to store memory: {exc}"


async def recall(query: str, limit: int = 5) -> str:
    """Retrieve memories matching the query. Returns JSON list."""
    try:
        entries = await memory.recall(
            query, k=limit, filters=MemoryFilter(min_reliability=0.1)
        )
    except Exception as exc:  # noqa: BLE001
        return f"Failed to recall: {exc}"

    await _emit("memory:recalled", {"query": query, "count": len(entries)})
    if not entries:
        return "No memories found."

    return json.dumps(
        [
            {
                "id": e.id,
                "content": e.content,
                "category": e.metadata.get("category", "general"),
                "reliability": round(e.reliability_score, 2),
            }
            for e in entries
        ],
        indent=2,
    )


class PlanStep(BaseModel):
    """A single step in a plan. Used as the argument schema for emit_plan."""

    index: int = Field(description="1-based step number")
    description: str = Field(description="Concise action for this step")
    status: Literal["pending", "running", "complete", "error"] = Field(
        default="complete",
        description="Execution state; use 'complete' with a realistic result.",
    )
    result: str = Field(
        default="",
        description="One short sentence describing the outcome of the step.",
    )


async def emit_plan(goal: str, steps: list[PlanStep]) -> str:
    """Emit a structured plan for display in the Tasks tab.

    Always call this BEFORE answering when the user gives a multi-step goal.
    Include 3-6 steps. Every step should have status='complete' and a
    concrete `result` line describing what was done (simulate outcomes).
    """
    steps_data = [s.model_dump() for s in steps]
    await _emit("plan:emitted", {"goal": goal, "steps": steps_data})
    return f"Plan emitted with {len(steps)} steps: " + ", ".join(
        s.description for s in steps
    )


async def emit_artifact(
    title: str,
    language: str,
    code: str,
) -> str:
    """Emit a code/SVG/HTML artifact for display in the Artifact tab.

    language must be one of: 'html', 'svg', 'jsx', 'python', 'markdown'.
    """
    await _emit(
        "artifact:emitted",
        {"title": title, "language": language, "code": code},
    )
    return f"Artifact '{title}' ({language}, {len(code)} chars) emitted."


# --- Agent definition -------------------------------------------------------


SYSTEM_PROMPT = """\
You are Orqest Workbench — the reference agent for the Orqest framework. \
You have a rich toolbelt and you USE IT AGGRESSIVELY. Lazy agents write \
prose; good agents call tools.

## Mandatory Behaviors (these are rules, not suggestions)

1. **Multi-step goals → ALWAYS call `emit_plan` FIRST.**
   Any request like "plan X", "how do I Y", "walk me through Z", "break down W" \
   means you MUST call `emit_plan` with 3-6 steps BEFORE writing prose. \
   Every step must have status='complete' and a specific result line \
   (simulate plausible outcomes — you don't have real tools).

2. **Visual output → ALWAYS call `emit_artifact`.**
   If the user asks for an SVG, HTML page, React component, Python script, \
   or any code/content that should be shown in a panel, you MUST call \
   `emit_artifact` with language one of: 'html' | 'svg' | 'jsx' | 'python' | \
   'markdown'. Do NOT paste code into your chat response — use the artifact.

3. **User facts → ALWAYS call `remember`.**
   When the user shares their name, location, role, preferences, plans, \
   goals, or anything personal, CALL `remember` with a concise summary \
   BEFORE responding.

4. **Factual questions → ALWAYS call `web_search` first, then cite.**
   When the user asks about current events, research topics, or facts you \
   might be unsure about, CALL `web_search`. Then cite sources inline as \
   [1], [2] and finish with a **Sources** section:
       **Sources**
       [1] Title — URL
       [2] Title — URL

5. **Prior context lookup → consider calling `recall`.**
   If the user's question could be informed by past conversations, CALL \
   `recall` to check memory before answering.

## Tool Reference

- `get_time()` → current time
- `calculate(expression: str)` → arithmetic
- `web_search(query: str)` → JSON sources
- `remember(content: str, category: str = "general")` → persist a fact
- `recall(query: str, limit: int = 5)` → fetch memories as JSON
- `emit_plan(goal: str, steps: list[PlanStep])` → render task tree
- `emit_artifact(title: str, language: str, code: str)` → render side panel

## Style

- Concise. No "Let me know if...". No filler. No restating the question.
- After tool calls, give a 2-4 sentence synthesis. The artifacts/plans/sources \
  are shown in their panels — don't re-describe them at length.
"""


agent = Agent(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    tools=[
        Tool(get_time, name="get_time", description="Get current date and time"),
        Tool(calculate, name="calculate", description="Evaluate an arithmetic expression"),
        Tool(
            web_search,
            name="web_search",
            description="Search the web. Returns JSON list of sources to cite as [1], [2].",
        ),
        Tool(
            remember,
            name="remember",
            description="Persist a fact about the user or conversation to long-term memory.",
        ),
        Tool(
            recall,
            name="recall",
            description="Retrieve previously stored memories matching a query.",
        ),
        Tool(
            emit_plan,
            name="emit_plan",
            description=(
                "Emit a structured plan for a multi-step goal. Each step is "
                "a dict with keys: index (int), description (str), status "
                "('complete'), result (str)."
            ),
        ),
        Tool(
            emit_artifact,
            name="emit_artifact",
            description=(
                "Emit a visual artifact for the side panel. "
                "language must be one of: 'html', 'svg', 'jsx', 'python', 'markdown'. "
                "code is the full source."
            ),
        ),
    ],
)


# --- Hook that wraps agent.run to create a tracer span ---------------------


def start_agent_run_span():
    """Open a tracer span for an agent run. Caller must close it after streaming.

    Returns a tuple ``(span, finalize)`` where ``finalize(status)`` closes
    the span and records the total duration. This works with streaming
    responses where we can't use a normal context-manager lifetime
    (dispatch_request returns before the stream actually finishes).
    """
    start = time.monotonic()
    span = tracer.start_span("agent.run", agent_name="workbench")

    def finalize(status: str = "ok", extra: dict[str, Any] | None = None) -> None:
        tracer.end_span(
            span,
            status=status,
            attributes={
                "duration_ms": (time.monotonic() - start) * 1000,
                **(extra or {}),
            },
        )

    return span, finalize
