# Orchestration — reference

Compressed judgment layer over `orqest/orchestration/`. For full API + edge cases, read `docs/concepts/orchestration.md`.

## The Step protocol

All four primitives operate on `Step` — a minimal interface with `step_name` and `async execute(input_data)`. You rarely implement it. Auto-coercion in `_coerce_step()`:

| You pass | Becomes | When the body runs |
|---|---|---|
| `BaseAgent` | `AgentStep` | Fresh `GlobalState` per execution; input goes onto the state as a user message |
| `async callable` | `FunctionStep` | Called directly with `input_data`; output passed through |
| `Step` instance | used as-is | n/a |

## Choosing a primitive

| Shape | Use when |
|---|---|
| `Pipeline` | Output of step *N* feeds step *N+1*. Stable, ordered, linear. |
| `Parallel` | Same input fans out to *N* steps, merged into one result. Independent work. |
| `Router` | One input → exactly one of *N* branches, by rule or LLM classifier. |
| `RefinementLoop` | Iterate a step with evaluator feedback until pass / max-iter / timeout / converged. |

If the work is "decompose this novel goal into subtasks I don't know yet" — you don't want orchestration, you want `MetaOrchestrator` (see `autonomy.md`).

## Pipeline — minimal wire-up

```python
from orqest.orchestration import Pipeline, StepConfig, ErrorStrategy

pipeline = Pipeline(
    [
        clean_text,                                                           # async fn
        (researcher, StepConfig(on_error=ErrorStrategy.RETRY, max_retries=3)),  # agent + per-step config
        summariser,                                                           # defaults to STOP
    ],
    name="research-summary",
)
result = await pipeline.run("quantum computing")

# Streaming variant — yields PipelineEvent objects
async for event in pipeline.run_stream("..."):
    print(event.event_type, event.step_name)
# Event types: pipeline_start, step_start, step_complete, step_skip, step_error, pipeline_complete, pipeline_error
```

`ErrorStrategy`: `STOP` (raise `PipelineStepError`), `SKIP` (log + pass previous output through), `RETRY` (up to `max_retries`).

## Parallel — minimal wire-up

```python
from orqest.orchestration import Parallel, MergeStrategy

parallel = Parallel(
    [search_web, search_docs],
    merge=MergeStrategy.collect_all,    # or first_wins, or any Callable[[list], Any]
    timeout=10.0,
    name="search-fanout",
)
result = await parallel.run("quantum computing")
# result.outputs  → list (None per failed step)
# result.errors   → list (None per successful step; TimeoutError for cancelled)
# result.merged   → whatever the merge strategy returned
```

Timed-out tasks are cancelled and recorded in `errors`.

## Router — minimal wire-up

```python
from orqest.orchestration import Router, Route

# Rule-based — first matching condition wins
router = Router(
    routes=[
        Route("code",    handle_code,    condition=lambda q: "code" in q.lower()),
        Route("general", handle_general, condition=lambda q: True),
    ],
    name="topic-router",
)

# LLM-classifier driven
router = Router(
    routes=[Route("code", code_agent), Route("research", research_agent)],
    classifier=classifier_agent,        # agent's output: .route, .name, or str(result)
    fallback=general_agent,             # runs when no route matches; else RouterError
)
```

## RefinementLoop — minimal wire-up

```python
from orqest.orchestration import RefinementLoop, EvalResult

def evaluate(output: str) -> EvalResult:
    score = grade(output)
    return EvalResult(passed=score > 0.9, score=score, feedback=critique(output))

def update_state(current_input: str, output: str, eval_result: EvalResult) -> str:
    return f"{current_input}\n\nFeedback: {eval_result.feedback}\nPrevious: {output}"

loop = RefinementLoop(
    step=writer_agent,
    evaluator=evaluate,                  # sync fn | async fn | BaseAgent → EvalResult
    state_updater=update_state,
    max_iterations=5,
    timeout=30.0,
    convergence_window=3,                # detect plateau over last N scores
    convergence_threshold=0.01,
    # keep_best=True is the default — guards against self-regression
)
result = await loop.run("Write about quantum computing")
# result.exit_reason ∈ {"passed", "max_iterations", "timeout", "converged", "confident"}
# result.output      → best-scoring iteration's output (not necessarily the last)
# result.best_iteration / result.best_score → for transparency
```

### Keep-best safety (default ON)

Self-improving loops can regress. By default, on any non-`passed` exit, `RefinementLoop` returns the highest-scoring iteration's output, not the final one. `passed=True` early-exit always returns the passing iteration. Set `keep_best=False` to restore strict last-iteration semantics.

### Confidence-driven exit (metacognition handshake)

```python
loop = RefinementLoop(
    step=writer_agent,                       # carries a confidence_protocol
    agent_self_eval=writer_agent,            # SAME agent — synthesises EvalResult from EnrichedOutput.confidence
    confidence_threshold=0.85,
    state_updater=update_state,
    max_iterations=5,
)
# exit_reason="confident" when EnrichedOutput.confidence ≥ threshold
```

`agent_self_eval` requires the agent to carry a `confidence_protocol` — validated at construction.

## Agent-as-tool — two flavors

| Need | Use |
|---|---|
| One-shot stateless tool from an agent | `from orqest.agents import as_tool` |
| Stateful + evaluator-driven refinement *inside* a tool call | `from orqest.compound import SubAgentTool` |

```python
# Stateless — 90% case
tool = as_tool(researcher_agent, name="research", description="Look up facts.")

# Stateful + refinement
sub_tool = SubAgentTool(
    agent=writer_agent,
    executor=lambda state, output: output.draft,    # extract result
    state_updater=lambda state, output: state,      # fold back into parent state
    evaluator=quality_evaluator,                    # optional refinement gate
    max_iterations=3,
)
```

`SubAgentTool.run(use_enriched=True)` lifts the final-iteration `EnrichedOutput` confidence onto the `SubAgentResult` — useful when the parent agent decides whether to re-call.

## Pitfalls

- **Pipeline empty list raises** at construction. Always at least one step.
- **`StepConfig.on_error="retry"` retries with the same input** — it's not exception-tolerant; transient HTTP errors are the canonical use case.
- **Parallel timeout cancels tasks**, doesn't wait. The cancelled tasks' outputs appear as `None` in `outputs` with `TimeoutError` in `errors`.
- **Router with no matching route + no fallback** raises `RouterError`. Always set a fallback or guarantee one route is unconditional.
- **`RefinementLoop` with a boolean-only evaluator** disables keep-best (it needs numeric `score` to compare). That's by design — without a score, "best" is undefined.

## Where to read more

- `docs/concepts/orchestration.md` — full reference
- `docs/concepts/agent-as-tool.md` — `as_tool` deep dive
- `docs/concepts/sub-agent-tool.md` — `SubAgentTool` deep dive
- `docs/concepts/hooks-and-lifecycle.md` — `HookDecision` semantics at compound boundaries
- `notebooks/04_orchestrated_workflow.ipynb` — runnable end-to-end demo
