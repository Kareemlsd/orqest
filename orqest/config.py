"""
Configuration module for the Orqest project.
Handles loading environment variables and providing global configuration.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

def find_dotenv(start: Path = None, filename: str = ".env") -> Path | None:
    """Search upward from start directory until a .env file is found."""
    if start is None:
        start = Path(__file__).resolve().parent

    for parent in [start, *start.parents]:
        candidate = parent / filename
        if candidate.exists():
            return candidate
    return None

def load_environment():
    """Load environment variables from the nearest .env file in the project."""
    dotenv_path = find_dotenv()
    if dotenv_path:
        load_dotenv(dotenv_path)
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"Loaded environment variables from {dotenv_path}")
    else:
        if os.getenv("DEBUG", "false").lower() == "true":
            print("No .env file found")

# Load on import
load_environment()

# Exported config values
LLM_API_KEY = os.getenv('LLM_API_KEY')
LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-3.5-turbo')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
EMBEDDING_API_KEY = os.getenv('EMBEDDING_API_KEY', LLM_API_KEY)
