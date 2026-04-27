"""Tests for the HookDecision protocol upgrade.

Covers the discriminated union (Continue/Skip/Redirect/Abort), the
aggregation rule (first-non-Continue-wins, Abort short-circuits), the
auto-wrapping of legacy None returns, the SafeCall isolation of crashes,
and the integration of decisions into CompoundTool, run_with_retry, and
MetaOrchestrator._execute_subtask.
"""

from __future__ import annotations

import pytest

from orqest.hooks import (
    Abort,
    Continue,
    HookAbortError,
    HookRunner,
    Redirect,
    Skip,
    _DecisionBase,
)


# ---- Discriminated union shape ----------------------------------------


class TestHookDecisionShape:
    def test_continue_no_payload(self):
        c = Continue()
        assert c.kind == "continue"

    def test_skip_requires_reason(self):
        s = Skip(reason="not allowed")
        assert s.kind == "skip"
        assert s.reason == "not allowed"
        assert s.stub_result == ""

    def test_skip_carries_stub_result(self):
        s = Skip(reason="x", stub_result={"y": 1})
        assert s.stub_result == {"y": 1}

    def test_redirect_requires_at_least_one_target(self):
        with pytest.raises(ValueError):
            Redirect()

    def test_redirect_with_args_only(self):
        r = Redirect(new_args={"x": 1})
        assert r.new_tool is None
        assert r.new_args == {"x": 1}

    def test_redirect_with_tool_only(self):
        r = Redirect(new_tool="other")
        assert r.new_args is None
        assert r.new_tool == "other"

    def test_abort_requires_reason(self):
        a = Abort(reason="security")
        assert a.kind == "abort"
        assert a.reason == "security"

    def test_decision_is_frozen(self):
        with pytest.raises(Exception):  # pydantic frozen → ValidationError
            Continue().kind = "skip"  # type: ignore[misc]

    def test_all_decisions_inherit_decision_base(self):
        for d in [Continue(), Skip(reason="x"), Redirect(new_args={"a": 1}), Abort(reason="y")]:
            assert isinstance(d, _DecisionBase)


# ---- Hook fixtures ----------------------------------------------------


class ContinueHook:
    async def before_tool(self, *a):
        return Continue()


class SkipBeforeHook:
    async def before_tool(self, *a):
        return Skip(reason="not allowed", stub_result={"skipped": True})


class RedirectArgsHook:
    async def before_tool(self, tool_name, args, state):
        return Redirect(new_args={"x": "rewritten"}, reason="sanitize")


class RedirectToolHook:
    async def before_tool(self, tool_name, args, state):
        return Redirect(new_tool="other_tool", reason="route")


class AbortHook:
    async def before_tool(self, *a):
        return Abort(reason="security policy")


class CrashyDecisionHook:
    async def before_tool(self, *a):
        raise RuntimeError("hook bug")


class LegacyNoneHook:
    """Hook that returns None — the pre-decision contract."""

    def __init__(self):
        self.called = False

    async def before_tool(self, *a):
        self.called = True
        return None


class BadReturnHook:
    """Hook that returns a non-decision, non-None value."""

    async def before_tool(self, *a):
        return "string-not-allowed"


class AfterRedirectHook:
    async def after_tool(self, *a):
        return Redirect(new_args={"retry_with": "v2"})


class AfterSkipHook:
    """Skip from after_tool is meaningless; HookRunner coerces to Continue."""

    async def after_tool(self, *a):
        return Skip(reason="too late")


# ---- HookRunner aggregation -------------------------------------------


class TestSingleHookDecisions:
    @pytest.mark.asyncio
    async def test_continue_returns_continue(self):
        runner = HookRunner([ContinueHook()])
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Continue)

    @pytest.mark.asyncio
    async def test_skip_passthrough(self):
        runner = HookRunner([SkipBeforeHook()])
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Skip)
        assert d.stub_result == {"skipped": True}

    @pytest.mark.asyncio
    async def test_redirect_args_passthrough(self):
        runner = HookRunner([RedirectArgsHook()])
        d = await runner.run_before("t", {"x": "orig"}, None)
        assert isinstance(d, Redirect)
        assert d.new_args == {"x": "rewritten"}

    @pytest.mark.asyncio
    async def test_abort_raises_hook_abort_error(self):
        runner = HookRunner([AbortHook()])
        with pytest.raises(HookAbortError) as excinfo:
            await runner.run_before("t", {}, None)
        assert "security policy" in str(excinfo.value)
        assert excinfo.value.source_hook == "AbortHook"

    @pytest.mark.asyncio
    async def test_legacy_none_becomes_continue(self):
        hook = LegacyNoneHook()
        runner = HookRunner([hook])
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Continue)
        assert hook.called is True

    @pytest.mark.asyncio
    async def test_crashy_hook_defaults_to_continue(self):
        runner = HookRunner([CrashyDecisionHook()])
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Continue)

    @pytest.mark.asyncio
    async def test_bad_return_value_logs_and_continues(self):
        runner = HookRunner([BadReturnHook()])
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Continue)


