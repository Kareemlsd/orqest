# Orqest UI + Procedural Memory — Implementation Design

> **Date:** 2026-04-25 · **Status:** ✅ **shipped (Wave 1.2 + Wave 3, 2026-04-25)** · **Author:** Plan agent (deep-dive)
> **Anchors:** `.claude/VISION.md` § features #5 and #2 (procedural extension), `.claude/AUDIT_2026-04-25.md` § "Feature #2" / "Feature #5"
> **Sequencing:** Procedural memory in Wave 1.2 (+23 tests, parallel with metacognition + HookDecision). Generative UI in Wave 3 (+54 tests, after metacognition + healing proved the event-typing pattern).
> **Dependencies:** Both tracks independent of each other and of metacognition/self-healing tracks.

---

## Audit-claim validation

### Track 1 — Generative UI

**`ExecutionPlan` is the closest pattern to generative UI: CONFIRMED.**
- `to_sse_init()` (execution_plan.py:80-82) returns `{"tasks": [...]}` — the *init* payload.
- `set_task_status()` (execution_plan.py:84-134) emits `event_type="plan.task.updated"` with payload `{task_id, status, [subtask_id]}` — the *delta* event.
- `emit_init()` (execution_plan.py:136-156) emits `event_type="plan.init"` with full init payload.
- Polymath consumer side reads exactly these (`demo/polymath/frontend/src/lib/events.ts:48-66`, `demo/polymath/frontend/src/hooks/usePlan.ts:44-57`).

**Schema hardcoded to plan tasks: CONFIRMED.** `event_type="plan.task.updated"` (execution_plan.py:129) and `payload = {"task_id": ..., "status": ...}` (execution_plan.py:122) hardcode the protocol.

**`AgentEvent` untyped on purpose: CONFIRMED.** `data: dict[str, Any]` (events.py:36). `_format_sse` (sse_sidecar.py:35-43) treats `data` as opaque JSON.

**SSE wire format constraint discovered:** `EventSource.addEventListener(event_type, handler)` (Polymath useSidecar.ts:77-79) — **a new event_type requires a frontend whitelist update today**. Target of the redesign.

### Track 2 — Procedural Memory

**`MemoryEntry.memory_type` is hard-typed `Literal["semantic", "episodic"]`: CONFIRMED.** `store.py:31`. Same Literal in `MemoryFilter.memory_type` (`store.py:20`). SQL schema has no type constraint beyond column existing (`local.py:24`: `memory_type TEXT NOT NULL DEFAULT 'semantic'`) — SQLite can accept arbitrary strings; constraint is purely Pydantic-level.

**`recall()` filters but doesn't branch retrieval strategy: CONFIRMED.** `local.py:127-197` has a single retrieval pipeline: FTS5 `MATCH` (or `LIKE` fallback), then SQL `WHERE` filters. **Embeddings are stored but never read for similarity** — the `embedding` column round-trips to `MemoryEntry` (local.py:261) but no SQL ever uses it.

**`MetaOrchestrator._find_or_spawn` already persists agent specs: CONFIRMED.** `meta.py:222-295`. Stores as `memory_type="episodic"`. Test at `tests/autonomy/test_meta.py:387-409` asserts `entry.memory_type == "episodic"` — backward-compat preservation point.

**`MemoryConfig` has no per-kind TTL/version policy: CONFIRMED.** `config.py:13-23`.

---

## Track 1 — Generative UI Design

The audit pegs `ExecutionPlan` as the canonical pattern. The design extracts it without breaking it: `ExecutionPlan` *becomes* a `PlanComponent` carrier whose existing event types ARE the same protocol the new framework defines.

### Module layout — `orqest/ui/`

