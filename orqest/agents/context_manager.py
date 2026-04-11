"""Token-aware context management for conversation history.

Provides progressive compaction: summarize old tool turns at 60% capacity,
emergency truncation at 85%. Uses heuristic token estimation to avoid
tiktoken dependency.
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from orqest.utils.token_counter import estimate_tokens


class ContextManager:
    """Progressive context compaction based on token budget.

    Three layers of compaction, activated by token usage thresholds:
    1. Tool result snipping (handled by budget_tool_results, separate processor)
    2. Turn summarization — at summarize_threshold, compress old tool-call turns
    3. Emergency truncation — at truncate_threshold, aggressive message dropping
    """

    def __init__(
        self,
        token_budget: int = 128_000,
        reserve: int = 20_000,
        summarize_threshold: float = 0.60,
        truncate_threshold: float = 0.85,
        min_recent_turns: int = 5,
        min_recent_tokens: int = 10_000,
    ):
        self.effective_budget = token_budget - reserve
        self.summarize_threshold = summarize_threshold
        self.truncate_threshold = truncate_threshold
        self.min_recent_turns = min_recent_turns
        self.min_recent_tokens = min_recent_tokens

    def compact(self, messages: list[ModelMessage]) -> list[ModelMessage]:
        """Apply progressive compaction based on token usage.

        Returns a new list — never mutates the input.
        """
        if not messages:
            return list(messages)

        tokens = estimate_tokens(messages)

        if tokens > self.effective_budget * self.truncate_threshold:
            return self._emergency_truncate(messages)
        if tokens > self.effective_budget * self.summarize_threshold:
            return self._summarize_old_turns(messages)
        return list(messages)

    def _summarize_old_turns(
        self, messages: list[ModelMessage]
    ) -> list[ModelMessage]:
        """Replace old tool-call turns with one-line summaries.

        Keeps the first message and the last min_recent_turns messages verbatim.
        For older messages: if a ModelResponse has ToolCallPart followed by a
        ModelRequest with ToolReturnPart, replace the pair with a synthetic
        summary message.
        """
        if len(messages) <= self.min_recent_turns + 1:
            return list(messages)

        first = messages[0]
        # Split into old and recent
        recent_start = max(1, len(messages) - self.min_recent_turns)
        old_messages = messages[1:recent_start]
        recent_messages = messages[recent_start:]

        # Process old messages: summarize tool call pairs
        compacted: list[ModelMessage] = [first]
        summaries: list[str] = []
        i = 0
        while i < len(old_messages):
            msg = old_messages[i]

            # Check for tool call response followed by tool return request
            if (
                isinstance(msg, ModelResponse)
                and i + 1 < len(old_messages)
                and isinstance(old_messages[i + 1], ModelRequest)
                and _is_tool_call_response(msg)
                and _is_tool_return_request(old_messages[i + 1])
            ):
                summary = _summarize_tool_pair(msg, old_messages[i + 1])
                summaries.append(summary)
                i += 2
            else:
                # Flush accumulated summaries before non-tool message
                if summaries:
                    compacted.append(_make_summary_message(summaries))
                    summaries = []
                compacted.append(msg)
                i += 1

        # Flush remaining summaries
        if summaries:
            compacted.append(_make_summary_message(summaries))

        compacted.extend(recent_messages)
        return compacted

    def _emergency_truncate(
        self, messages: list[ModelMessage]
    ) -> list[ModelMessage]:
        """Aggressive truncation preserving minimum recent context.

        Keeps the first message plus enough recent messages to reach
        min_recent_tokens.
        """
        if not messages:
            return []

        first = messages[0]
        first_tokens = estimate_tokens([first])

        # Walk backward from the end, accumulating tokens until we hit min_recent_tokens
        recent: list[ModelMessage] = []
        recent_tokens = 0
        for msg in reversed(messages[1:]):
            msg_tokens = estimate_tokens([msg])
            recent.insert(0, msg)
            recent_tokens += msg_tokens
            if (
                recent_tokens >= self.min_recent_tokens
                and len(recent) >= self.min_recent_turns
            ):
                break

        result = [first] + recent
        return result


def _is_tool_call_response(msg: ModelResponse) -> bool:
    """Check if a ModelResponse contains ToolCallPart."""
    return any(isinstance(p, ToolCallPart) for p in msg.parts)


def _is_tool_return_request(msg: ModelRequest) -> bool:
    """Check if a ModelRequest contains ToolReturnPart."""
    return any(isinstance(p, ToolReturnPart) for p in msg.parts)


def _summarize_tool_pair(
    call_resp: ModelResponse, return_req: ModelRequest
) -> str:
    """Create a one-line summary of a tool call + return pair."""
    tool_name = "unknown"
    args_preview = ""
    for part in call_resp.parts:
        if isinstance(part, ToolCallPart):
            tool_name = part.tool_name
            args_str = str(part.args) if part.args else ""
            if args_str and len(args_str) > 80:
                args_preview = args_str[:77] + "..."
            else:
                args_preview = args_str
            break

    # Determine success/failure from return content
    status = "completed"
    for part in return_req.parts:
        if isinstance(part, ToolReturnPart):
            content_str = str(part.content).lower()
            if "error" in content_str or "failed" in content_str:
                status = "failed"
            break

    if args_preview:
        return f"Called {tool_name}({args_preview}) → {status}"
    return f"Called {tool_name}() → {status}"


def _make_summary_message(summaries: list[str]) -> ModelRequest:
    """Create a synthetic ModelRequest containing tool call summaries."""
    text = "[Context summary — older tool calls]\n" + "\n".join(
        f"• {s}" for s in summaries
    )
    return ModelRequest(parts=[UserPromptPart(text)])
