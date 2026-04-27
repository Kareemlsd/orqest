#!/usr/bin/env bash
# Local dev helper. Usage:
#   ./dev.sh up       # start postgres (docker) + backend (venv) + frontend (npm)
#   ./dev.sh down     # stop everything
#   ./dev.sh test     # run backend tests in the local venv
#   ./dev.sh logs     # tail backend + frontend logs
#
# Requires: docker, uv, node 22+. The polymath-sandbox image must be built
# separately (`docker compose build sandbox-builder`) — it's only consumed
# by the backend's SandboxManager from Phase 2 onward.
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/.dev-logs"
mkdir -p "$LOG_DIR"

# Local env for backend — points at postgres in docker.
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://polymath:polymath@localhost:5432/polymath}"
export POLYMATH_MEMORY_DIR="${POLYMATH_MEMORY_DIR:-$ROOT/.dev-data/memory}"
mkdir -p "$POLYMATH_MEMORY_DIR"
# Load user secrets from .env if present.
if [ -f "$ROOT/.env" ]; then
  set -a; . "$ROOT/.env"; set +a
fi

cmd="${1:-}"

start_postgres() {
  echo "[dev] starting postgres container"
  (cd "$ROOT" && docker compose up -d postgres >/dev/null)
  # Wait until healthy.
  until docker exec polymath-postgres pg_isready -U polymath >/dev/null 2>&1; do
    sleep 1
  done
  echo "[dev] postgres ready on :5432"
}

start_backend() {
  local backend="$ROOT/backend"
  if [ ! -d "$backend/.venv" ]; then
    echo "[dev] creating backend venv"
    (cd "$backend" && uv venv --python 3.12 .venv)
    (cd "$backend" && .venv/bin/python -m ensurepip 2>/dev/null || true)
    uv pip install --python "$backend/.venv/bin/python" -e "$ROOT/../.." >/dev/null
    uv pip install --python "$backend/.venv/bin/python" -e "$backend" >/dev/null
    uv pip install --python "$backend/.venv/bin/python" \
      "pytest>=8" "pytest-asyncio>=0.23" "pytest-timeout>=2.3" "aiosqlite>=0.20" >/dev/null
  fi
  echo "[dev] starting backend on :8000"
  (cd "$backend" && \
     nohup .venv/bin/uvicorn polymath.server:app \
       --host 0.0.0.0 --port 8000 --reload --reload-dir polymath \
       >"$LOG_DIR/backend.log" 2>&1 &
   echo $! > "$LOG_DIR/backend.pid")
}

start_frontend() {
  local fe="$ROOT/frontend"
  if [ ! -d "$fe/node_modules" ]; then
    echo "[dev] installing frontend deps"
    (cd "$fe" && npm install >/dev/null 2>&1)
  fi
  echo "[dev] starting frontend on :3000"
  (cd "$fe" && \
     NEXT_PUBLIC_BACKEND_URL="http://localhost:8000" \
     BACKEND_INTERNAL_URL="http://localhost:8000" \
     PATH="$fe/node_modules/.bin:$PATH" \
     nohup node_modules/.bin/next dev \
       >"$LOG_DIR/frontend.log" 2>&1 &
   echo $! > "$LOG_DIR/frontend.pid")
}

case "$cmd" in
  up)
    start_postgres
    start_backend
    start_frontend
    echo "[dev] all up. tail logs with: ./dev.sh logs"
    echo "[dev] → http://localhost:3000"
    ;;
  down)
    for name in backend frontend; do
      pid_file="$LOG_DIR/$name.pid"
      if [ -f "$pid_file" ]; then
        kill "$(cat "$pid_file")" 2>/dev/null || true
        rm -f "$pid_file"
      fi
    done
    (cd "$ROOT" && docker compose stop postgres >/dev/null)
    echo "[dev] stopped"
    ;;
  restart)
    "$0" down
    "$0" up
    ;;
  test)
    (cd "$ROOT/backend" && .venv/bin/python -m pytest tests/ -q --tb=short)
    ;;
  logs)
    tail -f "$LOG_DIR/backend.log" "$LOG_DIR/frontend.log"
    ;;
  *)
    echo "usage: $0 {up|down|restart|test|logs}"
    exit 1
    ;;
esac
