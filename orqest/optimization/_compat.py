"""Single-file boundary for the optional ``gepa`` dependency.

Every import of a GEPA symbol in the optimization battery goes through
this module. Two reasons:

1. **Friendly error when the optional dep is missing.** Rather than the
   standard ``ModuleNotFoundError: No module named 'gepa'`` (with no hint
   that GEPA is opt-in), users get a one-line install instruction.
2. **Test isolation.** Tests monkey-patch ``orqest.optimization._compat.optimize``
   to avoid actually running GEPA. Keeping the import surface in one
   module means there's exactly one symbol to patch.
"""

from __future__ import annotations

_INSTALL_HINT = (
    "orqest.optimization requires the 'optimization' dependency group. "
    "Install with: uv sync --group optimization"
)

try:
    from gepa import optimize as _gepa_optimize  # type: ignore[import-not-found]
    from gepa.core.adapter import (  # type: ignore[import-not-found]
        EvaluationBatch as _GEPA_EvaluationBatch,
    )
    from gepa.core.adapter import (  # type: ignore[import-not-found]
        GEPAAdapter as _GEPA_Adapter,
    )
    from gepa.core.result import (  # type: ignore[import-not-found]
        GEPAResult as _GEPA_Result,
    )
except ImportError as _import_err:  # pragma: no cover - exercised only when missing
    # Capture the original exception in module scope; ``as exc:`` deletes the
    # name when the except block exits, so closures referencing it must
    # reach the captured copy instead.
    _GEPA_IMPORT_ERROR: ImportError = _import_err

    def _missing(*_a: object, **_kw: object) -> object:
        raise ImportError(_INSTALL_HINT) from _GEPA_IMPORT_ERROR

    optimize = _missing  # type: ignore[assignment]

    class _MissingBase:
        def __init_subclass__(cls, **_kw: object) -> None:
            raise ImportError(_INSTALL_HINT) from _GEPA_IMPORT_ERROR

    GEPAAdapter = _MissingBase  # type: ignore[assignment,misc]
    EvaluationBatch = _MissingBase  # type: ignore[assignment,misc]
    GEPAResult = _MissingBase  # type: ignore[assignment,misc]
else:
    optimize = _gepa_optimize
    GEPAAdapter = _GEPA_Adapter  # type: ignore[assignment,misc]
    EvaluationBatch = _GEPA_EvaluationBatch  # type: ignore[assignment,misc]
    GEPAResult = _GEPA_Result  # type: ignore[assignment,misc]


__all__ = ["EvaluationBatch", "GEPAAdapter", "GEPAResult", "optimize"]
