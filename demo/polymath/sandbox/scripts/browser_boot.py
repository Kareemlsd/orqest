"""Launch a persistent Chromium under Xvfb that the agent controls via Playwright.

Phase 3 will invoke this (or connect to it) from the browser tool. Phase 0
keeps it as a stub so the image builds without TODOs — running this script
directly is harmless.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.environ.get("DISPLAY", "") != ":99":
        print("DISPLAY not set to :99 — run this inside the sandbox container.", file=sys.stderr)
        return 1
    print("[browser-boot] stub — Phase 3 wires Playwright-over-CDP here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
