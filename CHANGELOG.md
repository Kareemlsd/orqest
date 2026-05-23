# Changelog

All notable changes to Orqest are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.0] - 2026-05-23

### Added

- **`openai-responses:` provider prefix** in `orqest.utils.resolve_model` — routes to `pydantic_ai.models.openai.OpenAIResponsesModel` so `LLM_MODEL=openai-responses:gpt-5.4` (etc.) goes through the OpenAI Responses API instead of `/v1/chat/completions`. Required for gpt-5.x with function tools + reasoning_effort (chat/completions rejects that combo with a 400). Uses the same `OPENAI_API_KEY`. Discovered while building Polymath's Koopman research session — gpt-5.4 + tools + reasoning silently desynchronised the message stream on chat/completions; switching to the Responses path resolved it.

- **`_repair_orphan_tool_returns` history processor** auto-appended to every `BaseAgent`'s history-processor chain. Walks the post-compaction window, tracks the set of visible `ToolCallPart.tool_call_id`s, and strips any `ToolReturnPart` whose id was sliced away by an earlier processor (`keep_recent_messages` boundary cut, `ContextManager._summarize_old_turns` summarisation of the matching call's `ModelResponse`, or any custom processor). Both OpenAI chat/completions and the Responses transport reject orphan tool returns with a 400 (`"messages with role 'tool' must be a response to a preceeding message with 'tool_calls'"` / `"No tool call found for function call output with call_id ..."`) — these blew up mid-run on Polymath's first long Koopman session. Belt-and-suspenders: also applied inside `ContextManager.compact()`'s own output. 0 backwards-compat hazards: stripping invalid parts only removes data that would have crashed the request anyway. Adjusted the 3 `_history_processors`-length assertions in `tests/agents/test_base_agent.py`, `tests/test_budget_tool_results.py`, and `tests/test_context_manager.py` to account for the +1 processor; the test_emergency_preserves_min_tokens assertion shifted from min-recent-tokens to min-recent-turns since the repair sweep can trim orphan ToolReturnParts out of the recent window.

- **`MetricBundle.aggregate(list[MetricBundle])` classmethod + `n_trials` / `stdev` fields** — collapse N independent observations of the same candidate × example pair into one representative bundle with mean metrics + per-dimension standard deviation. New optional fields `n_trials: int = 1` and `stdev: dict[str, float] | None = None` are backward-compatible — existing single-observation bundles serialize and behave identically. Aggregate handles optional dimensions (`confidence`, `robustness`) gracefully: present-only mean, `stdev` only when ≥2 trials supplied the dimension. Discovered while building the coding benchmark: single-trial LLM numbers swung ±10pp; multi-trial averaging is what stabilises an evaluator pipeline on weaker models. 10 new tests in `tests/optimization/test_bundle.py`.

- **`Evaluator(n_trials_per_example: int = 1)` parameter** — when `> 1`, runs the agent N times per gold example and aggregates via `MetricBundle.aggregate`. Each trial gets a fresh agent via `agent_factory(decoded)` so trials are independent. Default `1` preserves the legacy single-shot behavior at no extra cost. When every trial of an example fails, the aggregate keeps the failure info (not a misleadingly-averaged 0.0 accuracy). Cost scales linearly with `n_trials_per_example`; useful for weaker models where evaluator variance is the dominant noise source. 6 new tests in `tests/optimization/test_evaluator.py`.

- **`benchmarks/` directory + first benchmark (`benchmarks/coding/`)** — establishes the convention that every battery (or composition of batteries) ships with a reproducible head-to-head proving its value over a baseline. `benchmarks/coding/run.py` is the entry point for the 10-problem coding benchmark behind `notebooks/12_combo_autonomous_coder.ipynb`'s +17pp pass@1 / +14pp test_pass_rate claim: one command reproduces the multi-trial average. `benchmarks/README.md` documents the convention for adding new benchmarks (require a baseline, default to multi-trial averaging, honest cost + variance disclosures); `benchmarks/coding/README.md` documents what's tested, how to reproduce, and the honest caveats (LLM variance, stronger-model headroom, latency cost). Promoted from `scratch/combo/` after the iteration sprint surfaced that the numbers were buried where consumers couldn't find them. 4 new data-integrity tests in `tests/benchmarks/test_coding_fixture.py` pin the fixture's 10-problem / 92-hidden-test shape so silent drift breaks CI.

- **`orqest.sandbox.run_in_sandbox(...)` helper** + non-raising `run_in_sandbox_safe(...)` sibling — collapse the canonical "run candidate Python in a sandbox, get the return value back" pattern from ~30 lines (build `GeneratedToolSpec` → `DynamicToolFactory.spawn()` → invoke → unwrap `ExecutionResult`) into one async call. `return_expression` parameter handles the common case of appending `return func(args)` to a candidate function body. New `SandboxRunError(stage, code_snippet, underlying)` exception captures validation vs execution failures with structured diagnostic context. `run_in_sandbox_safe` returns `(success, output, error_msg)` for callers that prefer inline failure handling over try/except. The lower-level `Sandbox.execute()` + `GeneratedToolSpec` + `DynamicToolFactory` path stays the right choice when an agent itself needs to *call* a tool via pydantic-ai's tool-use mechanism; these helpers are for *direct* sandbox invocation from framework code. 13 new tests in `tests/sandbox/test_helpers.py`. Discovered while building `notebooks/12_combo_autonomous_coder.ipynb` where the evaluator wrapped this pattern ~30 lines per call.

- **`AgentSpec` accepts `output_type: type[BaseModel]` as an ergonomic alternative to `output_schema: dict`** — declaring an agent's output shape with a Pydantic class is terser (and statically typed) compared to authoring a JSON Schema dict by hand. Both paths remain supported: a new `@model_validator` enforces exactly-one-of so the two can't drift. The JSON Schema path stays the wire-format option (LLM-emittable specs, persistence); the Pydantic-class path is the in-process / code-side path. `AgentFactory.spawn()` dispatches on which is set with zero behavior change for existing callers. 6 new tests in `tests/autonomy/test_factory.py::TestAgentSpecOutputType`. Discovered while building `notebooks/12_combo_autonomous_coder.ipynb` where the JSON Schema dicts for two agents were ~16 lines vs ~4 lines per Pydantic class.

