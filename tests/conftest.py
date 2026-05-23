import pytest
from pydantic_ai.models.test import TestModel

from orqest.config import OrqestConfig


@pytest.fixture
def test_config():
    return OrqestConfig(
        llm_api_key="test-key-123",
        llm_model="openai:gpt-4.1",
        embedding_model="all-MiniLM-L6-v2",
        embedding_api_key="test-key-123",
    )


@pytest.fixture
def test_model():
    return TestModel()
