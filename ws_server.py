"""
WebSocket interface for the Android app.

The server pushes state to all connected clients whenever the robot
transitions to a new page:
    {"type": "state", "page_id": N, "data": {...}}

Clients send button/action events:
    {"type": "action", "action": "...", "data": {...}}

Button actions are mapped to natural-language phrases that the LLM pipeline
understands; questionnaire answers are passed through as-is.
"""

import asyncio
import json
import queue
import threading

import websockets
from websockets.server import WebSocketServerProtocol

DEFAULT_PORT = 8000

# Last-known state — sent immediately to any newly connected client.
_ws_state: dict = {"page_id": 1, "data": {}}

# Actions from connected clients (and terminal) are placed here;
# robot._ask_user() blocks on this queue.
action_queue: queue.Queue = queue.Queue()

# All currently connected WebSocket clients (accessed only from the event loop).
_clients: set[WebSocketServerProtocol] = set()

# The asyncio event loop running the WebSocket server (set in start_ws_server).
_loop: asyncio.AbstractEventLoop | None = None

# Maps UI action keywords to natural-language phrases the LLM understands.
# Questionnaire answers are passed through as-is (already natural language).
_ACTION_TEXT = {
    "start":    "Start Self-Screening",
    "confirm":  "yes",
    "accept":   "yes",
    "ready":    "ready",
    "continue": "continue",
    "skip":     "skip",
    "retry":    "retry",
    "exit":     "no",
    "finish":   "done",
}


async def _handler(websocket: WebSocketServerProtocol):
    """Handle a single WebSocket connection."""
    _clients.add(websocket)
    try:
        # Send the current state immediately so the client is in sync.
        await websocket.send(json.dumps({"type": "state", **_ws_state}))
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action = msg.get("action", "")
            data = msg.get("data", {})
            # Answers carry the full option text; everything else maps via the table.
            if action == "answer":
                text = data.get("answer", action)
            else:
                text = _ACTION_TEXT.get(action, action)
            if text:
                action_queue.put(text)
                print(f"\n  [app] '{text}'" + (f"  ({action})" if action != text else ""))
    except websockets.ConnectionClosed:
        pass
    finally:
        _clients.discard(websocket)


async def _broadcast(message: str):
    """Send a message to all connected clients."""
    if _clients:
        await asyncio.gather(
            *(c.send(message) for c in set(_clients)),
            return_exceptions=True,
        )


async def _serve(port: int):
    async with websockets.serve(_handler, "0.0.0.0", port):
        await asyncio.Future()  # run until cancelled


def update_state(page_id: int, data: dict):
    """Push the current page to all connected clients."""
    global _ws_state
    _ws_state = {"page_id": page_id, "data": data}
    if _loop and _loop.is_running():
        msg = json.dumps({"type": "state", "page_id": page_id, "data": data})
        asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)


class _ServerHandle:
    """Returned by start_ws_server; mirrors the HTTPServer.shutdown() API."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def shutdown(self):
        self._loop.call_soon_threadsafe(self._loop.stop)


def start_ws_server(port: int = DEFAULT_PORT) -> _ServerHandle:
    """Start the WebSocket server in a background daemon thread."""
    global _loop
    _loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_serve(port))

    thread = threading.Thread(target=_run, daemon=True, name="ws-server")
    thread.start()
    return _ServerHandle(_loop)