- **`BaseAgent` validates `output_type` at construction** — top-level `Any`-typed Pydantic fields now raise `BaseAgentSchemaError` immediately at agent construction, with a message naming the offending field and concrete remediations (narrow the type, use a container of `Any`, or use a JSON-string field). Previously this slipped through to first inference where OpenAI's structured-output endpoint surfaced an opaque `Invalid schema for function 'final_result'` 400 error with no breadcrumb. Containers holding `Any` (`list[Any]`, `dict[str, Any]`) and scalar output types (`str`, `int`, etc.) are still accepted — only top-level `Any` fields trigger rejection. Discovered while building `notebooks/12_combo_autonomous_coder.ipynb` where this cost ~20 min of debugging on two separate occasions. 6 new tests in `tests/agents/test_base_agent.py::TestOutputTypeSchemaValidation`. New exception class `orqest.agents.base_agent.BaseAgentSchemaError(ValueError)`.

### Docs

- **`docs/concepts/sandbox.md`** — new "Recipe: test-driven loops over LLM-generated code" section. Documents the per-spec pattern for safely running LLM-generated candidate functions: bake source into a fresh `GeneratedToolSpec` per (iteration × test), pass through the sandbox's static validator + RLIMIT-bounded subprocess, never `exec()` strings against the parent namespace. Names what the pattern protects against and what it doesn't (kernel isolation, network egress, filesystem reads). Discovered while building `notebooks/12_combo_autonomous_coder.ipynb` where the instinct was an exec-based test runner — which the validator rightly rejects.

- **`docs/concepts/topology_optimization.md`** — two new sections. (1) "Caveat: LLM-generated tests as evaluator feedback" — documents the Unsupervised Evaluation Paradox at the runtime layer: letting an LLM generate test labels for another LLM's code makes the loop *worse* on imperfect models, because hallucinated tests poison the fixer's signal (V2 of the coding benchmark regressed ~50pp from this exact pattern). Names what works instead (visible-test-only with keep-best). (2) "When NOT to use `RuntimeTopologyDesigner` — just hand-write a Pipeline" — honest framing on when the runtime designer's per-request LLM cost is worth paying vs. just instantiating known agents in known shapes. Three concrete tests for "should I reach for this primitive."

- **`docs/concepts/autonomy.md`** — new "When NOT to use `MetaOrchestrator` — just write the agents and a Pipeline" section, the parallel framing for the autonomy layer: the planner LLM call is the most expensive single invocation in the chain; only worth paying when the decomposition itself is the hard part. Cross-links to the topology version of the same principle.

- **`CLAUDE.md`** — new convention added to "Key Conventions": *"Every battery ships with a benchmark."* Names `benchmarks/coding/` as the canonical reference layout. Future batteries must ship with a reproducible head-to-head + README documenting expected numbers, variance, and cost.

### Changed

- **`RefinementLoop` now defaults to `keep_best=True`** — tracks the iteration with the highest `EvalResult.score` and returns *that* iteration's output if the final iteration regressed. Protects self-improving loops (test-driven coding, evaluator-feedback refinement) from "fixer breaks code that already worked" failure modes on imperfect models. The `passed=True` early exit still returns the passing iteration's output (passing is the explicit success bar). When the evaluator never returns a numeric score, keep-best is a no-op and the legacy "return latest" behavior holds — so callers using boolean-only evaluators see zero behavior change. `LoopResult` gains `best_iteration: int | None` and `best_score: float | None` (informational; populated regardless of the flag). **Migration:** set `RefinementLoop(..., keep_best=False)` to restore strict last-iteration semantics. Discovered while building `notebooks/12_combo_autonomous_coder.ipynb`, where we hand-rolled this safety property and saw it lift combo `pass@1` measurably on `gpt-4o-mini`. 6 new tests in `tests/orchestration/test_loop.py` (full suite 1051 → 1057).

### Added

