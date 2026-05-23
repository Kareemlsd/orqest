"""Sub-agent roster — register / invoke / list, plus the spawn_analyst
back-compat shim. Backed by procedural memory after the Phase α
consolidation (see ``.claude/POLYMATH_ASSESSMENT_2026-04-25.md`` §2).

The real model is never hit. Instead we monkeypatch the factory builder
to return a stub :class:`DynamicAgent` whose ``run_enriched()`` returns
a predictable :class:`EnrichedOutput`. The goal is to verify:

* persistence — registering writes a procedural :class:`MemoryEntry`
  and re-registering updates the same entry in place
* invocation — the persisted spec round-trips into a live agent and
  ``run_enriched`` is used so metacognition fields propagate
* lifecycle events — agent.spawned / agent.completed / agent.registered
* error routing — exceptions become JSON `error` fields, not crashes
"""

from __future__ import annotations

import json
import types
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel

from orqest.memory import MemoryFilter
from orqest.metacognition import EnrichedOutput

from polymath import runtime as runtime_mod
from polymath.autonomy.analyst import (
    build_analyst_registry,
    build_analyst_spec,
)
from polymath.db.models import Session
from polymath.db.session import get_sessionmaker
from polymath.state import PolymathState
from polymath.tools.autonomy import (
    _invoke_agent,
    _list_agents,
    _recall_sub_agent,
    _register_agent,
    _spawn_analyst,
)


class _Output(BaseModel):
    summary: str
    findings: list[str]
    next_steps: list[str] = []
    self_confidence: float | None = None
    uncertain_about: list[str] = []
    outside_my_capability: bool = False


class _StubAgent:
    """Stub :class:`DynamicAgent` honoring the metacognition contract.

    ``run_enriched`` returns an :class:`EnrichedOutput` populated from
    the structured ``self_confidence`` / ``uncertain_about`` /
    ``outside_my_capability`` fields on the underlying ``OutputT``.
    """

    def __init__(self, output: _Output, *, raises: Exception | None = None) -> None:
        self._output = output
        self._raises = raises
        self.last_state: Any = None
        # Mirror BaseAgent ctor — `_invoke_agent` mutates this attribute
        # to inject `StructuredOutputProtocol` after spawn.
        self._confidence_protocol: Any = None

    async def run_enriched(self, state: Any, **_: Any) -> EnrichedOutput:
        self.last_state = state
        if self._raises is not None:
            raise self._raises
        return EnrichedOutput(
            output=self._output,
            confidence=self._output.self_confidence,
            uncertainty_targets=list(self._output.uncertain_about),
            capability_boundary=self._output.outside_my_capability,
            protocol_name="structured",
        )

    async def run(self, state: Any, **_: Any) -> _Output:
        # Kept for completeness; production code should use run_enriched.
        self.last_state = state
        if self._raises is not None:
            raise self._raises
        return self._output


class _StubFactory:
    def __init__(self, agent: _StubAgent) -> None:
        self._agent = agent
        self.last_spec: Any = None

    def spawn(self, spec: Any, **_: Any) -> _StubAgent:
        self.last_spec = spec
        return self._agent


@pytest.fixture
def _stub_factory(monkeypatch: pytest.MonkeyPatch) -> _StubFactory:
    output = _Output(
        summary="The vector DB landscape is fragmented.",
        findings=["pgvector wins on integration", "milvus wins on scale"],
        next_steps=["benchmark recall on real data"],
        self_confidence=0.72,
        uncertain_about=["recall numbers on >10M vectors"],
    )
    factory = _StubFactory(_StubAgent(output))
    from polymath.tools import autonomy as autonomy_module
    monkeypatch.setattr(autonomy_module, "_build_factory", lambda: factory)
    return factory


async def _seed_session() -> str:
    sm = get_sessionmaker()
    sid = uuid4()
    async with sm() as db:
        db.add(Session(id=sid, title="t"))
        await db.commit()
    return str(sid)


def _ctx(sid: str) -> Any:
    return types.SimpleNamespace(deps=PolymathState(session_id=sid))


async def _list_procedural(sid: str) -> list[Any]:
    """Return all procedural memory entries for *sid* — test helper."""
    workbench = runtime_mod.get_runtime(sid).workbench
    return await workbench.memory.recall(
        query="",
        k=50,
        filters=MemoryFilter(memory_type="procedural"),
    )


