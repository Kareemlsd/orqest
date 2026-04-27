"""Browser tools — drive a persistent Chromium inside the session's sandbox.

The sandbox ships the Playwright Chromium binary under
``/ms-playwright/chromium-*/chrome-linux/chrome``. Phase 3 launches that
binary directly as a long-lived background process inside the sandbox so
the noVNC iframe keeps showing the browser window across agent turns.

Navigation, clicks, and typing rely on Chromium's own remote-debugging
port: we start Chromium with ``--remote-debugging-port=9222`` and use
Playwright's ``connect_over_cdp`` (running inside the sandbox) to drive
it. The browser window stays visible in the noVNC viewport the entire
time — exactly what sells the demo.
"""

from __future__ import annotations

import glob
import json
from typing import Annotated

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from polymath.runtime import emit
from polymath.sandbox.manager import SandboxError, get_manager
from polymath.state import PolymathState

_CDP_PORT = 9222
_LAUNCHER = r"""
set -eu
# Find the Playwright-shipped chrome binary (version-agnostic).
CHROME=$(ls -d /ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1 || true)
if [ -z "$CHROME" ]; then
  CHROME=$(command -v chromium || command -v chromium-browser || command -v google-chrome || true)
fi
if [ -z "$CHROME" ]; then
  echo "no chromium found"; exit 1
fi
export DISPLAY=:99
mkdir -p /workspace/.polymath/chrome-profile
# If Chromium is already running (we launched it in an earlier turn), skip.
if curl -sSf http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
  echo "already-running"
  exit 0
fi
nohup "$CHROME" \
  --no-sandbox --no-first-run --no-default-browser-check \
  --start-maximized --disable-features=Translate \
  --user-data-dir=/workspace/.polymath/chrome-profile \
  --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  about:blank \
  >/workspace/.polymath/chromium.log 2>&1 &
# Wait for DevTools endpoint to come up.
for i in $(seq 1 30); do
  if curl -sSf http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    echo "started"; exit 0
  fi
  sleep 0.25
done
echo "chromium failed to come up"; exit 2
"""

_DRIVER = r"""
import asyncio, json, sys
from playwright.async_api import async_playwright

ACTION = json.loads(sys.argv[1])

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        kind = ACTION["kind"]
        if kind == "open_url":
            await page.goto(ACTION["url"], wait_until="domcontentloaded", timeout=20000)
        elif kind == "click":
            await page.click(ACTION["selector"], timeout=10000)
            await page.wait_for_timeout(600)
        elif kind == "type":
            await page.fill(ACTION["selector"], ACTION["text"])
            if ACTION.get("submit"):
                await page.press(ACTION["selector"], "Enter")
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
        else:
            raise SystemExit(f"unknown action {kind}")
        print(json.dumps({
            "ok": True,
            "title": await page.title(),
            "url": page.url,
        }))

asyncio.run(main())
"""


async def _ensure_chromium(sid: str) -> None:
    """Start Chromium inside the sandbox if it isn't already running."""
    code, stdout, stderr, _ = await get_manager().exec(
        sid, ["bash", "-lc", _LAUNCHER], timeout_s=30
    )
    if code != 0:
        raise SandboxError((stderr or stdout).strip() or "chromium launch failed")


async def _drive(sid: str, action: dict) -> dict:
    await _ensure_chromium(sid)
    code, stdout, stderr, _ = await get_manager().exec(
        sid, ["python3", "-c", _DRIVER, json.dumps(action)], timeout_s=45
    )
    if code != 0:
        raise SandboxError((stderr or stdout).strip() or "browser action failed")
    last = stdout.strip().splitlines()[-1] if stdout.strip() else "{}"
    try:
        return json.loads(last)
    except json.JSONDecodeError:
        return {"ok": False, "raw": stdout.strip()}


async def _open_url(
    ctx: RunContext[PolymathState],
    url: Annotated[str, "Fully-qualified URL to open in the sandbox browser."],
) -> str:
    sid = ctx.deps.session_id
    await emit(sid, "browser.action", {"kind": "open_url", "url": url})
    try:
        result = await _drive(sid, {"kind": "open_url", "url": url})
    except SandboxError as exc:
        await emit(sid, "browser.error", {"url": url, "error": str(exc)})
        return json.dumps({"error": str(exc)})
    await emit(
        sid,
        "browser.navigated",
        {"url": result.get("url"), "title": result.get("title")},
    )
    return json.dumps(result)


async def _click(
    ctx: RunContext[PolymathState],
    selector: Annotated[str, "CSS selector (or text='…') of the element to click."],
) -> str:
    sid = ctx.deps.session_id
    await emit(sid, "browser.action", {"kind": "click", "selector": selector})
    try:
        result = await _drive(sid, {"kind": "click", "selector": selector})
    except SandboxError as exc:
        return json.dumps({"error": str(exc)})
    await emit(
        sid,
        "browser.navigated",
        {"url": result.get("url"), "title": result.get("title")},
    )
    return json.dumps(result)


async def _type_into(
    ctx: RunContext[PolymathState],
    selector: Annotated[str, "CSS selector of the target input."],
    text: Annotated[str, "Text to fill."],
    submit: Annotated[bool, "Press Enter after typing."] = False,
) -> str:
    sid = ctx.deps.session_id
    await emit(
        sid,
        "browser.action",
        {"kind": "type", "selector": selector, "submit": submit},
    )
    try:
        result = await _drive(
            sid,
            {"kind": "type", "selector": selector, "text": text, "submit": submit},
        )
    except SandboxError as exc:
        return json.dumps({"error": str(exc)})
    await emit(
        sid,
        "browser.navigated",
        {"url": result.get("url"), "title": result.get("title")},
    )
    return json.dumps(result)


browser_open_url = Tool(_open_url, name="browser_open_url")
browser_click = Tool(_click, name="browser_click")
browser_type = Tool(_type_into, name="browser_type")
