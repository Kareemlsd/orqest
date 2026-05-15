"""Diff and commit boundary — write an :class:`OptimizationResult` back.

By default :func:`apply_result` is a **dry run**: it builds and returns the
unified diffs but does not mutate the target. The caller flips ``dry_run=False``
to commit, which:

1. Writes the evolved values onto the target object (string slots become the
   new ``.system_prompt``; non-string genes are written via :func:`setattr`).
2. **Resets the target's cached ``pydantic_ai.Agent``** by setting
   ``target._agent = None`` when present. This is the footgun: ``BaseAgent``
   constructs its underlying ``pydantic_ai.Agent`` lazily and caches it
   keyed off the constructor-time ``system_prompt``. Without the reset, a
   committed prompt is invisible at runtime — the cached Agent keeps the
   old one. Always covered by ``test_apply_commit_resets_cached_agent``.

The target can also be a plain ``dict[str, Any]`` (e.g., a settings store);
in that case the keys of ``best_decoded`` are written into the dict and no
``_agent`` reset happens.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from orqest.optimization.runner import OptimizationResult


@dataclass(frozen=True)
class OptimizationDiff:
    """One slot's before/after diff."""

    gene_name: str
    before: str
    after: str
    unified: str
    """Unified diff (``difflib.unified_diff`` output) — useful for printing
    or logging the change."""

    @property
    def changed(self) -> bool:
        return self.before != self.after


def _stringify(value: Any) -> str:
    return value if isinstance(value, str) else repr(value)


def _build_diff(name: str, before: Any, after: Any) -> OptimizationDiff:
    before_s = _stringify(before)
    after_s = _stringify(after)
    unified = "\n".join(
        difflib.unified_diff(
            before_s.splitlines(),
            after_s.splitlines(),
            fromfile=f"{name} (before)",
            tofile=f"{name} (after)",
            lineterm="",
        )
    )
    return OptimizationDiff(
        gene_name=name, before=before_s, after=after_s, unified=unified
    )


def _resolve_attr_name(name: str) -> str:
    """Strip a gene name's logical prefix to get an attribute name.

    Genes are typically named structurally (``"researcher.system_prompt"``,
    ``"planner.system_prompt"``) so multiple agents can coexist in one
    genome. When the target is a single object (not a dict-of-agents), we
    resolve to the rightmost segment — ``getattr(target, "system_prompt")``.

    For names without a dot, this is a no-op.
    """
    return name.rsplit(".", 1)[-1] if "." in name else name


def _read_current(target: Any, name: str) -> Any:
    """Resolve the *current* value for a gene name on the target.

    Conventions, in order:

    * ``dict``: ``target[name]`` (full gene name; KeyError → ``""``).
    * Other (typically :class:`BaseAgent`): ``getattr(target,
      _resolve_attr_name(name), "")`` — strips the dotted prefix, since
      a single agent carries the attribute under its own short name.
    """
    if isinstance(target, dict):
        return target.get(name, "")
    return getattr(target, _resolve_attr_name(name), "")


def _write_value(target: Any, name: str, value: Any) -> None:
    """Write a new value onto the target, honoring agent-cache invariants."""
    if isinstance(target, dict):
        target[name] = value
        return

    setattr(target, _resolve_attr_name(name), value)
    # Critical: when the target is a BaseAgent (or anything that lazily
    # constructs a pydantic_ai.Agent and caches it on `_agent`), the cache
    # must be invalidated or the new prompt is silently ignored at runtime.
    if hasattr(target, "_agent"):
        target._agent = None


def apply_result(
    result: OptimizationResult,
    *,
    target: Any,
    dry_run: bool = True,
) -> list[OptimizationDiff]:
    """Build per-gene diffs against ``target``; write them when not dry-run.

    Args:
        result: The :class:`OptimizationResult` from
            :meth:`OptimizationRunner.optimize`.
        target: A :class:`BaseAgent` or a plain ``dict``. For agents, the
            evolved values are written via ``setattr`` and the cached
            ``_agent`` is invalidated. For dicts, evolved values are written
            by key.
        dry_run: When True (default), no mutation happens — the diffs are
            returned for inspection only. Flip to False to commit.

    Returns:
        One :class:`OptimizationDiff` per gene in ``result.best_decoded``,
        in iteration order. Diffs with ``before == after`` are still returned
        (with ``unified=""``) so the caller can confirm "no change" explicitly
        rather than inferring from absence.

    """
    diffs: list[OptimizationDiff] = []
    for name, after_value in result.best_decoded.items():
        before_value = _read_current(target, name)
        diff = _build_diff(name, before_value, after_value)
        diffs.append(diff)
        if not dry_run and diff.changed:
            _write_value(target, name, after_value)
    return diffs
