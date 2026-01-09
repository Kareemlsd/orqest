"""LLM model"""
import logging

import orqest.config as config
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)

def model(**kwargs) -> OpenAIModel:
    """
    Initialize and return an appropriate LLM model instance.

    The selection is based on the `config.LLM_MODEL` string. This function
    inspects that value to determine which provider/model class to instantiate,
    and it constructs the provider with `config.LLM_API_KEY`.

    Behavior by provider detection:
    - Anthropic: chosen when 'claude' appears in `config.LLM_MODEL`.
    - Google: chosen when 'gemini' appears in `config.LLM_MODEL`.
    - OpenRouter: chosen when `config.LLM_MODEL` contains the 'openrouter'
      prefix. For OpenRouter the expected format is:
          openrouter:<openrouter_model_id>
          (e.g. openrouter:anthropic/claude-3.5-sonnet)
      where the portion after the colon is used as `model_name`.
    - OpenAI (default): used for any other `config.LLM_MODEL` values.

    Keyword Arguments:
        **kwargs: Extra keyword arguments forwarded to the selected model
            constructor (when supported by that model class).

    Returns:
        OpenAIModel: An instance of the selected model class (or a compatible
        subclass). The returned object will be configured with the provider
        using `config.LLM_API_KEY`.

    Raises:
        (No explicit exceptions are raised here; provider/model constructors
        may raise their own exceptions on invalid configuration.)
    """
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
    elif 'openrouter' in config.LLM_MODEL:
        model_name = config.LLM_MODEL.split(':')
        model = OpenRouterModel(
            model_name=model_name[1],
            provider=OpenRouterProvider(
                api_key=config.LLM_API_KEY,
            ),
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



