"""
Text-to-speech engine.

Modes:
  none  – silent (default)
  local – speak through the local machine's audio output via pyttsx3
  temi  – send {"type": "tts", "text": "..."} to connected WebSocket clients
          for the Temi robot to handle
"""

_mode: str = "none"
_engine = None  # pyttsx3.Engine, only in local mode


def init(mode: str) -> None:
    """Initialise the TTS engine. Call once at startup before speak()."""
    global _mode, _engine
    _mode = mode
    if mode == "local":
        try:
            import pyttsx3
            _engine = pyttsx3.init()
            print("  [TTS: local (pyttsx3)]")
        except Exception as e:
            print(f"  [TTS: local unavailable — {e}]")
            _mode = "none"
    elif mode == "temi":
        print("  [TTS: temi (sending via WebSocket)]")
    else:
        _mode = "none"


def speak(text: str) -> None:
    """Speak text according to the current mode. Blocking in local mode."""
    if _mode == "local":
        if _engine is not None:
            _engine.say(text)
            _engine.runAndWait()
    elif _mode == "temi":
        from ws_server import broadcast_tts
        broadcast_tts(text)
