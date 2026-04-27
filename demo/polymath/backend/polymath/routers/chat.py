"""Chat streaming endpoint — routes to pydantic-ai's VercelAIAdapter.

The current build wires the full agent (research + plan + memory +
sandbox + browser + reports + autonomy). See
``demo/backend/workbench/router.py`` for the reference pattern this
mirrors.

Persistence: the user's incoming message is persisted *before* dispatch
so a crash mid-run still preserves the prompt; the assistant's final
text is persisted in :func:`on_complete` from
:meth:`AgentRunResult.new_messages`. Tool calls / tool returns are
stored as part of the user message's ``parts`` list (so we can
roundtrip later) but the rendered ``content`` field is the final text —
that matches the frontend's :class:`PersistedMessage` shape
(``frontend/src/hooks/useChat.ts``).

Takeover handling: chat turns are *never* rejected for active takeover
(Phase β.7). Tool calls fired during takeover are intercepted by
:class:`~polymath.workbench_factory.TakeoverGate` which returns
:class:`~orqest.hooks.Skip` with a deferred-stub result; the chat stream
completes with those stubs in place of real tool outputs.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from sqlmodel import select
from starlette.requests import Request
from starlette.responses import Response

from orqest.observability import AgentEvent

from polymath.config import get_default_config
from polymath.db.models import Message, Session
from polymath.db.session import get_sessionmaker
from polymath.orchestrator import get_polymath_agent
from polymath.runtime import get_runtime
from polymath.session_metrics import record_turn as record_turn_metrics
from polymath.state import PolymathState

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["chat"])


def _extract_user_text(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]] | None:
    """Pull the most-recent user message text + parts from a Vercel AI request body.

    The frontend sends ``{trigger: "submit-message", id: ..., messages: [...]}``
    where the last ``role: user`` entry is the new turn. Returns ``None`` if
    no user message is present (e.g., a malformed body that should be left
    for :class:`VercelAIAdapter` to reject).
    """
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return None
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        parts = msg.get("parts")
        if not isinstance(parts, list):
            continue
        text_chunks: list[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                t = p.get("text")
                if isinstance(t, str):
                    text_chunks.append(t)
        text = "".join(text_chunks)
        if text:
            return text, parts
    return None


async def _persist_user_message(
    sid: UUID, text: str, parts: list[dict[str, Any]]
) -> None:
    """Insert a ``role=user`` row before agent dispatch.

    Persisting *before* dispatch means a crash mid-run still leaves the
    user's prompt visible on reload. Rolls back silently on DB error so
    persistence never blocks the chat stream.
    """
    sm = get_sessionmaker()
    try:
        async with sm() as db:
            db.add(
                Message(
                    session_id=sid,
                    role="user",
                    content_json={"text": text, "parts": parts},
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — never block the stream on DB.
        logger.warning("polymath: persist user message failed for %s: %s", sid, exc)


async def _persist_assistant_message(sid: UUID, result: Any) -> str:
    """Insert a ``role=assistant`` row from a completed :class:`AgentRunResult`.

    Walks ``result.new_messages()`` looking for :class:`ModelResponse`
    instances and concatenates every :class:`TextPart`. If the agent
    produced no text (only tool calls without a final answer) the row
    is skipped — nothing useful for the transcript.

    Returns the concatenated assistant text (empty string if none) so
    callers can run additional post-turn analysis (e.g. metacognition
    self-rating) without re-walking ``result.new_messages()``.
    """
    text_chunks: list[str] = []
    try:
        new_messages = result.new_messages()
    except Exception as exc:  # noqa: BLE001 — defensive against shim adapters.
        logger.warning("polymath: result.new_messages() failed for %s: %s", sid, exc)
        return ""
    for msg in new_messages:
        if not isinstance(msg, ModelResponse):
            continue
        for part in msg.parts:
            if isinstance(part, TextPart):
                text_chunks.append(part.content)
    text = "".join(text_chunks).strip()
    if not text:
        return ""
    sm = get_sessionmaker()
    try:
        async with sm() as db:
            db.add(
                Message(
                    session_id=sid,
                    role="assistant",
                    content_json={"text": text},
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "polymath: persist assistant message failed for %s: %s", sid, exc
        )
    return text


async def _emit_self_rating(sid: UUID, last_user_text: str, assistant_text: str) -> None:
    """Run the self-rating protocol on the just-completed turn and emit it.

    The :class:`MetacognitionHook` only fires when a tool returns an
    :class:`EnrichedOutput` — none of Polymath's tools do that today, so
    the per-message confidence badge would stay silent without this
    explicit rating step. We invoke
    :class:`~orqest.metacognition.LLMSelfRatingProtocol` against the
    final assistant text, then emit a synthetic
    ``metacognition.confidence`` event on the session bus that the
    frontend's ``useMetacognition`` hook freezes onto the message id.

    Best-effort. Any failure (network, parse error, missing key) is
    logged at WARNING and swallowed; the badge just stays hidden for
    that turn.
    """
    cfg = get_default_config()
    if not cfg.ENABLE_SELF_RATING or not assistant_text:
        return
    try:
        from orqest.agents.state import GlobalState
        from orqest.metacognition.protocol import LLMSelfRatingProtocol

        agent = get_polymath_agent()
        protocol = LLMSelfRatingProtocol()
        state = GlobalState()
        if last_user_text:
            state.add_message("user", last_user_text)
        enriched = await protocol.enrich(
            agent, state, assistant_text,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "polymath: self-rating skipped for %s: %s", sid, exc
        )
        return

    try:
        runtime = get_runtime(str(sid))
        await runtime.workbench.event_bus.emit(
            AgentEvent(
                event_type="metacognition.confidence",
                agent_name=agent.agent_name,
                timestamp=datetime.now(UTC),
                data={
                    "confidence": enriched.confidence,
                    "uncertainty_targets": list(enriched.uncertainty_targets),
                    "capability_boundary": bool(enriched.capability_boundary),
                    "protocol": enriched.protocol_name,
                    "source": "post_turn_self_rating",
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "polymath: self-rating emit failed for %s: %s", sid, exc
        )


def _extract_assistant_message_id(result: Any) -> str | None:
    """Pull the message id of the just-completed assistant turn.

    Pydantic-AI's :class:`AgentRunResult` exposes ``new_messages()``
    which carries the freshly-produced :class:`ModelResponse` (one
    per LLM turn). We surface the *last* model response's id so the
    frontend's ``useChatMetrics`` hook can attribute the metadata
    strip to the matching assistant message in the AI SDK transcript.
    """
    try:
        new_messages = result.new_messages()
    except Exception:  # noqa: BLE001
        return None
    last_response: Any = None
    for msg in new_messages:
        if isinstance(msg, ModelResponse):
            last_response = msg
    if last_response is None:
        return None
    candidate = (
        getattr(last_response, "id", None)
        or getattr(last_response, "message_id", None)
    )
    return str(candidate) if candidate else None


def _count_tool_calls(result: Any) -> int:
    """Count tool invocations in the just-completed turn.

    Walks ``result.new_messages()`` and tallies parts whose ``part_kind``
    is ``"tool-call"`` (pydantic-ai's discriminator). Resilient to API
    drift — falls back on duck-typing the part class name.
    """
    try:
        new_messages = result.new_messages()
    except Exception:  # noqa: BLE001
        return 0
    count = 0
    for msg in new_messages:
        for part in getattr(msg, "parts", []) or []:
            kind = getattr(part, "part_kind", None) or type(part).__name__.lower()
            if "tool" in str(kind).lower() and "call" in str(kind).lower():
                count += 1
    return count


async def _emit_turn_completed(
    sid: UUID,
    result: Any,
    assistant_text: str,
    duration_ms: float,
) -> None:
    """Emit the typed `chat.turn.completed` event + update cumulative usage.

    The chrome's per-turn metadata strip and the session-header
    Context ring both depend on this event firing on every assistant
    turn. Best-effort: any failure (missing usage, unusual result
    shape) is logged at WARNING and swallowed so the chat stream
    closes cleanly.
    """
    try:
        usage_obj = result.usage() if callable(getattr(result, "usage", None)) else None
    except Exception:  # noqa: BLE001
        usage_obj = None

    def _u(name: str) -> int:
        if usage_obj is None:
            return 0
        v = getattr(usage_obj, name, 0)
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    input_tokens = _u("input_tokens")
    output_tokens = _u("output_tokens")
    total_tokens = _u("total_tokens") or (input_tokens + output_tokens)
    cache_read = _u("cache_read_tokens")
    cache_write = _u("cache_write_tokens")

    tool_calls = _count_tool_calls(result)
    message_id = _extract_assistant_message_id(result)

    cumulative = record_turn_metrics(
        str(sid),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        tool_calls=tool_calls,
        duration_ms=duration_ms,
    )

    try:
        runtime = get_runtime(str(sid))
        await runtime.workbench.event_bus.emit(
            AgentEvent(
                event_type="chat.turn.completed",
                agent_name="polymath",
                timestamp=datetime.now(UTC),
                data={
                    "message_id": message_id,
                    "duration_ms": duration_ms,
                    "tool_calls": tool_calls,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "cache_read_tokens": cache_read,
                    "cache_write_tokens": cache_write,
                    "assistant_text_length": len(assistant_text),
                    "cumulative": {
                        "input_tokens": cumulative.input_tokens,
                        "output_tokens": cumulative.output_tokens,
                        "total_tokens": cumulative.total_tokens,
                        "cache_read_tokens": cumulative.cache_read_tokens,
                        "cache_write_tokens": cumulative.cache_write_tokens,
                        "tool_calls": cumulative.tool_calls,
                        "turns": cumulative.turns,
                        "total_duration_ms": cumulative.total_duration_ms,
                    },
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "polymath: turn-completed emit failed for %s: %s", sid, exc
        )


def _content_from_json(content_json: dict[str, Any]) -> str:
    """Project a stored ``content_json`` blob to a flat string for the frontend.

    Preference order: ``text`` field → concatenated text from ``parts`` →
    JSON-stringified payload as a last-ditch fallback.
    """
    text = content_json.get("text")
    if isinstance(text, str):
        return text
    parts = content_json.get("parts")
    if isinstance(parts, list):
        chunks: list[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                t = p.get("text")
                if isinstance(t, str):
                    chunks.append(t)
        if chunks:
            return "".join(chunks)
    return json.dumps(content_json)


@router.post("/{sid}/chat/stream")
async def chat_stream(sid: UUID, request: Request) -> Response:
    """Stream agent tokens via the Vercel AI Data Stream Protocol."""
    sm = get_sessionmaker()
    async with sm() as db:
        session = await db.get(Session, sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Lazy-start the healing poll loop so it shares the request loop's
    # lifetime. Idempotent across turns.
    runtime = get_runtime(str(sid))
    await runtime.ensure_started()

    # Pre-dispatch persistence: read the body (Starlette caches it so
    # ``VercelAIAdapter`` can re-read it) and store the user's prompt.
    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    last_user_text = ""
    if isinstance(payload, dict):
        user_msg = _extract_user_text(payload)
        if user_msg is not None:
            text, parts = user_msg
            last_user_text = text
            await _persist_user_message(sid, text, parts)

    # The streaming path needs a pydantic-ai ``Agent``. ``BaseAgent.agent``
    # lazily constructs it from the ``PolymathAgent`` config (system_prompt,
    # output_type, tools, model, history processors) and caches it — the
    # adapter dispatches to the same instance the BaseAgent owns.
    polymath_agent = get_polymath_agent()
    deps = PolymathState(session_id=str(sid))

    turn_started_at = time.monotonic()

    async def on_complete(result) -> None:  # type: ignore[no-untyped-def]
        duration_ms = (time.monotonic() - turn_started_at) * 1000
        assistant_text = await _persist_assistant_message(sid, result)
        # Surface the cognitive backbone — fire a self-rating after the
        # turn closes so the chat surface gets a real per-message
        # confidence badge. Best-effort; gated by ENABLE_SELF_RATING.
        await _emit_self_rating(sid, last_user_text, assistant_text)
        # Per-turn metadata for the chrome's metadata strip + the
        # session-header Context ring. Best-effort; failures swallowed.
        await _emit_turn_completed(sid, result, assistant_text, duration_ms)
        logger.info("polymath: chat run complete for session %s", sid)

    return await VercelAIAdapter.dispatch_request(
        request, agent=polymath_agent.agent, deps=deps, on_complete=on_complete
    )


@router.get("/{sid}/messages")
async def list_messages(sid: UUID) -> dict:
    """Return persisted messages, oldest first, in the frontend's expected shape.

    Frontend contract — ``frontend/src/hooks/useChat.ts:25-30``:
    ``{ messages: [{id, role, content, created_at}] }``. The ``content``
    field is a flat string projected from the stored ``content_json``.
    """
    sm = get_sessionmaker()
    async with sm() as db:
        rows = (
            await db.execute(
                select(Message)
                .where(Message.session_id == sid)
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()
    return {
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": _content_from_json(m.content_json or {}),
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]
    }
