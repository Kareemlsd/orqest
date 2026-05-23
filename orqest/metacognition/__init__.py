"""Metacognition primitives — confidence, uncertainty, capability boundary.

The cognitive substrate for agents that know what they don't know. See
``docs/concepts/metacognition.md`` for the full picture; this module hosts:

* :class:`EnrichedOutput[OutputT]` — the runtime type that pairs an
  output with the agent's self-assessment of it.
* :class:`ConfidenceProtocol` — pluggable strategy for producing the
  assessment (zero-cost :class:`StructuredOutputProtocol`, +1-call
  :class:`LLMSelfRatingProtocol`, +k-call :class:`EnsembleProtocol`).
* :class:`MetacognitionHook` — :class:`ToolHook` bridge to
  :class:`EventBus`.
* :class:`MetacognitionConfig` — frozen orchestration policy.
* :func:`confidence_salience` — salience scorer for
  :class:`ContextManager` integration.
"""

from orqest.metacognition.config import MetacognitionConfig
from orqest.metacognition.enriched import EnrichedOutput
from orqest.metacognition.hook import MetacognitionHook
from orqest.metacognition.protocol import (
    ConfidenceProtocol,
    EnsembleProtocol,
    LLMSelfRatingProtocol,
    StructuredOutputProtocol,
)
from orqest.metacognition.salience import confidence_salience, recency_salience

__all__ = [
    "ConfidenceProtocol",
    "EnrichedOutput",
    "EnsembleProtocol",
    "LLMSelfRatingProtocol",
    "MetacognitionConfig",
    "MetacognitionHook",
    "StructuredOutputProtocol",
    "confidence_salience",
    "recency_salience",
]
