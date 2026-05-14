#!/usr/bin/env python3
"""scaffold_agent.py — lay down an Orqest agent module skeleton.

Copies the boilerplate from ``../assets/agent_module_template/`` into
``<app-dir>/agents/<name>/``, substituting placeholder strings so the
result is importable and PEP 8-clean.

Surfaces (selected via ``--surface``) progressively add layers:

* ``basic``            — single ``BaseAgent`` only. Smallest viable harness.
* ``workbench-events`` — adds ``Workbench`` + ``EventBus`` + ``HookRunner``
                         with ``EventBusPublishHook``. Use when the frontend
                         wants tool-call visibility (SSE).
* ``refinement``       — wraps the agent in ``RefinementLoop`` with
                         ``confidence_threshold``. Use for quality-gated runs.
* ``orchestrated``     — adds ``MetaOrchestrator`` + ``AgentFactory`` +
                         ``ToolRegistry``. Use for runtime decomposition.
* ``production``       — workbench-events + ``with_healing(...)``. Use for
                         production traffic.

Generated files (always):
    <app-dir>/agents/<name>/__init__.py
    <app-dir>/agents/<name>/agent.py
    <app-dir>/agents/<name>/types.py
    <app-dir>/agents/<name>/tools.py
    <app-dir>/agents/<name>/route.py

USAGE:

    python scripts/scaffold_agent.py \\
        --app-dir ./src/myapp \\
        --name orders_summary \\
        --surface basic

The script never overwrites existing files. If a destination file already
exists it prints a notice and skips it. Run with ``--force`` to overwrite.

After scaffolding:

1. Open the generated files and replace ``<NAME>`` placeholders with your
   actual class / variable names (the script already does this; this step
   is for any remaining ``<...>`` markers in docstrings).
2. Edit ``types.py`` to declare the agent's actual output schema.
3. Edit ``tools.py`` to wrap your existing app primitives.
4. Edit ``agent.py`` to fill in the system prompt.
5. Mount the router from your app's main router.
6. Produce ``AGENT_HARNESS.md`` per ``references/agent_harness_template.md``.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# The skill folder layout: this script lives at scripts/scaffold_agent.py;
# the assets live at ../assets/agent_module_template relative to here.
SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_ROOT / "assets" / "agent_module_template"


def _to_pascal_case(snake: str) -> str:
    """Convert ``orders_summary`` → ``OrdersSummary``."""
    parts = re.split(r"[_\-]+", snake)
    return "".join(p.capitalize() for p in parts if p)


def _substitute(text: str, *, name_snake: str, name_pascal: str) -> str:
    """Replace placeholder tokens in template content."""
    return (
        text.replace("<NAME>", name_pascal)
        .replace("<name>", name_snake)
        .replace("<Description>", f"{name_pascal} agent")
    )


def _is_valid_name(name: str) -> bool:
    """Validate the agent name is a usable Python identifier prefix."""
    return bool(re.fullmatch(r"[a-z][a-z0-9_]*", name))


def scaffold(
    app_dir: Path,
    name_snake: str,
    *,
    force: bool = False,
    surface: str = "basic",
) -> int:
    """Copy the template into the target project. Return exit code."""
    if not _is_valid_name(name_snake):
        print(
            f"[scaffold_agent] error: --name '{name_snake}' must be lowercase "
            "snake_case (start with a letter, then letters/digits/underscores).",
            file=sys.stderr,
        )
        return 2

    if not TEMPLATE_DIR.is_dir():
        print(
            f"[scaffold_agent] error: template dir missing at {TEMPLATE_DIR}. "
            "Is the skill installed correctly?",
            file=sys.stderr,
        )
        return 2

    if not app_dir.is_dir():
        print(
            f"[scaffold_agent] error: --app-dir '{app_dir}' is not a directory.",
            file=sys.stderr,
        )
        return 2

    name_pascal = _to_pascal_case(name_snake)
    target_dir = app_dir / "agents" / name_snake
    target_dir.mkdir(parents=True, exist_ok=True)

    # Ensure parent agents/ has an __init__.py for package discovery.
    parent_init = app_dir / "agents" / "__init__.py"
    if not parent_init.exists():
        parent_init.write_text(
            f'"""Agents package — {name_snake} and any future peers."""\n'
        )
        print(f"created  {parent_init}")

    print(f"scaffolding {name_pascal} agent (surface={surface}) at {target_dir}")
    print(f"template:   {TEMPLATE_DIR}")
    print()

    written = 0
    skipped = 0
    for src in sorted(TEMPLATE_DIR.iterdir()):
        if src.name in {"__pycache__"}:
            continue
        dst = target_dir / src.name
        if dst.exists() and not force:
            print(f"skipped  {dst} (exists; use --force to overwrite)")
            skipped += 1
            continue
        if src.is_file() and src.suffix == ".py":
            content = _substitute(
                src.read_text(),
                name_snake=name_snake,
                name_pascal=name_pascal,
            )
            dst.write_text(content)
            print(f"created  {dst}")
            written += 1
        else:
            shutil.copy2(src, dst)
            print(f"copied   {dst}")
            written += 1

    print()
    print(f"summary: {written} file(s) written, {skipped} skipped")
    print()
    if surface != "basic":
        print(
            f"NOTE: --surface {surface} was selected, but this script only emits "
            "the basic skeleton. After scaffolding, edit agent.py and "
            "route.py per references/recipes.md to add the additional layers "
            f"({surface!r} corresponds to recipe R1+/R4/R6/R7 — see recipes.md)."
        )
    print(
        "next steps:\n"
        f"  1. cd into {target_dir} and replace the <NAME> placeholders left in docstrings\n"
        f"  2. edit types.py to declare {name_pascal}Output's actual fields\n"
        f"  3. edit tools.py to wrap your app's existing primitives\n"
        f"  4. mount router from {target_dir / 'route.py'} in your main app router\n"
        "  5. produce AGENT_HARNESS.md per references/agent_harness_template.md"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scaffold an Orqest agent module skeleton.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--app-dir",
        type=Path,
        required=True,
        help="Target project root containing the existing app code "
        "(e.g. ./src/myapp).",
    )
    parser.add_argument(
        "--name",
        type=str,
        required=True,
        help="Agent name in lowercase snake_case (e.g. orders_summary).",
    )
    parser.add_argument(
        "--surface",
        type=str,
        choices=[
            "basic",
            "workbench-events",
            "refinement",
            "orchestrated",
            "production",
        ],
        default="basic",
        help="Recipe surface to scaffold for (basic = R1; orchestrated = R6; production = R7).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files.",
    )
    args = parser.parse_args(argv)
    return scaffold(
        args.app_dir.resolve(),
        args.name,
        force=args.force,
        surface=args.surface,
    )


if __name__ == "__main__":
    raise SystemExit(main())
