"""
Text-to-speech engine.

Modes:
  none  – silent (default)
  local – speak through the local machine's audio output via pyttsx3;
          runs in a background thread so the robot loop is never blocked;
          interrupted automatically when a new utterance starts or when
          stop() is called (e.g. the moment a user action arrives)
  temi  – send {"type": "tts", "text": "..."} to connected WebSocket clients
          for the Temi robot to handle
"""

import threading

_mode: str = "none"
_lock = threading.Lock()
_current_engine = None   # pyttsx3 engine currently running runAndWait()
_stop_flag = threading.Event()


def init(mode: str) -> None:
    """Validate mode and print a startup message. Call once before speak()."""
    global _mode
    if mode == "local":
        try:
            import pyttsx3  # noqa: F401 — confirm it is importable
            _mode = "local"
            print("  [TTS: local (pyttsx3)]")
        except Exception as e:
            print(f"  [TTS: local unavailable — {e}]")
            _mode = "none"
    elif mode == "temi":
        _mode = "temi"
        print("  [TTS: temi (sending via WebSocket)]")
    else:
        _mode = "none"


def speak(text: str) -> None:
    """Start speaking text, interrupting any speech already in progress."""
    if _mode == "local":
        # Stop whatever is playing, then clear the flag before starting the
        # new thread so the thread does not immediately see a stale stop signal.
        stop()
        _stop_flag.clear()
        threading.Thread(target=_speak_local, args=(text,), daemon=True).start()
    elif _mode == "temi":
        from ws_server import broadcast_tts
        broadcast_tts(text)


def stop() -> None:
    """Interrupt any speech currently in progress."""
    _stop_flag.set()
    with _lock:
        engine = _current_engine
    if engine is not None:
        try:
            engine.stop()
        except Exception:
            pass


def _speak_local(text: str) -> None:
    """Worker run on a daemon thread for local TTS."""
    global _current_engine
    import pyttsx3
    engine = pyttsx3.init()
    with _lock:
        _current_engine = engine
    try:
        # Guard against stop() being called between speak() and this point.
        if not _stop_flag.is_set():
            engine.say(text)
            engine.runAndWait()
    finally:
        with _lock:
            _current_engine = None
