# Notebooks

Real-LLM narrative notebooks that show Orqest primitives **composed** into
something whole. They live in [`notebooks/`](https://github.com/Kareemlsd/orqest/tree/main/notebooks)
in the repo and are best read in Jupyter Lab — see the
[notebooks README](https://github.com/Kareemlsd/orqest/blob/main/notebooks/README.md)
for setup.

## Recommended reading order — for engineers evaluating Orqest

A skeptical engineer should follow this tour. Notebook 12 leads because it's
the architecture proving itself end-to-end with a measured win on a real
benchmark. The other tour notebooks drill into each pillar individually.

| # | Notebook | What's surprising |
|---|----------|-------------------|
| 1 | [`12_combo_autonomous_coder.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/12_combo_autonomous_coder.ipynb) | **The full combo with a measured win.** Designer agent picks the topology, `AgentFactory` spawns coder+fixer from `AgentSpec`, `GeneratedToolSpec` + `SubprocessSandbox` run each iteration's tests dynamically. Beats single-shot baseline by **+17pp pass@1 / +14pp test_pass_rate** on a 10-problem coding benchmark (same model, 3-trial average). Zero regressions. |
| 2 | [`10_runtime_topology.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/10_runtime_topology.ipynb) | Topology design in isolation. `RuntimeTopologyDesigner` synthesises a shape per request; `MemoryStoreCache` reuses for similar future requests. |
| 3 | [`02_meta_orchestrator.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/02_meta_orchestrator.ipynb) | Specialists spawn themselves from a goal. `MetaOrchestrator` → `AgentSpec` → `AgentFactory` → live agents. |
| 4 | [`11_dynamic_tools.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/11_dynamic_tools.ipynb) | Tools materialise at runtime, sandboxed. `GeneratedToolSpec` → `DynamicToolFactory` → `Sandbox`. Three safety tiers in the same notebook. |
| 5 | [`04_orchestrated_workflow.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/04_orchestrated_workflow.ipynb) | The connective tissue, by hand. Router → Parallel → Pipeline → RefinementLoop with `Workbench` carrying tracer + bus. |
| 6 | [`01_cognitive_substrate.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/01_cognitive_substrate.ipynb) | Agents know when they're struggling. `metacognition.confidence` → `RegressionDetector` → `WatchdogHook` → `FallbackModel`. |

If you have **5 minutes**, open notebook 12 and skip to section 7 ("Head-to-head") —
that's the measured win in one table.

## All narrative notebooks

| Notebook | Theme |
|----------|-------|
| [`01_cognitive_substrate`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/01_cognitive_substrate.ipynb) ★ | An agent that knows when it's struggling |
| [`02_meta_orchestrator`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/02_meta_orchestrator.ipynb) ★ | Decompose a goal, spawn specialists at runtime |
| [`03_generative_ui`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/03_generative_ui.ipynb) | Agents that design their own surface |
| [`04_orchestrated_workflow`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/04_orchestrated_workflow.ipynb) ★ | Route, fan out, chain, refine — with observability |
| [`05_reasoning`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/05_reasoning.ipynb) | Provider-agnostic reasoning knob |
| [`06_optimization_basic`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/06_optimization_basic.ipynb) | Evolve a research summariser's prompt (GEPA) |
| [`07_optimization_compound`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/07_optimization_compound.ipynb) | Evolve the planner inside `MetaOrchestrator` |
| [`08_topology_search_basic`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/08_topology_search_basic.ipynb) | ADAS-style topology search (offline) |
| [`09_topology_with_gepa`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/09_topology_with_gepa.ipynb) | Two-phase: discover topology, then evolve prompts |
| [`10_runtime_topology`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/10_runtime_topology.ipynb) ★ | Per-request topology synthesis with semantic cache |
| [`11_dynamic_tools`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/11_dynamic_tools.ipynb) ★ | Runtime tool spawning with sandbox tiers |
| [`12_combo_autonomous_coder`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/12_combo_autonomous_coder.ipynb) ★ | **The combo end-to-end with a measured win** — designer + dynamic agents + dynamic tools + iteration on a coding benchmark (+17pp pass@1) |

★ = part of the 6-notebook evaluation tour.

## Primitive references

For one-primitive-at-a-time references (basic agent, streaming, pipeline,
parallel, router, memory, observability), see the
[`examples/`](https://github.com/Kareemlsd/orqest/tree/main/examples)
directory. Each example demonstrates one building block in isolation,
matching one of the pieces the narrative notebooks compose.
