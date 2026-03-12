"""
STT client — connects to the external speech-to-text server (stt_server.py).

Provides start()/stop() to control when the server listens for speech,
and a background reader thread that forwards recognized text into the
shared action queue.

The hold()/release_hold() pair suppresses start() while instruction videos
are playing on the frontend, preventing video narration from being picked
up as user speech.
"""

import threading
import time
from multiprocessing.connection import Client
from queue import Queue
from typing import Optional

ADDRESS = ("localhost", 61000)
"""Address of the STT server."""

START = "Start STT"
STOP = "Stop STT"

RETRY_INTERVAL = 3
"""Seconds between reconnection attempts."""

_connection = None
_action_queue: Optional[Queue] = None
_send_lock = threading.Lock()
_hold = False


def init(action_queue: Queue) -> None:
    """Connect to the STT server and start the reader thread.

    Blocks until connected, retrying every RETRY_INTERVAL seconds.
    """
    global _connection, _action_queue
    _action_queue = action_queue

    while True:
        try:
            _connection = Client(ADDRESS)
            print(f"  [STT: connected to server at {ADDRESS}]")
            break
        except ConnectionRefusedError:
            print(f"  [STT: no server at {ADDRESS}, retrying in {RETRY_INTERVAL}s]")
            time.sleep(RETRY_INTERVAL)

    threading.Thread(target=_reader, daemon=True, name="stt-reader").start()


def start() -> None:
    """Ask the STT server to start listening.

    No-op if a video hold is active (call release_hold() first).
    """
    if _hold:
        return
    _send(START)


def stop() -> None:
    """Ask the STT server to stop listening."""
    _send(STOP)


def hold() -> None:
    """Suppress start() and stop listening (video playing).

    No-op if a hold is already active.
    """
    global _hold
    if _hold:
        return
    _hold = True
    stop()


def release_hold() -> None:
    """Re-enable start() and resume listening immediately.

    No-op if no hold is active.
    """
    global _hold
    if not _hold:
        return
    _hold = False
    start()


def _send(command: str) -> None:
    """Send a command to the STT server (thread-safe)."""
    with _send_lock:
        if _connection is None:
            return
        try:
            _connection.send(command)
        except (OSError, ValueError) as e:
            print(f"  [STT: send failed: {e}]")


def _reader() -> None:
    """Background thread: forward recognized text to the action queue."""
    while True:
        try:
            text = _connection.recv()
        except (EOFError, OSError):
            print("  [STT: server connection lost]")
            break
        if text and _action_queue is not None:
            _action_queue.put(text)
            print(f"  [speech] '{text}'")
