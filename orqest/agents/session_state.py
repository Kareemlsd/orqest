"""Serializable session state for persistence.

Extends GlobalState with session tracking (session_id, created_at) and
JSON-safe serialization that correctly handles pydantic-ai ModelMessage
objects. ModelMessages are dataclasses, not Pydantic models, so they
require pydantic-ai's ModelMessagesTypeAdapter for round-tripping.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self
from uuid import uuid4

from loguru import logger
from pydantic import Field
from pydantic_ai.messages import ModelMessagesTypeAdapter

from orqest.agents.state import GlobalState


class BaseSessionState(GlobalState):
    """GlobalState extended with session tracking and serialization.

    Subclass this for domain-specific state. The serialization handles
    pydantic-ai ModelMessage objects which are dataclasses, not Pydantic models.
    """

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)

    def serialize(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict, including ModelMessages.

        ModelMessages are dataclasses that Pydantic cannot natively dump,
        so they are handled via pydantic-ai's ModelMessagesTypeAdapter.
        """
        data = self.model_dump(exclude={"message_history"})
        data["message_history"] = ModelMessagesTypeAdapter.dump_python(
            self.message_history, mode="json"
        )
        return data

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> Self:
        """Reconstruct from a serialized dict.

        Handles corrupt or missing message_history gracefully by falling
        back to an empty list -- this is a boundary where external JSON
        may be malformed.
        """
        raw = dict(data)
        history_raw = raw.pop("message_history", [])
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(history_raw)
        except Exception:
            logger.warning("Failed to deserialize message_history, using empty list")
            message_history = []
        return cls(message_history=message_history, **raw)