# ---- spec / registry shape -------------------------------------------


def test_build_analyst_spec_shape() -> None:
    spec = build_analyst_spec(goal="benchmark vector DBs")
    assert spec.name == "analyst"
    assert spec.metadata["goal"] == "benchmark vector DBs"
    assert {t.name for t in spec.tools} == {"web_search", "web_fetch"}
    props = spec.output_schema["properties"]
    assert {"summary", "findings", "next_steps"} <= set(props)
    # Phase α: optional metacognition fields are present (not required).
    assert {"self_confidence", "uncertain_about", "outside_my_capability"} <= set(props)
    assert "self_confidence" not in spec.output_schema.get("required", [])


def test_build_analyst_registry_has_web_tools() -> None:
    reg = build_analyst_registry()
    assert "web_search" in reg
    assert "web_fetch" in reg


# ---- register_agent ---------------------------------------------------


@pytest.mark.asyncio
async def test_register_agent_persists_entry() -> None:
    sid = await _seed_session()
    result = json.loads(
        await _register_agent(
            _ctx(sid),
            name="analyst",
            role="structured-output specialist",
            system_prompt="Be concise.",
            tools=["web_search"],
        )
    )
    assert result == {
        "ok": True,
        "action": "registered",
        "name": "analyst",
        "role": "structured-output specialist",
        "tools": ["web_search"],
    }
    entries = await _list_procedural(sid)
    assert len(entries) == 1
    assert entries[0].content == "analyst"
    skill_payload = entries[0].structured_content
    assert skill_payload is not None
    assert skill_payload["name"] == "analyst"
    assert skill_payload["trigger"] == "analyst"
    spec_payload = entries[0].metadata["agent_spec"]
    assert spec_payload["system_prompt"] == "Be concise."


@pytest.mark.asyncio
async def test_register_agent_idempotent_update() -> None:
    sid = await _seed_session()
    await _register_agent(
        _ctx(sid), name="writer", role="report writer",
        system_prompt="v1",
    )
    second = json.loads(
        await _register_agent(
            _ctx(sid), name="writer", role="senior report writer",
            system_prompt="v2",
        )
    )
    assert second["action"] == "updated"
    entries = await _list_procedural(sid)
    assert len(entries) == 1
    assert entries[0].metadata["role"] == "senior report writer"
    assert entries[0].metadata["agent_spec"]["system_prompt"] == "v2"


@pytest.mark.asyncio
async def test_register_agent_filters_unknown_tools() -> None:
    sid = await _seed_session()
    result = json.loads(
        await _register_agent(
            _ctx(sid), name="x", role="r", system_prompt="p",
            tools=["web_search", "rm_rf", "web_fetch"],
        )
    )
    assert result["tools"] == ["web_search", "web_fetch"]


# ---- invoke_agent -----------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_agent_uses_persisted_spec(_stub_factory: _StubFactory) -> None:
    sid = await _seed_session()
    await _register_agent(
        _ctx(sid), name="analyst", role="r", system_prompt="be sharp",
    )
    result = json.loads(
        await _invoke_agent(_ctx(sid), name="analyst", prompt="benchmark vector DBs")
    )
    assert result["agent"] == "analyst"
    assert result["report"]["summary"].startswith("The vector DB")
    # Spec passed to the factory came from procedural memory, not a fresh build.
    assert _stub_factory.last_spec.system_prompt == "be sharp"


@pytest.mark.asyncio
async def test_invoke_agent_lifts_metacognition_fields(
    _stub_factory: _StubFactory,
) -> None:
    sid = await _seed_session()
    await _register_agent(
        _ctx(sid), name="analyst", role="r", system_prompt="p",
    )
    result = json.loads(
        await _invoke_agent(_ctx(sid), name="analyst", prompt="x")
    )
    # The stub agent's output carries self_confidence=0.72; the
    # StructuredOutputProtocol should surface it on the JSON envelope.
    assert result["confidence"] == pytest.approx(0.72)
    assert result["uncertainty_targets"] == ["recall numbers on >10M vectors"]
    assert result["capability_boundary"] is False


@pytest.mark.asyncio
async def test_invoke_agent_unknown_returns_error() -> None:
    sid = await _seed_session()
    result = json.loads(
        await _invoke_agent(_ctx(sid), name="nope", prompt="x")
    )
    assert "error" in result
    assert "register_agent" in result["error"]


