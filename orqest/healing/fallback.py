"""Model-failover primitive.

:class:`FallbackModel` subclasses :class:`pydantic_ai.models.Model` and
delegates :meth:`request` / :meth:`request_stream` to a chain of
underlying models. Transient failures advance to the next model in the
chain; non-transient failures (auth, validation) propagate immediately.

:func:`resolve_model_with_fallback` is the friendly entry point — pass
a list of ``provider:model_id`` strings and a key (or per-provider
key map), get back a :class:`Model` you can hand to
:class:`pydantic_ai.Agent`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from orqest.observability.events import AgentEvent, EventBus
from orqest.utils.llm_model import resolve_model

ApiKeyArg = str | dict[str, str]
"""Accept either a single key or a ``{provider: key}`` mapping."""


def _default_transient_predicate(exc: BaseException) -> bool:
    """Best-effort identification of transient failures.

    Treats network, timeout, rate-limit, and 5xx as transient. Refuses
    to treat ValidationError / AuthenticationError as transient even
    when their class names are imported from third-party SDKs we don't
    have at lint time. Class-name string matching keeps us SDK-neutral.
    """
    name = type(exc).__name__
    non_transient = {
        "ValidationError",
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "InvalidRequestError",
    }
    if name in non_transient:
        return False
    transient = {
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutException",
        "RateLimitError",
        "ServiceUnavailableError",
        "InternalServerError",
        "ModelHTTPError",
        "APITimeoutError",
        "APIConnectionError",
    }
    if name in transient:
        return True
    # Default: treat any unknown exception as transient — the chain
    # falls back rather than failing closed. Errors logged at WARN.
    return True


def resolve_model_with_fallback(
    models: list[str],
    *,
    api_key: ApiKeyArg,
    bus: EventBus | None = None,
    transient_predicate: Callable[[BaseException], bool] | None = None,
) -> Model:
    """Resolve a chain of ``provider:model_id`` strings into a single
    :class:`FallbackModel`.

    Resolution failures (unknown provider, missing SDK, missing per-
    provider key) are logged at DEBUG and skipped. The chain remains
    valid as long as *one* entry resolves; raises ``ValueError`` if
    none do.

    Args:
        models: Ordered list — first is primary.
        api_key: Single key (used for every provider) or per-provider map.
        bus: Optional :class:`EventBus`. Emits ``healing.model_fallback``
            on each chain advance.
        transient_predicate: Override the default classifier.
    """
    resolved: list[Model] = []
    for spec in models:
        provider = spec.split(":", 1)[0]
        key = api_key if isinstance(api_key, str) else api_key.get(provider, "")
        if not key:
            logger.debug("No API key for provider {p}; skipping {s}", p=provider, s=spec)
            continue
        try:
            resolved.append(resolve_model(spec, api_key=key))
        except Exception as exc:
            logger.debug("resolve_model({s}) failed: {e}; skipping", s=spec, e=exc)
    if not resolved:
        raise ValueError(
            f"No model in {models!r} could be resolved. "
            "Check provider names and api_key map."
        )
    return FallbackModel(
        resolved, bus=bus, transient_predicate=transient_predicate
    )


class FallbackModel(Model):
    """pydantic-AI :class:`Model` wrapping a chain of fallback models.

    On transient failure during :meth:`request` or
    :meth:`request_stream`, advances ``_idx`` to the next model. The
    advance is *sticky* across requests in the same instance — once the
    primary failed, subsequent calls go straight to the fallback.
    Non-transient failures propagate.
    """

    def __init__(
        self,
        models: list[Model],
        *,
        bus: EventBus | None = None,
        transient_predicate: Callable[[BaseException], bool] | None = None,
    ) -> None:
        super().__init__()
        if not models:
            raise ValueError("FallbackModel requires at least one underlying model")
        self._models = list(models)
        self._bus = bus
        self._is_transient = transient_predicate or _default_transient_predicate
        self._idx = 0

    @property
    def model_name(self) -> str:
        names = ",".join(m.model_name for m in self._models)
        return f"fallback({names})"

    @property
    def system(self) -> str:
        return self._models[self._idx].system

    @property
    def active_model(self) -> Model:
        """The currently-active underlying model."""
        return self._models[self._idx]

    async def _emit_fallback(
        self, from_idx: int, to_idx: int, exc: BaseException
    ) -> None:
        if self._bus is None:
            return
        to_name = (
            self._models[to_idx].model_name if to_idx < len(self._models) else None
        )
        await self._bus.emit(
            AgentEvent(
                event_type="healing.model_fallback",
                agent_name="fallback_model",
                data={
                    "from": self._models[from_idx].model_name,
                    "to": to_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:200],
                },
            )
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        last_exc: BaseException | None = None
        for i in range(self._idx, len(self._models)):
            try:
                return await self._models[i].request(
                    messages, model_settings, model_request_parameters
                )
            except Exception as exc:
                last_exc = exc
                if not self._is_transient(exc):
                    raise
                await self._emit_fallback(i, i + 1, exc)
                self._idx = i + 1
        await self._emit_chain_exhausted(last_exc)
        raise RuntimeError(
            f"All fallback models exhausted; last error: {last_exc}"
        ) from last_exc

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncIterator[Any]:
        """Streaming variant. Mid-stream errors propagate (we may have
        already yielded chunks). Only pre-stream failures fall back."""
        last_exc: BaseException | None = None
        for i in range(self._idx, len(self._models)):
            try:
                async with self._models[i].request_stream(
                    messages, model_settings, model_request_parameters, run_context
                ) as stream:
                    yield stream
                return
            except Exception as exc:
                last_exc = exc
                if not self._is_transient(exc):
                    raise
                await self._emit_fallback(i, i + 1, exc)
                self._idx = i + 1
        await self._emit_chain_exhausted(last_exc)
        raise RuntimeError(
            f"All fallback models exhausted (stream); last error: {last_exc}"
        ) from last_exc

    async def _emit_chain_exhausted(self, last_exc: BaseException | None) -> None:
        """Emit a typed exhaustion event before raising the RuntimeError.

        The chrome's healing toast can render a clear "tried X, Y, Z;
        all failed" message instead of guessing from the underlying
        error string.
        """
        if self._bus is None:
            return
        try:
            await self._bus.emit(
                AgentEvent(
                    event_type="healing.model_chain_exhausted",
                    agent_name="fallback_model",
                    data={
                        "models_tried": [m.model_name for m in self._models],
                        "last_error_type": type(last_exc).__name__
                        if last_exc is not None
                        else None,
                        "last_error": str(last_exc)[:200] if last_exc else None,
                    },
                )
            )
        except Exception:  # noqa: BLE001 — never block the raise
            pass
