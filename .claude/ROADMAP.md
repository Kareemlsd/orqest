# Roadmap

## Core Problem

Building a single agent is easy. Going from one agent to multiple agents collaborating
requires a massive jump in infrastructure complexity — context management, execution
patterns, error handling, debugging — none of which is the developer's actual problem.

Orqest's goal: **make the jump from 1 agent to N agents incremental, not architectural.**

## Design Principle

An agent is defined once. How it participates — as a conversational agent, a pipeline
step, or a tool — is determined by how it's composed, not by rewriting the agent.
The same `BaseAgent[StateT, OutputT]` works in all contexts.

---

## Phase 1 — Composition Primitives

**Goal:** A developer can wire multiple agents together without writing glue code.

### 1.1 Agent-as-Tool

Wrap any `BaseAgent` as a pydantic-ai `Tool` so an orchestrating agent can call it.
The wrapped agent runs statelessly — it receives parameters, returns structured output,
and doesn't see conversation history. This is the right pattern for specialized agents
that do a focused job (e.g., a calculation, a classification, a transformation).

- Utility to wrap `BaseAgent` → pydantic-ai `Tool`
- The orchestrator decides when to call it (LLM-driven)
- No history passed — input/output only
- Example: `02_agent_as_tool/`

### 1.2 Sequential Pipeline

Chain agents where the output of one feeds the input of the next. Deterministic
execution order, developer-defined. The right pattern when the workflow is known
upfront (e.g., extract → validate → transform → summarize).

- `Pipeline([AgentA, AgentB, AgentC])` or similar composition API
- Each agent receives only the previous agent's output (no full history)
- Typed: the pipeline validates that output of step N is compatible with input of step N+1
- Short-circuit on failure — no silent propagation of bad state
- Example: `03_pipeline/`

### 1.3 Context Scoping

The core question of multi-agent systems: who gets what context?

- **Full history** — conversational agents that need the full thread
- **Previous output only** — pipeline steps that need just the prior result
- **Specific parameters** — tool-like agents that need explicit inputs, no context
- **Scoped view** — agents that see a subset of the shared state relevant to them

Provide clear primitives so the developer declares context scope per agent rather
than manually slicing and passing state.

---

## Phase 2 — Flexible Orchestration

**Goal:** Support non-linear workflows and dynamic routing.

### 2.1 Parallel Execution

Run independent agents concurrently (e.g., quality check + visualization can happen
at the same time). Collect and merge results.

- `parallel([AgentA, AgentB])` — runs both, returns both outputs
- Requires defining how outputs are merged or collected

### 2.2 Conditional Routing

Branch execution based on an agent's output or an explicit condition.

- Developer-defined conditions (if/else on output fields)
- LLM-driven routing (an orchestrator agent decides the next step)
- Fallback paths when an agent fails

### 2.3 Mixins / Capability Extensions

Extend agent capabilities through composition rather than deeper inheritance.

- Evaluate mixins vs. protocols vs. decorators based on real usage from Phase 1
- Candidates: retry logic, caching, input validation, output post-processing
- Decision deferred until Phase 1 patterns reveal what's actually needed

---

## Phase 3 — Production Readiness

**Goal:** Orqest is reliable enough to run in production and mature enough for
open-source contributors.

### 3.1 Observability

When agent 4 in a pipeline produces bad output, the developer needs to trace back
to which upstream agent caused the issue.

- Structured logging per agent (agent name, input summary, output summary, duration)
- Evaluate building on pydantic-ai's OpenTelemetry `instrument` support
- Pipeline-level trace that shows the full execution path

### 3.2 Error Recovery

- Configurable retry per agent within a pipeline
- Fallback agents (if A fails, try B)
- Checkpointing: save state after each step so a pipeline can resume mid-way

### 3.3 Testing Utilities

- Helpers for testing multi-agent composition without real API calls
- Pipeline-level test fixtures using `TestModel`
- Assertion helpers for validating agent interaction sequences

### 3.4 CI/CD & Open-Source Launch

- GitHub Actions for tests + lint on PR
- Published to PyPI
- Contributing guide
- Versioning strategy (SemVer from 0.1.0)

---

## What's NOT in Scope

- Domain-specific agents (the user builds those, orqest provides the building blocks)
- A visual UI or drag-and-drop builder
- Custom LLM inference (we use pydantic-ai for all model interaction)
- Competing with pydantic-ai — we build on top of it, not around it

## Current Status

- [x] BaseAgent[StateT, OutputT] with typed generics
- [x] Multi-provider model routing
- [x] Config without import-time side effects
- [x] History processing (pure function, turn integrity)
- [x] GlobalState for conversation tracking
- [x] Streaming (call_model_stream, stream_output, stream_events)
- [x] Multi-modal input support (images, PDFs, audio, video)
- [x] Token-aware context management (ContextManager with 3-layer compaction)
- [x] Tool result budgeting (budget_tool_results)
- [x] Phase 1.1 — Agent-as-Tool (as_tool())
- [x] Test suite (66 tests)
- [x] Examples: 01_basic_agent, 02_agent_as_tool, 03_streaming
- [x] MkDocs documentation site
- [ ] **Next: Phase 1.2 — Sequential Pipeline**
