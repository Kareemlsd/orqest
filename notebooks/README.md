# Notebooks

Thematic, narrative notebooks that show Orqest primitives **composed** into
something whole. Where [`examples/`](../examples/) has one notebook per
primitive (basic agent, streaming, pipeline, …), these weave several
primitives together to tell an end-to-end story.

They are **real-LLM** notebooks — they call your configured model. Running
them is also the project's empirical dogfooding pass: a notebook that won't
run cleanly is a bug report.

| Notebook | Theme | Primitives composed |
|----------|-------|---------------------|
| [`01_cognitive_substrate.ipynb`](01_cognitive_substrate.ipynb) | An agent that knows when it's struggling | `run_enriched` · `ConfidenceProtocol` · `MetacognitionHook` · `RegressionDetector` · `WatchdogHook` · `FallbackModel` |
| [`02_meta_orchestrator.ipynb`](02_meta_orchestrator.ipynb) | Decompose a goal, spawn specialists at runtime | `AgentSpec` · `AgentFactory` · `ToolRegistry` · `MetaOrchestrator` · `LocalMemoryStore` |
| [`03_generative_ui.ipynb`](03_generative_ui.ipynb) | Agents that design their own surface | `Workbench` · `ComponentRegistry` · `UIEmitter` · `ExecutionPlan` · `sse_sidecar` |
| [`04_orchestrated_workflow.ipynb`](04_orchestrated_workflow.ipynb) | Route, fan out, chain, refine — with observability | `Router` · `Parallel` · `Pipeline` · `RefinementLoop` · `Workbench` · `JSONTracer` |

## Running them

1. Put `LLM_API_KEY` and `LLM_MODEL` in a `.env` file at the repo root
   (see the main [README](../README.md#install)).
2. Install the notebook tooling and a kernel:
   ```bash
   uv sync --group notebooks
   uv run jupyter lab notebooks/
   ```
3. Run a notebook top to bottom. Each is self-contained.

## Scope

These notebooks exercise the **Tier-1 surface** — the primitives that work
end-to-end. Capabilities still labelled **Preview** (online MCP discovery,
the Supabase memory backend, embedding-based retrieval) are out of scope
until they are wired in the Advance phase; see [`CHANGELOG.md`](../CHANGELOG.md)
`[0.3.0]`.
