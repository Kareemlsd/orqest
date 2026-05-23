"""Integration tests for the host-side :class:`DockerSandbox`.

These tests need a running Docker daemon AND the ``orqest/agent-runtime:dev``
image already built locally. They're marked ``docker`` so the default test
run skips them. Run with:

    .venv/bin/python -m pytest tests/sandbox/test_docker.py -v -m docker

The image build is documented at the repo-root ``Dockerfile``.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

# Optional dep import — gate the whole module so collection works even
# when the docker SDK is missing.
docker = pytest.importorskip("docker")

from orqest.sandbox.docker import (
    DockerSandbox,
    DockerSandboxError,
)
from orqest.sandbox.jwt import encode as jwt_encode

pytestmark = pytest.mark.docker


_IMAGE = os.environ.get("ORQEST_AGENT_IMAGE", "orqest/agent-runtime:dev")


def _docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        # Also require the image to be present
        client.images.get(_IMAGE)
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not _docker_available(),
        reason=f"docker daemon or image {_IMAGE!r} unavailable",
    ),
]


# --- Construction -----------------------------------------------------------


def test_constructor_rejects_empty_user_id():
    with pytest.raises(ValueError, match="user_id"):
        DockerSandbox(user_id="", session_id="s1", image=_IMAGE)


def test_constructor_rejects_empty_session_id():
    with pytest.raises(ValueError, match="session_id"):
        DockerSandbox(user_id="u1", session_id="", image=_IMAGE)


def test_constructor_rejects_invalid_promotion_policy():
    with pytest.raises(ValueError, match="promotion_policy"):
        DockerSandbox(
            user_id="u1", session_id="s1", image=_IMAGE,
            promotion_policy="bogus",
        )


def test_constructor_mints_random_hmac_secret_when_omitted():
    sb1 = DockerSandbox(user_id="u1", session_id="s1", image=_IMAGE)
    sb2 = DockerSandbox(user_id="u1", session_id="s1", image=_IMAGE)
    # Two separate constructions must mint independent secrets
    assert sb1._hmac_secret != sb2._hmac_secret
    assert len(sb1._hmac_secret) >= 32


# --- Lifecycle --------------------------------------------------------------


@pytest.mark.asyncio
async def test_aenter_starts_container_and_publishes_port():
    sb = DockerSandbox(
        user_id="lifecycle-u1",
        session_id=str(uuid4()),
        image=_IMAGE,
        allowed_packages={"re"},
        memory_mb=512,
    )
    async with sb:
        assert sb.published_port is not None
        assert sb.container is not None
        assert sb.container.status in ("running", "created")
    # On exit, container should be removed
    assert sb.container is None


@pytest.mark.asyncio
async def test_jwt_minted_passes_container_auth():
    """Round-tripping a tools/list through the running container proves
    the JWT we minted matches what the server's middleware accepts."""
    sb = DockerSandbox(
        user_id="auth-u1",
        session_id=str(uuid4()),
        image=_IMAGE,
        allowed_packages={"re"},
        memory_mb=512,
    )
    async with sb:
        # If the JWT didn't validate, MCPConnection.connect would have
        # already failed with "missing bearer token" / similar.
        # Tools list should include the four built-ins.
        assert sb._mcp_connection is not None
        tools = sb._mcp_connection.tools
        names = {t.name for t in tools}
        assert {"execute_python", "promote_tool",
                "list_persisted_tools", "forget_tool"} <= names


# --- Execute round-trip -----------------------------------------------------


@pytest.mark.asyncio
async def test_execute_safe_arithmetic():
    sb = DockerSandbox(
        user_id="exec-u1",
        session_id=str(uuid4()),
        image=_IMAGE,
        allowed_packages={"re"},
        memory_mb=512,
    )
    async with sb:
        result = await sb.execute(
            "return args['x'] + args['y']",
            args={"x": 3, "y": 4},
            allowed_imports=set(),
            agent_id="alice",
            timeout_s=20.0,
        )
        assert result.success is True
        assert result.output == 7


@pytest.mark.asyncio
async def test_execute_with_allowed_import():
    sb = DockerSandbox(
        user_id="exec-u2",
        session_id=str(uuid4()),
        image=_IMAGE,
        allowed_packages={"re"},
        memory_mb=512,
    )
    async with sb:
        result = await sb.execute(
            "import re\nreturn re.findall(r'\\d+', args['t'])",
            args={"t": "a1 b22 c333"},
            allowed_imports={"re"},
            agent_id="alice",
            timeout_s=20.0,
        )
        assert result.success is True
        assert result.output == ["1", "22", "333"]


@pytest.mark.asyncio
async def test_disallowed_dependency_rejected():
    sb = DockerSandbox(
        user_id="dep-u1",
        session_id=str(uuid4()),
        image=_IMAGE,
        allowed_packages={"re"},  # 'requests' not allowed
        memory_mb=512,
    )
    async with sb:
        result = await sb.execute(
            "return 1",
            args={},
            allowed_imports=set(),
            agent_id="bob",
            dependencies=["requests"],
            timeout_s=20.0,
        )
        assert result.success is False
        assert "not in allowed_packages" in (result.error or "")


