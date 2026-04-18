"""Shared backend configuration.

Loads the Orqest config once and exports the model string + ensures the
OPENAI_API_KEY env var is set so pydantic-ai's default provider works.
"""

from __future__ import annotations

import os

from orqest import load_config

_config = load_config()
os.environ.setdefault("OPENAI_API_KEY", _config.llm_api_key)

MODEL = _config.llm_model
API_KEY = _config.llm_api_key
