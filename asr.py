"""
ASR mute/unmute state.

Extracted from listen.py so tts.py and ws_server.py can both import this
module at the top level without creating circular dependencies.
"""

from threading import Event

_muted: Event = Event()


def mute() -> None:
    """Suppress ASR output (called while TTS is playing)."""
    _muted.set()
    print("  [ASR: muted]")


def unmute() -> None:
    """Resume ASR output."""
    _muted.clear()
    print("  [ASR: listening — speak now]")


def is_muted() -> bool:
    return _muted.is_set()
