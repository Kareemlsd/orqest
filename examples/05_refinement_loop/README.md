# Example 05 — RefinementLoop with confidence-threshold exit

Demonstrates the Wave 1.3 metacognition integration into `RefinementLoop`:

- A `WriterAgent` whose output type carries `self_confidence` (read for free by `StructuredOutputProtocol`)
- `RefinementLoop(confidence_threshold=0.85, agent_self_eval=writer)` — the loop synthesises an `EvalResult` from the writer's own `EnrichedOutput.confidence` each iteration
- Exit reason `"confident"` when the writer's self-rated confidence reaches `0.85`, saving evaluator calls

## Run

```bash
LLM_API_KEY=your_key LLM_MODEL=openai:gpt-4.1 \
    .venv/bin/python examples/05_refinement_loop/main.py
```

Or with a `.env` file at the repo root containing `LLM_API_KEY` + `LLM_MODEL`:

```bash
.venv/bin/python examples/05_refinement_loop/main.py
```

## What you'll see

```
Exit reason: confident   # (or "max_iterations" if the agent never reaches 0.85)
Iterations:  3

Final paragraph:
…

Final self_confidence: 0.92
Remaining uncertainties:
  - Some specific 2024 adoption figure I should verify

Iteration history:
  iter 1: score=0.65 (below threshold) in 2400ms
  iter 2: score=0.78 (below threshold) in 2100ms
  iter 3: score=0.92 (passed) in 1800ms
```

## What's happening

1. `RefinementLoop.run(topic)` calls `writer.run_enriched(...)` because `agent_self_eval=writer`
2. `StructuredOutputProtocol` lifts `self_confidence` off the `Draft` output
3. The synthetic `EvalResult(passed=False, score=enriched.confidence)` is checked against `confidence_threshold=0.85`
4. If `score >= 0.85`: exit with `exit_reason="confident"`
5. Otherwise: `update_with_feedback` produces the next prompt (incorporating the writer's own `uncertain_about` list) and the loop re-runs

## Variations

- **External critic** instead of self-eval: drop `agent_self_eval=...`, pass `evaluator=critic_agent` (a `BaseAgent` whose output is `EvalResult`-shaped)
- **Convergence detection**: add `convergence_window=2` to exit when scores stop improving
- **Hard timeout**: add `timeout=30.0` (seconds)

See [`docs/concepts/metacognition.md`](../../docs/concepts/metacognition.md) for the full picture of the `EnrichedOutput` + `ConfidenceProtocol` integration.