# --- Cross-session persistence ---------------------------------------------


@pytest.mark.asyncio
async def test_persisted_tool_survives_across_sessions_for_same_user():
    """Promote a tool in session A; open session B for same user;
    library should include the promoted tool. Cross-container persistence
    is the v0.8.0 killer feature — guard it explicitly."""
    user_id = f"persist-u-{uuid4().hex[:8]}"
    session_a = str(uuid4())

    # Session A — promote a tool explicitly
    sb_a = DockerSandbox(
        user_id=user_id, session_id=session_a, image=_IMAGE,
        allowed_packages={"re"}, memory_mb=512,
    )
    async with sb_a:
        promote_result = await sb_a._mcp_call(
            "promote_tool",
            {
                "name": "echo_one",
                "description": "Always returns 1",
                "parameters": {},
                "implementation": "return 1",
                "allowed_imports": [],
                "dependencies": [],
            },
        )
        assert promote_result["name"] == "echo_one"

    # Session B (same user, new session) — library replay should include it
    session_b = str(uuid4())
    sb_b = DockerSandbox(
        user_id=user_id, session_id=session_b, image=_IMAGE,
        allowed_packages={"re"}, memory_mb=512,
    )
    async with sb_b:
        listed = await sb_b._mcp_call("list_persisted_tools", {})
        # FastMCP wrapping
        if isinstance(listed, dict) and "result" in listed:
            listed = listed["result"]
        names = {entry["name"] for entry in listed}
        assert "echo_one" in names


@pytest.mark.asyncio
async def test_cross_user_volume_isolation():
    """Bob's container must not see tools persisted by alice."""
    alice_user = f"alice-{uuid4().hex[:8]}"
    bob_user = f"bob-{uuid4().hex[:8]}"

    # Alice promotes
    sb_a = DockerSandbox(
        user_id=alice_user, session_id=str(uuid4()), image=_IMAGE,
        allowed_packages=set(), memory_mb=512,
    )
    async with sb_a:
        await sb_a._mcp_call(
            "promote_tool",
            {
                "name": "alice_secret",
                "description": "Alice-only",
                "parameters": {},
                "implementation": "return 'alice'",
                "allowed_imports": [],
                "dependencies": [],
            },
        )

    # Bob lists
    sb_b = DockerSandbox(
        user_id=bob_user, session_id=str(uuid4()), image=_IMAGE,
        allowed_packages=set(), memory_mb=512,
    )
    async with sb_b:
        listed = await sb_b._mcp_call("list_persisted_tools", {})
        if isinstance(listed, dict) and "result" in listed:
            listed = listed["result"]
        names = {entry["name"] for entry in listed}
        assert "alice_secret" not in names


# --- Hardening probes -------------------------------------------------------


@pytest.mark.asyncio
async def test_container_runs_with_hardened_flags():
    """Verify the host actually applies cap-drop / read-only / pids-limit."""
    sb = DockerSandbox(
        user_id="hard-u1",
        session_id=str(uuid4()),
        image=_IMAGE,
        allowed_packages=set(),
        memory_mb=512,
        pids_limit=256,
    )
    async with sb:
        sb.container.reload()
        host_cfg = sb.container.attrs["HostConfig"]
        assert host_cfg["CapDrop"] == ["ALL"]
        assert host_cfg["ReadonlyRootfs"] is True
        assert host_cfg["PidsLimit"] == 256
        # Memory expressed in bytes
        assert host_cfg["Memory"] == 512 * 1024 * 1024
        # Non-root user
        assert sb.container.attrs["Config"]["User"] == "1000:1000"


@pytest.mark.asyncio
async def test_invalid_jwt_rejected_by_container():
    """A bearer signed with the wrong secret must be rejected."""
    sb = DockerSandbox(
        user_id="rej-u1",
        session_id=str(uuid4()),
        image=_IMAGE,
        allowed_packages=set(),
        memory_mb=512,
    )
    async with sb:
        # Mint a JWT with a DIFFERENT secret + try a raw httpx tools/list
        import httpx
        bad_token = jwt_encode(
            {"sub": "rej-u1", "sid": sb.session_id, "exp": int(__import__("time").time()) + 60},
            "wrong-secret-" + "x" * 30,
        )
        port = sb.published_port
        url = f"http://127.0.0.1:{port}/mcp"
        # First initialize with the correct token to obtain a session id
        good_token = sb._mint_jwt()
        async with httpx.AsyncClient(follow_redirects=True) as h:
            init = await h.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Authorization": f"Bearer {good_token}",
                },
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18",
                               "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
                },
                timeout=10.0,
            )
            assert init.status_code == 200
            sid = init.headers.get("mcp-session-id")
            await h.post(url, headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {good_token}",
                "mcp-session-id": sid,
            }, json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

            # Now try tools/list with the WRONG bearer
            r = await h.post(url, headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {bad_token}",
                "mcp-session-id": sid,
            }, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            # Either HTTP-level reject (401) or JSON-RPC error
            body = r.text
            assert r.status_code != 200 or "error" in body
            # The auth path must have run
            assert "bearer" in body.lower() or "auth" in body.lower() or r.status_code in (401, 403)
