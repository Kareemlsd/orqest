"""Tests for run_with_retry helper."""

import json

import pytest

from orqest.agents.retry import run_with_retry
from orqest.hooks import HookRunner


class RecordingHook:
    def __init__(self):
        self.events: list[tuple[str, tuple]] = []

    async def before_tool(self, tool_name, args, state):
        self.events.append(("before", (tool_name, args, state)))

    async def after_tool(self, tool_name, args, result, state, duration_ms):
        self.events.append(("after", (tool_name, args, result, state)))

    async def on_error(self, tool_name, args, error, state):
        self.events.append(("error", (tool_name, args, error, state)))


async def _noop_before():
    """Reused state object for tests."""
    return "state-value"


@pytest.fixture()
def hook() -> RecordingHook:
    return RecordingHook()


@pytest.fixture()
def runner(hook: RecordingHook) -> HookRunner:
    return HookRunner([hook])


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_single_attempt_succeeds(
        self, hook: RecordingHook, runner: HookRunner
    ) -> None:
        calls: list[str] = []

        async def op(note: str) -> str:
            calls.append(note)
            return '{"success": true}'

        result = await run_with_retry(
            op,
            tool_name="tool",
            args={"note": "hello"},
            state="state",
            hooks=runner,
            note="hello",
        )

        assert result == '{"success": true}'
        assert calls == ["hello"]
        assert [e[0] for e in hook.events] == ["before", "after"]

    @pytest.mark.asyncio
    async def test_hooks_fire_before_and_after(
        self, hook: RecordingHook, runner: HookRunner
    ) -> None:
        async def op(_note: str) -> str:
            return "ok"

        await run_with_retry(
            op,
            tool_name="my_tool",
            args={"k": "v"},
            state={"session": "s1"},
            hooks=runner,
            note="hi",
        )

        assert hook.events[0][0] == "before"
        assert hook.events[0][1] == ("my_tool", {"k": "v"}, {"session": "s1"})
        assert hook.events[1][0] == "after"
        assert hook.events[1][1] == ("my_tool", {"k": "v"}, "ok", {"session": "s1"})


class TestRetry:
    @pytest.mark.asyncio
    async def test_retries_on_failure(self, runner: HookRunner) -> None:
        attempts: list[str] = []

        async def op(note: str) -> str:
            attempts.append(note)
            if len(attempts) < 2:
                raise RuntimeError("transient")
            return '{"success": true}'

        result = await run_with_retry(
            op,
            tool_name="t",
            args={},
            state=None,
            hooks=runner,
            note="orig",
        )

        assert result == '{"success": true}'
        assert len(attempts) == 2
        assert attempts[0] == "orig"
        assert "PREVIOUS ATTEMPT FAILED" in attempts[1]
        assert "transient" in attempts[1]

    @pytest.mark.asyncio
    async def test_exhaustion_returns_failure_payload(
        self, hook: RecordingHook, runner: HookRunner
    ) -> None:
        async def op(_note: str) -> str:
            raise RuntimeError("always broken")

        result = await run_with_retry(
            op,
            tool_name="t",
            args={},
            state=None,
            hooks=runner,
            note="orig",
            max_attempts=3,
        )

        payload = json.loads(result)
        assert payload == {
            "success": False,
            "error": "always broken",
            "attempts": 3,
        }
        # still fires after (not error) since we returned a payload cleanly
        assert [e[0] for e in hook.events] == ["before", "after"]

    @pytest.mark.asyncio
    async def test_non_retryable_breaks_early(self, runner: HookRunner) -> None:
        attempts: list[str] = []

        async def op(note: str) -> str:
            attempts.append(note)
            raise ValueError("permanent")

        def is_retryable(exc: Exception) -> bool:
            return not isinstance(exc, ValueError)

        result = await run_with_retry(
            op,
            tool_name="t",
            args={},
            state=None,
            hooks=runner,
            note="orig",
            max_attempts=5,
            is_retryable=is_retryable,
        )

        assert json.loads(result)["attempts"] == 1
        assert len(attempts) == 1


class TestEnrichment:
    @pytest.mark.asyncio
    async def test_custom_enrich_builds_next_note(self, runner: HookRunner) -> None:
        attempts: list[str] = []

        async def op(note: str) -> str:
            attempts.append(note)
            if len(attempts) < 2:
                raise RuntimeError("boom")
            return "ok"

        def enrich(original: str, err: str) -> str:
            return f"RETRY[{err}]::{original}"

        await run_with_retry(
            op,
            tool_name="t",
            args={},
            state=None,
            hooks=runner,
            note="hello",
            enrich_note=enrich,
        )

        assert attempts == ["hello", "RETRY[boom]::hello"]

    @pytest.mark.asyncio
    async def test_default_enrich_preserves_original(self, runner: HookRunner) -> None:
        attempts: list[str] = []

        async def op(note: str) -> str:
            attempts.append(note)
            if len(attempts) < 2:
                raise RuntimeError("err!")
            return "ok"

        await run_with_retry(
            op,
            tool_name="t",
            args={},
            state=None,
            hooks=runner,
            note="original prompt",
        )

        assert "original prompt" in attempts[1]
        assert "err!" in attempts[1]


class TestHookIsolation:
    """Operation failures don't fire run_error — they surface as failure payloads."""

    @pytest.mark.asyncio
    async def test_run_error_not_fired_on_operation_failure(
        self, hook: RecordingHook, runner: HookRunner
    ) -> None:
        async def op(_note: str) -> str:
            raise RuntimeError("bad")

        await run_with_retry(
            op,
            tool_name="t",
            args={},
            state=None,
            hooks=runner,
            note="n",
        )

        assert "error" not in [e[0] for e in hook.events]
