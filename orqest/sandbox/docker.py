"""Tier-2 sandbox — Docker container per session.

The :class:`DockerSandbox`:

1. Validates LLM-authored Python via the shared :mod:`orqest.sandbox._static`
   AST validator (host-side; no container needed for ``validate``).
2. At ``__aenter__``, runs the published ``orqest/agent-runtime`` image with:

   * ``--network=none --read-only --tmpfs /workspace --memory --cpus``
   * ``--cap-drop=ALL --security-opt no-new-privileges --user 1000:1000``
   * ``--pids-limit``
   * env: ``ORQEST_USER_ID``, ``ORQEST_SESSION_ID``, ``ORQEST_HMAC_SECRET``,
     ``ORQEST_ALLOWED_PACKAGES``, ``ORQEST_PROMOTION_POLICY``,
     ``ORQEST_PROMOTION_THRESHOLD``
   * volume: ``orqest-user-<user_id>:/data`` (per-user persisted tool library)
   * port-publish ``-p 127.0.0.1:0:8000``

3. Connects an MCP client over Streamable HTTP, attaching
   ``Authorization: Bearer <JWT>``.
4. ``execute(...)`` calls the container's ``execute_python`` MCP tool.
5. At ``__aexit__``, closes the MCP connection and ``docker rm -f``s the
   container. The ``orqest-user-<user_id>`` volume persists.

**Honest framing.** Tier 2 (hardened Docker). Shared-kernel — protects
against accidental damage and most prompt-injection scenarios. Does NOT
protect against adversarial multi-tenant code; for that, run inside a
microVM (Firecracker / Kata) or use a managed sandbox provider. See
:doc:`/concepts/sandbox` for the full tier hierarchy + threat model.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
from typing import Any

from loguru import logger

from orqest.sandbox._compat import DOCKER_AVAILABLE, docker_errors, docker_from_env
from orqest.sandbox._static import collect_issues, format_issues
from orqest.sandbox.jwt import encode as jwt_encode
from orqest.sandbox.protocol import ExecutionResult, ValidationError

_DEFAULT_JWT_TTL_S = 3600   # 1 hour; sandbox lifetime is typically a session
_BOOT_POLL_INTERVAL_S = 0.25
_BOOT_TIMEOUT_S = 30.0


class DockerSandbox:
    """Tier-2 sandbox — Docker container per session."""

    def __init__(
        self,
        *,
        user_id: str,
        session_id: str,
        image: str = "orqest/agent-runtime:latest",
        allowed_packages: set[str] | None = None,
        memory_mb: int = 2048,
        cpus: float = 2.0,
        pids_limit: int = 512,
        promotion_policy: str = "threshold",
        promotion_threshold: int = 3,
        host_port: int | None = None,
        hmac_secret: bytes | str | None = None,
        bus: Any = None,
        docker_client: Any = None,
        jwt_ttl_s: int = _DEFAULT_JWT_TTL_S,
    ) -> None:
        if not user_id:
            raise ValueError("user_id is required and must be a non-empty string")
        if not session_id:
            raise ValueError("session_id is required and must be a non-empty string")
        if promotion_policy not in {"threshold", "eager", "operator_approval"}:
            raise ValueError(
                f"promotion_policy must be one of "
                f"('threshold','eager','operator_approval'), got {promotion_policy!r}"
            )
        self._user_id = user_id
        self._session_id = session_id
        self._image = image
        self._allowed_packages = allowed_packages or set()
        self._memory_mb = memory_mb
        self._cpus = cpus
        self._pids_limit = pids_limit
        self._promotion_policy = promotion_policy
        self._promotion_threshold = promotion_threshold
        self._host_port = host_port
        # Mint a fresh random HMAC secret if not provided. The host process
        # holds the secret; it's passed to the container via env var.
        if hmac_secret is None:
            self._hmac_secret = secrets.token_hex(32)
        elif isinstance(hmac_secret, bytes):
            self._hmac_secret = hmac_secret.decode("utf-8")
        else:
            self._hmac_secret = hmac_secret
        self._bus = bus
        self._docker_client = docker_client
        self._jwt_ttl_s = jwt_ttl_s

        # Lifecycle state — populated on __aenter__
        self._container: Any = None
        self._mcp_connection: Any = None
        self._published_port: int | None = None

    # -- properties --------------------------------------------------------

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def image(self) -> str:
        return self._image

    @property
    def published_port(self) -> int | None:
        return self._published_port

    @property
    def container(self) -> Any:
        """The docker-py Container, after __aenter__. None before."""
        return self._container

    @property
    def mcp_url(self) -> str | None:
        """``http://127.0.0.1:<port>/mcp`` after __aenter__."""
        if self._published_port is None:
            return None
        return f"http://127.0.0.1:{self._published_port}/mcp"

    # -- Sandbox Protocol --------------------------------------------------

    async def validate(
        self,
        code: str,
        *,
        allowed_imports: set[str],
    ) -> None:
        """Static AST validation (host-side; no container needed)."""
        issues = collect_issues(code, allowed_imports=allowed_imports)
        if issues:
            raise ValidationError(
                format_issues(issues), code_snippet=code[:200]
            )

    async def execute(
        self,
        code: str,
        *,
        args: dict[str, Any],
        allowed_imports: set[str],
        timeout_s: float = 5.0,
        memory_mb: int = 128,
        agent_id: str | None = None,
        dependencies: list[str] | None = None,
    ) -> ExecutionResult:
        """Execute via the container's ``execute_python`` MCP tool.

        The container's executor handles:
        * Static AST validation (defense-in-depth — host already validated)
        * Per-agent venv creation + dep installation gated by allowlist
        * Subprocess execution with RLIMIT enforcement
        * JSON-serialization of the result

        We return the typed :class:`ExecutionResult` regardless of success.
        Infrastructure failures (container died, MCP transport dropped)
        return ``success=False`` with a diagnostic message rather than
        raising — agents should be able to handle tool failures as data.
        """
        if self._mcp_connection is None:
            return ExecutionResult(
                success=False,
                error="DockerSandbox not entered (use `async with sandbox:`)",
                duration_ms=0.0,
            )

        # `tool_name` would let the runtime threshold-counter promote this
        # implementation. We don't pass it from here because the LLM
        # doesn't know the tool name at execute time — DynamicToolFactory
        # wraps each spawned tool with the name baked in. Future: thread
        # `tool_name` from DynamicToolFactory via a kwarg.
        try:
            result = await self._mcp_call(
                "execute_python",
                {
                    "code": code,
                    "agent_id": agent_id or "default",
                    "args": dict(args),
                    "allowed_imports": list(allowed_imports),
                    "dependencies": list(dependencies) if dependencies else None,
                    "timeout_s": timeout_s,
                    "memory_mb": memory_mb,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                success=False,
                error=f"MCP transport error: {exc}",
                duration_ms=0.0,
            )

        # The container returns a dict shaped like ExecutionResult.
        return ExecutionResult(
            success=bool(result.get("success")),
            output=result.get("output"),
            error=result.get("error"),
            stdout=str(result.get("stdout", "")),
            duration_ms=float(result.get("duration_ms", 0.0)),
        )

    # -- Lifecycle --------------------------------------------------------

    async def __aenter__(self) -> "DockerSandbox":
        """Run the container, wait for MCP server, open the MCP connection."""
        if not DOCKER_AVAILABLE:
            docker_from_env()  # raises ImportError with install hint

        client = self._docker_client or docker_from_env()
        errs = docker_errors()

        # Ensure per-user volume exists (idempotent)
        volume_name = f"orqest-user-{self._user_id}"
        try:
            client.volumes.get(volume_name)
        except errs.NotFound:
            client.volumes.create(name=volume_name)

        # Build env + run command
        env = {
            "ORQEST_USER_ID": self._user_id,
            "ORQEST_SESSION_ID": self._session_id,
            "ORQEST_HMAC_SECRET": self._hmac_secret,
            "ORQEST_ALLOWED_PACKAGES": ",".join(sorted(self._allowed_packages)),
            "ORQEST_PROMOTION_POLICY": self._promotion_policy,
            "ORQEST_PROMOTION_THRESHOLD": str(self._promotion_threshold),
        }
        # Port publish — None lets Docker pick a free port
        ports: dict[str, Any] = {
            "8000/tcp": ("127.0.0.1", self._host_port) if self._host_port else ("127.0.0.1", None),
        }

        try:
            self._container = client.containers.run(
                self._image,
                detach=True,
                remove=False,  # we manage removal ourselves on __aexit__
                environment=env,
                ports=ports,
                volumes={volume_name: {"bind": "/data", "mode": "rw"}},
                mem_limit=f"{self._memory_mb}m",
                memswap_limit=f"{self._memory_mb}m",  # disable swap → hard memory cap
                nano_cpus=int(self._cpus * 1_000_000_000),
                pids_limit=self._pids_limit,
                read_only=True,
                tmpfs={
                    "/workspace": f"size={self._memory_mb}m,uid=1000,gid=1000",
                    "/tmp": "size=128m,uid=1000,gid=1000",
                },
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                user="1000:1000",
                network_mode="bridge",
                hostname="orqest-runtime",
                # NOTE on networking — honest tradeoff for v0.8.0 Tier 2:
                # We use ``bridge`` (not ``none``) because port-publish
                # requires it; ``none`` would isolate the container fully
                # but also block the host MCP client from reaching the
                # container's FastMCP server. The defense layers against
                # LLM-authored code reaching the network anyway are:
                #   1. Static AST validator (allowed_imports must include
                #      `socket` / `urllib` / `httpx` / etc. — default empty)
                #   2. allowed_packages allowlist (no pip-installing
                #      arbitrary network libs unless operator opts in)
                #   3. JWT auth on the MCP boundary
                # For full network isolation, run Tier 3 (microvm) instead.
                # See docs/concepts/sandbox.md for the threat model.
            )
        except errs.ImageNotFound as exc:
            raise DockerImageNotFoundError(
                f"image {self._image!r} not present locally; "
                f"run: docker pull {self._image}"
            ) from exc

        # Discover the published port — Docker populates NetworkSettings
        # asynchronously after `containers.run`, so we poll briefly.
        self._published_port = None
        for _ in range(40):  # ~4s budget
            self._container.reload()
            port_info = self._container.attrs["NetworkSettings"]["Ports"].get("8000/tcp")
            if port_info and port_info[0].get("HostPort"):
                self._published_port = int(port_info[0]["HostPort"])
                break
            await asyncio.sleep(0.1)
        if self._published_port is None:
            raise DockerSandboxError(
                f"container {self._container.short_id} did not publish port 8000 within 4s"
            )

        # Wait for the MCP server to start accepting connections
        await self._wait_for_mcp_ready()

        # Open the MCP client connection
        await self._open_mcp()
        self._emit("docker.session_started", host_port=self._published_port)
        return self

    async def __aexit__(self, *_args: Any) -> None:
        """Close MCP, ``docker rm -f`` the container."""
        try:
            if self._mcp_connection is not None:
                with contextlib.suppress(Exception):
                    await self._mcp_connection.disconnect()
                self._mcp_connection = None
        except Exception as exc:  # noqa: BLE001
            logger.debug("MCP disconnect failed: {e}", e=exc)

        try:
            if self._container is not None:
                with contextlib.suppress(Exception):
                    self._container.stop(timeout=5)
                with contextlib.suppress(Exception):
                    self._container.remove(force=True)
                self._emit("docker.session_ended", container_id=self._container.short_id)
                self._container = None
        except Exception as exc:  # noqa: BLE001
            logger.debug("docker container cleanup failed: {e}", e=exc)

    # -- Internals --------------------------------------------------------

    def _mint_jwt(self) -> str:
        """Mint a fresh JWT for the auth bearer header."""
        claims = {
            "sub": self._user_id,
            "sid": self._session_id,
            "exp": int(time.time()) + self._jwt_ttl_s,
        }
        return jwt_encode(claims, self._hmac_secret)

    async def _wait_for_mcp_ready(self) -> None:
        """Poll the MCP endpoint until it accepts requests, or time out."""
        import httpx

        deadline = time.monotonic() + _BOOT_TIMEOUT_S
        url = f"http://127.0.0.1:{self._published_port}/mcp"
        async with httpx.AsyncClient() as http:
            while time.monotonic() < deadline:
                try:
                    # MCP handshake — initialize doesn't require auth (see middleware design)
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 0,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "orqest-bootcheck", "version": "0"},
                        },
                    }
                    resp = await http.post(
                        url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream",
                        },
                        timeout=5.0,
                    )
                    if resp.status_code == 200:
                        return
                except (httpx.HTTPError, OSError):
                    pass
                await asyncio.sleep(_BOOT_POLL_INTERVAL_S)

        # If we got here, the container never came up — try to surface logs
        logs = ""
        if self._container is not None:
            try:
                logs = self._container.logs().decode("utf-8", errors="replace")[-500:]
            except Exception:  # noqa: BLE001
                pass
        raise DockerSandboxError(
            f"MCP server in container did not start within {_BOOT_TIMEOUT_S}s. "
            f"Recent container logs: {logs}"
        )

    async def _open_mcp(self) -> None:
        """Open an MCPConnection bound to the container's MCP endpoint."""
        from orqest.mcp.client import MCPConnection
        from orqest.mcp.config import MCPServerConfig

        token = self._mint_jwt()
        config = MCPServerConfig(
            name=f"docker-runtime-{self._session_id[:8]}",
            command="",
            transport="streamable-http",
            url=self.mcp_url,  # type: ignore[arg-type]
            headers={"Authorization": f"Bearer {token}"},
        )
        self._mcp_connection = MCPConnection(config)
        await self._mcp_connection.connect()

    async def _mcp_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a tool on the container's MCP server; unwrap the result."""
        if self._mcp_connection is None:
            raise DockerSandboxError("MCP connection not open")
        # MCPConnection holds the live ClientSession; reach for its private
        # _session attribute. (Existing pattern from MCPConnection itself.)
        session = self._mcp_connection._session  # noqa: SLF001
        if session is None:
            raise DockerSandboxError("MCP session not initialized")
        result = await session.call_tool(tool_name, arguments=arguments)
        # The tool returns a CallToolResult with `structuredContent` (FastMCP
        # auto-wraps dict returns). Fall back to the first text content block
        # if the structured content isn't there.
        sc = getattr(result, "structuredContent", None)
        if isinstance(sc, dict):
            return sc
        # Older MCP versions / non-structured tools — extract text content
        for block in (getattr(result, "content", None) or []):
            text = getattr(block, "text", None)
            if text:
                try:
                    return json.loads(text)
                except (TypeError, ValueError):
                    return {"_raw_text": text}
        return {}

    def _emit(self, event_type: str, **data: Any) -> None:
        if self._bus is None:
            return
        try:
            from orqest.observability.events import AgentEvent

            event = AgentEvent(
                event_type=event_type,
                agent_name="docker_sandbox",
                data={
                    "user_id": self._user_id,
                    "session_id": self._session_id[:8] + "…",
                    **data,
                },
            )
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                with contextlib.suppress(Exception):
                    asyncio.run(self._bus.emit(event))
                return
            loop.create_task(self._bus.emit(event))
        except Exception as exc:  # noqa: BLE001
            logger.debug("DockerSandbox emit failed: {e}", e=exc)


class DockerSandboxError(RuntimeError):
    """Generic DockerSandbox failure (container won't start, MCP unreachable)."""


class DockerImageNotFoundError(DockerSandboxError):
    """The configured image isn't present locally and we can't pull it."""


__all__ = [
    "DockerImageNotFoundError",
    "DockerSandbox",
    "DockerSandboxError",
]
