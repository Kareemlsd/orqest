"""Tests for the Skill / ToolCallSpec / SkillExample shape."""

from __future__ import annotations

from datetime import datetime

import pytest

from orqest.memory.store import MemoryEntry, Skill, SkillExample, ToolCallSpec


def test_skill_minimal_construction():
    s = Skill(name="lint", description="lint code", trigger="fix lint")
    assert s.version == 1
    assert s.tool_sequence == []
    assert s.success_examples == []
    assert s.expected_outcome == ""


def test_skill_round_trip_through_json():
    original = Skill(
        name="lint",
        description="lint and fix",
        trigger="fix lint",
        tool_sequence=[
            ToolCallSpec(tool_name="ruff_check", arguments={"path": "."}),
            ToolCallSpec(tool_name="ruff_format", arguments={"path": "."}),
        ],
        expected_outcome="green linter",
        success_examples=[
            SkillExample(inputs={"file": "x.py"}, outputs={"errors": 0}),
        ],
        version=3,
    )
    blob = original.model_dump_json()
    revived = Skill.model_validate_json(blob)
    assert revived == original


def test_skill_default_version_is_one():
    assert Skill(name="x", description="d", trigger="t").version == 1


def test_tool_call_spec_arguments_default_empty_dict():
    t = ToolCallSpec(tool_name="x")
    assert t.arguments == {}
    assert t.notes == ""


def test_skill_example_default_now_timestamp():
    e = SkillExample()
    assert isinstance(e.occurred_at, datetime)


def test_memory_entry_procedural_validates_skill_shape():
    """When memory_type=='procedural' AND structured_content is set,
    Skill validation gates the construction."""
    valid = Skill(name="x", description="d", trigger="t").model_dump()
    entry = MemoryEntry(
        content="t",
        structured_content=valid,
        memory_type="procedural",
    )
    assert entry.memory_type == "procedural"
    assert entry.structured_content == valid


def test_memory_entry_procedural_rejects_invalid_skill():
    with pytest.raises(Exception):
        MemoryEntry(
            content="x",
            structured_content={"missing_required_fields": True},
            memory_type="procedural",
        )


def test_memory_entry_non_procedural_skips_skill_validation():
    """Validator is gated to procedural — semantic/episodic with weird
    structured_content does not validate against Skill."""
    entry = MemoryEntry(
        content="x",
        structured_content={"random": "stuff"},
        memory_type="semantic",
    )
    assert entry.structured_content == {"random": "stuff"}


def test_memory_entry_procedural_without_structured_content_ok():
    """No structured_content → no validation (legacy procedural rows
    still load even if they predate the typed shape)."""
    entry = MemoryEntry(content="x", memory_type="procedural")
    assert entry.memory_type == "procedural"
    assert entry.structured_content is None
