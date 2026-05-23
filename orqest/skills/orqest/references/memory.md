# Memory — reference

Compressed judgment layer over `orqest/memory/`. For full reference + edge cases, read `docs/concepts/memory.md`.

## Three memory types (cognitive typology)

| Type | What it stores | Use for |
|---|---|---|
| `semantic` | Facts, concepts, preferences | "User prefers terse responses"; "Caesium-137 half-life = 30 years" |
| `episodic` | Events, observations, timeline | "User asked about X on 2026-04-25"; "Tool Y returned error on attempt 3" |
| `procedural` | Skills, sub-agent specs, tool-sequence recipes | A persisted `AgentSpec` for a sub-agent you trained; a "how to extract DOIs from text" recipe |

Procedural is the one most consumers under-use. It's how `MetaOrchestrator` persists the sub-agent roster across sessions.

## The two surfaces

```python
from orqest.memory import MemoryStore, LocalMemoryStore, MemoryEntry, MemoryFilter
```

- **`MemoryStore`** — Protocol (`store / recall / forget / update_reliability / count / list_recent / prune_expired`).
- **`LocalMemoryStore`** — the ships-by-default SQLite + FTS5 backend. Best-effort: errors log at WARNING, never raise.

## Minimal wire-up — `Workbench` does the bundling

```python
from orqest import Workbench
from orqest.memory import LocalMemoryStore, MemoryConfig, PerKindConfig, MemoryEntry

wb = Workbench(
    user_id="alice",
    session_id="2026-05-23-001",
    memory=LocalMemoryStore(
        config=MemoryConfig(
            local_db_path="~/.app/memory.db",
            semantic=PerKindConfig(decay_on_failure=0.7, prune_below=0.1),
            episodic=PerKindConfig(ttl_days=90),
            procedural=PerKindConfig(version_on_edit=True),
        ),
    ),
)

await wb.memory.store(MemoryEntry(
    content="User prefers terse responses.",
    memory_type="semantic",
    source_agent="onboarding",
    confidence=0.9,
))

hits = await wb.memory.recall(
    "response style",
    k=3,
    filters=MemoryFilter(memory_type="semantic", min_confidence=0.7),
)
```

`Workbench` also bundles `JSONTracer + EventBus + ui_registry + recent-events buffer`. One container, plumbed once.

## Embedding-based retrieval (optional)

Pass `embedder=...` (sync or async callable returning `list[float]`) to `LocalMemoryStore`. Stored entries get embedded at write time; semantic recall ranks by cosine similarity instead of FTS5 keyword match. Orqest stays embedding-model-neutral — bring your own (sentence-transformers, OpenAI embeddings, etc.).

Without an embedder: FTS5 → LIKE fallback if FTS5 isn't compiled in. Transparent — same API either way.

## Per-kind policy via `PerKindConfig`

| Field | Read by | Effect |
|---|---|---|
| `decay_on_failure` | `update_reliability(success=False)` | Multiplies `reliability_score` by this factor (default `0.7`) |
| `prune_below` | `update_reliability(success=False)` | Deletes entries whose score falls below this floor (default `0.1`) |
| `ttl_days` | `prune_expired()` | Entries older than this are deleted on the next manual maintenance call |
| `version_on_edit` | `store()` | Procedural-only: on update of an existing `Skill.name`, bumps `version` and keeps the prior row (audit trail) |

`prune_expired()` is manual — schedule it yourself; nothing auto-runs.

## Procedural memory — `Skill` shape

When `MetaOrchestrator` persists a sub-agent across sessions, it writes a procedural entry whose `structured_content` is a `Skill`:

```python
from orqest.memory import Skill, ToolCallSpec, SkillExample

skill = Skill(
    name="rate_limit_analyst",
    version=1,
    description="Diagnose rate-limit bursts and propose backoff strategies.",
    trigger="rate-limit",                                      # substring (case-insensitive)
    tool_calls=[ToolCallSpec(tool="get_rate_limit_logs", args={})],
    examples=[SkillExample(input="429 storm at 14:00", output="...")],
    agent_spec={...},                                          # the persisted AgentSpec, as a dict
)
```

`MetaOrchestrator._find_or_spawn` checks procedural memory keyed on `trigger` before asking the planner to emit a fresh `AgentSpec`. Optional `fuzzy_judge` callable on `ProceduralStrategy` rescues near-misses.

## Reliability self-healing

```python
await store.update_reliability(entry_id, success=False)   # score *= 0.7; prune if below 0.1
await store.update_reliability(entry_id, success=True)    # no-op
```

Each failure decays. Below the prune floor, the entry is deleted. Useful when an agent used a memory and got a wrong answer downstream — call `update_reliability(success=False)` so the bad fact gets less weight next time.

## `list_recent` — browse, not search

```python
recent = await store.list_recent(memory_type="episodic", limit=50)   # newest first
```

For UI surfaces that want "show me the last N events" rather than search.

## Pitfalls

- **Best-effort means silent.** A failed `store()` logs at WARNING and returns; nothing raises. Don't treat memory as a source of truth — treat it as a cache with reliability decay.
- **`prune_expired()` is manual.** It's not on a timer. Schedule it from your app loop or a cron.
- **Don't share a `LocalMemoryStore` across processes without care.** SQLite handles concurrent reads fine; concurrent writes are serialised by the OS. For multi-process production, look at the preview Supabase/pgvector seam.
- **`embedder` failure modes log + fall through.** If the embedder raises at `store()` time, the entry persists *without* an embedding (will only surface via FTS5/LIKE). At `recall()` time, embed failures fall back to FTS5/LIKE for that query. Both log at WARNING.
- **`MemoryFilter.memory_type` is exact-match.** No multi-type query in one call; loop if you need both semantic + episodic.

## Where to read more

- `docs/concepts/memory.md` — full reference (incl. FTS5 trigger details, schema, Supabase preview seam)
- `docs/concepts/autonomy.md` — how `MetaOrchestrator` uses procedural memory for the persistent roster
- `notebooks/02_meta_orchestrator.ipynb` — `LocalMemoryStore` persisting spawned `AgentSpec`s across turns
- `notebooks/10_runtime_topology.ipynb` — `MemoryStoreCache` reusing designed topologies via semantic similarity
