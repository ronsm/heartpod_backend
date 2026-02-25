"""
Text-to-speech engine.

Modes:
  none  – silent (default)
  local – speak through the local machine's audio output using piper-tts
          (cross-platform: macOS and Linux); runs in a background thread so
          the robot loop is never blocked; playback is interrupted immediately
          when stop() is called
  temi  – send {"type": "tts", "text": "..."} to connected WebSocket clients
          for the Temi robot to handle

Local mode requires:
  - piper-tts Python package  (`pip install piper-tts`)
  - Alba voice model in ./voices/en_GB-alba-medium.onnx
  Run `python download_voice.py` to fetch the voice model automatically.
"""

import os
import threading

_mode: str = "none"
_voice = None           # piper.voice.PiperVoice, loaded once at init
_stop_flag = threading.Event()
_seq_lock = threading.Lock()
_current_seq: int = 0   # incremented on every stop(); threads bail if stale
_sd_active = threading.Event()  # set only while sd.play()/sd.wait() is running

_VOICES_DIR = os.path.join(os.path.dirname(__file__), "voices")
_PIPER_MODEL = os.path.join(_VOICES_DIR, "en_GB-alba-medium.onnx")


def init(mode: str) -> None:
    """Validate mode and load resources. Call once before speak()."""
    global _mode, _voice
    if mode == "local":
        if not os.path.isfile(_PIPER_MODEL):
            print(f"  [TTS: local unavailable — voice model not found: {_PIPER_MODEL}]")
            print("  [TTS: run `python download_voice.py` to download the alba voice]")
            _mode = "none"
            return
        try:
            from piper.voice import PiperVoice
            _voice = PiperVoice.load(_PIPER_MODEL)
            _mode = "local"
            print(f"  [TTS: local (piper-tts, alba voice, {_voice.config.sample_rate} Hz)]")
        except ImportError:
            print("  [TTS: local unavailable — run `pip install piper-tts`]")
            _mode = "none"
    elif mode == "temi":
        _mode = "temi"
        print("  [TTS: temi (sending via WebSocket)]")
    else:
        _mode = "none"


def speak(text: str) -> None:
    """Start speaking text, interrupting any speech already in progress."""
    global _current_seq
    if _mode == "local":
        stop()
        _stop_flag.clear()
        with _seq_lock:
            _current_seq += 1
            seq = _current_seq
        threading.Thread(target=_speak_local, args=(text, seq), daemon=True).start()
    elif _mode == "temi":
        from ws_server import broadcast_tts
        broadcast_tts(text)


def stop() -> None:
    """Interrupt any speech currently in progress."""
    global _current_seq
    _stop_flag.set()
    with _seq_lock:
        _current_seq += 1
    if _sd_active.is_set():
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass


def _speak_local(text: str, seq: int) -> None:
    """Worker: synthesise with piper, then play via sounddevice."""
    if _stop_flag.is_set():
        return

    # synthesize() yields AudioChunk objects; audio_float_array is float32 in [-1, 1]
    try:
        chunks = [chunk.audio_float_array for chunk in _voice.synthesize(text)]
    except Exception as e:
        print(f"  [TTS synthesis error: {e}]")
        return

    if not chunks:
        print("  [TTS: synthesis produced no audio]")
        return

    with _seq_lock:
        current = _current_seq
    if _stop_flag.is_set() or seq != current:
        return

    import numpy as np
    import sounddevice as sd

    audio = np.concatenate(chunks)
    _sd_active.set()
    try:
        sd.play(audio, samplerate=_voice.config.sample_rate)
        sd.wait()
    finally:
        _sd_active.clear()
