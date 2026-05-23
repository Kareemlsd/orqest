"""Drift check: every ``from orqest…import X`` mention in the shipped skill
must resolve against the real package.

This catches a class of doc rot mechanically — if an API gets renamed or
removed but the skill still references the old name, this test fails. It
intentionally does **not** parse free-text mentions (too noisy); it only
parses ``from orqest…`` import statements inside fenced Python code
blocks, which is where the load-bearing references live.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from orqest.skills import SKILLS_ROOT

SKILL_DIR = SKILLS_ROOT / "orqest"
SKILL_FILES: list[Path] = [
    SKILL_DIR / "SKILL.md",
    *sorted((SKILL_DIR / "references").glob("*.md")),
]

# Matches ``from orqest[.submodule[.…]] import a, b, c``
# Captures: (module, comma-separated names)
_IMPORT_RE = re.compile(
    r"from\s+(orqest(?:\.[a-zA-Z_][\w.]*)?)\s+import\s+([^\n#]+)"
)

# Matches fenced ```python code blocks
_PYTHON_FENCE_RE = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)


def _extract_imports(text: str) -> list[tuple[str, str, int]]:
    """Return (module, name, line_no) triples for every ``from orqest…``
    import inside any ```python code block in ``text``.
    """
    out: list[tuple[str, str, int]] = []
    for block_match in _PYTHON_FENCE_RE.finditer(text):
        block_start_line = text[: block_match.start()].count("\n") + 1
        block = block_match.group(1)
        for imp in _IMPORT_RE.finditer(block):
            module, names_blob = imp.group(1), imp.group(2)
            # Strip trailing parentheses + whitespace, split on comma
            names_blob = names_blob.replace("(", "").replace(")", "").strip()
            # Handle multi-line imports by stripping any continuation
            names_blob = names_blob.replace("\\", "")
            for raw in names_blob.split(","):
                name = raw.strip().split(" as ")[0].strip()
                if not name:
                    continue
                line_no = block_start_line + block[: imp.start()].count("\n")
                out.append((module, name, line_no))
    return out


@pytest.fixture(scope="module")
def all_imports() -> list[tuple[Path, str, str, int]]:
    """One row per (file, module, name, line_no) found across all skill files."""
    rows: list[tuple[Path, str, str, int]] = []
    for path in SKILL_FILES:
        text = path.read_text(encoding="utf-8")
        for module, name, line_no in _extract_imports(text):
            rows.append((path, module, name, line_no))
    return rows


def test_skill_files_exist() -> None:
    """Sanity: the bundled skill files we expect are present."""
    for path in SKILL_FILES:
        assert path.is_file(), f"missing skill file: {path}"
    assert (SKILL_DIR / "SKILL.md") in SKILL_FILES
    # At least the three Stage-1 references must exist.
    refs = {p.name for p in (SKILL_DIR / "references").glob("*.md")}
    assert {"orchestration.md", "memory.md", "autonomy.md"} <= refs


def test_imports_resolve(all_imports: list[tuple[Path, str, str, int]]) -> None:
    """Every ``from orqest…import X`` mention resolves to a real attribute."""
    failures: list[str] = []
    seen_modules: dict[str, object] = {}

    for path, module, name, line_no in all_imports:
        if module not in seen_modules:
            try:
                seen_modules[module] = importlib.import_module(module)
            except ImportError as exc:  # pragma: no cover - failure path
                failures.append(
                    f"{path.name}:{line_no}: cannot import module {module!r}: {exc}"
                )
                continue
        mod = seen_modules[module]
        if not hasattr(mod, name):
            failures.append(
                f"{path.name}:{line_no}: {module}.{name} not found (referenced in skill)"
            )

    if failures:
        pytest.fail(
            "Skill references {} symbol(s) that don't exist:\n  - ".format(len(failures))
            + "\n  - ".join(failures)
        )


def test_skill_frontmatter_present() -> None:
    """SKILL.md starts with a YAML frontmatter block with name + description."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must begin with YAML frontmatter"
    end = text.find("\n---\n", 4)
    assert end > 0, "SKILL.md frontmatter block not terminated"
    fm = text[4:end]
    assert re.search(r"^name:\s*orqest\s*$", fm, re.MULTILINE), (
        "frontmatter must set name: orqest"
    )
    assert re.search(r"^description:\s*\S", fm, re.MULTILINE), (
        "frontmatter must set a non-empty description"
    )
