"""Pluggable strategies for extracting an agent's self-assessment.

Three concrete implementations land here:

* :class:`StructuredOutputProtocol` — zero-extra-cost. Lifts confidence
  fields off the agent's own ``OutputT`` (duck-typed). Default choice.
* :class:`LLMSelfRatingProtocol` — +1 LLM call per turn. Asks the model
  to rate its own output post-turn. Used when ``OutputT`` cannot carry
  confidence fields.
* :class:`EnsembleProtocol` — +k–1 LLM calls. Samples the agent k times,
  computes confidence from agreement on the output. For high-stakes
  one-shot decisions where calibration matters more than cost.

All protocols swallow internal failures and surface them as
``EnrichedOutput(confidence=None, metadata={"protocol_error": ...})``
— never raise.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

from loguru import logger

from orqest.metacognition.enriched import EnrichedOutput

if TYPE_CHECKING:
    from orqest.agents.base_agent import BaseAgent

OutputT = TypeVar("OutputT")


@runtime_checkable
class ConfidenceProtocol(Protocol):
    """Strategy for extracting (or producing) an agent's self-assessment.

    Called by :meth:`BaseAgent.run_enriched` after the underlying
    ``_run_implementation`` has produced the ``OutputT``. The protocol
    returns the enriched payload. Failures are swallowed and surfaced
    as ``confidence=None`` — never raise.
    """

    name: str

    async def enrich(
        self,
        agent: "BaseAgent",
        state: Any,
        output: Any,
        **agent_kwargs: Any,
    ) -> EnrichedOutput[Any]:
        ...


# ---- helpers ----------------------------------------------------------


def _coerce_confidence(value: Any) -> float | None:
    """Best-effort coercion of a model-emitted confidence into ``[0, 1]``."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _default_agreement(samples: list[Any]) -> float:
    """Pairwise-agreement confidence for an ensemble.

    ``1.0`` when every sample is equal (under Pydantic ``model_dump``),
    ``0.0`` when all distinct, in-between by share of equal pairs.
    """
    if len(samples) < 2:
        return 1.0
    keys: list[str] = []
    for s in samples:
        try:
            if hasattr(s, "model_dump"):
                keys.append(json.dumps(s.model_dump(), sort_keys=True, default=str))
            else:
                keys.append(json.dumps(s, sort_keys=True, default=str))
        except Exception:
            keys.append(repr(s))
    n = len(keys)
    pairs = n * (n - 1) // 2
    matches = sum(
        1
        for i in range(n)
        for j in range(i + 1, n)
        if keys[i] == keys[j]
    )
    return matches / pairs if pairs > 0 else 1.0


# ---- StructuredOutputProtocol -----------------------------------------


class StructuredOutputProtocol:
    """Lift confidence fields off the agent's own output schema.

    Zero-extra-cost protocol. Consumers extend their ``OutputT`` with
    fields the protocol knows how to read::

        class MyOutput(BaseModel):
            answer: str
            self_confidence: float | None = None
            uncertain_about: list[str] = []
            outside_my_capability: bool = False

    Output models that don't declare these fields produce
    ``confidence=None`` — best-effort.
    """

    name = "structured"

    def __init__(
        self,
        *,
        confidence_field: str = "self_confidence",
        uncertainty_field: str = "uncertain_about",
        boundary_field: str = "outside_my_capability",
    ) -> None:
        self._cf = confidence_field
        self._uf = uncertainty_field
        self._bf = boundary_field

    async def enrich(
        self,
        agent: "BaseAgent",
        state: Any,
        output: Any,
        **agent_kwargs: Any,
    ) -> EnrichedOutput[Any]:
        confidence = _coerce_confidence(getattr(output, self._cf, None))
        targets = list(getattr(output, self._uf, None) or [])
        boundary = bool(getattr(output, self._bf, False))
        return EnrichedOutput(
            output=output,
            confidence=confidence,
            uncertainty_targets=targets,
            capability_boundary=boundary,
            protocol_name=self.name,
        )


# ---- LLMSelfRatingProtocol --------------------------------------------


class _SelfRating:
    """Internal structured output for the rater agent.

    Defined as a plain dataclass-ish class to avoid pulling Pydantic
    everywhere; the protocol uses duck-typing on the rater's response.
    """

    confidence: float | None
    uncertainty_targets: list[str]
    capability_boundary: bool