- **Tier-2 Docker sandbox + per-user persisted MCP tool library** — closes the deferred W3.M item from `[0.3.0]`. The host-side `orqest.sandbox.docker.DockerSandbox` orchestrates per-session containers built from the new `orqest/agent-runtime` image (`Dockerfile` at repo root). The container ships its own `orqest.sandbox.docker_runtime` package — a FastMCP server exposing four tools (`execute_python`, `promote_tool`, `list_persisted_tools`, `forget_tool`), `SessionAuthMiddleware` (HMAC-signed JWT with `{sub: user_id, sid: session_id, exp}` claims), per-agent `uv venv`s under `/workspace/<session>/<agent_id>/venv` (created in ~50 ms; cached per agent), and a SQLite `ToolStore` mounted as the per-user named volume `orqest-user-<user_id>`. Promotion is threshold-based by default (N=3 successful invocations of the same `(name, code_hash)` auto-promote and fire `notifications/tools/list_changed`); `eager` and `operator_approval` modes also wired. Cross-session reuse: same user's NEXT session sees the persisted tools immediately on `tools/list`; cross-user isolation is enforced by per-user named volumes. Hardened defaults: `--cap-drop=ALL --read-only --user 1000:1000 --pids-limit --memory --cpus`, `tini` as PID 1, non-root user. Honest threat model: shared-kernel, protects against accidental damage and most prompt-injection scenarios; not adversarial-multi-tenant grade — Tier 3 (microvm) is the documented seam for that.
- `orqest.sandbox.docker_runtime/` — the in-container runtime package: `server.build_server[_from_env]`, `auth.SessionAuthMiddleware`, `executor.Executor` (per-agent venv + `uv pip install` gated by `ORQEST_ALLOWED_PACKAGES` allowlist + AST validator + RLIMIT-bounded subprocess), `store.ToolStore` (per-user SQLite, `(name, version)` PK, deduplication by `implementation_hash`).
- `orqest.sandbox.docker.DockerSandbox` (host-side) — Sandbox-Protocol-conformant; lifecycle is an async context manager (`__aenter__` → `docker run` + MCP boot-wait + JWT-auth open; `__aexit__` → `docker rm -f`, named volume persists). Required `user_id` + `session_id` ctor args (framework-issued; the LLM never sees them). Mints a fresh HMAC secret per construction by default; passes it to the container via `ORQEST_HMAC_SECRET`.
- `orqest.sandbox.jwt` — minimal HS256 JWT (encode/decode/verify), constant-time signature compare, `alg=none` confusion attack defended. Avoids pulling in `pyjwt` for this single internal use.
- `orqest.sandbox._compat` — soft-import boundary for the optional `docker` SDK; friendly `ImportError` with the install hint at first call to `docker_from_env()` rather than at module load.
- `orqest.workbench.Workbench(user_id=..., session_id=...)` — required ctor args (BREAKING — see below). New `with_docker_sandbox(*, user_id, session_id, image, allowed_packages, ...)` factory mirrors `with_healing(...)`; lazy-imports `orqest.sandbox.docker` so the workbench stays import-light.
- `orqest.autonomy.GeneratedToolSpec.dependencies: list[str]` — additive; LLM can declare pip dependencies that the container's executor will install into the agent's venv (gated by `allowed_packages`).
- `orqest.autonomy.tool_factory.spawn(spec, *, agent_id=None)` and `AgentFactory._resolve_tools(..., *, agent_id=None)` — `agent_id` propagates through the factory chain to `Sandbox.execute(..., agent_id=...)`. Tier-0/1 sandboxes accept-and-ignore for backward compat; Tier-2 routes to per-agent venvs.
- `orqest.sandbox.protocol.Sandbox.execute(...)` — additive `agent_id: str | None = None` and `dependencies: list[str] | None = None` kwargs.
- `orqest.mcp.MCPServerConfig.headers: dict[str, str]` and `transport: Literal["stdio","sse","streamable-http"]` — additive. `MCPConnection._open_transport` learns a `streamable-http` branch via `mcp.client.streamable_http.streamablehttp_client`, forwarding `config.headers` for the `Authorization: Bearer ...` workflow.
- `orqest.memory.MemoryEntry.memory_type = Literal["semantic","episodic","procedural","tool"]` (extension); `MemoryFilter` mirrored. `orqest.memory.strategies.ToolStrategy` (exact-name match with FTS5 fallback). `orqest.memory.MemoryConfig.tool: PerKindConfig` (versioning enabled; no TTL by default).
- ~74 new tests across `tests/sandbox/` (`test_jwt.py`, `test_docker_compat.py`, `test_docker.py` marked `docker`), `tests/sandbox/docker_runtime/` (`test_store.py`, `test_executor.py`, `test_auth.py`, `test_server.py`), `tests/mcp/test_streamable_http_transport.py`, `tests/memory/test_tool_memory_type.py`, `tests/autonomy/test_generated_tool_spec_dependencies.py`, `tests/workbench/test_user_session.py`. Full suite: **1051 passing** (no daemon) + 13 marked `docker` (require `docker` daemon AND the `orqest/agent-runtime` image — green when both available). New pytest marker `docker` registered in `[tool.pytest.ini_options]`.
- New optional dependency group `[dependency-groups] docker = ["docker>=7.0", "httpx>=0.27"]`. Mirrors the `optimization` pattern. Soft-imported via `orqest.sandbox._compat`.
- `BaseAgent(reasoning=...)` — a provider-agnostic reasoning/thinking knob (`"minimal"` | `"low"` | `"medium"` | `"high"`). pydantic-ai exposes thinking through a different `ModelSettings` key per provider (`anthropic_thinking` / `openai_reasoning_effort` / `google_thinking_config` / `openrouter_reasoning`); `reasoning` collapses that into one effort level, translated and merged into `model_settings` — explicit `model_settings` keys win on conflict. For budget-based providers (Anthropic, Google) a sensible `max_tokens` is filled when unset so reasoning works out of the box. New `orqest.utils.reasoning` module (`ReasoningEffort`, `resolve_reasoning_settings`); `ReasoningEffort` is re-exported from `orqest.agents`.
- **New battery `orqest.optimization`** — reflective prompt evolution via [GEPA](https://github.com/gepa-ai/gepa) (Genetic-Pareto, Agrawal et al., ICLR 2026 Oral). Three-layer split mirroring `healing/`: encoding (`Genome` + `PromptGene` / `ScalarGene` / `CategoricalGene`), evaluation (`Evaluator` + `GoldExample` + `MetricBundle` / `MetricWeights` aggregating accuracy / confidence / cost / latency / robustness), adaptation (`OrqestGEPAAdapter` + `OrqestEvalBatch` + `OptimizationRunner` + `OptimizationResult` + `apply_result` / `OptimizationDiff`). The adapter feeds GEPA both per-example scalar `scores` and per-objective `objective_scores` so the native `frontier_type="hybrid"` Pareto frontier discovers tradeoffs across both axes. `apply_result(dry_run=True)` is the default; commit invalidates the cached `pydantic_ai.Agent` so the new prompt actually takes effect. Async-bridge handles both fresh-process (`asyncio.run`) and Jupyter (worker thread). 62 new tests (62/62 green; full suite 689 → 751). Optional dependency — `uv sync --group optimization`. Concept doc at `docs/concepts/optimization.md`; demo notebooks `notebooks/06_optimization_basic.ipynb` (research summarizer) and `notebooks/07_optimization_compound.ipynb` (planner inside `MetaOrchestrator`). Scalar/categorical gene evolution gated by `OptimizationConfig.enable_scalar_genes` / `enable_categorical_genes` until the upstream W1.1 wiring lands.
- **Topology evolution under `orqest.optimization`** (W3) — ADAS-style structural search over a typed `TopologySpec` IR. Two new sub-batteries:
    - **Orchestration spec layer** (`orqest/orchestration/spec.py` + `hydrate.py`) — Pydantic models for `PipelineSpec` / `ParallelSpec` / `RouterSpec` / `RefinementLoopSpec` / `AgentStepSpec` / `FunctionStepSpec` plus the top-level `TopologySpec` and `OperationSpec` discriminated unions. `topology_from_spec()` hydrates a spec into a live runtime via an explicit `CallableRegistry` + agent factory map — no `eval`, no `exec`, no name forgery. Closes the audit-named gap (LLM cannot emit composition topology at runtime). Independently useful regardless of search.
    - **Topology search engine** (`orqest/optimization/topology.py` + `meta_agent.py`) — `TopologyGene` (Pydantic gene whose value is a serialized `TopologySpec`), `TopologyEvaluator` (subclass of `Evaluator`; adds `n_agents` / `depth` to `MetricBundle.raw`), and `MetaAgentSearch` (the ADAS-style design → reflexion → evaluate → archive loop). The meta agent emits typed JSON, not raw Python — sidestepping ADAS's `exec()`-in-process gap and the entire sandbox problem. Pluggable archive strategies (`top_k` default, `cumulative` ADAS-faithful, `parallel` per the [2510.06711 critique](https://arxiv.org/abs/2510.06711)). Pydantic ValidationError + hydration KeyError feed back to the meta agent as debug-retry feedback (analogue of ADAS's traceback retry, but type-safe). Returns an `OptimizationResult` shaped identically to the GEPA path so `apply_result` and downstream consumers work without dispatch. **Two-phase composition with GEPA is the recommended path** (ADAS first with fixed strong prompts, GEPA on the winner) — never nest, the multiplicative cost is fatal. Concept doc at `docs/concepts/topology_optimization.md`; demo notebooks `notebooks/08_topology_search_basic.ipynb` and `notebooks/09_topology_with_gepa.ipynb`. 95 new tests (44 spec/hydrate + 20 topology + 25 meta_agent + 6 topology-apply; full suite 768 → 863).
