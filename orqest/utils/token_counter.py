"""Heuristic token estimation for pydantic-ai message lists.

Uses a chars-per-token approximation (3.5) to avoid a tiktoken dependency.
Conservative for English text (~4 chars/token actual) but accounts for code
content which tokenizes at ~2-3 chars/token.
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

CHARS_PER_TOKEN: float = 3.5
MESSAGE_OVERHEAD_TOKENS: int = 4  # role marker, structural tokens


def estimate_tokens(messages: list[ModelMessage]) -> int:
    """Estimate token count for a message list.

    Walks all messages, sums text content lengths / CHARS_PER_TOKEN
    plus overhead per message.
    """
    total = 0
    for msg in messages:
        total += MESSAGE_OVERHEAD_TOKENS
        for part in msg.parts:
            if isinstance(part, (UserPromptPart, TextPart)):
                text = (
                    str(part.content)
                    if not isinstance(part.content, str)
                    else part.content
                )
                total += int(len(text) / CHARS_PER_TOKEN) + 1
            elif isinstance(part, ToolReturnPart):
                content_str = str(part.content)
                total += int(len(content_str) / CHARS_PER_TOKEN) + 1
            elif isinstance(part, ToolCallPart):
                # Count args contribution
                args_str = str(part.args) if part.args else ""
                if args_str:
                    total += int(len(args_str) / CHARS_PER_TOKEN) + 1
                # Tool name contributes too
                total += int(len(part.tool_name) / CHARS_PER_TOKEN) + 1
            elif hasattr(part, "content"):
                text = str(part.content)
                total += int(len(text) / CHARS_PER_TOKEN) + 1
    return total


def estimate_text_tokens(text: str) -> int:
    """Estimate token count for a plain text string."""
    return int(len(text) / CHARS_PER_TOKEN) + 1
