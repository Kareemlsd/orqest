"""Lifecycle hooks for tool execution.

A hook can either *observe* (legacy: return ``None``) or *decide*
(return a :class:`HookDecision`). Decisions let hooks redirect, skip,
or abort tool execution — the foundation for security gates,
self-healing watchdogs, and policy enforcement.

Hook errors are logged but never propagated, so a broken hook cannot
disrupt tool execution. A hook that crashes while computing a decision
defaults to :class:`Continue`.

The decision protocol applies at *compound-flow* boundaries:
:class:`~orqest.agents.compound_tool.CompoundTool`,
:func:`~orqest.agents.retry.run_with_retry`, and
:meth:`~orqest.autonomy.meta.MetaOrchestrator._execute_subtask`. It does
NOT intercept pydantic-AI's internal tool dispatch — for that future
expansion, each :class:`pydantic_ai.Tool.function` would need to be
wrapped with a hook-aware shim at construction time.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from loguru import logger
from pydantic import BaseModel, ConfigDict


# ---- HookDecision discriminated union ---------------------------------


class _DecisionBase(BaseModel):
    """Frozen base for all HookDecision variants."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Continue(_DecisionBase):
    """Proceed with the tool call as-is. The default no-op decision."""

    kind: Literal["continue"] = "continue"


class Skip(_DecisionBase):
    """Skip the tool call. The compound flow returns ``stub_result`` in
    place of the executor result. ``after_tool`` still fires so observers
    see the skip. ``reason`` surfaces in resulting events."""

    kind: Literal["skip"] = "skip"
    reason: str
    stub_result: Any = ""


class Redirect(_DecisionBase):
    """Replace the call's args and/or target tool before execution.

    At least one of ``new_args``/``new_tool`` must be set.
    """

    kind: Literal["redirect"] = "redirect"
    new_args: dict[str, Any] | None = None
    new_tool: str | None = None
    reason: str = ""

    def model_post_init(self, _ctx: Any) -> None:
        if self.new_args is None and self.new_tool is None:
            raise ValueError("Redirect requires new_args or new_tool (or both)")


class Abort(_DecisionBase):
    """Halt the compound flow. Raises :class:`HookAbortError` upstream;
    the surrounding :class:`CompoundTool` / :class:`MetaOrchestrator` /
    :func:`run_with_retry` handle it via their normal error paths."""

    kind: Literal["abort"] = "abort"
    reason: str


HookDecision = Continue | Skip | Redirect | Abort


class HookAbortError(RuntimeError):
    """Raised when a hook returns :class:`Abort`."""

    def __init__(self, reason: str, source_hook: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.source_hook = source_hook


# Module-level constant — cheap reusable identity.
CONTINUE = Continue()


# ---- ToolHook protocol ------------------------------------------------


@runtime_checkable
class ToolHook(Protocol):
    """Protocol for tool lifecycle hooks.

    Methods may return ``None`` (legacy fire-and-forget) or a
    :class:`HookDecision` (new — decision-issuing). :class:`HookRunner`
    auto-wraps ``None`` into :class:`Continue` so legacy hooks remain
    unchanged.

    Implement any subset of methods. The HookRunner checks for method
    existence before calling, so a hook that only implements
    ``before_tool`` works without raising on the others.
    """

    async def before_tool(
        self, tool_name: str, args: dict[str, Any], state: Any
    ) -> HookDecision | None:
        """Run before a tool executes."""
        ...

    async def after_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        state: Any,
        duration_ms: float,
    ) -> HookDecision | None:
        """Run after a tool completes successfully."""
        ...

    async def on_error(
        self,
        tool_name: str,
        args: dict[str, Any],
        error: Exception,
        state: Any,
    ) -> HookDecision | None:
        """Handle errors when a tool raises an exception."""
        ...


# ---- HookRunner -------------------------------------------------------


