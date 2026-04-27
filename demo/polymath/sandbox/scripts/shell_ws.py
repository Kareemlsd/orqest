"""Shell websocket — streams a bash PTY to the browser's xterm.js.

Minimal Phase 0 implementation: accepts ws connections on the configured
port, spawns `bash --login` under a PTY, pipes stdout back and stdin in.
The backend proxies `/ws/shell/{sid}` to this server on the session's
sandbox container.

Authentication lives at the backend proxy, not here — this socket binds
to 0.0.0.0 inside the sandbox, reachable only on the docker network.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pty
import signal
import struct
import fcntl
import termios
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol


async def handle(ws: WebSocketServerProtocol, cwd: str) -> None:
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["LANG"] = env.get("LANG", "C.UTF-8")

    pid, fd = pty.fork()
    if pid == 0:
        # Child: exec bash in the target cwd
        os.chdir(cwd)
        os.execvpe("/bin/bash", ["bash", "--login"], env)
        raise SystemExit(1)  # unreachable

    loop = asyncio.get_running_loop()

    async def pty_to_ws() -> None:
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, fd, 4096)
            except OSError:
                break
            if not data:
                break
            try:
                await ws.send(data)
            except websockets.ConnectionClosed:
                break

    async def ws_to_pty() -> None:
        async for msg in ws:
            # Text frames carry stdin; binary frames reserved for control.
            if isinstance(msg, str):
                os.write(fd, msg.encode())
            elif isinstance(msg, (bytes, bytearray)):
                # Control frame: {type: "resize", cols, rows}
                try:
                    _, cols, rows = struct.unpack("!Bhh", msg[:5])
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                except Exception:
                    os.write(fd, bytes(msg))

    try:
        await asyncio.gather(pty_to_ws(), ws_to_pty())
    finally:
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


async def main(host: str, port: int, cwd: str) -> None:
    async def handler(ws: WebSocketServerProtocol, _path: Any = None) -> None:
        await handle(ws, cwd)

    async with websockets.serve(handler, host, port, max_size=2**22):
        print(f"[shell-ws] listening on ws://{host}:{port} (cwd={cwd})", flush=True)
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7681)
    parser.add_argument("--cwd", default="/workspace")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port, args.cwd))