```
orqest/ui/
├── __init__.py
├── spec.py                  # UIComponentSpec[T] base + UIDeltaEvent + UIDeltaOp
├── registry.py              # ComponentRegistry (per-Workbench)
├── emitter.py               # UIEmitter — convenience helpers
├── components/
│   ├── __init__.py
│   ├── plan.py              # PlanComponent — wraps existing PlanTask payload
│   ├── chart.py             # ChartComponent
│   ├── table.py             # TableComponent
│   ├── form.py              # FormComponent
│   └── takeover.py          # TakeoverDialogComponent
└── events.py                # ui_init_event_type / ui_delta_event_type helpers
```

Public API reachable via `from orqest.ui import ...`. Root `orqest/__init__.py` is **NOT** modified (keeps root surface small per CLAUDE.md convention).

### `UIComponentSpec[T]` — generic base + discriminator field

**Decision: generic base + discriminator field (NOT closed discriminated union).** Reasons:
- A closed union forces every concrete component into core. Vision wants third-party (numatics-ai's `MoleculeViewer`, finance's `RiskHeatmap`).
- Pydantic generic with literal `component_type` field gives both inbound validation and outbound `model_dump()` discrimination.

```python
class UIComponentSpec(BaseModel, Generic[T]):
    component_type: str = Field(description="Discriminator — frontend resolver key.")
    component_id: str = Field(default_factory=lambda: str(uuid4()))
    data: T  # Concrete subclasses bind T to a specific BaseModel.
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_event_data(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
```

### Three concrete examples

**`PlanComponent`** — wraps existing `PlanTask` list; identical to `ExecutionPlan.to_sse_init()` so existing frontend continues working byte-for-byte.

**`ChartComponent`** — `chart_kind: Literal["line","bar","scatter","pie","heatmap"]`, `series: list[ChartSeries]`, `title`, `x_axis`, `y_axis`, `config`.

**`TableComponent`** — `columns: list[TableColumn]`, `rows: list[dict]`, `page_size`. `TableColumn` has `key`, `label`, `kind: Literal["text","number","date","boolean","link"]`, `sortable`.

### `UIDeltaEvent` — JSON-Patch-flavored

```python
UIDeltaOp = Literal["replace", "merge", "append", "remove"]

class UIDeltaEvent(BaseModel):
    component_id: str
    component_type: str
    op: UIDeltaOp
    path: str = Field(default="", description='Dot-path; "" means root.')
    value: Any = None
```

Op semantics:
- `replace`: set value at `path` to `value` (RFC 6902 replace)
- `merge`: shallow-merge dict into dict at path; else replace
- `append`: append `value` to list at path (streaming-append for chart series, table rows)
- `remove`: delete field/element at `path`

**Why not full RFC 6902?** `move`/`copy`/`test` rarely useful for UI. `add` split into `replace` (scalars) and `append` (list-tail) because that's the practical agent emission pattern. `merge` is non-RFC but matches partial dict updates.

### `ComponentRegistry` — per-Workbench service

**Decision: registry-as-service (per-Workbench), NOT import-time singleton.** Reasons: CLAUDE.md is explicit — "no side effects at import time." Per-instance matches `EventBus`/`Tracer` pattern. Multi-tenant backends need tenant isolation.

First-party components pre-registered by `Workbench.__init__` if `auto_register_first_party=True` (default).

```python
class ComponentRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, type[UIComponentSpec[Any]]] = {}

    def register(self, spec_class, *, overwrite=False) -> None: ...
    def get(self, component_type: str) -> type[UIComponentSpec] | None: ...
    def list_types(self) -> list[str]: ...
    def validate_payload(self, component_type, payload) -> UIComponentSpec | None: ...
```

`Workbench` integration: new `ui_registry: ComponentRegistry | None = None` ctor kwarg; default-construct + pre-register first-party. Existing tests pass because the new field defaults.

### `ExecutionPlan` refactor — backward-compatible

**Critical compat lever:** `ExecutionPlan` keeps its exact API. Internally, emit methods *also* publish a parallel typed `ui.<...>.init` / `ui.<...>.delta` event. **Gated on a constructor flag `emit_ui_events: bool = False` (default off) for the first ship** — without this flag, every existing test counting emissions would break (`tests/plan/test_execution_plan.py:113-138` asserts `len(bus.emitted) == 1`).

