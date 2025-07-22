"""
Configuration module for the Orqest project.
Handles loading environment variables and providing global configuration.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

def load_environment():
    """Load environment variables from .env file in the project root."""

    # Resolve the project root by going up from this file
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent  # Adjust depth as needed

    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path)

    # Print debug info if requested
    if os.getenv("DEBUG", "false").lower() == "true":
        print(f"Loaded environment variables from {dotenv_path}")

# Load on module import
load_environment()

# Exported config values
LLM_API_KEY = os.getenv('LLM_API_KEY')
LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-3.5-turbo')

EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
EMBEDDING_API_KEY = os.getenv('EMBEDDING_API_KEY', LLM_API_KEY)
