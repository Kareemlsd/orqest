# Examples

**If you're evaluating Orqest, start with the [notebooks/](../notebooks/) —
those are the composed, end-to-end stories the framework was built for.**

This directory is the **primitive reference**: one notebook (or script) per
building block, in isolation. When the notebooks compose something and you
need to drill into one piece, jump here.

## What's here

| # | Example | Primitive | Composed in… |
|---|---------|-----------|--------------|
| 01 | [`01_basic_agent/basic_agent.ipynb`](01_basic_agent/basic_agent.ipynb) | `BaseAgent[StateT, OutputT]`, `GlobalState`, multi-turn `call_model()` | every tour notebook |
| 02 | [`02_agent_as_tool/agent_as_tool.ipynb`](02_agent_as_tool/agent_as_tool.ipynb) | `as_tool()` — wrap an agent as a `pydantic_ai.Tool` | tour notebook 02 |
| 03 | [`03_streaming/streaming.ipynb`](03_streaming/streaming.ipynb) | `stream_output()` (partial structured) · `call_model_stream()` (raw tokens) · `stream_events()` (tool-call visibility) | — (independent feature) |
| 04 | [`04_pipeline/pipeline.ipynb`](04_pipeline/pipeline.ipynb) + [`executed_pipeline.ipynb`](04_pipeline/executed_pipeline.ipynb) | `Pipeline` (sequential) · `RefinementLoop` (evaluator-driven) · `ErrorStrategy` | tour notebook 04 |
| 05 | [`05_refinement_loop/main.py`](05_refinement_loop/main.py) + [`README`](05_refinement_loop/README.md) | `RefinementLoop(confidence_threshold=..., agent_self_eval=...)` — self-rated exit (Python script, not a notebook) | tour notebook 01 (metacognition) |
| 06 | [`06_parallel_and_router/parallel_and_router.ipynb`](06_parallel_and_router/parallel_and_router.ipynb) + [`executed_parallel.ipynb`](06_parallel_and_router/executed_parallel.ipynb) | `Parallel` (concurrent + merge) · `Router` (rule-based + classifier-based) | tour notebook 04 |
| 07 | [`07_hooks_and_session/hooks_and_session.ipynb`](07_hooks_and_session/hooks_and_session.ipynb) + [`executed_hooks.ipynb`](07_hooks_and_session/executed_hooks.ipynb) | `HookRunner` · `BaseSessionState` (serialise/deserialise) · `CompoundTool` | tour notebooks 10, 11 (caches + hooks) |
| 08 | [`08_memory/memory.ipynb`](08_memory/memory.ipynb) | `LocalMemoryStore` (SQLite + FTS5) · `MemoryEntry` · `MemoryFilter` · reliability decay | tour notebooks 02, 10 (cache backend) |
| 09 | [`09_observability/observability.ipynb`](09_observability/observability.ipynb) | `JSONTracer` (in-memory span tree) · `EventBus` (pub/sub) · `AgentEvent` | tour notebook 04 |

## Format note

Most examples are `.ipynb` notebooks runnable in Jupyter Lab. Example 05 is
a Python script (`main.py`) — same purpose, different format. It exercises
the metacognition-integrated `RefinementLoop` variant where the agent's own
`self_confidence` field drives loop exit.

## Running

Each example is self-contained and uses your configured model via the same
`.env` setup the notebooks use (`LLM_API_KEY` + `LLM_MODEL`). See the
[root README](../README.md#install) for the install instructions.

For notebooks:
```bash
uv sync --group notebooks
uv run jupyter lab examples/
```

For example 05's script:
```bash
.venv/bin/python examples/05_refinement_loop/main.py
```