- `MetaAgentConfig` re-exported from `orqest` root (matches `HealingConfig` / `MetacognitionConfig` / `OptimizationConfig` pattern).
- `apply_result` diff renderer now JSON pretty-prints Pydantic-model gene values (typed `TopologySpec` slots get readable line-by-line diffs).
- **Runtime topology design** — the runtime planner sibling to `MetaOrchestrator`. **Both new modules live under `orqest.autonomy/`** (not `orqest.optimization/`) because they are runtime planners, not optimizers — there's no loss function, no per-request scoring, no Pareto archive. They share the `TopologySpec` IR with `MetaAgentSearch` because the IR is provenance-agnostic, but the relationship is shared infrastructure, not shared algorithm:
    - **`orqest.autonomy.runtime`** — `RuntimeTopologyDesigner` (per-request `TopologySpec` synthesis via a user-provided `BaseAgent[GlobalState, TopologyDesign]`), plus the `TopologyCache` Protocol with three implementations: `NoCache` (default, zero state), `InMemoryLRU` (exact-match goal string), and `MemoryStoreCache` (backed by `LocalMemoryStore` with semantic recall + reliability decay on execution failure). The cache uses `memory_type="semantic"` with a namespaced `source_agent="topology_cache"` slot; reliability decay reuses the existing `PerKindConfig.decay_on_failure` machinery. `verify_on_hit=True` by default catches stale agent / callable references after registry changes; optional `fallback_spec` returns a safe minimal topology when design fails. Seed-library bootstrap accepts a list of validated topologies (typically the Pareto front from an offline `MetaAgentSearch` run) and biases the designer toward known-good shapes. **Honest framing:** the cache decays only on `topology.run` exceptions, not on bad-quality outputs — that's W3.E (deferred).
    - **`orqest.autonomy.topology_orchestrator`** — `TopologyOrchestrator` is the topology-shaped sibling to `MetaOrchestrator`. Per-request loop: design (cache or fresh) → hydrate → run → record outcome. Returns a typed `TopologyExecutionResult` with structural metrics (`n_agents`, `depth`), timing breakdown (`design_ms`, `execution_ms`, `total_ms`), and `cache_hit` signal. Bus events: `topology.execution_completed` / `topology.execution_failed` / `topology.cache_hit` / `topology.cache_miss` / `topology.designed` / `topology.design_failed` / `topology.fallback_used`.
    - **Import paths** — both modules are imported via the explicit submodule path:
        - `from orqest.autonomy.runtime import RuntimeTopologyDesigner, MemoryStoreCache, NoCache, InMemoryLRU, TopologyCache`
        - `from orqest.autonomy.topology_orchestrator import TopologyOrchestrator, TopologyExecutionResult`
      Not re-exported from `orqest.autonomy.__init__` to avoid a circular import (eagerly loading them at autonomy package init triggers loading `optimization.meta_agent` mid-init via `topology` → `autonomy.factory`). Matches the pattern used by other heavy batteries (e.g., `from orqest.compound import SubAgentTool`).
    - 35 new tests (25 runtime + 10 orchestrator; full suite 863 → 898). Concept doc section "Runtime topology design" appended to `docs/concepts/topology_optimization.md`. Demo notebook `notebooks/10_runtime_topology.ipynb` walks through cold design, cache reuse, full orchestrator loop, seed-library bootstrap, and online-learning failure decay end-to-end.
