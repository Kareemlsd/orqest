"""Curated ``__builtins__`` shared by every sandbox tier.

The same restricted namespace is used by :class:`InProcessSandbox` (Tier 0)
and by the subprocess wrappers used by :class:`SubprocessSandbox` (Tier 1)
and the in-container :class:`Executor` (Tier 2). Centralising it here is
load-bearing for safety: the static AST validator catches the well-known
escape hatches at parse time, but the *runtime* defence-in-depth depends
on the sandboxed code never seeing names like ``getattr`` or ``__import__``
at all.

Pre-Phase-1 the Tier-1 wrapper called ``exec(code, namespace)`` without
setting ``__builtins__`` in the namespace, which caused Python to inject
the full real builtin set. That made the AST validator the *only* safety
surface for many escape paths — a regression the validator alone could
not fully cover. After this module's adoption, every tier runs with the
same curated builtin set.
"""

from __future__ import annotations

import importlib
from typing import Any

# The canonical safe builtin set. Notable absences (deliberate, do not add
# without weighing escape implications): ``__import__``, ``eval``, ``exec``,
# ``compile``, ``open``, ``globals``, ``locals``, ``vars``, ``input``,
# ``breakpoint``, ``exit``, ``quit``, ``help``, ``getattr``, ``setattr``,
# ``delattr``, ``hasattr``, ``type``, ``dir``, ``super``, ``__build_class__``,
# ``memoryview``, ``bytearray``. ``print`` is included; callers redirect
# stdout to capture it.
_SAFE_BUILTINS: dict[str, Any] = {
    # Arithmetic + safe collection helpers + str/repr.
    "abs": abs,
    "all": all,
    "any": any,
    "ascii": ascii,
    "bin": bin,
    "bool": bool,
    "bytes": bytes,
    "callable": callable,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "hash": hash,
    "hex": hex,
    "id": id,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "object": object,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,  # captured via redirect_stdout
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    # Common exceptions so user code can catch / raise them.
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "RuntimeError": RuntimeError,
    "StopIteration": StopIteration,
    "ArithmeticError": ArithmeticError,
    "AssertionError": AssertionError,
    "AttributeError": AttributeError,
    "ZeroDivisionError": ZeroDivisionError,
    "True": True,
    "False": False,
    "None": None,
}


def _build_restricted_import(allowed_imports: set[str]):
    """Return a ``__import__`` shim that honours the allowlist.

    User code that writes ``import re`` lands here. The shim refuses any
    top-level module whose root is not in *allowed_imports*; allowed roots
    delegate to the real ``importlib.import_module`` so the loaded module
    behaves normally inside the sandbox.
    """
    allowed = frozenset(allowed_imports)

    def _restricted_import(
        name: str,
        globals: dict | None = None,  # noqa: A002 — matches builtin signature
        locals: dict | None = None,  # noqa: A002
        fromlist: tuple = (),
        level: int = 0,
    ) -> Any:
        root = name.split(".", 1)[0]
        if root not in allowed:
            raise ImportError(
                f"import of {name!r} blocked by sandbox; "
                f"allowed: {sorted(allowed) if allowed else 'empty'}"
            )
        return importlib.import_module(name)

    return _restricted_import


def build_safe_builtins(allowed_imports: set[str]) -> dict[str, Any]:
    """Return a fresh curated ``__builtins__`` dict for *allowed_imports*.

    Always returns a *new* dict so callers can mutate the result without
    affecting other sandbox invocations (e.g., adding per-call bindings).
    """
    builtins = dict(_SAFE_BUILTINS)
    builtins["__import__"] = _build_restricted_import(allowed_imports)
    return builtins


def build_safe_namespace(
    *,
    args: dict[str, Any],
    allowed_imports: set[str],
) -> dict[str, Any]:
    """Return a ready-to-``exec`` namespace with curated builtins + ``args``.

    Pre-binds every allowed import so user code that writes ``re.findall(...)``
    works without first writing ``import re``. Missing modules in the
    allowlist surface as :class:`ImportError` — callers should surface that
    as a sandbox failure rather than letting the exec crash.
    """
    namespace: dict[str, Any] = {
        "__builtins__": build_safe_builtins(allowed_imports),
        "args": dict(args),
    }
    for module_name in allowed_imports:
        root = module_name.split(".", 1)[0]
        namespace[root] = importlib.import_module(module_name)
    return namespace


__all__ = [
    "build_safe_builtins",
    "build_safe_namespace",
]
