"""<NAME> agent module — Orqest harness.

Public surface:

- :class:`<NAME>Agent` — the BaseAgent subclass
- :func:`build` — factory that constructs a fresh agent per request
- :class:`<NAME>Output` — Pydantic output shape
- :data:`router` — FastAPI router (in route.py); mount from your main app

See AGENT_HARNESS.md at the repo root for the harness extensibility playbook.
"""
from .agent import <NAME>Agent, build
from .types import <NAME>Output

__all__ = ["<NAME>Agent", "<NAME>Output", "build"]
