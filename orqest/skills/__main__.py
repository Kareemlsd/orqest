"""CLI entry point: ``python -m orqest.skills install [target]``.

Copies the bundled ``orqest`` skill folder into a target skills directory
(default: ``./.claude/skills/``). Idempotent — re-running overwrites
existing files. Project-scoped by default; pass ``~/.claude/skills`` for
a global install.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from orqest.skills import SKILLS_ROOT


def _install(target: Path, force: bool) -> int:
    src = SKILLS_ROOT / "orqest"
    if not src.is_dir():
        print(f"error: bundled skill source not found at {src}", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    dest = target / "orqest"
    if dest.exists() and not force:
        print(
            f"error: {dest} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 1
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    print(f"installed orqest skill → {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m orqest.skills",
        description="Install the bundled orqest agentic-IDE skill.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    install = sub.add_parser("install", help="Copy the bundled skill into a target dir.")
    install.add_argument(
        "target",
        nargs="?",
        default=".claude/skills",
        help="Destination skills directory (default: ./.claude/skills)",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing orqest/ subdirectory at the target.",
    )

    args = parser.parse_args(argv)
    if args.cmd == "install":
        return _install(Path(args.target).expanduser(), args.force)
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