- `unpack_topology_output` promoted from private `_unpack_topology_output` in `orqest.optimization.topology` — used by both `TopologyEvaluator` and `TopologyOrchestrator` to extract the meaningful payload (`ParallelResult.merged` / `LoopResult.output`) from a topology's `.run()` result.
- **`orqest.sandbox`** subpackage — safe execution surface for LLM-generated Python (closes the Phase-3 deferred `ToolSandbox` item). Two-stage Protocol: `validate(code, allowed_imports)` (static AST checks; raises `ValidationError` on disallowed import / forbidden call / dunder access / syntax error) and `execute(code, args, allowed_imports, timeout_s, memory_mb)` (always returns `ExecutionResult`; never raises for user-code failures). Two backends ship: `InProcessSandbox(unsafe=True)` (Tier 0 — `exec()` in a restricted namespace; refuses to construct without `unsafe=True` because there is no real isolation) and `SubprocessSandbox` (Tier 1, production default — fresh `python -c` subprocess per call with `RLIMIT_AS` + `RLIMIT_CPU` (POSIX) + outer `asyncio.wait_for` timeout; JSON args/result via stdin/stdout). Default-deny imports — empty `allowed_imports` rejects any `import` statement. Defense-in-depth — the subprocess re-validates internally before execution. Concept doc at `docs/concepts/sandbox.md`. **No new dependencies** (subprocess / resource / ast / json are stdlib).
- **Dynamic tool spawning** — closes the autonomy ladder's missing rung. `AgentSpec.tools` previously dropped any `ToolSpec` whose name wasn't pre-registered; now an LLM-emitted `GeneratedToolSpec` (carrying `implementation: str` + `allowed_imports: set[str]` + `timeout_s` + `memory_mb`) is materialized at runtime via `DynamicToolFactory(sandbox=...)`. Three new pieces:
    - **`orqest.autonomy.spec.GeneratedToolSpec`** — Pydantic model carrying the implementation. `AgentSpec.tools` widened to `list[ToolSpec | GeneratedToolSpec]`; Pydantic v2 smart-union dispatches by structure (the `implementation` field is the disambiguator). Backward-compatible — existing `ToolSpec(name=...)` construction unchanged.
    - **`orqest.autonomy.tool_factory.DynamicToolFactory`** — wraps a `Sandbox` to produce runnable `pydantic_ai.Tool` objects from `GeneratedToolSpec`. Bus events: `tool.spawned` / `tool.spawn_failed` / `sandbox.validation_rejected` / `tool.invocation_completed` / `tool.invocation_failed`. The spawned `Tool` returns a structured error dict on sandbox failure (not a Python exception) so the agent loop sees it as a tool result.
    - **`orqest.autonomy.AgentFactory(tool_factory=...)`** — `_resolve_tools` learns to dispatch on `isinstance`: `ToolSpec` → registry lookup (existing path), `GeneratedToolSpec` → `tool_factory.spawn(spec)`. When `tool_factory is None` and a `GeneratedToolSpec` appears, log + skip (matches the existing graceful-skip behavior for unknown registry names). Internal `_spawn_generated` async-bridges via `asyncio.run` (no loop) or worker thread (loop already running) — same pattern as `OrqestGEPAAdapter._run_async`.
    - **`BaseAgent.add_tool(tool)`** — appends to `self.tools` and invalidates the cached `pydantic_ai.Agent` so the next access rebuilds with the new tool list. Idempotent for tools sharing a `name` (last-write-wins). Closes the "agent encounters a capability gap mid-run; orchestrator hands it the missing tool" path.
    - **`orqest.autonomy.__init__`** re-exports `GeneratedToolSpec` + `DynamicToolFactory`.
    - 61 new tests (34 sandbox + 14 tool_factory + 7 factory-with-generated-tools + 6 add_tool; full suite 898 → 959). Concept docs: new `docs/concepts/sandbox.md`; appended "Dynamic tool spawning" section to `docs/concepts/autonomy.md`. Demo notebook `notebooks/11_dynamic_tools.ipynb` walks through sandbox standalone, factory spawn, mixed-tools dispatch, runtime add_tool, and an end-to-end real-LLM run where the agent uses a tool that didn't exist at agent-construction time.
    - **Future seams (deferred):** W3.J — procedural-memory persistence for spawned tools (`Skill` shape); W3.K — `SubprocessPoolSandbox` for amortizing startup cost; W3.L — `E2BSandbox` (hosted micro-VM, optional dep); W3.M — `DockerSandbox` / `FirecrackerSandbox` (real network/filesystem isolation); W3.C revisited — ADAS sandboxed codegen now unblocked.

### Breaking Changes

- `Workbench(...)` now requires `user_id: str` and `session_id: str` keyword args. Existing in-tree consumers (notebooks, examples, tests) updated. The args are framework-issued — never derived from LLM-visible context — and become the strict isolation key for the Docker tier's per-user persisted tool library. The previous `Workbench()` no-arg form was used by ~20 in-tree call sites; all migrated. No external consumers exist (orqest is unpublished as of `0.7.0`).

### Dependencies

- New optional dependency group `[dependency-groups] optimization = ["gepa>=0.1.1"]`. Not in core; pulls litellm + datasets + tiktoken transitively (~50–80 MB). Soft-imported via `orqest.optimization._compat` with a friendly `ImportError` when absent.
- New optional dependency group `[dependency-groups] docker = ["docker>=7.0", "httpx>=0.27"]`. Tier-2 host-side only; the `orqest/agent-runtime` container ships the rest. Soft-imported via `orqest.sandbox._compat`.
- Topology evolution adds **no new dependencies** — uses the existing pydantic-ai meta-agent + the orchestration primitives already in core.

## [0.4.0] - 2026-05-14

The advance pass — "complete & honest." Finishes the `[0.3.0]` preview tier into Tier 1: every capability that was a designed-but-unwired seam is now wired and test-covered. Test suite: 664 → 670.

### Added

- `PerKindConfig.ttl_days` + `LocalMemoryStore.prune_expired()` — per-kind retention windows; a best-effort maintenance call deletes entries past their TTL and returns the count. A kind with `ttl_days=None` is never pruned.
- `PerKindConfig.version_on_edit` — when enabled, re-storing a procedural skill by name bumps its `version` one past the highest stored version and keeps the prior rows as an audit trail.
- `LocalMemoryStore(embedder=...)` — a pluggable sync-or-async embedder. When set, `store()` embeds entry content and `SemanticStrategy` ranks recall by cosine similarity over stored vectors; FTS5 / LIKE otherwise. New `default_strategy_table(embedder=...)` parameter and `embed_text` / `_cosine` helpers in `orqest.memory.strategies`.
- `MCPDiscovery(well_known_urls=...)` — `search()` probes the configured base URLs for `/.well-known/mcp.json` (highest intent, tried first), then queries the registry endpoints, deduplicating by name. The documented well-known-manifest discovery source is now real.

### Changed

- The `RecoveryAction` union stays lean (`AbortRun` | `EscalateToUser`) by design — model-level recovery is `FallbackModel`, tool-level recovery is `DiscoveryHook`. The advance pass evaluated re-introducing `RetryDifferentModel` / `DiscoverAndRetry` / `RetrySameTool` and concluded they duplicated those dedicated, composable mechanisms.

### Preview

Still accepted but not yet wired:

- `MemoryConfig.backend="supabase"` / `supabase_*` — the pgvector backend.
- `MCPDiscovery` registry response-shape parsing — untested against live registries; no web-search fallback.

## [0.3.0] - 2026-05-14

The reconcile pass. A contradiction audit found ~27 places where the code and the docs disagreed — most often an "intent layer" (configs, types, hooks) built ahead of the "effect layer" that consumes it. This release wires the cheap gaps, deletes the dead ones, and corrects every stale claim. Tiered honesty contract: each subsystem's primary path is functional end-to-end; specific advanced capabilities are explicitly labelled **Preview**. Test suite: 655 → 664.

