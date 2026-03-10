"""
ASR mute/unmute state.

Extracted from listen.py so tts.py and ws_server.py can both import this
module at the top level without creating circular dependencies.
"""

import threading
import time
from threading import Event
from typing import Optional

_muted: Event = Event()
_unmuted_at: float = 0.0
_hold_until: float = 0.0  # wall-clock time before which unmute() must not fire
_locked: bool = False      # hard lock: unmute() is a no-op until unlock() is called
_deferred_unmute: Optional[threading.Timer] = None  # cancellable timer created by hold-mute deferral


def mute() -> None:
    """Suppress ASR output (called while TTS is playing)."""
    _muted.set()
    print("  [ASR: muted]")


def lock() -> None:
    """Permanently suppress ASR until unlock() is called (e.g., tap-only idle page).

    Unlike hold_mute_for(), this does NOT spawn any deferred timer — unmute()
    becomes a clean no-op for the duration of the lock.
    """
    global _locked
    _locked = True
    _muted.set()
    print("  [ASR: locked (tap-only)]")


def unlock() -> None:
    """Remove the permanent lock and unmute immediately."""
    global _locked
    _locked = False
    unmute()


def hold_mute_for(seconds: float) -> None:
    """Keep ASR muted for at least `seconds` seconds from now.

    Call this when a YouTube video is about to play so that the ASR stays
    muted for the video's duration, even if tts_status=stop arrives first.
    Any call to unmute() during this window will be deferred automatically.
    """
    global _hold_until
    _hold_until = time.time() + seconds
    _muted.set()
    print(f"  [ASR: hold-mute for {seconds:.0f}s (video playing)]")


def unmute() -> None:
    """Resume ASR output (deferred if a hold-mute window is still active)."""
    global _unmuted_at, _deferred_unmute
    if _locked:
        return
    remaining = _hold_until - time.time()
    if remaining > 0:
        if _deferred_unmute is not None:
            _deferred_unmute.cancel()
        _deferred_unmute = threading.Timer(remaining, unmute)
        _deferred_unmute.daemon = True
        _deferred_unmute.start()
        return
    _deferred_unmute = None
    _unmuted_at = time.time()
    _muted.clear()
    print("  [ASR: listening — speak now]")


def cancel_hold() -> None:
    """Clear any active hold-mute window and unmute immediately.

    Called when the video ends (via video_ended WebSocket message) or when
    the user presses I'm Ready before the hold timer expires.
    """
    global _hold_until, _deferred_unmute
    _hold_until = 0.0
    if _deferred_unmute is not None:
        _deferred_unmute.cancel()
        _deferred_unmute = None
    unmute()


def is_muted() -> bool:
    return _muted.is_set()


def last_unmuted_at() -> float:
    """Return the timestamp of the most recent unmute() call (0.0 if never unmuted)."""
    return _unmuted_at
