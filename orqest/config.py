"""Configuration for orqest.

Provides OrqestConfig as an immutable container for runtime settings.
Config is loaded explicitly via load_config() — never at import time —
so importing orqest has no side effects on the process environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv, find_dotenv


@dataclass(frozen=True)
class OrqestConfig:
    """Immutable runtime configuration."""

    llm_api_key: str
    llm_model: str
    embedding_model: str
    embedding_api_key: str


def load_config(*, dotenv_path: str | Path | None = None) -> OrqestConfig:
    """Load configuration from environment variables.

    Optionally loads a .env file first. Validates that required values are present
    so callers get a clear error at startup rather than a cryptic failure mid-run.

    Raises:
        ValueError: If LLM_API_KEY is not set.
    """
    if dotenv_path is None:
        found = find_dotenv(usecwd=True)
        if found:
            load_dotenv(found)
    else:
        load_dotenv(dotenv_path)

    llm_api_key = os.getenv("LLM_API_KEY")
    if not llm_api_key:
        raise ValueError(
            "LLM_API_KEY environment variable is required but not set. "
            "Set it in your environment or in a .env file."
        )

    llm_model = os.getenv("LLM_MODEL", "openai:gpt-3.5-turbo")
    embedding_model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    embedding_api_key = os.getenv("EMBEDDING_API_KEY", llm_api_key)

    return OrqestConfig(
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        embedding_model=embedding_model,
        embedding_api_key=embedding_api_key,
    )


@lru_cache(maxsize=1)
def get_default_config() -> OrqestConfig:
    """Cached convenience wrapper around load_config().

    Use load_config() directly when you need explicit control over the dotenv path
    or want a fresh (non-cached) config.
    """
    return load_config()