### Breaking Changes

- `compound.sub_agent_tool.EvalResult` renamed to `SubAgentEvalResult` — it collided by name with `orchestration.loop.EvalResult` (a different shape).
- `RecoveryAction` union reduced to `EscalateToUser | AbortRun`. `RetrySameTool` / `RetryDifferentModel` / `DiscoverAndRetry` are removed — they produced payloads no compound flow consumed.
- `PerKindConfig` reduced to `decay_on_failure` + `prune_below`; `ttl_days` and `version_on_edit` removed (no maintenance routine / versioning logic ever existed).
- `LocalMemoryStore.__init__` — `db_path` is now optional and a `config: MemoryConfig` keyword param was added.
- Prompt delivery — `CompoundTool.run` and `SubAgentTool.run` now inject the prompt into `state` as a user message. `CompoundTool` previously never passed the prompt to the agent at all; `SubAgentTool` passed it only as a `note=` kwarg (still forwarded for agents that read it).
- `RefinementLoop.__init__` raises `ValueError` when `agent_self_eval` is set but the agent has no `confidence_protocol`.
- Default model is `openai:gpt-4.1` everywhere (was `openai:gpt-3.5-turbo` in config, `openai:gpt-4o` in autonomy / the MCP server).
- Packaging — the explicit `openai` dependency is removed (still bundled transitively by `pydantic-ai`); `pytest`, the duplicate `dotenv`, and the unused `markdown` deps are removed.

### Fixed

- `on_error` hook decisions are now consumed — `CompoundTool` and `MetaOrchestrator` honor a `Redirect` from `on_error` as a bounded single retry. `DiscoveryHook` (whose only behaviour is an `on_error` `Redirect`) is functional again.
- `PerKindConfig.decay_on_failure` / `prune_below` are now wired into `LocalMemoryStore.update_reliability` (the decay factor and prune floor were hardcoded; the config was inert).
- `MCPConnection.connect()` branches on `config.transport` — `sse` servers (including everything `MCPDiscovery` returns) can now actually connect instead of being driven through the stdio client with an empty command.
- `MetaOrchestrator` memory-reuse is keyed consistently on `subtask.name` — the recall query, skill trigger, and spawned-agent cache were mismatched, so reuse was effectively never hit.
- `RefinementLoop` no longer silently accepts an `agent_self_eval` agent with no confidence protocol (the loop could never exit via `"confident"`).
- ~12 stale doc / docstring claims corrected: the `salience` "side-table cache", the `WatchdogHook` "hook.shadowed event", `MCPDiscovery`'s "three discovery sources", the `ContextManager` salience threshold, generative UI's "5 first-party components" (it is 17 across 3 layers), the MetaOrchestrator "successful specs" persistence claim, the "pay for what you use" provider claim, `load_sys_prompt` typing, and missing `__all__` exports (`WebSearchResponse`, `budget_tool_results`).

### Removed

- `RetrySameTool`, `RetryDifferentModel`, `DiscoverAndRetry` recovery actions and the `healing.retry_initiated` event.
- `HealingConfig.abort_on_unresolved_loop` — dead config flag, never read.
- `MCPConfig.connection_timeout` — dead config field, never read.
- `metacognition.protocol._SelfRating` — dead class, never referenced.
- `PerKindConfig.ttl_days` / `version_on_edit` and the `_episodic_default` / `_procedural_default` factories.

### Preview

The following are accepted but not yet wired end-to-end, and are now labelled as such in their docstrings and concept docs:

- `MemoryConfig.backend` / `supabase_*` / `embedding_*` — designed seams for a future pgvector backend and embedding-based retrieval.
- `MCPDiscovery` online registry search — untested against live registries; `probe_wellknown` exists but is not wired into `search()`.

## [0.2.0] - 2026-04-25

The cognitive-substrate completion. Three implementation waves landed in sequence on the same day (Wave 1: HookDecision + procedural memory + metacognition; Wave 2: healing + MCP auto-wire; Wave 3: generative UI). Test suite: 360 → 612 (+252).

### Added

