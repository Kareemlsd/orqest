"""State models for Orqest agents."""
import logging
from typing import Any, List, Optional, Dict

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GlobalState(BaseModel):
    """Global state for agents.

    This class represents the shared state that can be used by different agents
    in the Orqest framework. It includes methods for managing messages and
    retrieving the latest messages from different roles.

    Attributes:
        messages: List of messages in the conversation.
        assistant_message: The latest message from the assistant.
        message_history: History of the chat for context.
    """
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    assistant_message: str = Field(default_factory=str)
    message_history: List[Any] = Field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the message history.

        Args:
            role (str): The role of the message sender (e.g., "user", "assistant").
            content (str): The content of the message.
        """
        self.messages.append({"role": role, "content": content})

    def get_latest_user_message(self) -> Optional[str]:
        """Get the latest user message from the message history.

        Returns:
            Optional[str]: The latest user message if available, otherwise None.
        """
        for message in reversed(self.messages):
            if message.get("role") == "user":
                return message.get("content")
        return None

    def get_latest_assistant_message(self) -> Optional[str]:
        """Get the latest assistant message from the message history.

        Returns:
            Optional[str]: The latest assistant message if available, otherwise None.
        """
        for message in reversed(self.messages):
            if message.get("role") == "assistant":
                return message.get("content")
        return None


if __name__ == "__main__":
    pass