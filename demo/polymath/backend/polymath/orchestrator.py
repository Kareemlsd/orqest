"""Polymath orchestrator — typed :class:`~orqest.agents.BaseAgent` subclass.

Polymath is the flagship Orqest demo, so its top-level agent is built on
the canonical Orqest substrate (:class:`BaseAgent[StateT, OutputT]`)
rather than a hand-rolled :class:`pydantic_ai.Agent`. The streaming
chat path still ultimately dispatches to a ``pydantic_ai.Agent`` —
that instance is exposed via :attr:`BaseAgent.agent`, so the underlying
agent the :class:`VercelAIAdapter` sees is identical to the one
:class:`PolymathAgent` owns.

We export :func:`get_polymath_agent` (lazily cached) instead of a
module-level instance so API-key lookup stays out of import time —
matching Orqest's *no import-time side effects* discipline.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

from orqest.agents.base_agent import BaseAgent
from orqest.agents.context_manager import ContextManager
from orqest.io_utils.load_sys_prompt import load_sys_prompt
from orqest.metacognition import StructuredOutputProtocol

from polymath.config import get_default_config
from polymath.state import PolymathState
from polymath.tools.arxiv import arxiv_fetch, arxiv_search
from polymath.tools.autonomy import (
    invoke_agent,
    list_agents,
    register_agent,
    spawn_analyst,
)
from polymath.tools.browser import browser_click, browser_open_url, browser_type
from polymath.tools.citations import citation_graph
from polymath.tools.experiment import experiment_run
from polymath.tools.fs import edit_file, list_dir, read_file, write_file
from polymath.tools.memory import recall, remember
from polymath.tools.pdf import pdf_extract
from polymath.tools.plan import init_plan, update_plan
from polymath.tools.report import markdown_to_pdf, render_chart
from polymath.tools.shell import run_command, run_python_snippet
from polymath.tools.tabs import close_tab, open_tab, update_tab
from polymath.tools.ui import emit_component, remove_component, update_component
from polymath.tools.web import web_fetch, web_search

_FALLBACK_PROMPT = (
    "You are Polymath, a general-purpose autonomous agent. Begin every run by "
    "calling `init_plan` with a 2–5 task outline, then use the other tools to "
    "execute it. Flip each task's status via `update_plan` as you go. Use "
    "`remember` to capture durable findings; `recall` before repeating research."
)

# Token budgets per provider family. Used by the ContextManager to size
# its compaction thresholds. 128k is the conservative default — most
# modern OpenAI / Anthropic / Google flagships ship with at least this.
_MODEL_BUDGETS: dict[str, int] = {
    "openai:gpt-4o": 128_000,
    "openai:gpt-4.1": 128_000,
    "anthropic:claude-sonnet-4-6": 200_000,
    "anthropic:claude-opus-4-7": 200_000,
}


def _budget_for(model: str) -> int:
    """Pick a context-window budget for *model*.

    Falls back to 128 000 for unknown models — the safest cross-vendor
    default. The :class:`ContextManager` uses this only to set its
    summarize/truncate thresholds; it never blocks on overflow.
    """
    return _MODEL_BUDGETS.get(model, 128_000)


_ReasoningEffort = Literal["minimal", "low", "medium", "high"]


def _resolve_reasoning_effort(model: str) -> _ReasoningEffort | None:
    """Pick a reasoning effort for *model*, honoring ``POLYMATH_REASONING_EFFORT``.

    Returns ``None`` for models known not to support reasoning OR for model+
    transport combinations that error at runtime — e.g. ``openai:gpt-5*`` over
    the default ``/v1/chat/completions`` endpoint **rejects** the combination
    of function tools + ``reasoning_effort`` (OpenAI requires the Responses
    API for that combo). The framework would otherwise return 400 mid-stream
    and the user sees an unrecoverable error toast.

    To opt INTO reasoning + tools with GPT-5 specifically, switch the model
    string to ``openai-responses:gpt-5.4`` (uses the Responses API) — that
    path is allowed below.

    Default for reasoning-capable models is ``"medium"`` — synthesis benefits
    from extra thinking but the cost ceiling stays bounded. Override via env
    ``POLYMATH_REASONING_EFFORT={minimal,low,medium,high,off}``.
    """
    override = os.getenv("POLYMATH_REASONING_EFFORT")
    if override in ("minimal", "low", "medium", "high"):
        return override  # type: ignore[return-value]
    if override in ("none", "off", ""):
        if override is not None:
            return None
    # KNOWN BAD: openai:gpt-5* with function tools over chat/completions rejects
    # reasoning_effort. Polymath has 20+ tools wired, so chat/completions is
    # the only path. Skip reasoning here until we switch to the Responses API.
    if model.startswith("openai:gpt-5"):
        return None
    # Reasoning-capable models that work cleanly with tools today:
    reasoning_capable = (
        # OpenAI Responses-API path — supports reasoning + tools
        "openai-responses:",
        # OpenAI o-series (use chat/completions; reasoning + tools OK historically)
        "openai:o1", "openai:o3", "openai:o4",
        # Anthropic thinking-capable models — thinking + tools work fine
        "anthropic:claude-sonnet-4-7", "anthropic:claude-opus-4-7",
        "anthropic:claude-sonnet-4-6", "anthropic:claude-opus-4-6",
        # Google thinking-capable
        "google:gemini-2.5",
    )
    if any(model.startswith(prefix) for prefix in reasoning_capable):
        return "medium"
    return None


def _resolve_system_prompt() -> str:
    """Load the orchestrator system prompt, falling back to the inline default."""
    try:
        return load_sys_prompt("orchestrator.md")
    except Exception:
        return _FALLBACK_PROMPT


class PolymathAgent(BaseAgent[PolymathState, str]):
    """The Polymath orchestrator — typed :class:`BaseAgent` subclass.

    Wires the full tool surface (research, plan, memory, sandbox,
    browser, reports, autonomy) onto a :class:`BaseAgent`. The chat
    router dispatches to :attr:`PolymathAgent.agent` (the lazily-built
    ``pydantic_ai.Agent``) for streaming via :class:`VercelAIAdapter`;
    callers that want a non-streaming run (tests, MCP server, scripted
    invocations) use :meth:`run` / :meth:`run_enriched` directly.
    """

    def __init__(self) -> None:
        cfg = get_default_config()
        api_key = cfg.require_llm_key()
        # Browser tools are heavy (noVNC + Chromium). Default-off; flip
        # via POLYMATH_ENABLE_BROWSER=1 to surface them on the orchestrator.
        browser_tools = (
            [browser_open_url, browser_click, browser_type]
            if cfg.ENABLE_BROWSER
            else []
        )
        super().__init__(
            agent_name="polymath",
            system_prompt=_resolve_system_prompt(),
            output_type=str,
            model=cfg.LLM_MODEL,
            api_key=api_key,
            tools=[
                # Primary literature (use FIRST for research questions in dynamical
                # systems / world models / control theory)
                arxiv_search,
                arxiv_fetch,
                pdf_extract,
                citation_graph,
                # General web (blog posts, lecture notes, non-arxiv sources)
                web_search,
                web_fetch,
                # Plan
                init_plan,
                update_plan,
                # Memory
                remember,
                recall,
                # Sandbox (Phase 2)
                read_file,
                write_file,
                edit_file,
                list_dir,
                run_command,
                run_python_snippet,
                # Experiments — structured wrapper for numerical research runs
                # (train a small NN on a toy dynamical system, fit EDMD, etc.)
                # See tools/experiment.py for the contract.
                experiment_run,
                # Browser (Phase 3) — gated on cfg.ENABLE_BROWSER.
                *browser_tools,
                # Reports (Phase 4)
                render_chart,
                markdown_to_pdf,
                # Autonomy (Phase 4b) — persistent sub-agent roster
                register_agent,
                invoke_agent,
                list_agents,
                spawn_analyst,
                # Generative UI (L1/L2/L3) — typed component emit / patch / remove.
                emit_component,
                update_component,
                remove_component,
                # Right-pane tab manifest (Phase B) — open / patch / close.
                open_tab,
                update_tab,
                close_tab,
            ],
            # Token-aware compaction sized to the configured model.
            context_manager=ContextManager(token_budget=_budget_for(cfg.LLM_MODEL)),
            # Reasoning effort — translates per-provider (openai_reasoning_effort
            # / anthropic_thinking / google_thinking_config). "medium" balances
            # quality vs cost for research synthesis; flip to "high" for hard
            # multi-paper contradictions via POLYMATH_REASONING_EFFORT=high.
            # Models that don't support reasoning ignore this gracefully.
            reasoning=_resolve_reasoning_effort(cfg.LLM_MODEL),
            # Forward-compat: the streaming chat path uses VercelAIAdapter,
            # which doesn't currently invoke run_enriched, so this protocol
            # only fires when a caller explicitly uses run_enriched()
            # (tests / MCP / scripted runs). Set here so that path is
            # confidence-aware out of the box; harmless for streaming.
            confidence_protocol=StructuredOutputProtocol(),
        )

    async def _run_implementation(self, state: PolymathState, **kwargs: Any) -> str:
        """Single-shot run path used outside the SSE stream.

        The streaming chat handler dispatches directly to
        ``polymath_agent.agent`` (the underlying pydantic-ai
        :class:`Agent`) via :class:`VercelAIAdapter`, so this method is
        only reached when callers use :meth:`run` or :meth:`run_enriched`
        — typically tests, MCP-server-served invocations, or scripted
        smoke runs.
        """
        latest = (
            state.get_latest_message("user")
            if hasattr(state, "get_latest_message")
            else ""
        )
        prompt = latest if isinstance(latest, str) and latest else ""
        result = await self.call_model(prompt, state)
        return str(result.output) if hasattr(result, "output") else str(result)


@lru_cache(maxsize=1)
def get_polymath_agent() -> PolymathAgent:
    """Return the singleton :class:`PolymathAgent`, built on first call."""
    return PolymathAgent()
