"""Bundled agentic-IDE skills shipped with orqest.

The canonical skill lives at ``orqest/skills/orqest/`` and is shipped as
package data. Use ``python -m orqest.skills install [target]`` to copy
it into a project's ``.claude/skills/`` directory (or any other agent's
skill folder).
"""

from pathlib import Path

SKILLS_ROOT = Path(__file__).parent
"""Filesystem path to the bundled skills directory. Resolved against the
installed package location — works whether orqest is installed editable,
from a wheel, or via ``pip install -e .``."""


__all__ = ["SKILLS_ROOT"]
