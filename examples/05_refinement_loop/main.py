"""Example 05 — RefinementLoop with confidence-threshold exit.

Demonstrates the Wave 1.3 metacognition integration: a writer agent that
self-rates its output via ``EnrichedOutput.confidence`` is wrapped in a
``RefinementLoop(confidence_threshold=0.85, agent_self_eval=writer)``.
The loop exits with ``exit_reason="confident"`` once the writer's own
confidence reaches the threshold, saving evaluator calls when the agent
already knows the draft is good enough.

Run::

    LLM_API_KEY=... LLM_MODEL=openai:gpt-4.1 \
        python examples/05_refinement_loop/main.py
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from orqest import RefinementLoop, load_config
from orqest.agents import BaseAgent, GlobalState
from orqest.metacognition import StructuredOutputProtocol


class Draft(BaseModel):
    """A single paragraph plus the agent's own confidence in it."""

    paragraph: str = Field(description="A single polished paragraph.")
    self_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Self-rated probability the paragraph satisfies the brief. "
            "Be conservative — set high (>=0.85) only when the paragraph "
            "is at least 50 words, contains specific evidence (numbers / "
            "dates / citations), and avoids filler words ('very', "
            "'really', 'just')."
        ),
    )
    uncertain_about: list[str] = Field(
        default_factory=list,
        description="Bullet list of remaining concerns (the bottleneck on confidence).",
    )


class WriterAgent(BaseAgent[GlobalState, Draft]):
    """Drafts a paragraph and self-rates confidence + uncertainty."""


def build_writer(*, model: str, api_key: str) -> WriterAgent:
    """Build a WriterAgent wired with StructuredOutputProtocol."""
    return WriterAgent(
        agent_name="writer",
        system_prompt=(
            "You are a precise technical writer. Write a single paragraph on "
            "the user's topic. Requirements:\n"
            "- At least 50 words\n"
            "- Include specific numbers, statistics, or dates as evidence\n"
            "- Avoid filler words: 'very', 'really', 'just'\n"
            "- Be substantive, not promotional\n"
            "If you receive feedback about a previous draft, revise the "
            "paragraph and update self_confidence + uncertain_about honestly."
        ),
        output_type=Draft,
        model=model,
        api_key=api_key,
        confidence_protocol=StructuredOutputProtocol(),
    )


def update_with_feedback(current_input: str, output: Draft, eval_result) -> str:
    """Feed the previous draft + the agent's own uncertainties back in."""
    bullets = (
        "\n- ".join(output.uncertain_about) if output.uncertain_about else "(none)"
    )
    return (
        f"Previous draft (self_confidence={output.self_confidence:.2f}):\n"
        f"{output.paragraph}\n\n"
        f"You flagged these uncertainties:\n- {bullets}\n\n"
        f"Revise the paragraph to resolve them. Keep the same topic. "
        f"Set self_confidence honestly — only mark >=0.85 when you're sure "
        f"the paragraph satisfies all requirements."
    )


async def main() -> None:
    """Run the refinement loop end-to-end and print the result."""
    config = load_config()

    writer = build_writer(model=config.llm_model, api_key=config.llm_api_key)

    # `agent_self_eval=writer` makes the loop synthesise an EvalResult from
    # the writer's own EnrichedOutput.confidence each iteration. The
    # `evaluator` slot is bypassed for scoring, so we pass a no-op callable.
    def _unused_evaluator(_output):  # noqa: ANN001, ANN202
        raise AssertionError("not called when agent_self_eval is set")

    loop = RefinementLoop(
        step=writer,
        evaluator=_unused_evaluator,
        state_updater=update_with_feedback,
        max_iterations=5,
        confidence_threshold=0.85,
        agent_self_eval=writer,
    )

    topic = (
        "Write a paragraph about the economic impact of large language "
        "models on the software industry, citing concrete adoption numbers."
    )
    result = await loop.run(topic)

    print(f"Exit reason: {result.exit_reason}")
    print(f"Iterations:  {result.iterations}\n")
    print("Final paragraph:\n")
    print(result.output.paragraph)
    print(f"\nFinal self_confidence: {result.output.self_confidence:.2f}")
    if result.output.uncertain_about:
        print("Remaining uncertainties:")
        for item in result.output.uncertain_about:
            print(f"  - {item}")
    print("\nIteration history:")
    for record in result.history:
        score = (
            f"{record.eval_result.score:.2f}"
            if record.eval_result.score is not None
            else "—"
        )
        passed = "passed" if record.eval_result.passed else "below threshold"
        print(
            f"  iter {record.iteration}: score={score} ({passed}) "
            f"in {record.duration_ms:.0f}ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
