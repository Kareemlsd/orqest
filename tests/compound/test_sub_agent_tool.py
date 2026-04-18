"""Tests for SubAgentTool — first-pass, refinement, best-effort semantics."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from orqest.compound import SubAgentTool
from orqest.compound.sub_agent_tool import EvalResult


# --- fixtures ---


class _State:
    """Simple mutable state container for tests."""

    def __init__(self) -> None:
        self.history: list[str] = []
        self.final: str = ""


class _Output(BaseModel):
    note_seen: str


class _FakeAgent:
    agent_name = "fake_agent"

    def __init__(self, outputs: list[_Output]):
        self.outputs = outputs
        self.calls: list[dict] = []

    async def run(self, state: _State, **kwargs) -> _Output:
        self.calls.append(dict(kwargs))
        return self.outputs.pop(0)


def _executor_factory(results: list[str]):
    idx = {"i": 0}

    async def exec_(agent_output: _Output, state: _State) -> str:
        r = results[idx["i"]]
        idx["i"] += 1
        return r

    return exec_


def _updater(result: str, state: _State) -> None:
    state.history.append(result)
    state.final = result


# --- first-pass ---


class TestFirstPass:
    @pytest.mark.asyncio
    async def test_runs_agent_executor_updater_in_order(self):
        agent = _FakeAgent(outputs=[_Output(note_seen="initial")])
        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory(["RESULT"]),
            state_updater=_updater,
        )
        state = _State()

        out = await tool.run(state, "initial")

        assert out.result == "RESULT"
        assert out.iterations == 1
        assert out.refined is False
        assert out.exit_reason == "passed"
        assert state.final == "RESULT"
        assert state.history == ["RESULT"]
        # The agent received "note" = prompt
        assert agent.calls[0]["note"] == "initial"

    @pytest.mark.asyncio
    async def test_caller_kwargs_override_default_note(self):
        agent = _FakeAgent(outputs=[_Output(note_seen="x")])
        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory(["r"]),
            state_updater=_updater,
        )
        state = _State()
        await tool.run(state, "default", note="override", extra="k")

        assert agent.calls[0]["note"] == "override"
        assert agent.calls[0]["extra"] == "k"

    @pytest.mark.asyncio
    async def test_tool_name_defaults_to_agent_name(self):
        agent = _FakeAgent(outputs=[_Output(note_seen="x")])
        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory(["r"]),
            state_updater=_updater,
        )
        assert tool.name == "fake_agent"

    @pytest.mark.asyncio
    async def test_explicit_name_wins(self):
        agent = _FakeAgent(outputs=[_Output(note_seen="x")])
        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory(["r"]),
            state_updater=_updater,
            name="custom",
        )
        assert tool.name == "custom"


# --- refinement ---


class TestRefinement:
    @pytest.mark.asyncio
    async def test_refines_when_evaluator_fails(self):
        agent = _FakeAgent(
            outputs=[_Output(note_seen="a"), _Output(note_seen="b")]
        )
        passes = iter([False, True])  # fail first, pass second

        def evaluator(result: str) -> EvalResult:
            return EvalResult(passed=next(passes))

        def build_refine(result: str, prompt: str) -> str:
            return f"REFINED({prompt}) because of {result}"

        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory(["bad", "good"]),
            state_updater=_updater,
            evaluator=evaluator,
            max_refinements=1,
            build_refinement_prompt=build_refine,
        )

        state = _State()
        out = await tool.run(state, "start")

        assert out.result == "good"
        assert out.iterations == 2
        assert out.refined is True
        assert out.exit_reason == "passed"
        # State went through both results (best-effort commit before refine)
        assert state.history == ["bad", "good"]
        # Second call carried the refined note
        assert "REFINED(start)" in agent.calls[1]["note"]

    @pytest.mark.asyncio
    async def test_first_pass_passes_no_refinement(self):
        agent = _FakeAgent(outputs=[_Output(note_seen="a")])

        def evaluator(result: str) -> EvalResult:
            return EvalResult(passed=True)

        def build_refine(result: str, prompt: str) -> str:
            pytest.fail("should not be called")

        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory(["good"]),
            state_updater=_updater,
            evaluator=evaluator,
            max_refinements=3,
            build_refinement_prompt=build_refine,
        )
        state = _State()
        out = await tool.run(state, "start")

        assert out.result == "good"
        assert out.iterations == 1
        assert out.refined is False

    @pytest.mark.asyncio
    async def test_hits_max_refinements(self):
        agent = _FakeAgent(
            outputs=[
                _Output(note_seen="a"),
                _Output(note_seen="b"),
                _Output(note_seen="c"),
            ]
        )

        def evaluator(_result: str) -> EvalResult:
            return EvalResult(passed=False)  # always fail

        def build_refine(result: str, prompt: str) -> str:
            return f"refine-{result}"

        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory(["r1", "r2", "r3"]),
            state_updater=_updater,
            evaluator=evaluator,
            max_refinements=2,
            build_refinement_prompt=build_refine,
        )
        state = _State()
        out = await tool.run(state, "start")

        # 1 initial + 2 refinements = 3 iterations
        assert out.iterations == 3
        assert out.refined is True
        assert out.exit_reason == "max_refinements"
        assert state.history == ["r1", "r2", "r3"]

    @pytest.mark.asyncio
    async def test_refinement_exception_keeps_original(self):
        agent = AsyncMock()
        agent.agent_name = "brittle"
        agent.run = AsyncMock(
            side_effect=[
                _Output(note_seen="first"),  # initial pass
                RuntimeError("sub-agent failed on refinement"),  # refinement blows up
            ]
        )

        def evaluator(_result: str) -> EvalResult:
            return EvalResult(passed=False)

        def build_refine(result: str, prompt: str) -> str:
            return "r"

        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory(["first_result"]),
            state_updater=_updater,
            evaluator=evaluator,
            max_refinements=2,
            build_refinement_prompt=build_refine,
        )
        state = _State()
        out = await tool.run(state, "start")

        assert out.result == "first_result"
        assert out.iterations == 1
        assert out.exit_reason == "refinement_failed_keep_original"


# --- validation ---


class TestValidation:
    def test_max_refinements_without_evaluator_raises(self):
        agent = _FakeAgent(outputs=[])
        with pytest.raises(ValueError, match="evaluator"):
            SubAgentTool(
                agent=agent,
                executor=_executor_factory([]),
                state_updater=_updater,
                max_refinements=1,
                build_refinement_prompt=lambda r, p: p,
            )

    def test_max_refinements_without_prompt_builder_raises(self):
        agent = _FakeAgent(outputs=[])
        with pytest.raises(ValueError, match="build_refinement_prompt"):
            SubAgentTool(
                agent=agent,
                executor=_executor_factory([]),
                state_updater=_updater,
                evaluator=lambda r: EvalResult(passed=True),
                max_refinements=1,
            )

    def test_max_refinements_zero_needs_neither(self):
        agent = _FakeAgent(outputs=[])
        # Should not raise
        tool = SubAgentTool(
            agent=agent,
            executor=_executor_factory([]),
            state_updater=_updater,
        )
        assert tool._max_refinements == 0
