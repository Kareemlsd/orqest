# Polymath sandbox image — one container PER user session, spun up on demand
# by the backend's SandboxManager.
#
# Ships:
#   - Python 3.12 (with pandas/numpy/matplotlib/weasyprint in Phase 4)
#   - Node 22
#   - Chromium via Playwright (Phase 3)
#   - Xvfb + x11vnc + noVNC for browser viewport streaming
#   - A small shell-WS server so the frontend's xterm tab can stream bash
#
# The mcr.microsoft.com/playwright base ships all Chromium deps and a
# known-working Xvfb + fonts setup, which is noisy to reproduce on
# debian-slim. Lifting it saves hours per the Phase 0 plan risks list.

FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DISPLAY=:99

# Install the extra bits the Playwright image doesn't already have:
# - x11vnc + novnc + websockify → VNC-over-websocket for the iframe
# - tini → proper PID 1 so signals reach Chromium cleanly
# - weasyprint runtime deps (cairo, pango, gdk-pixbuf) → Phase 4 PDF
# - less + nano → friendly when a user takes over the shell tab
# - nodejs 22 from nodesource → Phase 2 code scaffolding demos
RUN apt-get update && apt-get install -y --no-install-recommends \
      x11vnc \
      novnc \
      websockify \
      tini \
      procps \
      less \
      nano \
      curl \
      ca-certificates \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libcairo2 \
      libgdk-pixbuf-2.0-0 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Python packages the agent will want inside the sandbox. Kept lean for
# Phase 0; Phase 4 may add more. Users can `pip install X` from tools
# during a session — this is the baseline.
COPY requirements.txt /opt/polymath-sandbox/requirements.txt
RUN pip install --no-cache-dir -r /opt/polymath-sandbox/requirements.txt

# A tiny websocket server that pipes a bash PTY to the browser's xterm.js.
COPY scripts/shell_ws.py /opt/polymath-sandbox/shell_ws.py
COPY scripts/browser_boot.py /opt/polymath-sandbox/browser_boot.py

# Entrypoint starts Xvfb, x11vnc, noVNC, shell-WS, then sleeps so the
# container stays alive. Tools exec into this container via `docker exec`.
COPY entrypoint.sh /opt/polymath-sandbox/entrypoint.sh
RUN chmod +x /opt/polymath-sandbox/entrypoint.sh

# /workspace is the session's working directory. Bind-mounted from a
# named volume by SandboxManager so it survives container restarts.
WORKDIR /workspace

EXPOSE 6080 7681

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/polymath-sandbox/entrypoint.sh"]
