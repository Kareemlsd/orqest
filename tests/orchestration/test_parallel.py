"""Tests for Parallel orchestration primitive."""
import asyncio
import time

import pytest

from orqest.orchestration.parallel import MergeStrategy, Parallel, ParallelResult


# --- Helpers ---


async def _double(x: int) -> int:
    """Return input doubled."""
    return x * 2


async def _triple(x: int) -> int:
    """Return input tripled."""
    return x * 3


async def _add_ten(x: int) -> int:
    """Return input plus ten."""
    return x + 10


async def _slow_step(x: int) -> int:
    """Sleep long enough to trigger a timeout."""
    await asyncio.sleep(5)
    return x


async def _failing_step(_: int) -> int:
    """Always raises."""
    raise RuntimeError("intentional failure")


async def _short_sleep(x: int) -> int:
    """Sleep briefly then return input."""
    await asyncio.sleep(0.1)
    return x


class TestParallelValidation:
    """Constructor validation."""

    def test_empty_steps_raises_value_error(self) -> None:
        """Empty steps list is rejected at construction time."""
        with pytest.raises(ValueError, match="at least one step"):
            Parallel(steps=[])


class TestParallelExecution:
    """Core execution behavior."""

    @pytest.mark.asyncio
    async def test_all_succeed(self) -> None:
        """Three steps all succeed and collect_all returns list of three."""
        p = Parallel(steps=[_double, _triple, _add_ten])
        result = await p.run(5)

        assert isinstance(result, ParallelResult)
        assert result.outputs == [10, 15, 15]
        assert result.errors == [None, None, None]
        assert result.merged == [10, 15, 15]

    @pytest.mark.asyncio
    async def test_timeout_cancels_slow_step(self) -> None:
        """A slow step gets a TimeoutError while fast steps succeed."""
        p = Parallel(steps=[_double, _slow_step], timeout=0.2)
        result = await p.run(3)

        assert result.outputs[0] == 6
        assert result.outputs[1] is None
        assert result.errors[0] is None
        assert isinstance(result.errors[1], TimeoutError)

    @pytest.mark.asyncio
    async def test_one_failure_captured(self) -> None:
        """A failing step records its exception; others succeed."""
        p = Parallel(steps=[_double, _failing_step, _triple])
        result = await p.run(4)

        assert result.outputs[0] == 8
        assert result.outputs[1] is None
        assert result.outputs[2] == 12
        assert result.errors[0] is None
        assert isinstance(result.errors[1], RuntimeError)
        assert result.errors[2] is None
        assert result.merged == [8, 12]

    @pytest.mark.asyncio
    async def test_custom_merge_first_wins(self) -> None:
        """first_wins merge returns only the first successful output."""
        p = Parallel(
            steps=[_double, _triple],
            merge=MergeStrategy.first_wins,
        )
        result = await p.run(7)

        assert result.merged == 14

    @pytest.mark.asyncio
    async def test_all_fail_merge_receives_empty(self) -> None:
        """When every step fails, merge receives an empty list."""
        p = Parallel(steps=[_failing_step, _failing_step])
        result = await p.run(1)

        assert all(o is None for o in result.outputs)
        assert all(isinstance(e, RuntimeError) for e in result.errors)
        assert result.merged == []

    @pytest.mark.asyncio
    async def test_concurrent_execution_timing(self) -> None:
        """Two 0.1s steps complete in roughly 0.1s, not 0.2s."""
        p = Parallel(steps=[_short_sleep, _short_sleep])

        start = time.monotonic()
        result = await p.run(42)
        elapsed = time.monotonic() - start

        assert result.outputs == [42, 42]
        assert elapsed < 0.18, f"Expected ~0.1s, got {elapsed:.3f}s"