```python
def as_component(self, component_id: str | None = None) -> "PlanComponent":
    """Wrap as UIComponentSpec for the generative-UI pipeline."""
    cid = component_id or "plan"
    return PlanComponent(
        component_id=cid,
        data=PlanComponentData(tasks=list(self.tasks)),
    )

# emit_init: after existing plan.init emission, additionally:
if self._emit_ui_events:
    component = self.as_component()
    await bus.emit(AgentEvent(
        event_type="ui.plan.init",
        agent_name=agent_name,
        data=component.to_event_data(),
    ))

# set_task_status: after existing plan.task.updated emission:
if self._emit_ui_events:
    delta_path = (
        f"tasks.{task_idx}.subtasks.{sub_idx}.status"
        if subtask_id is not None else
        f"tasks.{task_idx}.status"
    )
    await bus.emit(AgentEvent(
        event_type="ui.plan.delta",
        agent_name=agent_name,
        data=UIDeltaEvent(
            component_id="plan",
            component_type="plan",
            op="replace",
            path=delta_path,
            value=status,
        ).model_dump(mode="json"),
    ))
```

### Migration phases

- **Phase A (this design):** ship `orqest.ui` + `as_component()` + flag-gated dual emission. Zero impact on existing consumers.
- **Phase B (follow-on):** flip `emit_ui_events` default to `True` after Polymath validation.
- **Phase C (future major):** mark legacy `plan.init` / `plan.task.updated` as deprecated; consumers move to `ui.plan.*`.

### SSE protocol surface

**Event-type conventions:**
- `ui.<component_type>.init` — full UIComponentSpec payload. Replaces any previously-rendered component with same `component_id`.
- `ui.<component_type>.delta` — partial update via `UIDeltaEvent`.
- `ui.<component_type>.remove` — payload `{component_id}`. Frontend removes.

SSE wire format unchanged. Backend exposes `GET /ui/component-types` returning `Workbench.ui_registry.list_types()` so the frontend resolver auto-builds the listener list (eliminating the hardcoded whitelist).

