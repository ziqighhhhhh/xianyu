"""Minimal diagnostics for the goofish LWP WebSocket endpoint.

The real-time chat protocol is not fully reverse engineered yet; this module
only verifies token acquisition and the WebSocket handshake so operators can
tell whether an account is ready for LWP.
"""

from __future__ import annotations

import asyncio
import json

WS_URL = "wss://wss-goofish.dingtalk.com/account"


def exchange(token: str, frames: list[dict], timeout: float = 6.0) -> dict:
    """Connect, send frames, and collect one response per frame (best effort)."""
    from websockets.sync.client import connect
    responses = []
    try:
        with connect(f"{WS_URL}?accessToken={token}", open_timeout=timeout,
                     close_timeout=2, max_size=8 * 1024 * 1024) as ws:
            for frame in frames:
                ws.send(json.dumps(frame, ensure_ascii=False))
            for _ in frames:
                try:
                    responses.append(json.loads(ws.recv(timeout=timeout)))
                except TimeoutError:
                    break
            return {"connected": True, "responses": responses}
    except Exception as exc:
        return {"connected": False, "error": f"{type(exc).__name__}: {exc}", "responses": responses}


async def _probe(token: str, timeout: float) -> dict:
    import websockets
    url = f"{WS_URL}?accessToken={token}"
    async with websockets.connect(url, open_timeout=timeout, close_timeout=2) as ws:
        return {"connected": True, "subprotocol": ws.subprotocol or "", "state": ws.state.name}


def probe(token: str, timeout: float = 6.0) -> dict:
    try:
        return asyncio.run(_probe(token, timeout))
    except Exception as exc:
        return {"connected": False, "error": f"{type(exc).__name__}: {exc}"}