class HookRunner:
    """Dispatches hook events to registered hooks and aggregates decisions.

    Aggregation rule: **first-non-Continue wins, with Abort short-circuiting.**

    1. Iterate hooks in registration order.
    2. If any hook returns :class:`Abort`, raise :class:`HookAbortError` immediately.
    3. Otherwise, the first hook returning a non-:class:`Continue` decision
       (:class:`Skip` or :class:`Redirect`) is the active decision.
    4. Subsequent hooks still run (observers may want to log), but their
       decisions are recorded as "shadowed" and logged at INFO.

    Errors in hooks are logged at WARNING level and never re-raised. A
    hook that crashes while computing a decision defaults to
    :class:`Continue`.
    """

    def __init__(self, hooks: list[ToolHook] | None = None) -> None:
        self._hooks: list[ToolHook] = list(hooks) if hooks else []

    async def run_before(
        self, tool_name: str, args: dict[str, Any], state: Any
    ) -> HookDecision:
        """Aggregate ``before_tool`` decisions across hooks."""
        return await self._aggregate("before_tool", tool_name, args, state)

    async def run_after(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        state: Any,
        duration_ms: float,
    ) -> HookDecision:
        """Aggregate ``after_tool`` decisions across hooks.

        Note: ``Skip`` from ``after_tool`` is meaningless (the executor
        already ran) — it's logged at WARNING and treated as
        :class:`Continue`. ``Redirect`` from ``after_tool`` requests a
        bounded re-execution (the caller decides how to honor it).
        """
        return await self._aggregate(
            "after_tool", tool_name, args, result, state, duration_ms
        )

    async def run_error(
        self,
        tool_name: str,
        args: dict[str, Any],
        error: Exception,
        state: Any,
    ) -> HookDecision:
        """Aggregate ``on_error`` decisions across hooks."""
        return await self._aggregate("on_error", tool_name, args, error, state)

    async def _aggregate(
        self, method_name: str, *args: Any
    ) -> HookDecision:
        active: HookDecision = CONTINUE
        shadowed: list[tuple[str, HookDecision]] = []
        for hook in self._hooks:
            decision = await self._safe_call(hook, method_name, *args)
            if isinstance(decision, Abort):
                raise HookAbortError(decision.reason, type(hook).__name__)
            if isinstance(active, Continue) and not isinstance(decision, Continue):
                active = decision
            elif not isinstance(decision, Continue):
                shadowed.append((type(hook).__name__, decision))
        if shadowed:
            logger.info(
                "Hook decisions shadowed by earlier non-Continue: {s}",
                s=[(name, type(d).__name__) for name, d in shadowed],
            )
        # `Skip` returned from `after_tool` is meaningless — coerce to Continue.
        if method_name == "after_tool" and isinstance(active, Skip):
            logger.warning(
                "Skip returned from after_tool is meaningless (executor already ran); "
                "treating as Continue. reason={r}",
                r=active.reason,
            )
            return CONTINUE
        return active

    async def _safe_call(
        self, hook: ToolHook, method_name: str, *args: Any
    ) -> HookDecision:
        """Invoke a hook method if it exists; coerce return value to a
        :class:`HookDecision`. ``None`` becomes :class:`Continue`. Any
        exception is logged and yields :class:`Continue`."""
        method = getattr(hook, method_name, None)
        if method is None:
            return CONTINUE
        try:
            ret = await method(*args)
        except Exception:
            logger.warning(
                "Hook {hook}.{method} failed; defaulting to Continue",
                hook=type(hook).__name__,
                method=method_name,
            )
            return CONTINUE
        if ret is None:
            return CONTINUE
        if isinstance(ret, _DecisionBase):
            return ret  # type: ignore[return-value]
        logger.warning(
            "Hook {hook}.{method} returned non-decision {t}; treating as Continue",
            hook=type(hook).__name__,
            method=method_name,
            t=type(ret).__name__,
        )
        return CONTINUE
