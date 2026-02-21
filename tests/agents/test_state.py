from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

from orqest.agents.state import GlobalState


class TestGlobalState:
    def test_empty_init(self):
        state = GlobalState()
        assert state.messages == []
        assert state.message_history == []

    def test_add_message(self):
        state = GlobalState()
        state.add_message("user", "hello")
        assert len(state.messages) == 1
        assert state.messages[0] == {"role": "user", "content": "hello"}

    def test_add_multiple_messages(self):
        state = GlobalState()
        state.add_message("user", "hi")
        state.add_message("assistant", "hello")
        state.add_message("user", "bye")
        assert len(state.messages) == 3


class TestGetLatestMessage:
    def test_latest_user(self):
        state = GlobalState()
        state.add_message("user", "first")
        state.add_message("assistant", "reply")
        state.add_message("user", "second")
        assert state.get_latest_message("user") == "second"

    def test_latest_assistant(self):
        state = GlobalState()
        state.add_message("user", "hi")
        state.add_message("assistant", "first reply")
        state.add_message("assistant", "second reply")
        assert state.get_latest_message("assistant") == "second reply"

    def test_no_messages_returns_none(self):
        state = GlobalState()
        assert state.get_latest_message("user") is None

    def test_no_matching_role_returns_none(self):
        state = GlobalState()
        state.add_message("user", "hello")
        assert state.get_latest_message("assistant") is None

    def test_arbitrary_role(self):
        state = GlobalState()
        state.add_message("system", "you are helpful")
        assert state.get_latest_message("system") == "you are helpful"


class TestMessageHistory:
    def test_stores_model_messages(self):
        state = GlobalState()
        req = ModelRequest(parts=[UserPromptPart("hello")])
        resp = ModelResponse(parts=[TextPart("hi there")])
        state.message_history = [req, resp]
        assert len(state.message_history) == 2
        assert isinstance(state.message_history[0], ModelRequest)
        assert isinstance(state.message_history[1], ModelResponse)

    def test_empty_by_default(self):
        state = GlobalState()
        assert state.message_history == []
