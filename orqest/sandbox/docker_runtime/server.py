"""FastMCP server — the body of the orqest/agent-runtime container.

Wires:

* :class:`SessionAuthMiddleware` — JWT validation on every tools/call + tools/list.
* :class:`Executor` — per-agent venv + subprocess code execution.
* :class:`ToolStore` — SQLite-backed per-user tool persistence.
* Four built-in tools (always advertised):

  * ``execute_python(code, agent_id, args, allowed_imports, dependencies,
    timeout_s, memory_mb)`` — run an LLM-authored implementation.
  * ``promote_tool(name, description, parameters, implementation,
    allowed_imports, dependencies)`` — persist + dynamically register a tool.
    Internally callable by the threshold-counter; also externally callable
    for ``"eager"`` promotion mode.
  * ``list_persisted_tools()`` — enumerate the SQLite library.
  * ``forget_tool(name, version)`` — remove from SQLite + registry.

* On startup, replays the SQLite library — every persisted tool gets
  registered via ``mcp.add_tool(...)`` BEFORE the server starts accepting
  connections. New connections see them in their first ``tools/list``.

* On promotion, ``mcp.add_tool(...)`` fires
  ``notifications/tools/list_changed`` automatically (FastMCP behavior
  when called inside an active request context).
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import Tool as FastMCPTool
from loguru import logger

from orqest.sandbox.docker_runtime.auth import SessionAuthMiddleware
from orqest.sandbox.docker_runtime.executor import Executor, ExecutorConfig
from orqest.sandbox.docker_runtime.store import PersistedTool, ToolStore


def _hash_impl(implementation: str) -> str:
    return hashlib.sha256(implementation.encode("utf-8")).hexdigest()


def _persisted_to_runner(
    tool: PersistedTool,
    *,
    executor: Executor,
    store: ToolStore,
):
    """Build the async callable that becomes the MCP tool body for a
    persisted (already-promoted) tool. Captures the spec into the closure;
    every invocation increments ``invocation_count`` for telemetry.
    """

    async def _runner(args: dict[str, Any] | None = None) -> Any:
        result = await executor.execute(
            code=tool.implementation,
            args=dict(args or {}),
            allowed_imports=set(tool.allowed_imports),
            agent_id=f"persisted__{tool.name}",
            dependencies=list(tool.dependencies),
            timeout_s=10.0,
            memory_mb=256,
        )
        store.record_invocation(tool.name, version=tool.version)
        if result.success:
            return result.output
        return {
            "error": result.error or "execution failed",
            "stage": "executor.execute",
            "tool_name": tool.name,
        }

    _runner.__name__ = tool.name
    _runner.__doc__ = tool.description
    return _runner


def build_server(
    *,
    executor: Executor,
    store: ToolStore,
    middleware: SessionAuthMiddleware | None,
    promotion_policy: str = "threshold",
    promotion_threshold: int = 3,
) -> FastMCP:
    """Construct the FastMCP server with built-in tools + persisted library.

    Args:
        executor: An :class:`Executor` configured with the per-session
            workspace + allowed_packages.
        store: A :class:`ToolStore` backed by ``/data/orqest-tools.sqlite``.
        middleware: Optional :class:`SessionAuthMiddleware`. ``None`` skips
            auth (useful for tests).
        promotion_policy: ``"threshold"`` / ``"eager"`` / ``"operator_approval"``.
        promotion_threshold: For threshold mode, N successful invocations
            of an unpersisted tool before auto-promotion.

    """
    mcp = FastMCP("orqest-agent-runtime")
    if middleware is not None:
        mcp.add_middleware(middleware)

    # Counter: (tool_name, code_hash) → successful invocation count.
    # When promotion_policy=="threshold" and count >= threshold, auto-promote.
    counts: dict[tuple[str, str], int] = defaultdict(int)
    # Track which (name, hash) pairs are already persisted to avoid re-promote
    persisted_hashes: set[tuple[str, str]] = set()

    def _refresh_persisted_hashes() -> None:
        persisted_hashes.clear()
        for t in store.list_all():
            persisted_hashes.add((t.name, t.implementation_hash))

    _refresh_persisted_hashes()

    # Replay persisted tools — each becomes an MCP tool advertised in
    # tools/list. Done BEFORE accepting connections so the first
    # tools/list response includes them.
    for tool in store.replay():
        mcp.add_tool(FastMCPTool.from_function(
            _persisted_to_runner(tool, executor=executor, store=store),
            name=tool.name,
            description=tool.description,
        ))
        logger.info("replayed persisted tool '{n}' v{v}", n=tool.name, v=tool.version)

    @mcp.tool()
    async def execute_python(
        code: str,
        agent_id: str,
        args: dict[str, Any] | None = None,
        allowed_imports: list[str] | None = None,
        dependencies: list[str] | None = None,
        timeout_s: float = 5.0,
        memory_mb: int = 128,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        """Run an LLM-authored Python implementation in the agent's venv.

        Returns a dict with ``success`` / ``output`` / ``error`` / ``stdout``
        / ``duration_ms`` matching :class:`ExecutionResult`.

        ``tool_name`` (when supplied) is used by the threshold-counter
        to decide whether to auto-promote this implementation to a
        persisted, named tool. Pass it as the LLM-emitted tool name.
        """
        result = await executor.execute(
            code=code,
            args=dict(args or {}),
            allowed_imports=set(allowed_imports or []),
            agent_id=agent_id,
            dependencies=list(dependencies) if dependencies else None,
            timeout_s=timeout_s,
            memory_mb=memory_mb,
        )

        # Promotion logic — only on success + when caller named the tool
        if result.success and tool_name and promotion_policy == "threshold":
            key = (tool_name, _hash_impl(code))
            if key not in persisted_hashes:
                counts[key] += 1
                if counts[key] >= promotion_threshold:
                    logger.info(
                        "auto-promoting tool '{n}' after {c} successes",
                        n=tool_name, c=counts[key],
                    )
                    await _do_promote(
                        name=tool_name,
                        description=tool_name,  # caller can re-promote with better desc
                        parameters={},
                        implementation=code,
                        allowed_imports=list(allowed_imports or []),
                        dependencies=list(dependencies or []),
                        agent_id=agent_id,
                    )

        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "stdout": result.stdout,
            "duration_ms": result.duration_ms,
        }

    async def _do_promote(
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        implementation: str,
        allowed_imports: list[str],
        dependencies: list[str],
        agent_id: str | None,
    ) -> PersistedTool:
        """Internal promote — used by both threshold-counter and the
        explicit ``promote_tool`` MCP tool.
        """
        tool = store.persist(
            name=name,
            description=description,
            parameters=parameters,
            implementation=implementation,
            allowed_imports=allowed_imports,
            dependencies=dependencies,
            promoted_from_agent=agent_id,
        )
        # Register as MCP tool — fires notifications/tools/list_changed
        mcp.add_tool(FastMCPTool.from_function(
            _persisted_to_runner(tool, executor=executor, store=store),
            name=tool.name,
            description=tool.description,
        ))
        persisted_hashes.add((tool.name, tool.implementation_hash))
        logger.info(
            "promoted tool '{n}' v{v} (hash {h:.10})",
            n=tool.name, v=tool.version, h=tool.implementation_hash,
        )
        return tool

    @mcp.tool()
    async def promote_tool(
        name: str,
        description: str,
        parameters: dict[str, Any],
        implementation: str,
        allowed_imports: list[str] | None = None,
        dependencies: list[str] | None = None,
    ) -> dict[str, Any]:
        """Explicitly persist + register a tool. Bypasses the threshold counter.

        Useful for ``"eager"`` promotion mode or operator-driven promotion.
        Returns the persisted tool's ``{name, version, hash}``.
        """
        if promotion_policy not in ("eager", "operator_approval", "threshold"):
            raise ValueError(f"unknown promotion_policy {promotion_policy!r}")
        tool = await _do_promote(
            name=name,
            description=description,
            parameters=parameters,
            implementation=implementation,
            allowed_imports=list(allowed_imports or []),
            dependencies=list(dependencies or []),
            agent_id=None,
        )
        return {
            "name": tool.name,
            "version": tool.version,
            "implementation_hash": tool.implementation_hash,
            "promoted_at": tool.promoted_at,
        }

    @mcp.tool()
    async def list_persisted_tools() -> list[dict[str, Any]]:
        """Enumerate the persisted tool library (latest version per name)."""
        return [
            {
                "name": t.name,
                "version": t.version,
                "description": t.description,
                "parameters": t.parameters,
                "allowed_imports": t.allowed_imports,
                "dependencies": t.dependencies,
                "invocation_count": t.invocation_count,
                "promoted_at": t.promoted_at,
                "promoted_from_agent": t.promoted_from_agent,
            }
            for t in store.replay()
        ]

    @mcp.tool()
    async def forget_tool(name: str, version: int | None = None) -> dict[str, Any]:
        """Remove a persisted tool by name (and optional version).

        Returns ``{deleted: int}``. NOTE: the corresponding MCP tool
        registration is NOT removed from the server's in-memory registry
        in this version (FastMCP's remove API is awkward); the server
        must restart to fully unregister. Future hardening: track the
        FastMCP tool keys and call ``mcp.local_provider.remove_tool``.
        """
        deleted = store.forget(name, version=version)
        _refresh_persisted_hashes()
        return {"deleted": deleted, "name": name}

    return mcp


def build_server_from_env() -> FastMCP:
    """Construct the server using the env-var contract (see __main__)."""
    user_id = os.environ.get("ORQEST_USER_ID", "")
    session_id = os.environ.get("ORQEST_SESSION_ID", "")
    if not user_id or not session_id:
        raise RuntimeError(
            "ORQEST_USER_ID and ORQEST_SESSION_ID must be set "
            "(framework-issued; cannot be empty)"
        )

    allowed_pkgs_raw = os.environ.get("ORQEST_ALLOWED_PACKAGES", "")
    allowed_packages = frozenset(
        pkg.strip() for pkg in allowed_pkgs_raw.split(",") if pkg.strip()
    )

    promotion_policy = os.environ.get("ORQEST_PROMOTION_POLICY", "threshold")
    try:
        promotion_threshold = int(os.environ.get("ORQEST_PROMOTION_THRESHOLD", "3"))
    except ValueError:
        promotion_threshold = 3

    db_path = os.environ.get("ORQEST_TOOLS_DB", "/data/orqest-tools.sqlite")

    executor = Executor(ExecutorConfig(
        session_id=session_id,
        allowed_packages=allowed_packages,
    ))
    store = ToolStore(db_path)
    middleware = SessionAuthMiddleware.from_env()

    return build_server(
        executor=executor,
        store=store,
        middleware=middleware,
        promotion_policy=promotion_policy,
        promotion_threshold=promotion_threshold,
    )


__all__ = [
    "build_server",
    "build_server_from_env",
]
