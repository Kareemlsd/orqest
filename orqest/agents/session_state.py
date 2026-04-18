"""Serializable session state for persistence.

Extends :class:`GlobalState` with session tracking (``session_id``,
``created_at``) and Pydantic-native serialization for pydantic-ai
``ModelMessage`` histories. The key trick is a
``SerializableMessageHistory`` annotation that teaches Pydantic how to
round-trip ``ModelMessage`` values (which are dataclasses, not Pydantic
models) directly through ``model_dump`` / ``model_validate``.

The imperative ``serialize()`` / ``deserialize()`` helpers remain as thin
wrappers for callers that prefer method-style access.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Self
from uuid import uuid4

from loguru import logger
from pydantic import Field, PlainSerializer, PlainValidator
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from orqest.agents.state import GlobalState


def _serialize_message_history(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Dump a list of pydantic-ai ``ModelMessage`` to JSON-safe dicts."""
    return ModelMessagesTypeAdapter.dump_python(messages, mode="json")


def _validate_message_history(value: Any) -> list[ModelMessage]:
    """Parse a serialized list of messages, tolerating corruption.

    Accepts either an already-hydrated list of ``ModelMessage`` values or
    the JSON-safe list-of-dicts form produced by the serializer. Corrupt
    input falls back to an empty list — this is a boundary where external
    JSON may be malformed.
    """
    if not isinstance(value, list) or len(value) == 0:
        return []
    if isinstance(value[0], dict):
        try:
            return ModelMessagesTypeAdapter.validate_python(value)
        except Exception:
            logger.warning("Failed to deserialize message_history, using empty list")
            return []
    return value


SerializableMessageHistory = Annotated[
    list[ModelMessage],
    PlainValidator(_validate_message_history),
    PlainSerializer(_serialize_message_history, return_type=list[dict[str, Any]]),
]
"""Annotated ``list[ModelMessage]`` that round-trips via ``model_dump`` /
``model_validate`` without manual adapter calls."""


class BaseSessionState(GlobalState):
    """GlobalState extended with session tracking and native serialization.

    Subclass for domain-specific state. ``model_dump()`` and
    ``model_validate()`` handle ``message_history`` correctly thanks to the
    :data:`SerializableMessageHistory` annotation.
    """

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    message_history: SerializableMessageHistory = Field(default_factory=list)

    def serialize(self) -> dict[str, Any]:
        """Return a JSON-safe dict representation of this state.

        Thin wrapper over ``model_dump(mode="json")``; kept for callers
        that prefer method-style access.
        """
        return self.model_dump(mode="json")

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> Self:
        """Reconstruct a state from a serialized dict.

        Thin wrapper over ``model_validate``; corrupt ``message_history``
        is handled inside the :data:`SerializableMessageHistory` validator.
        """
        return cls.model_validate(data)
