# Orqest Public API Surface

The 18-symbol root re-exports plus documented submodule paths. Stay on this surface — never import from `orqest.internal.*` (no such module) or reach into module privates (`_leading_underscore`).

## Root re-exports — `from orqest import ...`

The slim facade. Use these for the most-common types.

| Symbol | Purpose |
|--------|---------|
| `Workbench` | Runtime container (memory + tracer + bus + ui_registry) |
| `Pipeline` | Sequential composition of agents/functions |
| `Parallel` | Concurrent fan-out + merge |
| `Router` | Rule-based or classifier-driven routing |
| `RefinementLoop` | Iterative refinement with evaluator + confidence threshold |
| `ExecutionPlan` | Multi-step workflow tracking |
| `PlanStatus`, `PlanSubtask`, `PlanTask` | Plan tracking types |
| `EnrichedOutput` | Output + confidence + uncertainty (metacognition) |
| `MetacognitionConfig` | Frozen dataclass for re-decomposition policy |
| `HealingConfig` | Frozen dataclass for watchdog + fallback config |
| `HookRunner`, `ToolHook` | Lifecycle hook plumbing |
| `HookDecision` | Discriminated union (Continue/Skip/Redirect/Abort) |
| `Continue`, `Skip`, `Redirect`, `Abort` | Hook decision variants |
| `HookAbortError` | Raised when a hook returns Abort |
| `OrqestConfig`, `load_config`, `get_default_config` | Config primitives |

## Submodule imports

Sub-types live in their submodule's `__all__`. Import via the documented path.

### `orqest.agents`

The agent runtime layer.

| Symbol | Purpose |
|--------|---------|
| `BaseAgent[StateT, OutputT]` | Generic, async-first abstract base class |
| `GlobalState` | Conversation state (app messages + pydantic-ai message history) |
| `BaseSessionState` | Adds session_id, created_at, serializable history |
| `CompoundTool` | Agent → executor → state-update with hooks |
| `run_with_retry` | Exception-based retry wrapper |
| `as_tool` | Wrap a BaseAgent as a pydantic-ai Tool |
| `Prompt` | Type alias `str | Sequence[UserContent]` for multi-modal |

### `orqest.memory`

Cognitive memory typology.

| Symbol | Purpose |
|--------|---------|
| `MemoryStore` | Protocol — `store`, `recall`, `forget`, `update_reliability`, `count` |
| `LocalMemoryStore` | SQLite + FTS5 backend; optional embedding-cosine recall via an `embedder`; `prune_expired()` maintenance |
| `MemoryEntry` | Pydantic — content + memory_type + confidence + metadata |
| `MemoryFilter` | Query constraints + `skill_name` / `skill_min_version` |
| `Skill`, `ToolCallSpec`, `SkillExample` | Procedural memory shapes |
| `MemoryConfig`, `PerKindConfig` | Per-kind policy — decay / prune / `ttl_days` / `version_on_edit` |

### `orqest.observability`

| Symbol | Purpose |
|--------|---------|
| `EventBus` | In-process pub/sub |
| `AgentEvent` | Frozen Pydantic event |
| `Span`, `Tracer`, `JSONTracer` | Tracing primitives |
| `EventBusPublishHook` | ToolHook → EventBus bridge |
| `sse_sidecar` | Async iterator yielding SSE-formatted strings |

### `orqest.autonomy`

Runtime agent design.

| Symbol | Purpose |
|--------|---------|
| `AgentSpec`, `ToolSpec` | Serializable contracts |
| `AgentFactory` | `spawn(spec) -> DynamicAgent` |
| `ToolRegistry` | Central tool namespace + `get_or_discover` |
| `MetaOrchestrator` | Goal → decompose → spawn-or-find → execute |
| `DynamicAgent` | The runtime-spawned agent type |

### `orqest.metacognition`

| Symbol | Purpose |
|--------|---------|
| `ConfidenceProtocol` | Pluggable strategy Protocol |
| `StructuredOutputProtocol` | Zero-cost; lifts confidence off output type |
| `LLMSelfRatingProtocol` | +1 LLM call rater agent |
| `EnsembleProtocol(k=N)` | +k–1 parallel calls; pairwise agreement |
| `MetacognitionHook` | ToolHook → metacognition.confidence events |
| `confidence_salience`, `recency_salience` | Salience scorers for ContextManager |

### `orqest.healing`