class TestMultipleHookAggregation:
    @pytest.mark.asyncio
    async def test_continue_then_skip_skip_wins(self):
        runner = HookRunner([ContinueHook(), SkipBeforeHook()])
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Skip)

    @pytest.mark.asyncio
    async def test_skip_then_redirect_first_wins(self):
        runner = HookRunner([SkipBeforeHook(), RedirectArgsHook()])
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Skip)

    @pytest.mark.asyncio
    async def test_redirect_tool_then_redirect_tool_first_wins(self):
        class RedirectA:
            async def before_tool(self, *a):
                return Redirect(new_tool="A")

        class RedirectB:
            async def before_tool(self, *a):
                return Redirect(new_tool="B")

        runner = HookRunner([RedirectA(), RedirectB()])
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Redirect)
        assert d.new_tool == "A"

    @pytest.mark.asyncio
    async def test_continue_then_abort_short_circuits(self):
        runner = HookRunner([ContinueHook(), AbortHook()])
        with pytest.raises(HookAbortError):
            await runner.run_before("t", {}, None)


class TestAfterToolSemantics:
    @pytest.mark.asyncio
    async def test_after_skip_coerced_to_continue(self):
        runner = HookRunner([AfterSkipHook()])
        d = await runner.run_after("t", {}, "result", None, 1.0)
        assert isinstance(d, Continue)

    @pytest.mark.asyncio
    async def test_after_redirect_passthrough(self):
        runner = HookRunner([AfterRedirectHook()])
        d = await runner.run_after("t", {}, "result", None, 1.0)
        assert isinstance(d, Redirect)
        assert d.new_args == {"retry_with": "v2"}


class TestPartialHookImplementations:
    @pytest.mark.asyncio
    async def test_hook_without_method_is_continue(self):
        class OnlyAfter:
            async def after_tool(self, *a):
                return Skip(reason="post")

        runner = HookRunner([OnlyAfter()])
        # before_tool not implemented → Continue
        d = await runner.run_before("t", {}, None)
        assert isinstance(d, Continue)


# ---- CompoundTool integration -----------------------------------------


class _FakeAgent:
    agent_name = "fake"

    async def run(self, state, **kwargs):
        return {"agent_output": "ok"}


@pytest.mark.asyncio
async def test_compound_tool_skip_returns_stub_result():
    from orqest.agents.compound_tool import CompoundTool

    executor_calls = []

    async def executor(output, state):
        executor_calls.append((output, state))
        return "real-result"

    runner = HookRunner([SkipBeforeHook()])
    tool = CompoundTool(_FakeAgent(), executor, hooks=runner)
    agent_output, result = await tool.run("state", "prompt")
    assert result == {"skipped": True}
    assert executor_calls == []  # executor never invoked


@pytest.mark.asyncio
async def test_compound_tool_redirect_mutates_args_observed():
    """Redirect.new_args is merged into the args observed by after_tool."""
    from orqest.agents.compound_tool import CompoundTool

    seen_after_args: list[dict] = []

    class WatcherHook:
        async def before_tool(self, *a):
            return Redirect(new_args={"injected": "yes"})

        async def after_tool(self, tool_name, args, result, state, duration_ms):
            seen_after_args.append(dict(args))

    async def executor(output, state):
        return "result"

    runner = HookRunner([WatcherHook()])
    tool = CompoundTool(_FakeAgent(), executor, hooks=runner)
    await tool.run("state", "prompt")
    assert seen_after_args
    assert seen_after_args[0].get("injected") == "yes"


@pytest.mark.asyncio
async def test_compound_tool_abort_propagates():
    from orqest.agents.compound_tool import CompoundTool

    async def executor(output, state):
        return "result"

    runner = HookRunner([AbortHook()])
    tool = CompoundTool(_FakeAgent(), executor, hooks=runner)
    with pytest.raises(HookAbortError):
        await tool.run("state", "prompt")


# ---- run_with_retry integration ---------------------------------------


@pytest.mark.asyncio
async def test_run_with_retry_skip_short_circuits():
    from orqest.agents.retry import run_with_retry

    op_calls: list[str] = []

    async def operation(note: str) -> str:
        op_calls.append(note)
        return "done"

    runner = HookRunner([SkipBeforeHook()])
    result = await run_with_retry(
        operation,
        tool_name="t",
        args={},
        state=None,
        hooks=runner,
        note="hello",
    )
    # Skip stub_result is a dict; it's JSON-serialized.
    assert "skipped" in result
    assert op_calls == []


@pytest.mark.asyncio
async def test_run_with_retry_redirect_overrides_note():
    from orqest.agents.retry import run_with_retry

    seen_notes: list[str] = []

    async def operation(note: str) -> str:
        seen_notes.append(note)
        return "ok"

    class RedirectNoteHook:
        async def before_tool(self, *a):
            return Redirect(new_args={"note": "REWRITTEN"})

    runner = HookRunner([RedirectNoteHook()])
    result = await run_with_retry(
        operation,
        tool_name="t",
        args={},
        state=None,
        hooks=runner,
        note="ORIGINAL",
    )
    assert result == "ok"
    assert seen_notes == ["REWRITTEN"]


@pytest.mark.asyncio
async def test_run_with_retry_abort_propagates():
    from orqest.agents.retry import run_with_retry

    async def operation(note: str) -> str:
        return "ok"

    runner = HookRunner([AbortHook()])
    with pytest.raises(HookAbortError):
        await run_with_retry(
            operation,
            tool_name="t",
            args={},
            state=None,
            hooks=runner,
            note="hello",
        )
