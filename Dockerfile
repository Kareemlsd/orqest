# syntax=docker/dockerfile:1.6
#
# orqest/agent-runtime — the body of the Tier-2 :class:`DockerSandbox`.
#
# Built once per orqest release; pulled by consumers via:
#   docker pull orqest/agent-runtime:<VERSION>
#
# The host-side DockerSandbox runs:
#   docker run -d --rm \
#     --memory=2g --cpus=2 --pids-limit=512 \
#     --read-only --tmpfs /workspace --tmpfs /tmp \
#     --cap-drop=ALL --security-opt no-new-privileges \
#     --network=none \
#     -e ORQEST_USER_ID=alice -e ORQEST_SESSION_ID=<uuid> \
#     -e ORQEST_HMAC_SECRET=<random> \
#     -e ORQEST_ALLOWED_PACKAGES=pandas,re,json \
#     -p 127.0.0.1:0:8000 \
#     -v orqest-user-alice:/data \
#     orqest/agent-runtime:<VERSION>
#
# Build:
#   docker buildx build --build-arg ORQEST_VERSION=0.8.0 \
#       -t orqest/agent-runtime:0.8.0 .
#
# Honest framing — see docs/concepts/sandbox.md:
#   This is Tier-2 (hardened Docker). Shared-kernel — protects against
#   accidental damage and most prompt-injection scenarios. Does NOT
#   protect against adversarial multi-tenant code; for that, run inside
#   a microVM (Firecracker/Kata) or use a managed sandbox provider.

FROM python:3.12-slim AS base

# 1. System deps — only what we genuinely need:
#    - tini: PID 1 reaper (prevents zombies from OOM-killed children
#            from ripping through PID 1 and killing the container)
#    - curl + ca-certificates: uv install fallback (uv ships its own,
#      but consumer Dockerfiles that layer on top sometimes need them)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# 2. uv — single static binary, ~40MB. Used for per-agent venv creation
#    (~50ms) and `uv pip install` (10-100x faster than pip).
RUN pip install --no-cache-dir uv

# 3. Install orqest + supporting libs.
#
#    Two modes — controlled by ORQEST_SOURCE build-arg:
#      "pypi"  (default) → pip install orqest==<ORQEST_VERSION>
#                            (use for release builds)
#      "local"           → COPY . /tmp/orqest && pip install /tmp/orqest
#                            (use for dev builds; rebuild whenever you
#                             change orqest source)
#
#    Release builds:
#      docker buildx build --build-arg ORQEST_VERSION=0.8.0 \
#          -t orqest/agent-runtime:0.8.0 .
#    Dev builds:
#      docker buildx build --build-arg ORQEST_SOURCE=local \
#          -t orqest/agent-runtime:dev .

ARG ORQEST_VERSION
ARG ORQEST_SOURCE=pypi

# Light deps first
RUN pip install --no-cache-dir "loguru>=0.7"

# Install orqest with a pip CONSTRAINTS file pinning fastmcp to 2.x.
# Constraints differ from requirements: they're *only* applied to
# packages that get installed, so they cap pydantic-ai-slim's
# `fastmcp>=3.2.4` transitive bump back to 2.x.
# Why we need 2.x: SessionAuthMiddleware uses get_http_headers() inside
# on_list_tools / on_call_tool. fastmcp 3.x changed the middleware
# lifecycle so that lookup returns an empty dict and auth fails.
# Pydantic-ai's MCP-client is unused inside the container, so the
# downgrade doesn't break anything that actually runs here.
COPY pyproject.toml /tmp/orqest-build/pyproject.toml
COPY README.md /tmp/orqest-build/README.md
COPY orqest /tmp/orqest-build/orqest
RUN echo "fastmcp>=2.10,<2.14" > /tmp/constraints.txt && \
    if [ "$ORQEST_SOURCE" = "local" ]; then \
        PIP_CONSTRAINT=/tmp/constraints.txt pip install --no-cache-dir /tmp/orqest-build "fastmcp>=2.10,<2.14" && \
        rm -rf /tmp/orqest-build; \
    elif [ -n "$ORQEST_VERSION" ]; then \
        PIP_CONSTRAINT=/tmp/constraints.txt pip install --no-cache-dir "orqest==${ORQEST_VERSION}" "fastmcp>=2.10,<2.14" && \
        rm -rf /tmp/orqest-build; \
    else \
        echo "Either ORQEST_VERSION (PyPI mode) or ORQEST_SOURCE=local must be set" && exit 1; \
    fi && rm /tmp/constraints.txt

# 4. Non-root sandbox user. Never run LLM code as root.
RUN useradd --create-home --shell /sbin/nologin --uid 1000 sandbox

# 5. Filesystem layout. /workspace is mounted as a tmpfs at runtime
#    (volatile, per-session); /data is mounted as a per-user named volume
#    (persistent across container teardowns; isolated per user).
RUN mkdir -p /workspace /data && chown -R 1000:1000 /workspace /data

USER 1000:1000
WORKDIR /workspace

# Defaults — can be overridden via -e at `docker run` time.
# UV_CACHE_DIR points at the writable tmpfs because the container root
# filesystem is mounted read-only by the host orchestrator.
ENV PYTHONUNBUFFERED=1 \
    ORQEST_HOST=0.0.0.0 \
    ORQEST_PORT=8000 \
    ORQEST_TOOLS_DB=/data/orqest-tools.sqlite \
    UV_CACHE_DIR=/workspace/.uv-cache \
    XDG_CACHE_HOME=/workspace/.cache

EXPOSE 8000

# tini handles SIGCHLD reaping. Without it, OOM-killed subprocess children
# become zombies that clutter the PID table and eventually exhaust pids_limit.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Bind the FastMCP server. The host orchestrator publishes 8000 via
# `-p 127.0.0.1:<host>:8000`. Inside the container we bind 0.0.0.0
# because there's no other network surface (--network=none on the host
# makes this safe; no inbound traffic from anywhere except via the
# published localhost port).
CMD ["python", "-m", "orqest.sandbox.docker_runtime"]
