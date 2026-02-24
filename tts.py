"""
Text-to-speech engine.

Modes:
  none  – silent (default)
  local – speak through the local machine's audio output via pyttsx3
  temi  – send {"type": "tts", "text": "..."} to connected WebSocket clients
          for the Temi robot to handle
"""

_mode: str = "none"


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
    """Speak text according to the current mode. Blocking in local mode."""
    if _mode == "local":
        # A fresh engine is created for every utterance. Reusing a single
        # pyttsx3 engine across calls is unreliable on macOS: after the first
        # runAndWait() the internal loop exits and subsequent say() calls are
        # silently dropped.
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    elif _mode == "temi":
        from ws_server import broadcast_tts
        broadcast_tts(text)
