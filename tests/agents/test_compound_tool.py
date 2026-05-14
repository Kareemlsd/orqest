"""Tests for CompoundTool pattern."""

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.compound_tool import CompoundTool
from orqest.agents.state import GlobalState
from orqest.hooks import HookRunner, Redirect


# --- Helpers ---


class SimpleOutput(BaseModel):
    text: str


class StubAgent(BaseAgent[GlobalState, SimpleOutput]):
    """Agent that returns a fixed output."""

    async def _run_implementation(self, state, **kwargs):
        result = await self.call_model("test", state)
        return result.output


class RecordingHook:
    """Hook that records calls for assertion."""

    def __init__(self):
        self.events: list[str] = []

    async def before_tool(self, tool_name, args, state):
        self.events.append("before")

    async def after_tool(self, tool_name, args, result, state, duration_ms):
        self.events.append("after")

    async def on_error(self, tool_name, args, error, state):
        self.events.append("error")


# --- Tests ---


class TestCompoundToolBasic:
    """Core compound tool behavior."""

    @pytest.mark.asyncio
    async def test_basic_flow(self, test_model):
        agent = StubAgent(
            agent_name="stub",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )

        async def executor(output, state):
            return f"executed:{output.text}"

        tool = CompoundTool(agent, executor)
        state = GlobalState()
        state.add_message("user", "go")
        agent_output, result = await tool.run(state, prompt="go")
        assert isinstance(agent_output, SimpleOutput)
        assert "executed:" in result

    @pytest.mark.asyncio
    async def test_name_defaults_to_agent_name(self, test_model):
        agent = StubAgent(
            agent_name="my_agent",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )

        async def executor(output, state):
            return None

        tool = CompoundTool(agent, executor)
        assert tool.name == "my_agent"

    @pytest.mark.asyncio
    async def test_custom_name(self, test_model):
        agent = StubAgent(
            agent_name="stub",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )

        async def executor(output, state):
            return None

        tool = CompoundTool(agent, executor, name="custom_name")
        assert tool.name == "custom_name"


class TestCompoundToolHooks:
    """Hooks fire before and after execution."""

    @pytest.mark.asyncio
    async def test_hooks_fire_before_and_after(self, test_model):
        agent = StubAgent(
            agent_name="stub",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )
        hook = RecordingHook()

        async def executor(output, state):
            return "ok"

        tool = CompoundTool(agent, executor, hooks=HookRunner([hook]))
        state = GlobalState()
        state.add_message("user", "go")
        await tool.run(state, prompt="go")
        assert hook.events == ["before", "after"]

    @pytest.mark.asyncio
    async def test_error_hook_fires_on_executor_failure(self, test_model):
        agent = StubAgent(
            agent_name="stub",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )
        hook = RecordingHook()

        async def failing_executor(output, state):
            raise RuntimeError("executor failed")

        tool = CompoundTool(agent, failing_executor, hooks=HookRunner([hook]))
        state = GlobalState()
        state.add_message("user", "go")
        with pytest.raises(RuntimeError, match="executor failed"):
            await tool.run(state, prompt="go")
        assert "before" in hook.events
        assert "error" in hook.events
        assert "after" not in hook.events


class TestCompoundToolStateUpdater:
    """State updater behavior."""

    @pytest.mark.asyncio
    async def test_state_updater_called(self, test_model):
        agent = StubAgent(
            agent_name="stub",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )
        updated = []

        def updater(state, result):
            updated.append(result)
            return state

        async def executor(output, state):
            return "result_value"

        tool = CompoundTool(agent, executor, state_updater=updater)
        state = GlobalState()
        state.add_message("user", "go")
        await tool.run(state, prompt="go")
        assert updated == ["result_value"]

    @pytest.mark.asyncio
    async def test_no_state_updater(self, test_model):
        agent = StubAgent(
            agent_name="stub",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )

        async def executor(output, state):
            return "ok"

        tool = CompoundTool(agent, executor)
        state = GlobalState()
        state.add_message("user", "go")
        agent_output, result = await tool.run(state, prompt="go")
        assert result == "ok"


class TestCompoundToolOnErrorRedirect:
    """on_error hooks can issue a Redirect for a bounded executor retry."""

    @pytest.mark.asyncio
    async def test_on_error_redirect_retries_executor(self, test_model):
        """A Redirect from on_error retries the executor once (the
        DiscoveryHook recovery path)."""
        agent = StubAgent(
            agent_name="stub",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )
        calls = {"n": 0}

        async def executor(output, state):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("tool not found")
            return "recovered"

        class RedirectOnError:
            async def on_error(self, tool_name, args, error, state):
                return Redirect(new_tool=tool_name, reason="discovered via MCP")

        tool = CompoundTool(agent, executor, hooks=HookRunner([RedirectOnError()]))
        state = GlobalState()
        state.add_message("user", "go")
        agent_output, result = await tool.run(state, prompt="go")
        assert result == "recovered"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_on_error_continue_reraises_original(self, test_model):
        """Without a Redirect, a failed executor still propagates."""
        agent = StubAgent(
            agent_name="stub",
            system_prompt="test",
            output_type=SimpleOutput,
            model=test_model,
        )

        async def executor(output, state):
            raise RuntimeError("boom")

        tool = CompoundTool(agent, executor)
        state = GlobalState()
        state.add_message("user", "go")
        with pytest.raises(RuntimeError, match="boom"):
            await tool.run(state, prompt="go")
