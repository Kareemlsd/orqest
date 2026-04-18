"""Tests for BaseSessionState serialization and session tracking."""

import uuid

import pytest
from pydantic import Field
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from orqest.agents.session_state import BaseSessionState


def _req(text: str = "hello") -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(text)])


def _resp(text: str = "reply") -> ModelResponse:
    return ModelResponse(parts=[TextPart(text)])


class TestBaseSessionState:
    """Core session state behavior."""

    def test_session_id_auto_generated(self):
        state = BaseSessionState()
        assert state.session_id is not None
        uuid.UUID(state.session_id)

    def test_unique_session_ids(self):
        a = BaseSessionState()
        b = BaseSessionState()
        assert a.session_id != b.session_id

    def test_created_at_populated(self):
        state = BaseSessionState()
        assert state.created_at is not None


class TestSerialization:
    """Serialize/deserialize round-trip."""

    def test_round_trip_preserves_fields(self):
        state = BaseSessionState(session_id="abc-123")
        state.add_message("user", "hello")
        data = state.serialize()
        restored = BaseSessionState.deserialize(data)
        assert restored.session_id == "abc-123"
        assert len(restored.messages) == 1
        assert restored.messages[0]["content"] == "hello"

    def test_message_history_round_trip(self):
        state = BaseSessionState()
        state.message_history = [_req("hello"), _resp("world")]
        data = state.serialize()
        restored = BaseSessionState.deserialize(data)
        assert len(restored.message_history) == 2

    def test_empty_message_history(self):
        data = {"session_id": "test-id"}
        restored = BaseSessionState.deserialize(data)
        assert restored.message_history == []

    def test_corrupt_message_history_fallback(self):
        data = {
            "session_id": "test-id",
            "message_history": [{"garbage": True}],
        }
        restored = BaseSessionState.deserialize(data)
        assert restored.message_history == []


class TestSubclass:
    """Subclasses with extra fields serialize correctly."""

    def test_subclass_extra_fields(self):

        class MyState(BaseSessionState):
            project_name: str = Field(default="untitled")

        state = MyState(project_name="demo")
        state.add_message("user", "hi")
        data = state.serialize()
        assert data["project_name"] == "demo"
        restored = MyState.deserialize(data)
        assert restored.project_name == "demo"
        assert len(restored.messages) == 1


class TestPydanticNative:
    """model_dump/model_validate work without calling serialize/deserialize."""

    def test_model_dump_roundtrip(self):
        state = BaseSessionState(session_id="p-1")
        state.message_history = [_req("hi"), _resp("hello")]
        data = state.model_dump(mode="json")
        restored = BaseSessionState.model_validate(data)
        assert restored.session_id == "p-1"
        assert len(restored.message_history) == 2

    def test_model_dump_json_produces_string(self):
        state = BaseSessionState(session_id="p-2")
        state.message_history = [_req("hi")]
        json_str = state.model_dump_json()
        assert isinstance(json_str, str)
        assert "p-2" in json_str

    def test_corrupt_message_history_handled_by_validator(self):
        state = BaseSessionState.model_validate(
            {"session_id": "x", "message_history": [{"garbage": True}]}
        )
        assert state.message_history == []
