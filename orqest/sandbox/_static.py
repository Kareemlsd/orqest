"""Static AST validation shared between sandbox backends.

Both :class:`InProcessSandbox` and :class:`SubprocessSandbox` perform the
same syntactic + import-allowlist check before execution. Centralizing it
here keeps the two backends behaviorally identical at the validate layer.

Default-deny posture: an empty ``allowed_imports`` set rejects any code
that contains an ``import`` or ``from ... import`` statement. Beyond
imports, we also reject the most common in-process escape hatches:
``eval``, ``exec``, ``compile``, ``__import__``, ``open``, and dunder
attribute access (``obj.__subclasses__``, ``cls.__class__``, etc.).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

# Names that must never appear as call targets, even if reachable via
# Python builtins. Every sandbox tier also strips these from the runtime
# ``__builtins__`` dict (see ``_safe_builtins.py``); the static check
# fails fast and produces a clearer error than a runtime ``NameError``.
#
# Reflection helpers (``getattr`` / ``setattr`` / ``delattr`` / ``hasattr``,
# ``type``, ``dir``, ``super``, ``__build_class__``) are blocked because
# they let user code reach dunders by string lookup, bypassing the
# ast.Attribute-based check below. Without them blocked, ``getattr(obj,
# "__cla" + "ss__")`` would defeat the dunder-attribute blocklist entirely.
_FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        # Direct execution / namespace access
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "globals",
        "locals",
        "vars",
        "input",
        "breakpoint",
        # Reflection / introspection escape hatches
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "type",
        "dir",
        "super",
        "__build_class__",
    }
)

# Dunder attributes that bridge from a safe value back to dangerous
# capabilities (e.g. ``().__class__.__bases__[0].__subclasses__()``).
_FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
        "__globals__",
        "__builtins__",
        "__import__",
        "__loader__",
        "__spec__",
        "__code__",
        "__closure__",
        "__getattribute__",
        "__reduce__",
        "__reduce_ex__",
        # Instance/class dict reach-through (``cls.__dict__["__class__"]``)
        "__dict__",
        # Subclass-creation hijack
        "__init_subclass__",
        # Direct dunder invocation
        "__init__",
        "__new__",
    }
)


@dataclass(frozen=True)
class StaticIssue:
    """One static-validation failure."""

    reason: str
    node_kind: str
    line: int


def _import_root(name: str) -> str:
    """Top-level import name (``re.match`` → ``re``, ``os.path`` → ``os``)."""
    return name.split(".", 1)[0]


def collect_issues(code: str, *, allowed_imports: set[str]) -> list[StaticIssue]:
    """Return every static issue in *code* given the allowed-imports set.

    An empty list means the code passes static validation. Returning a list
    rather than raising lets the caller emit a single error containing all
    failures, which is friendlier when the LLM emits code with multiple
    problems.
    """
    issues: list[StaticIssue] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        issues.append(
            StaticIssue(
                reason=f"syntax error: {exc.msg}",
                node_kind="SyntaxError",
                line=exc.lineno or 0,
            )
        )
        return issues

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _import_root(alias.name)
                if root not in allowed_imports:
                    issues.append(
                        StaticIssue(
                            reason=(
                                f"import {alias.name!r} not in allowed_imports "
                                f"({sorted(allowed_imports) if allowed_imports else 'empty'})"
                            ),
                            node_kind="Import",
                            line=node.lineno,
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = _import_root(module)
            if root not in allowed_imports:
                issues.append(
                    StaticIssue(
                        reason=(
                            f"from {module!r} import ... not in allowed_imports "
                            f"({sorted(allowed_imports) if allowed_imports else 'empty'})"
                        ),
                        node_kind="ImportFrom",
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name) and target.id in _FORBIDDEN_NAMES:
                issues.append(
                    StaticIssue(
                        reason=f"call to forbidden name {target.id!r}",
                        node_kind="Call",
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in _FORBIDDEN_ATTRIBUTES:
                issues.append(
                    StaticIssue(
                        reason=f"access to forbidden attribute {node.attr!r}",
                        node_kind="Attribute",
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.Subscript):
            # Catch ``obj["__class__"]``-style string-keyed reach-through.
            # Only constant string subscripts are checked; we deliberately
            # don't try to evaluate dynamic expressions (that's what the
            # blocked-builtins set + runtime restriction are for).
            slice_node = node.slice
            if (
                isinstance(slice_node, ast.Constant)
                and isinstance(slice_node.value, str)
                and slice_node.value in _FORBIDDEN_ATTRIBUTES
            ):
                issues.append(
                    StaticIssue(
                        reason=(
                            f"subscript access to forbidden attribute "
                            f"{slice_node.value!r}"
                        ),
                        node_kind="Subscript",
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            # Catches references like ``f = exec`` even when not called.
            issues.append(
                StaticIssue(
                    reason=f"reference to forbidden name {node.id!r}",
                    node_kind="Name",
                    line=node.lineno,
                )
            )

    return issues


def format_issues(issues: list[StaticIssue]) -> str:
    """Single human-readable string for a ValidationError message."""
    if not issues:
        return "(no issues)"
    return "; ".join(
        f"line {issue.line}: {issue.reason} ({issue.node_kind})"
        for issue in issues
    )


__all__ = [
    "StaticIssue",
    "collect_issues",
    "format_issues",
]
