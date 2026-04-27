"""SandboxManager — one Docker container per user session.

Thin orchestration layer over the ``docker`` Python SDK. Containers run the
``polymath-sandbox:latest`` image (Chromium + Xvfb + x11vnc + noVNC + shell
WS + Python + Node). Each session's ``/workspace`` lives on a named volume
so its state survives container restarts.

The manager is async-friendly but the ``docker`` SDK is sync; we offload
calls to a thread so the backend event loop keeps flowing.

Security note: the backend process must have access to the host docker
socket. Demo-grade; production would use a Firecracker microVM provider.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_IMAGE = os.getenv("POLYMATH_SANDBOX_IMAGE", "polymath-sandbox:latest")
_DEFAULT_NETWORK = os.getenv("POLYMATH_SANDBOX_NETWORK", "polymath_polymath-net")
_CONTAINER_NAME_PREFIX = "polymath-session-"
_VOLUME_NAME_PREFIX = "polymath-session-"
_WORKSPACE_DIR = "/workspace"
_STDOUT_CHUNK_CHARS = 4096
_DEFAULT_TIMEOUT_S = 120.0


def _first_host_port(bindings: list[dict] | None) -> int | None:
    """Return the first host port in a docker ``Ports`` map value."""
    if not bindings:
        return None
    try:
        return int(bindings[0].get("HostPort"))
    except (TypeError, ValueError):
        return None


@dataclass(slots=True, frozen=True)
class SandboxInfo:
    """Metadata about a running sandbox container."""

    session_id: str
    container_id: str
    volume_name: str
    image: str
    novnc_port: int | None = None  # host port mapped to sandbox :6080
    shell_port: int | None = None  # host port mapped to sandbox :7681


class SandboxError(RuntimeError):
    """Raised when a sandbox operation fails in a way the agent should see."""


class SandboxManager:
    """Per-process orchestrator for per-session sandbox containers.

    Lazy-imports ``docker`` so test environments that mock the manager don't
    need the docker SDK on their path.
    """

    def __init__(
        self,
        *,
        image: str = _DEFAULT_IMAGE,
        network: str = _DEFAULT_NETWORK,
    ) -> None:
        self._image = image
        self._network = network
        self._client = None  # lazy
        self._sessions: dict[str, SandboxInfo] = {}
        self._lock = asyncio.Lock()

    # ---------- public API ----------

    async def ensure(self, session_id: str) -> SandboxInfo:
        """Return the container for *session_id*, starting one if needed.

        Idempotent — safe to call on every chat turn. Existing containers
        that have died are recreated; live ones are returned as-is.
        """
        async with self._lock:
            info = self._sessions.get(session_id)
            if info is not None and await self._is_running(info.container_id):
                return info
            info = await self._start(session_id)
            self._sessions[session_id] = info
            return info

    async def stop(self, session_id: str, *, remove_volume: bool = False) -> None:
        """Stop + remove the session's container. Named volume persists
        unless ``remove_volume=True`` (used on session deletion)."""
        async with self._lock:
            info = self._sessions.pop(session_id, None)
        if info is None:
            return
        client = self._get_client()
        try:
            container = await asyncio.to_thread(client.containers.get, info.container_id)
            await asyncio.to_thread(container.stop, timeout=5)
            await asyncio.to_thread(container.remove, force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sandbox: stop(%s) ignored: %s", session_id, exc)
        if remove_volume:
            try:
                vol = await asyncio.to_thread(client.volumes.get, info.volume_name)
                await asyncio.to_thread(vol.remove, force=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("sandbox: remove_volume(%s) ignored: %s", session_id, exc)

    async def exec(
        self,
        session_id: str,
        cmd: list[str],
        *,
        workdir: str = _WORKSPACE_DIR,
        env: dict[str, str] | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> tuple[int, str, str, bool]:
        """Run *cmd* inside the session's sandbox. Returns (exit_code,
        stdout, stderr, truncated). No streaming; for that use :meth:`stream_exec`.
        """
        info = await self.ensure(session_id)
        client = self._get_client()

        def _run() -> tuple[int, str, str, bool]:
            container = client.containers.get(info.container_id)
            created = container.client.api.exec_create(
                container.id,
                cmd,
                workdir=workdir,
                environment=env or {},
                stdout=True,
                stderr=True,
            )
            started_at = time.monotonic()
            stream_iter = container.client.api.exec_start(
                created["Id"], stream=True, demux=True
            )
            out_buf: list[bytes] = []
            err_buf: list[bytes] = []
            truncated = False
            total = 0
            for std, err in stream_iter:
                if std:
                    out_buf.append(std)
                    total += len(std)
                if err:
                    err_buf.append(err)
                    total += len(err)
                if total > 2_000_000:
                    truncated = True
                    break
                if time.monotonic() - started_at > timeout_s:
                    truncated = True
                    break
            info2 = container.client.api.exec_inspect(created["Id"])
            code = int(info2.get("ExitCode") or 0)
            return (
                code,
                b"".join(out_buf).decode(errors="replace"),
                b"".join(err_buf).decode(errors="replace"),
                truncated,
            )

        return await asyncio.to_thread(_run)

    async def put_file(self, session_id: str, path: str, content: bytes) -> int:
        """Write *content* to *path* inside the sandbox's /workspace.

        Path is confined to /workspace — passing an absolute path outside or
        a traversal like ``../`` raises :class:`SandboxError`.
        """
        safe = self._safe_path(path)
        info = await self.ensure(session_id)

        def _write() -> int:
            import tarfile
            import io

            client = self._get_client()
            container = client.containers.get(info.container_id)

            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tf:
                ti = tarfile.TarInfo(name=safe.lstrip("/"))
                ti.size = len(content)
                ti.mtime = int(time.time())
                tf.addfile(ti, io.BytesIO(content))
            buf.seek(0)
            ok = container.put_archive(_WORKSPACE_DIR, buf.read())
            if not ok:
                raise SandboxError(f"failed to put_archive {path}")
            return len(content)

        return await asyncio.to_thread(_write)

    async def get_file(
        self, session_id: str, path: str, *, max_bytes: int = 200_000
    ) -> tuple[bytes, bool]:
        """Read *path* from the sandbox. Returns (bytes, truncated)."""
        safe = self._safe_path(path)
        info = await self.ensure(session_id)

        def _read() -> tuple[bytes, bool]:
            import tarfile
            import io

            client = self._get_client()
            container = client.containers.get(info.container_id)
            stream, stat = container.get_archive(
                f"{_WORKSPACE_DIR}/{safe.lstrip('/')}"
            )
            buf = io.BytesIO()
            for chunk in stream:
                buf.write(chunk)
                if buf.tell() > max_bytes * 2:
                    break
            buf.seek(0)
            with tarfile.open(fileobj=buf, mode="r") as tf:
                names = tf.getnames()
                if not names:
                    raise SandboxError(f"empty archive for {path}")
                f = tf.extractfile(names[0])
                if f is None:
                    raise SandboxError(f"{path} is a directory")
                data = f.read(max_bytes + 1)
            truncated = len(data) > max_bytes
            return (data[:max_bytes], truncated)

        return await asyncio.to_thread(_read)

    async def list_dir(
        self, session_id: str, path: str = ".", *, limit: int = 200
    ) -> tuple[list[dict], bool]:
        """Return a shallow listing of a directory inside /workspace.

        Raises :class:`SandboxError` when the target path does not exist
        or is not a directory — the agent / frontend then know the
        difference between *empty directory* and *bad path*. Earlier
        versions silently returned ``[]`` for both, which made every
        wrong path look indistinguishable from a fresh workspace.

        The ``/workspace`` root is treated as a special case: if it
        doesn't exist yet (a brand-new container that has never had a
        file written to it) we return an empty listing rather than an
        error, since "empty workspace" is a valid initial state.
        """
        safe = self._safe_path(path)
        target = f"{_WORKSPACE_DIR}/{safe.lstrip('/')}" if safe else _WORKSPACE_DIR
        script = (
            "import os, json, sys\n"
            "p = sys.argv[1]\n"
            "limit = int(sys.argv[2])\n"
            "if not os.path.exists(p):\n"
            "    print(json.dumps({'status': 'missing', 'path': p}))\n"
            "    sys.exit(0)\n"
            "if not os.path.isdir(p):\n"
            "    print(json.dumps({'status': 'not_a_directory', 'path': p}))\n"
            "    sys.exit(0)\n"
            "entries = os.listdir(p)\n"
            "rows = []\n"
            "for n in entries[:limit]:\n"
            "    ap = os.path.join(p, n)\n"
            "    try:\n"
            "        st = os.stat(ap)\n"
            "    except OSError:\n"
            "        continue\n"
            "    rows.append({\n"
            "        'name': n,\n"
            "        'path': os.path.relpath(ap, '/workspace'),\n"
            "        'kind': 'dir' if os.path.isdir(ap) else 'file',\n"
            "        'size': st.st_size,\n"
            "        'mtime': st.st_mtime,\n"
            "    })\n"
            "print(json.dumps({'status': 'ok', 'rows': rows, 'total': len(entries)}))\n"
        )
        code, out, err, _ = await self.exec(
            session_id, ["python3", "-c", script, target, str(limit + 1)]
        )
        if code != 0:
            raise SandboxError(err.strip() or "list_dir failed")
        import json

        try:
            payload = json.loads(out.strip() or '{"status":"ok","rows":[],"total":0}')
        except json.JSONDecodeError as exc:
            raise SandboxError(f"list_dir produced unparseable output: {exc}") from exc
        status = payload.get("status", "ok")
        if status == "missing":
            # Treat the workspace root as empty when the volume has just
            # been created and nothing's been written yet; every other
            # missing path is a genuine error the agent should see.
            if target == _WORKSPACE_DIR:
                return [], False
            raise SandboxError(f"directory does not exist: {path}")
        if status == "not_a_directory":
            raise SandboxError(f"not a directory: {path}")
        rows = payload["rows"][:limit]
        truncated = payload["total"] > limit
        return rows, truncated

    # ---------- internals ----------

    def _get_client(self):
        if self._client is None:
            import docker  # lazy

            # Pick up DOCKER_HOST if set; otherwise probe common sockets
            # (Docker Desktop on Linux puts its socket under ~/.docker/desktop/
            # and the daemon runs as the user, unlike the root-owned
            # /var/run/docker.sock).
            env_host = os.getenv("DOCKER_HOST")
            if env_host:
                self._client = docker.DockerClient(base_url=env_host)
            else:
                candidates = [
                    Path.home() / ".docker" / "desktop" / "docker.sock",
                    Path("/var/run/docker.sock"),
                ]
                sock = next((p for p in candidates if p.exists() and os.access(p, os.R_OK)), None)
                if sock is None:
                    # Let docker.from_env() produce its native error message.
                    self._client = docker.from_env()
                else:
                    self._client = docker.DockerClient(base_url=f"unix://{sock}")
        return self._client

    def _container_name(self, session_id: str) -> str:
        return f"{_CONTAINER_NAME_PREFIX}{session_id}"

    def _volume_name(self, session_id: str) -> str:
        return f"{_VOLUME_NAME_PREFIX}{session_id}"

    def _safe_path(self, path: str) -> str:
        """Reject absolute paths and traversal; return a /workspace-relative path."""
        p = Path(path)
        if p.is_absolute():
            raise SandboxError("absolute paths are not allowed; scope is /workspace")
        # Normalize, then check no component is ``..``
        parts = [part for part in p.parts if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise SandboxError("traversal (..) rejected")
        return str(Path(*parts)) if parts else ""

    async def _is_running(self, container_id: str) -> bool:
        try:
            client = self._get_client()
            container = await asyncio.to_thread(client.containers.get, container_id)
            return container.status == "running"
        except Exception:  # noqa: BLE001
            return False

    async def _start(self, session_id: str) -> SandboxInfo:
        client = self._get_client()
        name = self._container_name(session_id)
        vol = self._volume_name(session_id)

        # Clean up any stale same-named container from a previous crash.
        def _cleanup_previous() -> None:
            try:
                existing = client.containers.get(name)
                try:
                    existing.stop(timeout=3)
                except Exception:  # noqa: BLE001
                    pass
                existing.remove(force=True)
            except Exception:  # noqa: BLE001
                pass

        await asyncio.to_thread(_cleanup_previous)

        def _ensure_volume():
            try:
                client.volumes.get(vol)
            except Exception:  # noqa: BLE001
                client.volumes.create(name=vol)

        await asyncio.to_thread(_ensure_volume)

        network_kwarg = {"network": self._network} if self._network else {}

        def _run() -> tuple[str, int | None, int | None]:
            container = client.containers.run(
                self._image,
                name=name,
                detach=True,
                volumes={vol: {"bind": _WORKSPACE_DIR, "mode": "rw"}},
                # Publish noVNC + shell-WS to random host ports so the
                # locally-running frontend iframe can reach them.
                ports={"6080/tcp": None, "7681/tcp": None},
                labels={"polymath.session_id": session_id},
                **network_kwarg,
            )
            # Dynamic ports are only populated after reload().
            container.reload()
            ports_map = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
            novnc = _first_host_port(ports_map.get("6080/tcp"))
            shell = _first_host_port(ports_map.get("7681/tcp"))
            return container.id, novnc, shell

        container_id, novnc_port, shell_port = await asyncio.to_thread(_run)
        logger.info(
            "sandbox: session %s started container %s (noVNC :%s, shell :%s)",
            session_id,
            container_id[:12],
            novnc_port,
            shell_port,
        )
        return SandboxInfo(
            session_id=session_id,
            container_id=container_id,
            volume_name=vol,
            image=self._image,
            novnc_port=novnc_port,
            shell_port=shell_port,
        )


# Process-level default manager.
_default: SandboxManager | None = None


def get_manager() -> SandboxManager:
    global _default
    if _default is None:
        _default = SandboxManager()
    return _default