`GET /sessions/{sid}/ui/snapshot` reconstructs each known `component_id` from the event ring buffer (generalizes Polymath's existing `GET /sessions/{sid}/plan` pattern).

### Frontend resolver protocol (TypeScript pseudo-types)

```typescript
export interface UIComponentSpec<T = unknown> {
  component_type: string;
  component_id: string;
  data: T;
  metadata: Record<string, unknown>;
  created_at: string;
}

export type ComponentRenderer<T = unknown> =
  React.ComponentType<{ spec: UIComponentSpec<T>; sessionId: string }>;

export type ComponentResolver = (componentType: string) => ComponentRenderer | undefined;
```

`useGenerativeUI(sessionId, resolver)` succeeds `usePlan`. Existing `usePlan` becomes a thin wrapper filtering for `component_type === "plan"`.

### Polymath migration sketch

Backend: wherever Polymath emits `artifact.created` for a chart, additionally emit `UIEmitter.init(ChartComponent(...))`. Keep `artifact.created` during transition.

Frontend: `useGenerativeUI` keyed by `component_type`. `ChartsTab` filters to `chart`; renderer reads `data.series` directly. `ReportTab` reads latest `report` UIComponent. Existing artifact REST endpoint stays — generative UI augments, doesn't replace, file storage.

### Tests for Track 1 — ~20 tests

`tests/ui/{test_spec,test_registry,test_emitter,components/test_chart,components/test_table,test_execution_plan_integration}.py`

Coverage: spec round-trips, registry register/duplicate/overwrite, emitter init/delta/no-bus, component schema validation, dual-emission integration verifying both legacy AND typed events fire when flag on.

---

## Track 2 — Procedural Memory + Per-Kind Retrieval

### `MemoryEntry.memory_type` extension

```python
# store.py:31 (and :20)
memory_type: Literal["semantic", "episodic", "procedural"] = "semantic"
```

Backward compat: existing values continue to validate. Old persisted rows already in user databases continue to load (column is `TEXT NOT NULL` with no CHECK constraint).

### `Skill` shape — Option B (separate `structured_content` field)

**Decision: separate `structured_content: dict[str, Any] | None` field; `content` stays `str`.** Reasons: preserves SQL/FTS5 contract (FTS5 indexes `content`); typed payload lives in `structured_content`. Cleaner than `content: Union[str, Skill]`.

```python
class ToolCallSpec(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""

class SkillExample(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.now)

class Skill(BaseModel):
    name: str
    description: str
    trigger: str  # NL phrase that should match incoming queries
    tool_sequence: list[ToolCallSpec]
    expected_outcome: str
    success_examples: list[SkillExample] = Field(default_factory=list)
    version: int = 1


class MemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str  # For procedural: the trigger text (FTS5-indexed)
    structured_content: dict[str, Any] | None = None  # NEW
    memory_type: Literal["semantic", "episodic", "procedural"] = "semantic"
    # ... rest unchanged

    @model_validator(mode="after")
    def _validate_procedural_shape(self) -> "MemoryEntry":
        if self.memory_type == "procedural" and self.structured_content is not None:
            Skill.model_validate(self.structured_content)
        return self
```

SQL schema migration: `ALTER TABLE memories ADD COLUMN structured_content TEXT` (best-effort; existing column → swallow).

### `MemoryFilter` extension

```python
class MemoryFilter(BaseModel):
    memory_type: Literal["semantic", "episodic", "procedural"] | None = None
    source_agent: str | None = None
    min_confidence: float | None = None
    min_reliability: float | None = None
    skill_name: str | None = None  # NEW — exact-match on structured_content.name
    skill_min_version: int | None = None  # NEW
```

### Per-kind retrieval strategy

Avoid giant if/elif. Use strategy-pattern dispatch driven by a small mapping:

```python
# orqest/memory/strategies.py — NEW

class RetrievalStrategy(Protocol):
    async def recall(self, db, query, *, k, filters, fts_available) -> list[Row]: ...

class SemanticStrategy:
    """Embedding cosine when present, FTS5 fallback, LIKE final fallback.
    ORDER BY last_accessed DESC. Identical to current behavior."""
    async def recall(self, db, query, *, k, filters, fts_available): ...

class EpisodicStrategy:
    """FTS5 ordered by created_at DESC. Honors metadata.session_id filter."""
    async def recall(self, db, query, *, k, filters, fts_available): ...

class ProceduralStrategy:
    """Exact-match on structured_content.trigger (case-insensitive),
    LLM-judged trigger match for fuzzy cases (optional, callable injected)."""
    def __init__(self, fuzzy_judge=None) -> None:
        self._judge = fuzzy_judge
    async def recall(self, db, query, *, k, filters, fts_available): ...

def default_strategy_table() -> dict[str, RetrievalStrategy]:
    return {
        "semantic":   SemanticStrategy(),
        "episodic":   EpisodicStrategy(),
        "procedural": ProceduralStrategy(),
    }
```

`LocalMemoryStore.recall` dispatches:

```python
async def recall(self, query, *, k=5, filters=None) -> list[MemoryEntry]:
    db = await self._ensure_db()
    kind = (filters.memory_type if filters else None) or "semantic"
    strategy = self._strategies.get(kind, self._strategies["semantic"])
    rows = await strategy.recall(db, query, k=k, filters=filters, fts_available=self._fts_available)
    entries = [_row_to_entry(r) for r in rows]
    await self._touch_access(db, entries)
    return entries
```

Existing single-strategy behavior preserved as `SemanticStrategy` — current tests in `tests/memory/test_local.py` pass byte-identically.

**ProceduralStrategy details:**
1. Lowercase the query.
2. SQL: rows with `memory_type='procedural'` whose `structured_content.trigger` (via `json_extract`) equals or substring-matches `query`. Order by `reliability_score DESC, version DESC`.
3. If exact match returns ≥1 row, return up to `k`.
4. If no exact match AND `fuzzy_judge` injected, pull up to 20 candidate triggers, ask judge which match, return judged matches up to `k`.
5. Else `[]`.

The fuzzy judge is **injected, not built-in** — Orqest core doesn't ship LLM-judge orchestration in the memory module. Consumer wires it.

### `MemoryConfig` per-kind

```python
@dataclass(frozen=True)
class PerKindConfig:
    ttl_days: int | None = None  # None = forever
    decay_on_failure: float = 0.7  # current default
    prune_below: float = 0.1  # current default
    version_on_edit: bool = False

@dataclass(frozen=True)
class MemoryConfig:
    backend: Literal["local", "supabase"] = "local"
    local_db_path: str = "~/.orqest/memory.db"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    supabase_url: str | None = None
    supabase_key: str | None = None
    # NEW per-kind policies (defaults preserve current behavior):
    semantic: PerKindConfig = field(default_factory=PerKindConfig)
    episodic: PerKindConfig = field(default_factory=lambda: PerKindConfig(ttl_days=90))
    procedural: PerKindConfig = field(default_factory=lambda: PerKindConfig(version_on_edit=True))
```

`version_on_edit=True`: when storing procedural entry whose `structured_content.name` matches existing, increment version; keep prior row for audit. Implementation in `LocalMemoryStore._maybe_version_skill` triggered inside `store()` only when `memory_type="procedural"` and `version_on_edit=True`.

### `MetaOrchestrator._find_or_spawn` migration — two-phase

Today: stores `AgentSpec.model_dump_json()` in `MemoryEntry.content`, `memory_type="episodic"`.

A persisted `AgentSpec` IS procedural memory: it's *how to do a kind of thing*. Migration:

**Phase A — additive write:** in `_find_or_spawn` (`meta.py:280-291`), after existing episodic write, *also* write a procedural mirror entry with `structured_content={"name": spec.name, "trigger": subtask.name, ...}` and `content=subtask.name`. Both rows persist.

**Phase B — read-side migration:** recall path tries procedural first (exact-match on trigger). On miss, falls back to episodic.

**Test rewrite:** `tests/autonomy/test_meta.py:406` assertion changes from `entry.memory_type == "episodic"` to "any entry has memory_type=='episodic' AND any entry has memory_type=='procedural'". Single test rewrite Track 2 requires.

**Phase C (future major):** drop episodic mirror.

### Tests for Track 2 — ~22 new tests + 1 rewritten

`tests/memory/{test_store.py (extended), test_skill.py (new), test_local.py (extended), test_strategies.py (new), test_config.py (extended)}` + `tests/autonomy/test_meta.py` (1 rewritten).

Coverage: literal extension validation, Skill round-trip, structured_content procedural validation gating, exact-trigger match, case-insensitive recall, fuzzy judge injection, ordering by reliability+version, FTS5/LIKE fallback paths, per-kind config defaults, dual-write migration assertion.

### Concept doc extension — `docs/concepts/memory.md`

Add three sections after existing "Memory Types" table: **Procedural memory (skills)**, **Per-kind retrieval**, **Per-kind config (TTL, decay, versioning)**.

---

## Backward compatibility — exhaustive touched-file list

### Track 1 — additive only (one compat lever)

| File | Change | Risk | Mitigation |
|---|---|---|---|
| `orqest/ui/*` | NEW | none | n/a |
| `orqest/plan/execution_plan.py` | `as_component()`; flag-gated dual emission | `tests/plan/test_execution_plan.py:113-138` count emissions | `emit_ui_events: bool = False` default off; existing tests pass; new UI tests exercise flag-on path |
| `orqest/workbench/workbench.py` | Optional `ui_registry` kwarg | none (additive default) | — |

### Track 2 — additive + 1 test rewrite

| File | Change | Risk | Mitigation |
|---|---|---|---|
| `orqest/memory/store.py` | Literal extension; `structured_content` field; `Skill`/`ToolCallSpec`/`SkillExample`; filter fields; gated validator | `tests/memory/test_store.py` reads `memory_type`, JSON round-trips | Literal is superset; new fields default None — pass |
| `orqest/memory/local.py` | `ALTER TABLE` (best-effort); `recall` dispatches to strategies; existing logic moves to `SemanticStrategy` | `tests/memory/test_local.py` (10 tests) | Dispatched `SemanticStrategy` byte-identical for default `memory_type` — pass |
| `orqest/memory/config.py` | Add per-kind `PerKindConfig` fields | `tests/memory/test_config.py` | Additive; existing fields unchanged |
| `orqest/memory/strategies.py` | NEW | none | n/a |
| `orqest/memory/__init__.py` | Export new types | none | Additive |
| `orqest/autonomy/meta.py` | `_find_or_spawn` writes both episodic + procedural; recall tries procedural first | `tests/autonomy/test_meta.py:406` asserts episodic-only | **Test rewrite:** loosen to "any episodic AND any procedural" |
| `docs/concepts/memory.md` | Extension | n/a | — |

**Total: 8 core files touched, 1 test rewritten.** ~20 new UI tests + ~22 new memory tests.

---

## Open design questions

### Track 1
1. `UIEmitter` location: `orqest.ui` vs `orqest.observability`? **Lean: `orqest.ui`** (EventBus stays protocol-neutral).
2. `UIDeltaEvent.path` — JSONPath or dot-path? **Lean: dot-path** (frontend simplicity, agent-emission ergonomics). Open: escape rule for keys with dots.
3. `emit_ui_events` flag flip default to `True`? **Lean: next minor release after Polymath migration validates.**
4. Unknown component_type frontend behavior? **Lean: drop silently with log.** Open: late-registration handling.
5. `model_validator` enforcing `component_type`/`data` consistency? **Lean: YAGNI** — Pydantic Literal default already enforces.

### Track 2
6. Procedural `content` is just trigger text — should it be derived blob (`f"{name}\n{description}\n{trigger}"`) for richer FTS5 matching? **Lean: start with `content == trigger`; revisit after Polymath usage.**
7. `version_on_edit` keeps prior rows in same table — when does archive grow unbounded? **Lean: same table for simplicity; revisit if needed.**
8. Fuzzy judge in `MemoryConfig` vs `LocalMemoryStore` ctor? **Lean: `LocalMemoryStore` ctor** (judges are runtime objects, MemoryConfig is frozen dataclass).
9. Polymath episodic-mirror drop timing? **Lean: same major version bump as legacy `plan.init` deprecation.**
10. `MemoryFilter.skill_min_version` — needed yet? **Lean: keep** (cheap to add, costly later if data has multiple versions).
11. `json_extract` SQLite version compat? **Lean: JSON1 only** (broadly available).
12. Embeddings for `structured_content` vs `content`? **Lean: keep tied to `content`**; future `embedding_subject: Literal["content","structured_content"]` knob.

### Cross-track
13. Manifest endpoint `GET /event-types`? **Lean: yes** — single mechanism benefits both tracks. Out of scope; flagged.
14. `Workbench.snapshot()` add UI snapshot? **Lean: yes** (small addition); defer to follow-on.

## Critical files for implementation

- `orqest/plan/execution_plan.py`
- `orqest/memory/store.py`
- `orqest/memory/local.py`
- `orqest/memory/config.py`
- `orqest/autonomy/meta.py`
- `orqest/workbench/workbench.py`
- New: `orqest/ui/*`, `orqest/memory/strategies.py`
