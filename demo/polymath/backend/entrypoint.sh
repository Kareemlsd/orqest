#!/bin/sh
# Polymath backend entrypoint.
#
# `orqest` is mounted at /orqest by docker-compose but only exists at
# container run time, not build time. We install it here (non-editable —
# pip copies the source into site-packages, so the read-only mount is
# fine) and then start uvicorn.
set -eu

echo "[polymath] installing orqest from /orqest …"
# The /orqest bind-mount is read-only (demo-friendly — no accidental writes
# to the user's source tree). Pip's egg_info step needs to write into the
# source dir, so we stage a writable copy under /tmp first.
STAGING=/tmp/orqest-install
rm -rf "$STAGING"
mkdir -p "$STAGING"
# Copy just what the build needs — skip venvs, caches, editable metadata.
cp -r /orqest/orqest /orqest/pyproject.toml "$STAGING/"
cp /orqest/README.md "$STAGING/README.md" 2>/dev/null || true
pip install --no-cache-dir "$STAGING"
rm -rf "$STAGING"

echo "[polymath] starting uvicorn on :8000 …"
exec uvicorn polymath.server:app --host 0.0.0.0 --port 8000 --reload \
  --reload-dir /app/polymath
