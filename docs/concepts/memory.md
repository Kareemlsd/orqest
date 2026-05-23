# Memory

Orqest provides a pluggable memory subsystem for agents to store and recall knowledge across interactions. The `MemoryStore` protocol defines the interface; `LocalMemoryStore` provides a SQLite backend with FTS5 full-text search.

## Memory Types

| Type | Purpose | Example |
|------|---------|---------|
| `semantic` | Facts and knowledge | "Python uses indentation for blocks" |
| `episodic` | Experiences and events | "User asked about quantum computing on 2025-01-15" |

## MemoryStore Protocol

All memory backends implement this protocol:

```python
from orqest.memory import MemoryStore

# The protocol requires these async methods:
# store(entry) -> str            # persist entry, return id
# recall(query, k, filters) -> list[MemoryEntry]  # retrieve top-k matches
# forget(entry_id) -> None       # remove by id
# update_reliability(entry_id, success) -> None  # adjust reliability
# count() -> int                 # total entries
```

## LocalMemoryStore (SQLite + FTS5)

The default backend uses SQLite with optional FTS5 full-text search:

```python
import asyncio
from orqest.memory import LocalMemoryStore, MemoryEntry, MemoryFilter


async def main():
    store = LocalMemoryStore("~/.orqest/memory.db")

    # Store a memory
    entry = MemoryEntry(
        content="Quantum computers use qubits instead of classical bits",
        memory_type="semantic",
        source_agent="research_agent",
        confidence=0.95,
    )
    entry_id = await store.store(entry)

    # Recall memories matching a query
    results = await store.recall("quantum computing", k=5)
    for r in results:
        print(f"[{r.memory_type}] {r.content} (confidence: {r.confidence})")

    # Filter by type, source, or confidence
    filtered = await store.recall(
        "quantum",
        k=3,
        filters=MemoryFilter(
            memory_type="semantic",
            source_agent="research_agent",
            min_confidence=0.8,
        ),
    )

    # Forget a memory
    await store.forget(entry_id)

    # Clean up
    await store.close()


asyncio.run(main())
```

### FTS5 Full-Text Search

`LocalMemoryStore` attempts to create FTS5 virtual tables on initialization. If FTS5 is unavailable (some SQLite builds omit it), it falls back to `LIKE` queries. This is transparent -- the API is identical either way.

FTS5 triggers keep the search index in sync with the main table on insert, update, and delete.

### Self-Healing Reliability

Memories have a `reliability_score` (0.0 to 1.0) that decays on failure:

```python
# Mark a memory as unreliable (e.g., agent used it and got wrong answer)
await store.update_reliability(entry_id, success=False)
# reliability_score *= 0.7

# Entries below 0.1 are automatically pruned
```

Each failure multiplies the score by 0.7. Entries that drop below 0.1 are automatically deleted. Successful usage is a no-op (the score stays where it is).

### Best-Effort Operations

All `LocalMemoryStore` operations are best-effort: errors are logged via `loguru` at WARNING level and never raised to the caller. This prevents memory subsystem failures from disrupting agent execution.

## MemoryEntry

A single unit of stored knowledge:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | Auto UUID | Unique identifier |
| `content` | `str` | required | The memory content |
| `memory_type` | `"semantic"`, `"episodic"`, or `"procedural"` | `"semantic"` | Classification |
| `source_agent` | `str` | `"unknown"` | Which agent created this |
| `confidence` | `float` | `1.0` | How confident the agent was (0-1) |
| `embedding` | `list[float] \| None` | `None` | Vector embedding — computed by the store's `embedder` if one is configured |
| `metadata` | `dict` | `{}` | Arbitrary key-value pairs |
| `created_at` | `datetime` | now | Creation timestamp |
| `last_accessed` | `datetime` | now | Last recall timestamp |
| `access_count` | `int` | `0` | Number of times recalled |
| `reliability_score` | `float` | `1.0` | Self-healing reliability (0-1) |

## MemoryConfig

Configuration for the memory subsystem. `PerKindConfig` carries the
per-kind policy — `decay_on_failure` / `prune_below` (reliability),
`ttl_days` (retention), `version_on_edit` (skill audit trail):

```python
from orqest.memory import LocalMemoryStore, MemoryConfig, PerKindConfig

config = MemoryConfig(
    backend="local",                    # "local" or "supabase"
    local_db_path="~/.orqest/memory.db",
    semantic=PerKindConfig(decay_on_failure=0.7, prune_below=0.1),
    episodic=PerKindConfig(ttl_days=90),          # auto-expire old sessions
    procedural=PerKindConfig(version_on_edit=True),  # keep a skill history
)

store = LocalMemoryStore(config=config)
```

### Embedding-based retrieval

Pass an `embedder` and semantic recall ranks by cosine similarity over
stored vectors instead of FTS5 keyword match. Orqest stays
embedding-model-neutral — the consumer brings the embedder (a local
`sentence-transformers` model, an embeddings API, anything):

```python
def embed(text: str) -> list[float]:
    ...  # your embedding model — sync or async

store = LocalMemoryStore(config=config, embedder=embed)
```

With no `embedder`, recall falls back to FTS5 / LIKE — unchanged.

### Maintenance

`await store.prune_expired()` deletes entries older than their per-kind
`ttl_days` and returns the count — a manual maintenance call (schedule it
yourself; it is not auto-run).

!!! note "Preview — non-local backend"

    `backend="supabase"` and `supabase_url` / `supabase_key` are designed
    seams for a future pgvector backend — accepted but not yet wired. The
    `local` backend, per-kind policy, and embedding retrieval *are* wired.

## What's Happening Under the Hood

1. `LocalMemoryStore` lazily opens the SQLite database on first operation
2. Tables and FTS5 indexes are created if they don't exist
3. `recall()` uses FTS5 `MATCH` (or `LIKE` fallback) and applies filter conditions as SQL `WHERE` clauses
4. Each recall updates `last_accessed` and increments `access_count` for accessed entries
5. `update_reliability(success=False)` multiplies the score by the per-kind `decay_on_failure` factor (default 0.7) and prunes entries below the per-kind `prune_below` floor (default 0.1)

## Related Concepts

- [Agents](agents.md) -- agents that use memory for context
- [Session Persistence](session-persistence.md) -- persisting conversation state (complementary to memory)
- [Observability](observability.md) -- tracing memory operations

## Runnable demos

- [`notebooks/02_meta_orchestrator.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/02_meta_orchestrator.ipynb) — `LocalMemoryStore` persisting spawned `AgentSpec`s across turns
- [`notebooks/10_runtime_topology.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/10_runtime_topology.ipynb) — `MemoryStoreCache` reusing designed topologies via semantic similarity
