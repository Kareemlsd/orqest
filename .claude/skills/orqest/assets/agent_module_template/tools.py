"""Tools for the <NAME> agent.

Each tool is an async function that wraps an existing app primitive (DB
query, service call, internal API). Type the parameters and return value;
pydantic-ai infers the schema. Reuse existing app models — never duplicate.
"""
from __future__ import annotations

# Example shape — replace with your actual tools:
#
# from app.orders.queries import get_recent_orders  # existing app primitive
#
#
# async def list_recent_orders(user_id: str, limit: int = 10) -> list[dict]:
#     """Return the user's most recent orders.
#
#     ``limit`` defaults to 10 and is capped at 100 by the underlying query.
#     """
#     rows = await get_recent_orders(user_id=user_id, limit=limit)
#     return [r.to_dict() for r in rows]
