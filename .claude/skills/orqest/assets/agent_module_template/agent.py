"""<NAME> agent — Orqest BaseAgent harness.

Replace placeholder strings (<NAME>, <Description>, <build factory args>) and
adjust output_type / system_prompt / tools to fit your application.

This template intentionally stays minimal. Add complexity only when discovery
surfaces a need for it (memory, healing, metacognition, generative UI, etc.).
"""
from __future__ import annotations

from orqest.agents import BaseAgent, GlobalState

from .types import <NAME>Output

# Tools live in ./tools.py — import async functions here, e.g.:
#     from .tools import list_recent_orders


class <NAME>Agent(BaseAgent[GlobalState, <NAME>Output]):
    """<one-line description tied to Phase A discovery answer 5>."""


def build(*, model: str, api_key: str, **scope: object) -> <NAME>Agent:
    """Build a fresh agent instance.

    Args:
        model: ``provider:model_id`` (e.g., ``openai:gpt-4.1``).
        api_key: API key for the chosen provider.
        **scope: per-request scope variables (e.g., ``user_id``) referenced
            in the system prompt or by tools.
    """
    return <NAME>Agent(
        agent_name="<name>",
        system_prompt=(
            "<Replace this with your system prompt. Reference the Phase A "
            "discovery answers — task, output expectations, scope.>"
        ),
        output_type=<NAME>Output,
        model=model,
        api_key=api_key,
        tools=[
            # list async tool functions here — see ./tools.py
        ],
    )