@pytest.mark.asyncio
async def test_invoke_agent_appends_context(_stub_factory: _StubFactory) -> None:
    sid = await _seed_session()
    await _register_agent(
        _ctx(sid), name="analyst", role="r", system_prompt="p",
    )
    await _invoke_agent(
        _ctx(sid), name="analyst",
        prompt="analyze findings",
        context="pgvector: fast.\nmilvus: scalable.",
    )
    msg = _stub_factory._agent.last_state.get_latest_message("user")
    assert "analyze findings" in msg
    assert "pgvector: fast" in msg


@pytest.mark.asyncio
async def test_invoke_agent_emits_lifecycle_events(
    _stub_factory: _StubFactory,
) -> None:
    sid = await _seed_session()
    rt = runtime_mod.get_runtime(sid)
    seen: list[tuple[str, dict]] = []

    async def handler(evt) -> None:
        seen.append((evt.event_type, evt.data))

    rt.workbench.event_bus.subscribe_all(handler)

    await _register_agent(
        _ctx(sid), name="analyst", role="r", system_prompt="p",
    )
    await _invoke_agent(_ctx(sid), name="analyst", prompt="x")
    types_emitted = [t for t, _ in seen]
    assert "agent.registered" in types_emitted
    assert "agent.spawned" in types_emitted
    assert "agent.completed" in types_emitted

    spawned = next(d for t, d in seen if t == "agent.spawned")
    assert spawned["persistent"] is True

    completed = next(d for t, d in seen if t == "agent.completed")
    # Phase α: completion event includes confidence so the frontend can
    # render a badge without round-tripping through metacognition.confidence.
    assert completed["confidence"] == pytest.approx(0.72)


@pytest.mark.asyncio
async def test_invoke_agent_routes_exception_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = await _seed_session()
    await _register_agent(
        _ctx(sid), name="analyst", role="r", system_prompt="p",
    )
    failing = _StubAgent(
        _Output(summary="", findings=[]), raises=RuntimeError("model 5xx")
    )
    factory = _StubFactory(failing)
    from polymath.tools import autonomy as autonomy_module
    monkeypatch.setattr(autonomy_module, "_build_factory", lambda: factory)

    rt = runtime_mod.get_runtime(sid)
    seen: list[tuple[str, dict]] = []

    async def handler(evt) -> None:
        seen.append((evt.event_type, evt.data))

    rt.workbench.event_bus.subscribe_all(handler)

    result = json.loads(
        await _invoke_agent(_ctx(sid), name="analyst", prompt="x")
    )
    assert "error" in result
    assert "model 5xx" in result["error"]
    completed = next(d for t, d in seen if t == "agent.completed")
    assert completed["ok"] is False


# ---- list_agents ------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_returns_roster() -> None:
    sid = await _seed_session()
    await _register_agent(
        _ctx(sid), name="analyst", role="analyses",
        system_prompt="p",
    )
    await _register_agent(
        _ctx(sid), name="writer", role="writes",
        system_prompt="p", tools=["web_fetch"],
    )
    result = json.loads(await _list_agents(_ctx(sid)))
    by_name = {a["name"]: a for a in result["agents"]}
    assert set(by_name) == {"analyst", "writer"}
    assert by_name["writer"]["tools"] == ["web_fetch"]


# ---- spawn_analyst — back-compat -------------------------------------


@pytest.mark.asyncio
async def test_spawn_analyst_auto_registers_and_invokes(
    _stub_factory: _StubFactory,
) -> None:
    sid = await _seed_session()
    result = json.loads(
        await _spawn_analyst(_ctx(sid), goal="x")
    )
    assert result["agent"] == "analyst"
    found = await _recall_sub_agent(sid, "analyst")
    assert found is not None
    entry, _ = found
    assert entry.metadata["role"].lower().startswith("general")


@pytest.mark.asyncio
async def test_spawn_analyst_reuses_existing_registration(
    _stub_factory: _StubFactory,
) -> None:
    sid = await _seed_session()
    await _register_agent(
        _ctx(sid), name="analyst", role="custom analyst",
        system_prompt="custom",
    )
    await _spawn_analyst(_ctx(sid), goal="x")
    entries = await _list_procedural(sid)
    roles = [e.metadata["role"] for e in entries]
    assert roles == ["custom analyst"]
