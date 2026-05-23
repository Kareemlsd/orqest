"""One-shot smoke: resolve DeepSeek V3.2 via OpenRouter, make a tiny call.

Reads OPENROUTER_API_KEY from the environment (loaded from .env by python-dotenv).
Cost: ~$0.0001. Run with `.venv/bin/python scripts/smoke_openrouter.py`.
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from orqest.utils.llm_model import resolve_model
from pydantic_ai import Agent
from pydantic import BaseModel


class Greeting(BaseModel):
    text: str


async def main():
    api_key = os.environ["OPENROUTER_API_KEY"]
    model_id = os.environ.get("SPIDER_TASK_MODEL", "openrouter:deepseek/deepseek-v3.2")
    print(f"Resolving model: {model_id}")
    m = resolve_model(model_id, api_key=api_key)
    print(f"Resolved: {type(m).__name__}  model_name={m.model_name}  system={m.system}")

    agent = Agent(model=m, output_type=Greeting, system_prompt="Greet me concisely.")
    result = await agent.run("Hi.")
    print(f"Output: {result.output!r}")
    usage = result.usage()
    print(f"Usage: input={usage.input_tokens}  output={usage.output_tokens}")


asyncio.run(main())
