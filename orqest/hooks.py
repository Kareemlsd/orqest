"""Lifecycle hooks for tool execution.

Provides a fire-and-forget hook system for wrapping tool calls with
before/after/error callbacks. Hook errors are logged but never propagated,
so a broken hook cannot disrupt tool execution.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class ToolHook(Protocol):
    """Protocol for tool lifecycle hooks.

    Implement any subset of methods. The HookRunner checks for method
    existence before calling, so a hook that only implements before_tool
    works without raising on after_tool or on_error.
    """

    async def before_tool(
        self, tool_name: str, args: dict[str, Any], state: Any
    ) -> None:
        """Run before a tool executes."""
        ...

    async def after_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        state: Any,
        duration_ms: float,
    ) -> None:
        """Run after a tool completes successfully."""
        ...

    async def on_error(
        self,
        tool_name: str,
        args: dict[str, Any],
        error: Exception,
        state: Any,
    ) -> None:
        """Handle errors when a tool raises an exception."""
        ...


class HookRunner:
    """Dispatches hook events to registered hooks.

    Errors in hooks are logged at WARNING level and never re-raised,
    so a broken hook cannot disrupt tool execution.
    """

    def __init__(self, hooks: list[ToolHook] | None = None) -> None:
        """Initialize with an optional list of hooks."""
        self._hooks: list[ToolHook] = list(hooks) if hooks else []

    async def fire_before(
        self, tool_name: str, args: dict[str, Any], state: Any
    ) -> None:
        """Dispatch before_tool to all registered hooks."""
        for hook in self._hooks:
            await self._safe_call(
                hook, "before_tool", tool_name=tool_name, args=args, state=state
            )

    async def fire_after(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        state: Any,
        duration_ms: float,
    ) -> None:
        """Dispatch after_tool to all registered hooks."""
        for hook in self._hooks:
            await self._safe_call(
                hook,
                "after_tool",
                tool_name=tool_name,
                args=args,
                result=result,
                state=state,
                duration_ms=duration_ms,
            )

    async def fire_error(
        self,
        tool_name: str,
        args: dict[str, Any],
        error: Exception,
        state: Any,
    ) -> None:
        """Dispatch on_error to all registered hooks."""
        for hook in self._hooks:
            await self._safe_call(
                hook,
                "on_error",
                tool_name=tool_name,
                args=args,
                error=error,
                state=state,
            )

    async def _safe_call(
        self, hook: ToolHook, method_name: str, **kwargs: Any
    ) -> None:
        """Invoke a hook method if it exists, swallowing any exception."""
        method = getattr(hook, method_name, None)
        if method is None:
            return
        try:
            await method(**kwargs)
        except Exception:
            logger.warning(
                "Hook {hook}.{method} failed",
                hook=type(hook).__name__,
                method=method_name,
            )
