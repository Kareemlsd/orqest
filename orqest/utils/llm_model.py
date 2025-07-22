"""LLM model"""
import logging

import orqest.config as config
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)


def model(**kwargs) -> OpenAIModel:
    """Initialize and return the OpenAI model."""
    model = OpenAIModel(
        model_name=config.LLM_MODEL,
        provider=OpenAIProvider(
            api_key=config.LLM_API_KEY
        ),
        **kwargs,
    )
    return model