_DEFAULT_RATING_PROMPT = (
    "You just produced an output for a task. Reflect on it and rate it.\n\n"
    "TASK INPUT (most-recent user message):\n{state_summary}\n\n"
    "OUTPUT:\n{output_summary}\n\n"
    "Reply with JSON only: "
    '{{"confidence": <float 0-1>, "uncertainty_targets": [<strings>], '
    '"capability_boundary": <bool>}}'
)


class LLMSelfRatingProtocol:
    """Ask the model to rate its own output post-turn.

    Cost: +1 LLM call per agent turn. The protocol parses a JSON-shaped
    rating off the rater's reply; on parse failure or empty reply, falls
    back to ``confidence=None`` and stores the error in ``metadata``.
    """

    name = "llm_self_rating"

    def __init__(
        self,
        *,
        rating_prompt: str | None = None,
        summariser: Callable[[Any], str] | None = None,
    ) -> None:
        self._rating_prompt = rating_prompt or _DEFAULT_RATING_PROMPT
        self._summariser = summariser or (lambda x: str(x)[:1000])

    async def enrich(
        self,
        agent: "BaseAgent",
        state: Any,
        output: Any,
        **agent_kwargs: Any,
    ) -> EnrichedOutput[Any]:
        try:
            from pydantic_ai import Agent as PydanticAgent  # local import

            state_summary = self._summarise_state(state)
            output_summary = self._summariser(output)
            prompt = self._rating_prompt.format(
                state_summary=state_summary, output_summary=output_summary
            )

            rater = PydanticAgent(
                model=agent.model,
                output_type=str,
                system_prompt=(
                    "You are a careful self-rater. Reply ONLY with the JSON "
                    "object requested. No prose, no markdown fences."
                ),
            )
            result = await rater.run(prompt)
            payload = self._parse_rating(result.output)
        except Exception as exc:
            logger.debug("LLMSelfRatingProtocol failed: {e}", e=exc)
            return EnrichedOutput(
                output=output,
                protocol_name=self.name,
                metadata={"protocol_error": type(exc).__name__},
            )

        return EnrichedOutput(
            output=output,
            confidence=_coerce_confidence(payload.get("confidence")),
            uncertainty_targets=[
                str(t) for t in (payload.get("uncertainty_targets") or [])
            ],
            capability_boundary=bool(payload.get("capability_boundary", False)),
            protocol_name=self.name,
        )

    @staticmethod
    def _parse_rating(text: str) -> dict[str, Any]:
        text = text.strip()
        # Strip markdown code fences if model added them despite instructions.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)

    def _summarise_state(self, state: Any) -> str:
        # Best-effort: GlobalState exposes get_latest_message; fall back to repr.
        try:
            latest = state.get_latest_message("user")
        except Exception:
            latest = None
        if latest:
            return self._summariser(latest)
        return self._summariser(state)


# ---- EnsembleProtocol -------------------------------------------------


class EnsembleProtocol:
    """Sample the agent k times, compute confidence from agreement.

    Confidence is the share of pairs of samples that match (under
    Pydantic ``model_dump``). The output of the *first* sample is
    returned alongside the confidence score — confidence is a *signal
    about* the output, not a way to swap outputs.

    Cost: +k–1 LLM calls. Samples run in parallel via :func:`asyncio.gather`.
    """

    name = "ensemble"

    def __init__(
        self,
        k: int = 3,
        *,
        agreement_fn: Callable[[list[Any]], float] | None = None,
    ) -> None:
        if k < 2:
            raise ValueError("EnsembleProtocol requires k >= 2")
        self._k = k
        self._agreement_fn = agreement_fn or _default_agreement

    async def enrich(
        self,
        agent: "BaseAgent",
        state: Any,
        output: Any,
        **agent_kwargs: Any,
    ) -> EnrichedOutput[Any]:
        import asyncio

        try:
            extra = await asyncio.gather(
                *[
                    agent._run_implementation(state, **agent_kwargs)
                    for _ in range(self._k - 1)
                ],
                return_exceptions=True,
            )
        except Exception as exc:
            logger.debug("EnsembleProtocol failed during sampling: {e}", e=exc)
            return EnrichedOutput(
                output=output,
                protocol_name=self.name,
                metadata={"protocol_error": type(exc).__name__},
            )

        successes: list[Any] = [output]
        for result in extra:
            if isinstance(result, BaseException):
                continue
            successes.append(result)

        confidence = (
            self._agreement_fn(successes) if len(successes) >= 2 else None
        )
        return EnrichedOutput(
            output=output,
            confidence=confidence,
            protocol_name=self.name,
            metadata={"sample_count": len(successes), "k": self._k},
        )
