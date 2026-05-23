# Orchestration

Orqest provides four orchestration primitives for composing agents into workflows: **Pipeline** (sequential), **Parallel** (concurrent), **Router** (conditional), and **RefinementLoop** (iterative). All operate on the `Step` protocol, meaning agents and plain async functions are interchangeable.

## The Step Protocol

Every orchestration primitive works with `Step` -- a minimal interface requiring a `step_name` property and an async `execute(input_data)` method.

You rarely implement `Step` directly. Pass a `BaseAgent` or an async function and it gets auto-coerced:

```python
from orqest.orchestration import Pipeline, FunctionStep

# BaseAgent → automatically wrapped as AgentStep
# async function → automatically wrapped as FunctionStep
# Both satisfy the Step protocol

async def clean_text(data: str) -> str:
    return data.strip().lower()

pipeline = Pipeline([clean_text, my_agent])
```

| Type | What happens |
|------|-------------|
| `BaseAgent` | Wrapped in `AgentStep` -- creates a fresh `GlobalState` per execution |
| `async callable` | Wrapped in `FunctionStep` -- called directly with `input_data` |
| `Step` instance | Used as-is |

## Pipeline

Runs steps sequentially, feeding each step's output as the next step's input.

```python
import asyncio
from orqest.orchestration import Pipeline, StepConfig, ErrorStrategy


async def fetch_data(query: str) -> str:
    return f"Raw data for: {query}"

async def summarize(data: str) -> str:
    return f"Summary of: {data}"


async def main():
    pipeline = Pipeline(
        [
            fetch_data,
            summarize,
        ],
        name="research",
    )
    result = await pipeline.run("quantum computing")
    print(result)  # "Summary of: Raw data for: quantum computing"


asyncio.run(main())
```

### Error Strategies

Each step can have its own error strategy via `StepConfig`:

```python
pipeline = Pipeline([
    (fetch_data, StepConfig(name="fetch", on_error=ErrorStrategy.RETRY, max_retries=3)),
    (summarize, StepConfig(name="summarize", on_error=ErrorStrategy.SKIP)),
    validate,  # defaults to ErrorStrategy.STOP
])
```

| Strategy | Behavior |
|----------|----------|
| `STOP` | Raise `PipelineStepError` immediately (default) |
| `SKIP` | Log and skip to the next step, passing the previous output through |
| `RETRY` | Retry up to `max_retries` times before raising |

### Streaming Events

Use `run_stream()` to observe pipeline execution in real time:

```python
async for event in pipeline.run_stream("input"):
    print(f"{event.event_type}: {event.step_name}")
```

Events: `pipeline_start`, `step_start`, `step_complete`, `step_skip`, `step_error`, `pipeline_complete`, `pipeline_error`.

## Parallel

Runs steps concurrently and merges results.

```python
import asyncio
from orqest.orchestration import Parallel, MergeStrategy


async def search_web(query: str) -> str:
    return f"Web result for: {query}"

async def search_docs(query: str) -> str:
    return f"Docs result for: {query}"


async def main():
    parallel = Parallel(
        [search_web, search_docs],
        merge=MergeStrategy.collect_all,
        timeout=10.0,
        name="search",
    )
    result = await parallel.run("quantum computing")
    print(result.merged)    # ["Web result for: ...", "Docs result for: ..."]
    print(result.errors)    # [None, None] — no errors


asyncio.run(main())
```

### Merge Strategies

| Strategy | Behavior |
|----------|----------|
| `MergeStrategy.collect_all` | Return all successful results as a list (default) |
| `MergeStrategy.first_wins` | Return the first successful result |
| Custom callable | Any `Callable[[list[Any]], Any]` |

The `ParallelResult` contains `outputs` (per-step, `None` on failure), `errors` (per-step, `None` on success), and `merged` (the merge strategy result).

Timed-out tasks are cancelled and recorded as `TimeoutError` in `errors`.

## Router

Routes input to a single step based on conditions or an LLM classifier.

### Rule-Based Routing

```python
import asyncio
from orqest.orchestration import Router, Route


async def handle_code(query: str) -> str:
    return f"Code answer: {query}"

async def handle_general(query: str) -> str:
    return f"General answer: {query}"


async def main():
    router = Router(
        routes=[
            Route("code", handle_code, condition=lambda q: "code" in q.lower()),
            Route("general", handle_general, condition=lambda q: True),
        ],
        name="topic_router",
    )
    result = await router.run("Write code for sorting")
    print(result)  # "Code answer: Write code for sorting"


asyncio.run(main())
```

Routes are evaluated in order -- first match wins.

### LLM-Driven Routing

Pass a `classifier` agent that returns the route name:

