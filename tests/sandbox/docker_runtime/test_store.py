"""Tests for orqest.sandbox.docker_runtime.store.ToolStore."""

from __future__ import annotations

import pytest

from orqest.sandbox.docker_runtime.store import (
    PersistedTool,
    ToolStore,
    _hash_impl,
)


@pytest.fixture
def store():
    s = ToolStore(":memory:")
    yield s
    s.close()


# --- Hash helper -----------------------------------------------------------


def test_hash_impl_stable():
    assert _hash_impl("return 1") == _hash_impl("return 1")


def test_hash_impl_different_implementations_differ():
    assert _hash_impl("return 1") != _hash_impl("return 2")


# --- persist + replay ------------------------------------------------------


def test_persist_creates_version_1(store):
    tool = store.persist(
        name="extract_dois",
        description="Extract DOIs.",
        parameters={"text": {"type": "string"}},
        implementation="return []",
        allowed_imports=["re"],
        dependencies=[],
    )
    assert isinstance(tool, PersistedTool)
    assert tool.name == "extract_dois"
    assert tool.version == 1
    assert tool.invocation_count == 0


def test_persist_dedupe_on_same_hash(store):
    """Re-persisting with identical implementation should NOT bump version."""
    t1 = store.persist(
        name="x", description="x", parameters={},
        implementation="return 1", allowed_imports=[],
    )
    t2 = store.persist(
        name="x", description="x updated", parameters={},
        implementation="return 1",  # same hash
        allowed_imports=[],
    )
    assert t1.version == t2.version == 1


def test_persist_bump_version_on_different_implementation(store):
    """Different implementation → version bumps; old version is retained."""
    t1 = store.persist(
        name="x", description="x", parameters={},
        implementation="return 1", allowed_imports=[],
    )
    t2 = store.persist(
        name="x", description="x", parameters={},
        implementation="return 2", allowed_imports=[],
    )
    assert t1.version == 1
    assert t2.version == 2
    # Both versions are queryable
    assert store.get("x", version=1) is not None
    assert store.get("x", version=2) is not None


def test_replay_returns_latest_version_per_name(store):
    store.persist(name="x", description="x", parameters={},
                  implementation="return 1", allowed_imports=[])
    store.persist(name="x", description="x", parameters={},
                  implementation="return 2", allowed_imports=[])
    store.persist(name="y", description="y", parameters={},
                  implementation="return 'y'", allowed_imports=[])

    replayed = store.replay()
    by_name = {t.name: t for t in replayed}
    assert by_name["x"].version == 2
    assert by_name["y"].version == 1


def test_get_with_no_version_returns_latest(store):
    store.persist(name="x", description="x", parameters={},
                  implementation="return 1", allowed_imports=[])
    store.persist(name="x", description="x", parameters={},
                  implementation="return 2", allowed_imports=[])
    latest = store.get("x")
    assert latest is not None
    assert latest.version == 2


def test_get_missing_returns_none(store):
    assert store.get("nonexistent") is None


# --- forget ----------------------------------------------------------------


def test_forget_specific_version(store):
    store.persist(name="x", description="x", parameters={},
                  implementation="return 1", allowed_imports=[])
    store.persist(name="x", description="x", parameters={},
                  implementation="return 2", allowed_imports=[])
    deleted = store.forget("x", version=1)
    assert deleted == 1
    assert store.get("x", version=1) is None
    assert store.get("x", version=2) is not None


def test_forget_all_versions(store):
    store.persist(name="x", description="x", parameters={},
                  implementation="return 1", allowed_imports=[])
    store.persist(name="x", description="x", parameters={},
                  implementation="return 2", allowed_imports=[])
    deleted = store.forget("x")
    assert deleted == 2
    assert store.get("x") is None


def test_forget_missing_returns_zero(store):
    assert store.forget("nonexistent") == 0


# --- record_invocation -----------------------------------------------------


def test_record_invocation_increments(store):
    store.persist(name="x", description="x", parameters={},
                  implementation="return 1", allowed_imports=[])
    assert store.get("x").invocation_count == 0
    store.record_invocation("x")
    store.record_invocation("x")
    store.record_invocation("x")
    assert store.get("x").invocation_count == 3


def test_record_invocation_silent_on_missing(store):
    # Doesn't raise
    store.record_invocation("nonexistent")


# --- field round trips -----------------------------------------------------


def test_dependencies_round_trip(store):
    store.persist(
        name="x", description="x", parameters={"a": {"type": "string"}},
        implementation="return 1", allowed_imports=["re", "json"],
        dependencies=["pandas>=2.0", "httpx"],
    )
    tool = store.get("x")
    assert tool.allowed_imports == ["re", "json"]
    assert tool.dependencies == ["pandas>=2.0", "httpx"]
    assert tool.parameters == {"a": {"type": "string"}}
