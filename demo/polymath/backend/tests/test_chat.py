"""Tests for /sessions/{sid}/chat/stream — validation + persistence behaviour.

Note: these tests do NOT hit a real LLM. They exercise the request-validation
path (which is what AI SDK v6 callers depend on), the session-exists gate,
and the message-persistence layer (user messages persisted before dispatch,
assistant messages persisted via the ``on_complete`` callback).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlmodel import select


@pytest.mark.asyncio
async def test_chat_stream_rejects_unknown_session(client: AsyncClient) -> None:
    """POST to a non-existent session returns 404 before streaming."""
    body = {
        "id": str(uuid.uuid4()),
        "trigger": "submit-message",
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "parts": [{"type": "text", "text": "hi"}],
            }
        ],
    }
    r = await client.post(f"/sessions/{uuid.uuid4()}/chat/stream", json=body)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_chat_stream_rejects_bad_uuid(client: AsyncClient) -> None:
    r = await client.post(
        "/sessions/not-a-uuid/chat/stream",
        json={"id": "x", "trigger": "submit-message", "messages": []},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_messages_empty_for_new_session(client: AsyncClient) -> None:
    """A freshly-created session with no chat activity returns an empty list."""
    sid = (await client.post("/sessions")).json()["id"]
    r = await client.get(f"/sessions/{sid}/messages")
    assert r.status_code == 200
    assert r.json() == {"messages": []}


@pytest.mark.asyncio
async def test_user_message_persisted_before_dispatch(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user's prompt lands in the DB even when dispatch crashes.

    Patches ``VercelAIAdapter.dispatch_request`` to raise. The user row
    must still exist afterwards because :func:`_persist_user_message`
    runs before dispatch.
    """
    sid = (await client.post("/sessions")).json()["id"]

    from polymath.routers import chat as chat_module

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("dispatch crashed")

    monkeypatch.setattr(
        chat_module.VercelAIAdapter, "dispatch_request", classmethod(_boom)
    )

    body = {
        "id": str(uuid.uuid4()),
        "trigger": "submit-message",
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "parts": [{"type": "text", "text": "what is the capital of France?"}],
            }
        ],
    }
    # Dispatch raises; FastAPI returns a 500 — but the user row is already
    # committed by then.
    try:
        await client.post(f"/sessions/{sid}/chat/stream", json=body)
    except RuntimeError:
        pass

    from polymath.db.models import Message
    from polymath.db.session import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as db:
        rows = (
            await db.execute(
                select(Message).where(Message.session_id == uuid.UUID(sid))
            )
        ).scalars().all()
    user_rows = [r for r in rows if r.role == "user"]
    assert len(user_rows) == 1
    assert user_rows[0].content_json["text"] == "what is the capital of France?"


@pytest.mark.asyncio
async def test_assistant_message_persisted_on_complete(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assistant's final text is persisted via the on_complete callback.

    Stubs ``dispatch_request`` to invoke ``on_complete`` with a fake
    :class:`AgentRunResult` whose ``new_messages()`` yields a single
    ``ModelResponse`` with two ``TextPart`` chunks.
    """
    sid = (await client.post("/sessions")).json()["id"]

    from pydantic_ai.messages import ModelResponse, TextPart
    from starlette.responses import Response

    from polymath.routers import chat as chat_module

    class _FakeResult:
        def new_messages(self) -> list[ModelResponse]:
            return [
                ModelResponse(parts=[TextPart(content="Paris "), TextPart(content="is the answer.")])
            ]

    captured: dict[str, Any] = {}

    async def _capture_dispatch(cls, request, *, on_complete=None, **kwargs):
        captured["on_complete"] = on_complete
        if on_complete is not None:
            await on_complete(_FakeResult())
        return Response(content=b"", media_type="text/plain")

    monkeypatch.setattr(
        chat_module.VercelAIAdapter,
        "dispatch_request",
        classmethod(_capture_dispatch),
    )

    body = {
        "id": str(uuid.uuid4()),
        "trigger": "submit-message",
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "parts": [{"type": "text", "text": "capital of France?"}],
            }
        ],
    }
    r = await client.post(f"/sessions/{sid}/chat/stream", json=body)
    assert r.status_code == 200
    assert captured.get("on_complete") is not None

    from polymath.db.models import Message
    from polymath.db.session import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as db:
        rows = (
            await db.execute(
                select(Message)
                .where(Message.session_id == uuid.UUID(sid))
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()
    roles = [r.role for r in rows]
    assert roles == ["user", "assistant"]
    assert rows[1].content_json["text"] == "Paris is the answer."


@pytest.mark.asyncio
async def test_list_messages_returns_persisted_in_order(client: AsyncClient) -> None:
    """Seeded messages come back oldest-first with the expected shape."""
    sid_str = (await client.post("/sessions")).json()["id"]

    from datetime import UTC, datetime, timedelta

    from polymath.db.models import Message
    from polymath.db.session import get_sessionmaker

    sm = get_sessionmaker()
    base = datetime.now(UTC).replace(tzinfo=None)
    sid = uuid.UUID(sid_str)
    async with sm() as db:
        db.add(
            Message(
                session_id=sid,
                role="user",
                content_json={"text": "hi"},
                created_at=base,
            )
        )
        db.add(
            Message(
                session_id=sid,
                role="assistant",
                content_json={"text": "hello"},
                created_at=base + timedelta(seconds=1),
            )
        )
        await db.commit()

    r = await client.get(f"/sessions/{sid_str}/messages")
    assert r.status_code == 200
    payload = r.json()
    msgs = payload["messages"]
    assert len(msgs) == 2
    # Oldest-first.
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hi"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "hello"
    # Frontend contract — every message has these four fields.
    for m in msgs:
        assert set(m.keys()) >= {"id", "role", "content", "created_at"}


@pytest.mark.asyncio
async def test_list_messages_concatenates_parts_when_no_text_field(
    client: AsyncClient,
) -> None:
    """If a row was stored with only ``parts`` (no flat ``text``) we still flatten it.

    Defensive against future schema drift where a v2 persistence path
    might write only ``parts`` without the ``text`` mirror.
    """
    sid_str = (await client.post("/sessions")).json()["id"]

    from polymath.db.models import Message
    from polymath.db.session import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as db:
        db.add(
            Message(
                session_id=uuid.UUID(sid_str),
                role="user",
                content_json={
                    "parts": [
                        {"type": "text", "text": "hello "},
                        {"type": "text", "text": "world"},
                    ]
                },
            )
        )
        await db.commit()

    r = await client.get(f"/sessions/{sid_str}/messages")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["content"] == "hello world"
