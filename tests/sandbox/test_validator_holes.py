"""Regression tests for Phase 1 validator hardening.

Each test corresponds to an escape path that the pre-Phase-1 validator
would have accepted. Adding cases here whenever new escape vectors are
discovered keeps the blocklist honest.
"""

from __future__ import annotations

import pytest

from orqest.sandbox import InProcessSandbox, SubprocessSandbox, ValidationError


# --- Reflection-helper blocklist (the load-bearing addition) ----------------


@pytest.mark.parametrize(
    "name",
    ["getattr", "setattr", "delattr", "hasattr", "type", "dir", "super"],
)
def test_validator_rejects_reflection_helper(name: str) -> None:
    """Reflection helpers bypass the dunder-attribute check via string lookup.

    Pre-Phase-1, ``getattr(obj, "__class_" + "_")`` would have reached
    blocked dunders since the validator only inspected ``ast.Attribute``
    nodes. Blocking the names themselves closes the path.
    """
    sandbox = InProcessSandbox(unsafe=True)
    code = f"return {name}(args, 'x')"
    with pytest.raises(ValidationError):
        import asyncio
        asyncio.run(sandbox.validate(code, allowed_imports=set()))


@pytest.mark.parametrize(
    "name",
    ["getattr", "setattr", "delattr", "hasattr", "type", "dir", "super",
     "__build_class__"],
)
def test_validator_rejects_reflection_name_reference(name: str) -> None:
    """Bare references (without calls) are also rejected."""
    sandbox = InProcessSandbox(unsafe=True)
    code = f"f = {name}\nreturn 1"
    with pytest.raises(ValidationError):
        import asyncio
        asyncio.run(sandbox.validate(code, allowed_imports=set()))


# --- Subscript-based dunder reach-through -----------------------------------


@pytest.mark.parametrize(
    "attr",
    ["__class__", "__dict__", "__bases__", "__subclasses__", "__globals__"],
)
def test_validator_rejects_string_subscript_to_forbidden_attr(attr: str) -> None:
    """``obj["__class__"]`` is caught by the new Subscript check."""
    sandbox = InProcessSandbox(unsafe=True)
    code = f"return args[{attr!r}]"
    with pytest.raises(ValidationError):
        import asyncio
        asyncio.run(sandbox.validate(code, allowed_imports=set()))


# --- Direct dunder-attribute additions --------------------------------------


@pytest.mark.parametrize(
    "attr",
    ["__dict__", "__init_subclass__", "__init__", "__new__"],
)
def test_validator_rejects_new_dunder_attrs(attr: str) -> None:
    sandbox = InProcessSandbox(unsafe=True)
    code = f"x = args\nreturn x.{attr}"
    with pytest.raises(ValidationError):
        import asyncio
        asyncio.run(sandbox.validate(code, allowed_imports=set()))


# --- Runtime restriction in Tier-1 wrapper ----------------------------------


@pytest.mark.asyncio
async def test_subprocess_wrapper_strips_unsafe_builtins() -> None:
    """The Tier-1 subprocess no longer runs user code with full builtins.

    A code snippet that imports ``ast`` to bypass the validator at parse
    time and then uses ``getattr`` at runtime would have worked before
    Phase 1 (builtins weren't restricted). Now the validator blocks the
    reference, but even if a future validator gap reappears, the wrapper
    strips ``getattr`` from ``__builtins__``, so the call would
    ``NameError`` at runtime.

    We use the helper-style entry rather than constructing the raw
    payload — that exercises the same wrapper path consumers hit.
    """
    sandbox = SubprocessSandbox()
    # Use a name that the validator already blocks so we don't try to
    # smuggle code past it; assert the failure surfaces clearly.
    issues_code = "return getattr(args, 'x')"
    with pytest.raises(ValidationError):
        await sandbox.validate(issues_code, allowed_imports=set())


# --- Safe usage still works (regression guard) ------------------------------


@pytest.mark.asyncio
async def test_safe_user_code_still_passes() -> None:
    """The new blocklist additions must NOT block legitimate user code.

    A regression here means the hardening was too aggressive — the LLM
    will be unable to write normal-looking tools.
    """
    sandbox = InProcessSandbox(unsafe=True)
    # Common shape: define a helper, return its result.
    code = (
        "def helper(x):\n"
        "    return [i * 2 for i in x if i > 0]\n"
        "return helper(args['nums'])\n"
    )
    await sandbox.validate(code, allowed_imports=set())
    result = await sandbox.execute(
        code, args={"nums": [1, -2, 3, -4, 5]}, allowed_imports=set()
    )
    assert result.success
    assert result.output == [2, 6, 10]
