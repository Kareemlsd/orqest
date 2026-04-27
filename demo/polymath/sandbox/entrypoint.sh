#!/usr/bin/env bash
# Sandbox entrypoint — starts Xvfb, x11vnc, noVNC, shell-WS in the
# background and sleeps. Tools invoke bash/python/playwright via
# `docker exec` from the backend.
set -eu

log() { echo "[sandbox] $*"; }

cleanup() {
  log "shutting down"
  pkill -TERM -P $$ || true
  exit 0
}
trap cleanup INT TERM

mkdir -p /workspace
chown -R pwuser:pwuser /workspace 2>/dev/null || true

# 1. Xvfb — virtual X display :99, 1440x900
log "starting Xvfb on :99"
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &

# Give Xvfb a beat to come up before clients connect.
sleep 0.5

# 2. x11vnc — exposes :99 on TCP 5900 with no auth (behind docker network)
log "starting x11vnc on :5900"
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -quiet &

# 3. noVNC — bridges websocket on 6080 → 5900 tcp. `--web` serves the
#    noVNC html/js so the iframe can pull it.
log "starting noVNC on :6080"
websockify \
  --web /usr/share/novnc \
  --heartbeat=30 \
  6080 localhost:5900 &

# 4. Shell-WS server — streams a bash PTY on port 7681 for xterm.js.
log "starting shell-ws on :7681"
python3 /opt/polymath-sandbox/shell_ws.py --port 7681 --cwd /workspace &

# 5. Idle loop. Tools enter via `docker exec`; this process just keeps
#    the container alive and harvests child exits.
log "ready — Xvfb :99, VNC 5900, noVNC 6080, shell 7681"
while true; do
  wait -n || true
done