**`orqest.metacognition` (Wave 1.3 — vision feature #3 "Metacognition primitives"):**
- `EnrichedOutput[OutputT]` — Pydantic generic pairing an output with `confidence` (`float | None` in `[0, 1]`), `uncertainty_targets: list[str]`, `capability_boundary: bool`, `protocol_name`, and free-form `metadata`
- `ConfidenceProtocol` Protocol + three concrete strategies: `StructuredOutputProtocol` (zero-cost; lifts `self_confidence`/`uncertain_about`/`outside_my_capability` off the agent's own `OutputT`), `LLMSelfRatingProtocol` (+1 LLM call; rater agent emits JSON, markdown-fence-tolerant parser), `EnsembleProtocol(k=N)` (+k–1 parallel calls; pairwise-agreement confidence)
- `MetacognitionHook` — `ToolHook` that emits `metacognition.confidence` events whenever a tool result is an `EnrichedOutput`
- `MetacognitionConfig` frozen dataclass with `redecompose_threshold` / `max_redecompositions` / `confidence_floor`
- `confidence_salience` / `recency_salience` — pure salience scorers for `ContextManager` integration
- `BaseAgent.run_enriched(state, *, confidence_protocol=None) -> EnrichedOutput[OutputT]` (additive; `run` untouched)
- `BaseAgent` ctor gains keyword-only `confidence_protocol` for an agent-level default
- `RefinementLoop` ctor gains `confidence_threshold: float | None` (new exit reason `"confident"`) and `agent_self_eval: BaseAgent | None`
- `SubAgentResult.confidence` / `uncertainty_targets` / `capability_boundary` (additive optional fields); `SubAgentTool.run(use_enriched=True)` lifts the final-iteration enrichment
- `ContextManager(salience_fn=...)` — pluggable per-message salience scorer; emergency truncation rescues high-salience old messages
- `MetaOrchestrator(metacognition: MetacognitionConfig | None = None)` — re-decomposes remaining subtasks when `_extract_confidence(result.output) < redecompose_threshold`

**`orqest.healing` (Wave 2 — vision feature #4 "Self-healing primitives"):**
- `HookDecision` discriminated union: `Continue` / `Skip(reason, stub_result)` / `Redirect(new_args, new_tool, reason)` / `Abort(reason)` (Wave 1.1 — also a Wave 2 prerequisite)
- `HookAbortError` — propagated when a hook returns `Abort`
- `ToolHook` protocol upgrade: methods may return `HookDecision | None`. `HookRunner._safe_call` auto-wraps `None` → `Continue`. `HookRunner._aggregate` first-non-Continue-wins with `Abort` short-circuit (Wave 1.1)
- `CompoundTool.run`, `run_with_retry`, `MetaOrchestrator._execute_subtask` honor `Skip` / `Redirect` / `Abort` (Wave 1.1)
- `Watchdog` Protocol + `Detection` Pydantic model (Wave 2.C)
- `StallDetector` (timeout on open tool calls, idempotent subscribe), `LoopDetector` (sliding window of `(tool_name, args_hash)`), `RegressionDetector` (subscribes to `metacognition.confidence` events; graceful no-op without metacog) (Wave 2.C)
- `RecoveryAction` discriminated union: `RetrySameTool` / `RetryDifferentModel` / `EscalateToUser` / `AbortRun` / `DiscoverAndRetry` + `default_policy` (Wave 2.C)
- `WatchdogHook` — `ToolHook` mapping Detection → policy → `HookDecision`. Emits `healing.action` events (Wave 2.C)
- `FallbackModel` — subclasses `pydantic_ai.models.Model`; sticky failover; transient classifier (5xx/timeout → fall back; auth/validation → propagate); emits `healing.model_fallback` (Wave 2.C)
- `resolve_model_with_fallback(models, *, api_key, bus, transient_predicate)` — accepts a chain; per-provider key map with graceful skip on missing keys (Wave 2.C)
- `HealingRunner` async context manager — wires watchdogs to a bus, runs poll loop, emits `healing.detection` events, owns the `WatchdogHook` and (optional) `FallbackModel` (Wave 2.C)
- `Workbench.with_healing(config, *, api_key=...)` convenience factory (lazy import) (Wave 2.C)
- `HealingConfig` frozen dataclass (Wave 2.C)
- `ToolRegistry.get_or_discover(name, *, discovery, manager, permission, audit_bus, max_servers)` — deliberate auto-discovery path (Wave 2.D)
- `DiscoveryHook` — `ToolHook` recovering from "tool not found" runtime errors via MCP discovery; returns `Redirect(new_tool=name)` after registration (Wave 2.D)
- `PermissionGate` Protocol + `AllowAll` / `DenyAll` (default) / `AllowList` (regex) (Wave 2.D)
- Audit-log events: `discovery.requested` / `discovery.connected` / `discovery.denied` / `discovery.failed` (Wave 2.D)

**`orqest.ui` (Wave 3 — vision feature #5 "Generative UI"):**
- `UIComponentSpec[T]` — generic Pydantic with `component_type` `Literal` discriminator, `component_id`, typed `data: T`, `metadata`, `created_at`
- `UIDeltaEvent` — partial update with `op: Literal["replace","merge","append","remove"]` + dot-path + value
- `UIDeltaOp` type alias
- `ComponentRegistry` per-Workbench (no module singleton): `register`, `get`, `list_types`, `validate_payload`
- `default_registry()` — pre-loads first-party components
- `UIEmitter(bus)` — `init` / `delta` / `remove` convenience over `EventBus`
- `ui_init_event_type` / `ui_delta_event_type` / `ui_remove_event_type` helpers (event-type convention `ui.<component_type>.{init,delta,remove}`)
- First-party components: `PlanComponent`, `ChartComponent` (line/bar/scatter/pie/heatmap with typed `ChartSeries`), `TableComponent` (typed `TableColumn`), `FormComponent` (typed `FormField`), `TakeoverDialogComponent` (confirm/input/choice), plus declarative grammars (`VegaChartComponent`, `MermaidComponent`, `LatexComponent`, `JsonViewerComponent`) and the `SandboxedHTMLComponent` escape hatch
- `ExecutionPlan.enable_ui_events(*, component_id="plan")` — opt-in flag-gated dual emission of `ui.plan.init`/`ui.plan.delta` alongside legacy `plan.init`/`plan.task.updated`
- `ExecutionPlan.as_component()` — wraps the plan as a `PlanComponent`
- `Workbench(ui_registry=..., auto_register_first_party_ui=True)` ctor kwargs

**Cognitive memory typology (Wave 1.2 — vision feature #2 "Cognitive memory typology" completion):**
- `MemoryEntry.memory_type` extended to `Literal["semantic", "episodic", "procedural"]`
- `Skill` / `ToolCallSpec` / `SkillExample` Pydantic shapes (procedural payload in `MemoryEntry.structured_content`)
- `MemoryEntry.structured_content: dict[str, Any] | None` (validation gated to `memory_type == "procedural"`)
- `MemoryFilter.skill_name` / `skill_min_version` for procedural filtering
- `RetrievalStrategy` Protocol + `SemanticStrategy` (legacy FTS5/LIKE behavior preserved) / `EpisodicStrategy` (`ORDER BY created_at DESC`) / `ProceduralStrategy` (exact trigger match + optional injected fuzzy judge)
- `default_strategy_table()` — the per-kind dispatch table consumed by `LocalMemoryStore`
- `LocalMemoryStore(strategies=...)` — strategy override for custom backends
- Best-effort `ALTER TABLE` migration for the `structured_content` column
- `MemoryConfig` extended with `semantic` / `episodic` / `procedural` `PerKindConfig` fields (TTL / decay / version-on-edit)
- `MetaOrchestrator._find_or_spawn` dual-write migration: persists both episodic mirror (legacy) and procedural `Skill` entries; recall is procedural-first with episodic fallback

**Test suite:** 360 → 612 at wave-3 ship (+252 across the three waves; 360 pre-existing tests stayed green at every wave boundary). Subsequent consumer-side polish (2026-04-26) brought the suite to 655.

## [0.1.0] - 2026-04-24

Phases 2–5 of the original Orqest roadmap stabilized: Memory, Autonomy, Observability, and MCP. The substrate that the Wave 1–3 cognitive features in 0.2.0 build on.

### Added

**`orqest.memory` (Phase 2):**
- `MemoryStore` Protocol — `store`, `recall`, `forget`, `update_reliability`, `count`
- `MemoryEntry` — content + `memory_type` (initially `"semantic" | "episodic"`) + source agent + confidence + reliability score + metadata + access tracking
- `MemoryFilter` — query constraints (memory_type, source_agent, min_confidence, before/after timestamps)
- `LocalMemoryStore` — SQLite + FTS5 backend (with `LIKE` fallback when FTS5 unavailable). Lazy init; best-effort error handling (logged, never raised). Self-healing reliability decay on failure.
- `MemoryConfig` — frozen dataclass for backend selection and embedding model

**`orqest.autonomy` (Phase 3):**
- `AgentSpec` / `ToolSpec` — serializable contracts; LLM can emit these as structured output
- `AgentFactory.spawn(spec) -> DynamicAgent` — builds a Pydantic output model from JSON Schema via `pydantic.create_model()`; resolves tools from the registry; injects constraints into the system prompt
- `ToolRegistry` — `register`, `get`, `search(query, k)` (keyword scoring), `list_all`, `remove`, dunder methods
- `MetaOrchestrator(planner_agent, registry, default_model)` — goal → `TaskDecomposition` → per `SubTask` spawn-or-find agent → execute → `SubTaskResult` → aggregated `ExecutionResult`
- `DynamicAgent` extends `BaseAgent[GlobalState, BaseModel]`

**`orqest.observability` (Phase 4):**
- `Span` — `trace_id`, `span_id`, `parent_span_id`, `name`, `agent_name`, timing, `status`, `attributes`, `events`
- `Tracer` Protocol; `JSONTracer` is the default in-memory implementation (no external deps)
- `AgentEvent` — frozen immutable event (`event_type`, `agent_name`, `timestamp`, `data`, `span_id`, `trace_id`)
- `EventBus` — in-process pub/sub; `subscribe(event_type)`, `subscribe_all`, `emit(event)`. Handler exceptions logged and discarded (fire-and-forget)
- `EventBusPublishHook` — bridges `ToolHook` → `EventBus`; emits `tool.before`, `tool.after`, `tool.error` with configurable preview truncation
- `sse_sidecar(bus, replay=(), heartbeat_s=15.0, queue_size=256)` — async iterator yielding SSE-formatted strings; ring-buffered against slow consumers; optional historical replay for reconnection

**`orqest.workbench`:**
- `Workbench` — runtime container bundling memory + tracer + event_bus + recent_events ring buffer

**`orqest.compound`:**
- `SubAgentTool[StateT, ResultT]` + `SubAgentResult` — captures agent → executor → state-update → optional refinement; refinement-loop integrated

**`orqest.plan`:**
- `ExecutionPlan`, `PlanTask`, `PlanSubtask`, `PlanStatus` — typed multi-step workflow tracking; `to_sse_init()` is byte-stable as a frontend contract

**`orqest.mcp` (Phase 5):**
- `MCPServerConfig` / `MCPConfig` — explicit server definitions + auto-discovery toggle
- `MCPConnection(config)` — single-server lifecycle: `await connect()` → `.tools` → `await disconnect()`
- `MCPServerManager` — multi-server orchestration, `async with` context manager, `connect_all`, `get_all_tools` (flat list), `search_tools`
- `MCPToolAdapter.adapt[_many]` — MCP tool definitions → pydantic-ai `Tool` instances (graceful error-string return wrapper)
- `MCPDiscovery.search(query, max_results)` — online discovery (registry + well-known manifests + web fallback)
- Auto-discovery scans `~/.claude.json`, `~/.claude/claude.json`, `~/.config/Claude/claude_desktop_config.json`
- `create_orqest_server(factory, registry, meta, default_model, api_key)` — FastMCP server exposing `create_agent`, `run_agent`, `solve_goal`, `list_agents`. Run with `python -m orqest.mcp.server`

**`orqest.tools.web`:**
- `web_search(query, k, provider, api_key)` — pluggable provider strategy (tavily / exa / brave / serper); graceful degradation when key missing
- `web_fetch(url)` — plain GET with `WebFetchResult(url, status_code, content_type, text, truncated)`

**Multi-modal prompts and streaming:**
- `BaseAgent.call_model` / `call_model_stream` / `stream_output` / `stream_events` accept `str | Sequence[UserContent]` (images, PDFs, audio, video via pydantic-ai's `ImageUrl` / `DocumentUrl` / `AudioUrl` / `VideoUrl` / `BinaryContent`)
- `Prompt` type alias (`str | Sequence[UserContent]`) exported from `orqest.agents`
- `call_model_stream()` — async context manager for streaming with history wiring
- `stream_output()` — async generator yielding partial structured output as the LLM generates tokens
- `stream_events()` — async generator yielding all agent events including tool call/result visibility

**Composition extensions:**
- `as_tool()` — wrap any `BaseAgent` as a pydantic-ai `Tool` for stateless orchestrator invocation
- `call_model()` on `BaseAgent` — multi-turn conversation support with automatic history wiring
- `CompoundTool` pattern — agent → executor → state update with HookRunner dispatch
- `run_with_retry()` — exception-based retry with default enrichment
- `ContextManager` — token-aware three-tier compaction (tool-result snip → turn summarization at 60% → emergency truncation at 85%)
- Documentation site (MkDocs Material) with concept docs + auto-generated API reference

### Changed
- `GlobalState.message_history` typed as `list[ModelMessage]` instead of `list[Any]`

## [0.0.1] - 2025-07-21

### Added
- `BaseAgent[StateT, OutputT]` — generic, async-first abstract base class for agents
- `GlobalState` — conversation state with app-level messages and pydantic-ai message history
- `keep_recent_messages()` — history truncation preserving first message and turn integrity
- `resolve_model()` — multi-provider model routing (OpenAI, Anthropic, Google, OpenRouter) using `provider:model_id` format
- `OrqestConfig` — frozen dataclass for runtime configuration
- `load_config()` and `get_default_config()` — explicit config loading with no import-time side effects
- `load_sys_prompt()` — system prompt file loader with upward directory search
- Tool and toolset registration on `BaseAgent`
- Custom history processor support
- Example notebook `01_basic_agent` with single agent and structured output
- Test suite covering all modules
