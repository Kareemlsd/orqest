"""Conversation state shared across agent runs.

GlobalState tracks two distinct things:
- `messages`: application-level conversation log (role/content dicts) for the user's use.
- `message_history`: raw pydantic-ai ModelMessage objects for passing back into Agent.run().
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai.messages import ModelMessage


class GlobalState(BaseModel):
    """Shared conversation state for orqest agents."""

    messages: list[dict[str, Any]] = Field(default_factory=list)
    message_history: list[ModelMessage] = Field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        """Append a role/content pair to the conversation log."""
        self.messages.append({"role": role, "content": content})

    def get_latest_message(self, role: str) -> str | None:
        """Return the content of the most recent message with the given role."""
        for message in reversed(self.messages):
            if message.get("role") == role:
                return message.get("content")
        return None