| Symbol | Purpose |
|--------|---------|
| `Watchdog`, `Detection` | Protocol + Pydantic record |
| `StallDetector`, `LoopDetector`, `RegressionDetector` | Concrete watchdogs |
| `RecoveryAction` | Discriminated union |
| `EscalateToUser`, `AbortRun` | Recovery action variants |
| `WatchdogHook` | ToolHook mapping Detection → policy → HookDecision |
| `default_policy` | Default Detection → RecoveryAction mapping |
| `FallbackModel` | pydantic-ai Model subclass with sticky failover |
| `resolve_model_with_fallback` | Build a FallbackModel chain |
| `HealingRunner` | Async context manager owning the poll loop |

### `orqest.ui`

Generative UI primitives + first-party components.

| Symbol | Purpose |
|--------|---------|
| `UIComponentSpec[T]` | Generic Pydantic with `component_type` discriminator |
| `UIDeltaEvent`, `UIDeltaOp` | Delta-based partial updates |
| `ComponentRegistry`, `default_registry` | Per-Workbench schema registry |
| `UIEmitter` | init/delta/remove convenience over EventBus |
| `ui_init_event_type`, `ui_delta_event_type`, `ui_remove_event_type` | Event-type helpers |
| First-party components | `PlanComponent`, `ChartComponent`, `TableComponent`, `FormComponent`, `TakeoverDialogComponent` |
| Layer-2 grammars | `VegaChartComponent`, `MermaidComponent`, `LatexComponent`, `JsonViewerComponent` |
| Layer-3 escape hatch | `SandboxedHTMLComponent` |
| Other primitives | `LayoutComponent`, `TextComponent`, `MarkdownComponent`, `ImageComponent`, `BadgeComponent`, `ButtonComponent`, `InputComponent` |

### `orqest.mcp`

Model Context Protocol — client + server + auto-discovery.

| Symbol | Purpose |
|--------|---------|
| `MCPServerConfig`, `MCPConfig` | Connection definitions |
| `MCPConnection`, `MCPServerManager` | Single + multi-server lifecycles |
| `MCPToolAdapter` | MCP tool defs → pydantic-ai Tool |
| `MCPDiscovery`, `DiscoveredServer` | Search — registry endpoints + configured well-known manifests |
| `DiscoveryHook` | Opportunistic auto-register on tool-not-found |
| `PermissionGate` | Protocol — `AllowAll`, `DenyAll` (default), `AllowList` (regex) |

### `orqest.tools.web`

| Symbol | Purpose |
|--------|---------|
| `web_search` | Multi-provider search (tavily/exa/brave/serper); graceful when key missing |
| `web_fetch` | Plain GET with truncation |

### `orqest.compound`

| Symbol | Purpose |
|--------|---------|
| `SubAgentTool[StateT, ResultT]` | Agent → executor → state-update + optional refinement |
| `SubAgentResult` | Result with optional confidence/uncertainty fields |

### `orqest.plan`

| Symbol | Purpose |
|--------|---------|
| `ExecutionPlan` | Multi-step workflow tracking with byte-stable SSE init |
| `PlanTask`, `PlanSubtask`, `PlanStatus` | Plan tracking types |

### `orqest.utils`

Internal helpers (use sparingly).

| Symbol | Purpose |
|--------|---------|
| `resolve_model` | Multi-provider model resolution from `provider:model_id` |
| `estimate_tokens` | Heuristic token counting (3.5 chars/token) |

## Imports cheat sheet

```python
# Most common: facade types
from orqest import Workbench, Pipeline, Parallel, RefinementLoop, HookRunner, load_config

# Agents
from orqest.agents import BaseAgent, GlobalState, BaseSessionState, as_tool

# Memory
from orqest.memory import LocalMemoryStore, MemoryEntry, MemoryFilter, Skill

# Observability
from orqest.observability import EventBus, sse_sidecar, EventBusPublishHook

# Autonomy
from orqest.autonomy import AgentSpec, AgentFactory, ToolRegistry, MetaOrchestrator

# Metacognition
from orqest.metacognition import StructuredOutputProtocol, LLMSelfRatingProtocol, MetacognitionHook

# Healing
from orqest.healing import HealingConfig, StallDetector, FallbackModel, HealingRunner

# UI
from orqest.ui import UIComponentSpec, ChartComponent, UIEmitter, ComponentRegistry

# MCP
from orqest.mcp import MCPServerManager, MCPDiscovery, DiscoveryHook, AllowList

# Web tools
from orqest.tools.web import web_search, web_fetch
```

## Hard rules

- **Stay on the documented public surface.** Never import from `orqest.internal.*` (doesn't exist) or reach into module privates.
- **Don't reach into pydantic-ai internals** either. Wrap, compose, bridge — never re-implement what pydantic-ai already provides.
- **One inheritance level.** `BaseAgent → ConcreteAgent` is fine. Beyond that, prefer Protocols and composition.
