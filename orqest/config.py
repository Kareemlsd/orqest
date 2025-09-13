"""
Configuration module for the Orqest project.
Handles loading environment variables and providing global configuration.
"""
import os
from dotenv import load_dotenv, find_dotenv

# Load environment variables (searches upward for .env file)
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

# Debug info
if os.getenv("DEBUG", "false").lower() == "true":
    print(f"Loaded environment variables from {dotenv_path or 'no .env found'}")

# Exported config values
LLM_API_KEY = os.getenv('LLM_API_KEY')
LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-3.5-turbo')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
EMBEDDING_API_KEY = os.getenv('EMBEDDING_API_KEY', LLM_API_KEY)
