"""Tests for EventBusPublishHook."""

from __future__ import annotations

import pytest

from orqest.hooks import HookRunner
from orqest.observability import AgentEvent, EventBus, EventBusPublishHook


class _RecordingSubscriber:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)


@pytest.fixture()
def bus_and_sub() -> tuple[EventBus, _RecordingSubscriber]:
    bus = EventBus()
    sub = _RecordingSubscriber()
    bus.subscribe_all(sub)
    return bus, sub


@pytest.fixture()
def runner_with_hook(bus_and_sub) -> tuple[HookRunner, _RecordingSubscriber]:
    bus, sub = bus_and_sub
    hook = EventBusPublishHook(bus, agent_name="orchestrator")
    return HookRunner([hook]), sub


class TestLifecycleEmission:
    @pytest.mark.asyncio
    async def test_before_tool_emits(self, runner_with_hook):
        runner, sub = runner_with_hook
        await runner.run_before("generate_mesh", {"note": "plate"}, None)

        assert len(sub.events) == 1
        ev = sub.events[0]
        assert ev.event_type == "tool.before"
        assert ev.agent_name == "orchestrator"
        assert ev.data["tool_name"] == "generate_mesh"
        assert ev.data["args"] == {"note": "plate"}

    @pytest.mark.asyncio
    async def test_after_tool_emits_with_duration_and_preview(
        self, runner_with_hook
    ):
        runner, sub = runner_with_hook
        await runner.run_after(
            "generate_mesh",
            {"note": "plate"},
            result='{"success": true}',
            state=None,
            duration_ms=42.5,
        )

        assert len(sub.events) == 1
        ev = sub.events[0]
        assert ev.event_type == "tool.after"
        assert ev.data["duration_ms"] == 42.5
        assert ev.data["result_preview"] == '{"success": true}'
        assert ev.data["result_len"] == len('{"success": true}')

    @pytest.mark.asyncio
    async def test_on_error_emits_error_metadata(self, runner_with_hook):
        runner, sub = runner_with_hook
        await runner.run_error(
            "run_simulation",
            {"note": "solve"},
            ValueError("bad BC"),
            state=None,
        )

        assert len(sub.events) == 1
        ev = sub.events[0]
        assert ev.event_type == "tool.error"
        assert ev.data["error_type"] == "ValueError"
        assert ev.data["error_message"] == "bad BC"


class TestPayloadTruncation:
    @pytest.mark.asyncio
    async def test_long_result_is_truncated(self, bus_and_sub):
        bus, sub = bus_and_sub
        hook = EventBusPublishHook(bus, agent_name="x", result_preview_chars=32)
        runner = HookRunner([hook])

        big = "x" * 1000
        await runner.run_after("tool", {}, big, None, 1.0)

        ev = sub.events[0]
        preview = ev.data["result_preview"]
        assert preview.endswith("...")
        # 32 chars of content + "..." suffix
        assert len(preview) == 35
        # full length is still reported accurately
        assert ev.data["result_len"] == 1000

    @pytest.mark.asyncio
    async def test_long_string_args_are_summarized(self, runner_with_hook):
        runner, sub = runner_with_hook
        await runner.run_before("t", {"note": "y" * 500}, None)

        summarized = sub.events[0].data["args"]["note"]
        assert summarized.endswith("...")
        assert len(summarized) == 123  # 120 chars + "..."


class TestStateIntrospection:
    @pytest.mark.asyncio
    async def test_session_and_project_ids_attached(self, runner_with_hook):
        runner, sub = runner_with_hook

        class State:
            session_id = "sess-1"
            project_id = "proj-1"

        await runner.run_before("t", {}, State())
        ev = sub.events[0]
        assert ev.data["session_id"] == "sess-1"
        assert ev.data["project_id"] == "proj-1"

    @pytest.mark.asyncio
    async def test_missing_state_attrs_are_omitted_not_errored(
        self, runner_with_hook
    ):
        runner, sub = runner_with_hook
        await runner.run_before("t", {}, None)  # bare None state
        ev = sub.events[0]
        assert "session_id" not in ev.data
        assert "project_id" not in ev.data


class TestHandlerIsolation:
    """Hook errors in the bus publisher must not propagate to the runner."""

    @pytest.mark.asyncio
    async def test_exploding_subscriber_does_not_break_tool_flow(self):
        bus = EventBus()

        def boom(_event: AgentEvent) -> None:
            raise RuntimeError("subscriber broken")

        bus.subscribe_all(boom)
        hook = EventBusPublishHook(bus, agent_name="x")
        runner = HookRunner([hook])

        # Must not raise — EventBus swallows handler errors.
        await runner.run_before("t", {}, None)
        await runner.run_after("t", {}, "r", None, 1.0)
