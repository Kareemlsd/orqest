# Notebooks

Thematic, narrative notebooks that show Orqest primitives **composed** into
something whole. Where [`examples/`](../examples/) has one notebook per
primitive (basic agent, streaming, pipeline, …), these weave several
primitives together to tell an end-to-end story.

They are **real-LLM** notebooks — they call your configured model. Running
them is also the project's empirical dogfooding pass: a notebook that won't
run cleanly is a bug report.

## Recommended reading order — if you're evaluating Orqest

A skeptical engineer already comfortable with LLM orchestration (DSPy /
LangGraph / CrewAI / AutoGen) should follow this tour. It's ordered to put
the strongest evidence first: the combo notebook is the architecture proving
itself on a real benchmark, then we drill into each pillar individually.

| # | Notebook | What's surprising |
|---|----------|-------------------|
| 1 | [`12_combo_autonomous_coder.ipynb`](12_combo_autonomous_coder.ipynb) | **The full combo on a real benchmark, with a measured win.** Designer agent picks the topology per problem → `AgentFactory.spawn(AgentSpec)` hydrates coder + fixer dynamically → `GeneratedToolSpec` + `SubprocessSandbox` spawn a fresh test-runner tool per iteration. **Beats single-shot baseline by +17pp pass@1 / +14pp test_pass_rate** on a 10-problem coding benchmark (averaged over 3 trials; same model both sides). Zero regressions. |
| 2 | [`10_runtime_topology.ipynb`](10_runtime_topology.ipynb) | **Topology design in isolation.** `RuntimeTopologyDesigner` synthesises a `TopologyDesign` per request; `MemoryStoreCache` reuses for similar future requests. The "I didn't write that, the framework did" moment. |
| 3 | [`02_meta_orchestrator.ipynb`](02_meta_orchestrator.ipynb) | **Specialists spawn themselves.** `MetaOrchestrator` decomposes a goal into `AgentSpec`s; `AgentFactory` hydrates them into live `BaseAgent`s. |
| 4 | [`11_dynamic_tools.ipynb`](11_dynamic_tools.ipynb) | **Tools materialise at runtime.** `GeneratedToolSpec` → `DynamicToolFactory` → `Sandbox`. Three sandbox tiers (`InProcessSandbox` → `SubprocessSandbox` → `DockerSandbox`) for the safety objection. |
| 5 | [`04_orchestrated_workflow.ipynb`](04_orchestrated_workflow.ipynb) | **The connective tissue, by hand.** Router → Parallel → Pipeline → RefinementLoop with `Workbench` carrying tracer + bus. |
| 6 | [`01_cognitive_substrate.ipynb`](01_cognitive_substrate.ipynb) | **And the agents know when they're struggling.** `run_enriched` → `metacognition.confidence` → `RegressionDetector` → `WatchdogHook` → `FallbackModel`. |

If you have **5 minutes**, open notebook 12 and skip to section 7 ("Head-to-head") —
that's the measured win in one table.

## All notebooks

| Notebook | Theme | Primitives composed |
|----------|-------|---------------------|
| [`01_cognitive_substrate.ipynb`](01_cognitive_substrate.ipynb) ★ | An agent that knows when it's struggling | `run_enriched` · `ConfidenceProtocol` · `MetacognitionHook` · `RegressionDetector` · `WatchdogHook` · `FallbackModel` |
| [`02_meta_orchestrator.ipynb`](02_meta_orchestrator.ipynb) ★ | Decompose a goal, spawn specialists at runtime | `AgentSpec` · `AgentFactory` · `ToolRegistry` · `MetaOrchestrator` · `LocalMemoryStore` |
| [`03_generative_ui.ipynb`](03_generative_ui.ipynb) | Agents that design their own surface | `Workbench` · `ComponentRegistry` · `UIEmitter` · `ExecutionPlan` · `sse_sidecar` |
| [`04_orchestrated_workflow.ipynb`](04_orchestrated_workflow.ipynb) ★ | Route, fan out, chain, refine — with observability | `Router` · `Parallel` · `Pipeline` · `RefinementLoop` · `Workbench` · `JSONTracer` |
| [`05_reasoning.ipynb`](05_reasoning.ipynb) | Let the model think harder — one provider-agnostic knob | `reasoning` · `resolve_reasoning_settings` · `BaseAgent` · `Pipeline` |
| [`06_optimization_basic.ipynb`](06_optimization_basic.ipynb) | Evolve a research summariser's prompt against a 15-example gold set | `OptimizationRunner` · `Genome` · `PromptGene` · `Evaluator` · `MetricBundle` · `apply_result` |
| [`07_optimization_compound.ipynb`](07_optimization_compound.ipynb) | Evolve the planner inside `MetaOrchestrator` and watch the orchestration improve downstream | `OptimizationRunner` · `MetaOrchestrator` · `PlannerAgent` · `apply_result` |
| [`08_topology_search_basic.ipynb`](08_topology_search_basic.ipynb) | ADAS-style structural search — meta agent designs Pipeline / Parallel / Router compositions | `TopologyGene` · `TopologyEvaluator` · `MetaAgentSearch` · `PipelineSpec` · `CallableRegistry` · `apply_result` |
| [`09_topology_with_gepa.ipynb`](09_topology_with_gepa.ipynb) | Two-phase: discover topology (Phase 1) then evolve prompts on the winner (Phase 2). Full ablation table. | `MetaAgentSearch` + `OptimizationRunner` (composed) |
| [`10_runtime_topology.ipynb`](10_runtime_topology.ipynb) ★ | Per-request topology synthesis with semantic-cache reuse + seed-library bootstrap + online learning via reliability decay | `RuntimeTopologyDesigner` · `TopologyOrchestrator` · `MemoryStoreCache` · `TopologyDesign` |
| [`11_dynamic_tools.ipynb`](11_dynamic_tools.ipynb) ★ | Spawn `pydantic_ai.Tool`s at runtime from `GeneratedToolSpec` (implementation included), bind to agents, mix with pre-registered tools. End-to-end real-LLM run uses a tool the LLM didn't have at construction. | `Sandbox` · `InProcessSandbox` · `SubprocessSandbox` · `GeneratedToolSpec` · `DynamicToolFactory` · `BaseAgent.add_tool` |
| [`12_combo_autonomous_coder.ipynb`](12_combo_autonomous_coder.ipynb) ★ | **The combo end-to-end with a measured win.** Designer + AgentFactory + GeneratedToolSpec + SubprocessSandbox + refinement loop on a 10-problem coding benchmark. Same model both sides; combo beats single-shot baseline by +17pp pass@1 / +14pp test_pass_rate (3-trial average). | `RuntimeTopologyDesigner` ish · `AgentFactory.spawn(AgentSpec)` · `DynamicToolFactory` · `GeneratedToolSpec` · `SubprocessSandbox` |

★ = part of the 6-notebook evaluation tour.

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

## Verification status

All 12 notebooks were re-executed top-to-bottom against the current API on
**2026-05-16** with `jupyter nbconvert --execute`. Every notebook completed
cleanly (exit 0). Cell outputs are committed; reviewing the diff will show
real-LLM output drift between runs, which is expected — semantic content
is unchanged. Notebook 12's head-to-head numbers are pre-computed from
3-trial averages via `scratch/combo/run_trials.py` and embedded in the
notebook; the live cells exercise the mechanism but not the full benchmark.

If a notebook stops running cleanly, treat that as a bug report: open an
issue with the broken cell + traceback before patching the notebook.
