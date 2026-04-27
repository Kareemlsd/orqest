"""Tests for resolve_model_with_fallback + FallbackModel."""

from __future__ import annotations

import pytest
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from orqest.healing import FallbackModel, resolve_model_with_fallback
from orqest.healing.fallback import _default_transient_predicate
from orqest.observability.events import AgentEvent, EventBus


# ---- _default_transient_predicate ------------------------------------


def test_transient_recognises_timeouts():
    class ConnectTimeout(Exception):
        pass

    assert _default_transient_predicate(ConnectTimeout()) is True


def test_transient_refuses_auth_errors():
    class AuthenticationError(Exception):
        pass

    assert _default_transient_predicate(AuthenticationError()) is False


def test_transient_refuses_validation_errors():
    class ValidationError(Exception):
        pass

    assert _default_transient_predicate(ValidationError()) is False


def test_transient_unknown_exception_treated_as_transient():
    """Default policy: unknown errors are transient — fail open, not closed."""

    class WeirdError(Exception):
        pass

    assert _default_transient_predicate(WeirdError()) is True


# ---- FallbackModel construction --------------------------------------


def test_fallback_model_requires_at_least_one_model():
    with pytest.raises(ValueError):
        FallbackModel([])


def test_fallback_model_name_concatenates_underlying():
    a = TestModel()
    b = TestModel()
    fm = FallbackModel([a, b])
    assert "fallback(" in fm.model_name


def test_fallback_model_initial_active_is_first():
    a = TestModel()
    b = TestModel()
    fm = FallbackModel([a, b])
    assert fm.active_model is a


# ---- request() failover behavior -------------------------------------


class _StubModel:
    """Fake Model — only what we need for `.request()` test."""

    def __init__(self, name: str, *, raises: BaseException | None = None) -> None:
        self.model_name = name
        self.system = "test"
        self._raises = raises
        self.calls = 0

    async def request(self, *args, **kwargs):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return f"response-from-{self.model_name}"


@pytest.mark.asyncio
async def test_request_succeeds_on_primary():
    a = _StubModel("a")
    b = _StubModel("b")
    fm = FallbackModel([a, b])  # type: ignore[list-item]
    result = await fm.request([], None, None)  # type: ignore[arg-type]
    assert result == "response-from-a"
    assert a.calls == 1
    assert b.calls == 0


@pytest.mark.asyncio
async def test_request_falls_back_on_transient_failure():
    class _Transient(Exception):
        """Default predicate treats unknown exceptions as transient."""

    a = _StubModel("a", raises=_Transient("boom"))
    b = _StubModel("b")
    fm = FallbackModel([a, b])  # type: ignore[list-item]
    result = await fm.request([], None, None)  # type: ignore[arg-type]
    assert result == "response-from-b"
    assert a.calls == 1
    assert b.calls == 1


@pytest.mark.asyncio
async def test_request_propagates_non_transient_failure():
    class AuthenticationError(Exception):
        """Recognised non-transient by the default predicate."""

    a = _StubModel("a", raises=AuthenticationError("nope"))
    b = _StubModel("b")
    fm = FallbackModel([a, b])  # type: ignore[list-item]
    with pytest.raises(AuthenticationError):
        await fm.request([], None, None)  # type: ignore[arg-type]
    assert a.calls == 1
    assert b.calls == 0


@pytest.mark.asyncio
async def test_all_exhausted_raises_runtime_error():
    class _Transient(Exception):
        pass

    a = _StubModel("a", raises=_Transient("boom"))
    b = _StubModel("b", raises=_Transient("boom"))
    fm = FallbackModel([a, b])  # type: ignore[list-item]
    with pytest.raises(RuntimeError, match="exhausted"):
        await fm.request([], None, None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_failover_emits_event_on_bus():
    class _Transient(Exception):
        pass

    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("healing.model_fallback", lambda e: captured.append(e))

    a = _StubModel("a", raises=_Transient("boom"))
    b = _StubModel("b")
    fm = FallbackModel([a, b], bus=bus)  # type: ignore[list-item]
    await fm.request([], None, None)  # type: ignore[arg-type]
    assert len(captured) == 1
    assert captured[0].data["from"] == "a"
    assert captured[0].data["to"] == "b"


@pytest.mark.asyncio
async def test_advance_is_sticky():
    """Once we've fallen back, subsequent requests start from the new index."""

    class _Transient(Exception):
        pass

    a = _StubModel("a", raises=_Transient("boom"))
    b = _StubModel("b")
    fm = FallbackModel([a, b])  # type: ignore[list-item]
    await fm.request([], None, None)  # type: ignore[arg-type]
    a.calls = 0  # reset
    b.calls = 0
    await fm.request([], None, None)  # type: ignore[arg-type]
    assert a.calls == 0  # never re-tried
    assert b.calls == 1


# ---- resolve_model_with_fallback -------------------------------------


def test_resolve_with_no_resolvable_models_raises():
    with pytest.raises(ValueError):
        resolve_model_with_fallback(
            ["nonsense_provider:nonsense_model"], api_key="x"
        )


def test_resolve_returns_fallback_model_for_one_resolvable():
    """At least one resolvable provider → returns a FallbackModel."""
    fm = resolve_model_with_fallback(
        ["openai:gpt-4o"], api_key="test-key"
    )
    assert isinstance(fm, FallbackModel)
    assert isinstance(fm, Model)


def test_resolve_with_per_provider_key_map_skips_missing():
    """When a per-provider key is missing, that provider is skipped."""
    fm = resolve_model_with_fallback(
        ["openai:gpt-4o", "anthropic:claude-sonnet-4-6"],
        api_key={"openai": "k1"},  # only openai has a key
    )
    assert isinstance(fm, FallbackModel)
