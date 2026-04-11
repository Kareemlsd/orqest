"""Tests for the HookRunner and ToolHook protocol."""

import pytest

from orqest.hooks import HookRunner, ToolHook


# --- Hook implementations for testing ---


class FullHook:
    """Hook that records all calls."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def before_tool(self, tool_name, args, state):
        self.calls.append(("before_tool", {"tool_name": tool_name, "args": args}))

    async def after_tool(self, tool_name, args, result, state, duration_ms):
        self.calls.append((
            "after_tool",
            {"tool_name": tool_name, "result": result, "duration_ms": duration_ms},
        ))

    async def on_error(self, tool_name, args, error, state):
        self.calls.append(("on_error", {"tool_name": tool_name, "error": error}))


class BeforeOnlyHook:
    """Hook that only implements before_tool."""

    def __init__(self):
        self.called = False

    async def before_tool(self, tool_name, args, state):
        self.called = True


class ExplodingHook:
    """Hook that raises on every method."""

    async def before_tool(self, tool_name, args, state):
        raise RuntimeError("boom in before_tool")

    async def after_tool(self, tool_name, args, result, state, duration_ms):
        raise RuntimeError("boom in after_tool")

    async def on_error(self, tool_name, args, error, state):
        raise RuntimeError("boom in on_error")


# --- Tests ---


class TestHookRunnerEmpty:
    """HookRunner with no hooks should not error."""

    @pytest.mark.asyncio
    async def test_fire_before_no_hooks(self):
        runner = HookRunner()
        await runner.fire_before("tool", {}, None)

    @pytest.mark.asyncio
    async def test_fire_after_no_hooks(self):
        runner = HookRunner()
        await runner.fire_after("tool", {}, "result", None, 100.0)

    @pytest.mark.asyncio
    async def test_fire_error_no_hooks(self):
        runner = HookRunner()
        await runner.fire_error("tool", {}, RuntimeError("err"), None)


class TestHookRunnerDispatches:
    """Verify hooks receive correct arguments."""

    @pytest.mark.asyncio
    async def test_before_tool_fires(self):
        hook = FullHook()
        runner = HookRunner([hook])
        await runner.fire_before("my_tool", {"k": "v"}, "state")
        assert len(hook.calls) == 1
        assert hook.calls[0][0] == "before_tool"
        assert hook.calls[0][1]["tool_name"] == "my_tool"

    @pytest.mark.asyncio
    async def test_after_tool_fires_with_duration(self):
        hook = FullHook()
        runner = HookRunner([hook])
        await runner.fire_after("my_tool", {}, "result_val", "state", 42.5)
        assert len(hook.calls) == 1
        assert hook.calls[0][0] == "after_tool"
        assert hook.calls[0][1]["duration_ms"] == 42.5
        assert hook.calls[0][1]["result"] == "result_val"

    @pytest.mark.asyncio
    async def test_on_error_fires_with_exception(self):
        hook = FullHook()
        runner = HookRunner([hook])
        exc = ValueError("test error")
        await runner.fire_error("my_tool", {}, exc, "state")
        assert len(hook.calls) == 1
        assert hook.calls[0][0] == "on_error"
        assert hook.calls[0][1]["error"] is exc


class TestHookRunnerErrorHandling:
    """Hook errors are logged but never propagated."""

    @pytest.mark.asyncio
    async def test_exploding_hook_does_not_propagate(self):
        runner = HookRunner([ExplodingHook()])
        await runner.fire_before("tool", {}, None)
        await runner.fire_after("tool", {}, "r", None, 1.0)
        await runner.fire_error("tool", {}, RuntimeError("x"), None)


class TestHookRunnerPartialHook:
    """Hook with only some methods implemented."""

    @pytest.mark.asyncio
    async def test_before_only_hook_skips_after(self):
        hook = BeforeOnlyHook()
        runner = HookRunner([hook])
        await runner.fire_before("tool", {}, None)
        assert hook.called is True
        # after_tool and on_error should not error
        await runner.fire_after("tool", {}, "r", None, 1.0)
        await runner.fire_error("tool", {}, RuntimeError("x"), None)


class TestHookRunnerMultiple:
    """Multiple hooks are all called in order."""

    @pytest.mark.asyncio
    async def test_all_hooks_called_in_order(self):
        hook_a = FullHook()
        hook_b = FullHook()
        runner = HookRunner([hook_a, hook_b])
        await runner.fire_before("tool", {}, None)
        assert len(hook_a.calls) == 1
        assert len(hook_b.calls) == 1


class TestToolHookProtocol:
    """ToolHook is a runtime-checkable protocol."""

    def test_full_hook_is_tool_hook(self):
        assert isinstance(FullHook(), ToolHook)

    def test_before_only_is_not_full_tool_hook(self):
        """Partial hooks don't satisfy the full protocol but work with HookRunner."""
        assert not isinstance(BeforeOnlyHook(), ToolHook)
