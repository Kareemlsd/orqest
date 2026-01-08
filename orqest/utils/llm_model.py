"""LLM model"""
import logging

import orqest.config as config
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

logger = logging.getLogger(__name__)

def model(**kwargs) -> OpenAIModel:
    """Initialize and return the OpenAI model."""
    if 'claude' in config.LLM_MODEL:
        model = AnthropicModel(
            model_name=config.LLM_MODEL,
            provider=AnthropicProvider(
                api_key=config.LLM_API_KEY
            ),
            **kwargs,
        )
    elif 'gemini' in config.LLM_MODEL:
        model = GoogleModel(
            model_name=config.LLM_MODEL,
            provider=GoogleProvider(
                api_key=config.LLM_API_KEY
            ),
            **kwargs,
        )
    else:
        model = OpenAIChatModel(
            model_name=config.LLM_MODEL,
            provider=OpenAIProvider(
                api_key=config.LLM_API_KEY
            ),
            **kwargs,
        )
    return model