```python
router = Router(
    routes=[
        Route("code", code_agent),
        Route("research", research_agent),
        Route("creative", creative_agent),
    ],
    classifier=classifier_agent,
    fallback=general_agent,
)
```

The classifier agent's output is duck-typed: if it has a `route` or `name` attribute, that value is used as the route name. Otherwise `str(result)` is used.

A `fallback` step runs when no route matches. Without a fallback, `RouterError` is raised.

## RefinementLoop

Iterates a step with evaluation feedback until the output passes, max iterations are reached, the timeout expires, or scores converge.

```python
import asyncio
from orqest.orchestration import RefinementLoop, EvalResult


async def write_draft(prompt: str) -> str:
    return f"Draft based on: {prompt}"

def evaluate(output: str) -> EvalResult:
    score = 0.8 if "draft" in output.lower() else 0.3
    return EvalResult(
        passed=score > 0.9,
        feedback="Needs more detail" if score <= 0.9 else "Good",
        score=score,
    )

def update_state(current_input: str, output: str, eval_result: EvalResult) -> str:
    return f"{current_input}\n\nFeedback: {eval_result.feedback}\nPrevious: {output}"


async def main():
    loop = RefinementLoop(
        step=write_draft,
        evaluator=evaluate,
        state_updater=update_state,
        max_iterations=5,
        timeout=30.0,
        convergence_window=3,
        convergence_threshold=0.01,
    )
    result = await loop.run("Write about quantum computing")
    print(f"Exit: {result.exit_reason}, Iterations: {result.iterations}")
    for record in result.history:
        print(f"  #{record.iteration}: passed={record.eval_result.passed}, "
              f"score={record.eval_result.score}, {record.duration_ms:.0f}ms")


asyncio.run(main())
```

### Exit Conditions

| Reason | Trigger |
|--------|---------|
| `"passed"` | Evaluator returns `EvalResult(passed=True)` |
| `"max_iterations"` | Reached the configured limit |
| `"timeout"` | Wall-clock time exceeded |
| `"converged"` | Scores within `convergence_window` vary less than `convergence_threshold` |

### Evaluators

The evaluator can be:

- A sync function returning `EvalResult`
- An async function returning `EvalResult`
- A `BaseAgent` whose output is treated as `EvalResult`

### What's Happening Under the Hood

1. The step executes with the current input
2. The evaluator scores the output, producing `EvalResult`
3. If passed, return. If not, `state_updater(current_input, output, eval_result)` produces the next input
4. Convergence detection checks if recent scores are plateauing (optional)
5. Repeat until an exit condition triggers

`LoopResult` contains the final `output`, `iterations` count, `exit_reason`, and full `history` of `IterationRecord` objects, plus `best_iteration` and `best_score` (see Keep-Best Safety below).

### Keep-Best Safety (default ON)

Self-improving loops on imperfect models can *regress*: the step proposes a revised candidate that scores worse than a prior one. To protect against this, `RefinementLoop` defaults to `keep_best=True`:

- Across iterations, the loop tracks the candidate that achieved the highest `EvalResult.score`.
- On any non-`passed` exit (`max_iterations`, `converged`, `timeout`), if the final iteration's score is strictly *less* than the best seen, the loop returns the *best* iteration's output instead of the final one.
- The `passed=True` early exit always returns the passing iteration's output — passing is the explicit success bar and overrides keep-best.
- When the evaluator never returns a numeric `score` (boolean-only `passed`/`feedback`), keep-best is a no-op: the legacy "return latest output" behavior holds.
- `LoopResult.best_iteration` and `best_score` are always populated for transparency (even with `keep_best=False`) so callers can diagnose regressions.

```python
loop = RefinementLoop(
    step=coder,
    evaluator=run_visible_tests,  # returns EvalResult(passed=False, score=fraction_passing)
    state_updater=feed_failures_to_fixer,
    max_iterations=3,
    # keep_best=True is the default — no need to set it
)
result = await loop.run(problem)
# result.output is the highest-scoring iteration, not necessarily the last
# result.best_iteration tells you which iteration that was
```

**Migration:** set `RefinementLoop(..., keep_best=False)` to restore strict last-iteration semantics for callers that depend on it.

## Related Concepts

- [Agents](agents.md) -- the `BaseAgent` that orchestration primitives wrap
- [Hooks & Lifecycle](hooks-and-lifecycle.md) -- fire-and-forget callbacks for tool execution
- [Agent as Tool](agent-as-tool.md) -- lightweight single-agent composition

## Runnable demo

[`notebooks/04_orchestrated_workflow.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/04_orchestrated_workflow.ipynb) — Router → Parallel → Pipeline → RefinementLoop with `Workbench` carrying tracer + bus.
