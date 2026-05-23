"""Tests for the memory_type='tool' extension.

The 'tool' kind is a host-side mirror of the in-container SQLite tool
library that the Tier-2 DockerSandbox persists per-user. Tools are looked
up by name (not similarity), and structured_content carries a
GeneratedToolSpec-shaped dict.
"""

from __future__ import annotations

import pytest

from orqest.memory.config import MemoryConfig, PerKindConfig
from orqest.memory.local import LocalMemoryStore
from orqest.memory.store import MemoryEntry, MemoryFilter
from orqest.memory.strategies import ToolStrategy, default_strategy_table


def _tool_spec_dump(name: str, description: str = "x") -> dict:
    """Minimal GeneratedToolSpec.model_dump() shape."""
    return {
        "name": name,
        "description": description,
        "parameters": {"text": {"type": "string"}},
        "implementation": "return args['text'].upper()",
        "allowed_imports": [],
        "dependencies": [],
        "timeout_s": 5.0,
        "memory_mb": 128,
    }


# --- Construction / validation ---------------------------------------------


def test_memory_entry_accepts_tool_type():
    entry = MemoryEntry(
        content="extract DOIs from text",
        memory_type="tool",
        structured_content=_tool_spec_dump("extract_dois"),
        source_agent="alice",
    )
    assert entry.memory_type == "tool"
    assert entry.structured_content["name"] == "extract_dois"


def test_memory_filter_accepts_tool_type():
    f = MemoryFilter(memory_type="tool", source_agent="alice")
    assert f.memory_type == "tool"


def test_tool_entries_skip_skill_validator():
    """Tool entries should NOT trigger the procedural Skill-shape validator
    (which would require trigger / tool_sequence fields the GeneratedToolSpec
    doesn't have)."""
    # If the validator misfired, this would raise
    entry = MemoryEntry(
        memory_type="tool",
        content="x",
        structured_content={"only_tool_fields": True, "name": "x"},
    )
    assert entry.memory_type == "tool"


# --- Strategy table --------------------------------------------------------


def test_default_strategy_table_includes_tool():
    table = default_strategy_table()
    assert "tool" in table
    assert isinstance(table["tool"], ToolStrategy)


# --- Store + recall round-trip --------------------------------------------


@pytest.mark.asyncio
async def test_store_then_recall_by_name():
    store = LocalMemoryStore(":memory:")
    entry = MemoryEntry(
        content="extract DOIs from text",
        memory_type="tool",
        structured_content=_tool_spec_dump("extract_dois"),
        source_agent="alice",
    )
    await store.store(entry)
    recalled = await store.recall(
        "extract_dois", k=5, filters=MemoryFilter(memory_type="tool")
    )
    assert len(recalled) == 1
    assert recalled[0].structured_content["name"] == "extract_dois"


@pytest.mark.asyncio
async def test_recall_filters_other_kinds():
    """Tool recall should NOT return procedural / semantic entries."""
    store = LocalMemoryStore(":memory:")
    # Add a semantic entry with the same content
    await store.store(MemoryEntry(
        content="extract_dois",
        memory_type="semantic",
    ))
    # Add the tool entry
    await store.store(MemoryEntry(
        content="extract DOIs from text",
        memory_type="tool",
        structured_content=_tool_spec_dump("extract_dois"),
    ))
    recalled = await store.recall(
        "extract_dois", k=5, filters=MemoryFilter(memory_type="tool")
    )
    assert len(recalled) == 1
    assert recalled[0].memory_type == "tool"


# --- Per-kind config -------------------------------------------------------


def test_memory_config_includes_tool_kind():
    cfg = MemoryConfig()
    assert isinstance(cfg.tool, PerKindConfig)
    # Tools never auto-expire by default
    assert cfg.tool.ttl_days is None
    # Re-promotion bumps version (auditable history)
    assert cfg.tool.version_on_edit is True
    # Aggressive decay — bad tools are bad
    assert cfg.tool.decay_on_failure == 0.5
