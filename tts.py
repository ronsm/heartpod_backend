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

Playback backends (local mode):
  macOS – afplay subprocess reading a temp WAV file
  Linux – aplay subprocess reading WAV from stdin

ASR muting:
  speak() mutes the ASR pipeline for the duration of playback plus
  ASR_UNMUTE_DELAY (from config.py) so any audio captured at the end of
  playback has time to drain through Whisper before the pipeline reopens.
"""

import io
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave

import asr
from config import ASR_UNMUTE_DELAY
from ws_server import broadcast_tts, broadcast_tts_active

_mode: str = "none"
_voice = None           # piper.voice.PiperVoice, loaded once at init
_stop_flag = threading.Event()
_seq_lock = threading.Lock()
_current_seq: int = 0   # incremented on every stop(); threads bail if stale
_proc_lock = threading.Lock()
_current_proc = None    # current afplay/aplay subprocess
_temi_fallback_timer = None  # threading.Timer: unmutes after estimated temi playback

_VOICES_DIR = os.path.join(os.path.dirname(__file__), "voices")
_PIPER_MODEL = os.path.join(_VOICES_DIR, "en_GB-alba-medium.onnx")

# Rough average speech rate used to estimate temi playback duration (seconds/word).
_TEMI_SECS_PER_WORD = 0.4


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
            backend = "afplay" if sys.platform == "darwin" else "aplay"
            print(f"  [TTS: local (piper-tts, alba voice, {_voice.config.sample_rate} Hz, {backend})]")
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
    global _current_seq, _temi_fallback_timer
    if _mode == "local":
        asr.mute()
        stop()
        _stop_flag.clear()
        with _seq_lock:
            _current_seq += 1
            seq = _current_seq
        broadcast_tts_active(True)
        threading.Thread(target=_speak_local, args=(text, seq), daemon=True).start()
    elif _mode == "temi":
        if _temi_fallback_timer is not None:
            _temi_fallback_timer.cancel()
        asr.mute()
        broadcast_tts(text)
        # Fallback: fires if the real robot never sends tts_status=stop
        # (e.g. on emulator where onTtsStatusChanged never fires).
        def _temi_fallback():
            asr.unmute()
            broadcast_tts_active(False)
        words = len(text.split())
        delay = max(2.0, words * _TEMI_SECS_PER_WORD + 0.5)
        _temi_fallback_timer = threading.Timer(delay, _temi_fallback)
        _temi_fallback_timer.daemon = True
        _temi_fallback_timer.start()


def stop() -> None:
    """Interrupt any speech currently in progress."""
    global _current_seq
    _stop_flag.set()
    with _seq_lock:
        _current_seq += 1
    with _proc_lock:
        if _current_proc is not None:
            try:
                _current_proc.kill()
            except Exception:
                pass


def _speak_local(text: str, seq: int) -> None:
    """Worker: synthesise with piper, then play audio."""
    import numpy as np
    try:
        if _stop_flag.is_set():
            return

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

        audio = np.concatenate(chunks)  # float32, range [-1, 1]

        if sys.platform == "darwin":
            _play_macos(audio, seq)
        else:
            _play_aplay(audio, seq)

    finally:
        # Unlock the frontend and unmute ASR when playback ends.
        # The seq guard ensures a thread killed by stop() doesn't unlock while
        # a newer speak() is already in progress.
        with _seq_lock:
            if seq == _current_seq:
                broadcast_tts_active(False)
        time.sleep(ASR_UNMUTE_DELAY)
        with _seq_lock:
            if seq == _current_seq:
                asr.unmute()


def _play_macos(audio, seq: int) -> None:
    """Write a temp WAV file and play via afplay (macOS).

    Using a file rather than stdin avoids the PortAudio conflict that arises
    when sounddevice (TTS) and pyaudio (sr.Microphone) both initialise the
    CoreAudio backend simultaneously.
    """
    global _current_proc
    import numpy as np

    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_voice.config.sample_rate)
        wf.writeframes(audio_int16.tobytes())

    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    try:
        tmp.write(buf.getvalue())
        tmp.close()

        try:
            proc = subprocess.Popen(
                ["afplay", tmp.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print("  [TTS: afplay not found]")
            return

        with _proc_lock:
            _current_proc = proc

        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except Exception:
            pass
        finally:
            with _proc_lock:
                if _current_proc is proc:
                    _current_proc = None
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _play_aplay(audio, seq: int) -> None:
    """Encode to WAV and pipe to aplay (Linux)."""
    global _current_proc
    import numpy as np

    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_voice.config.sample_rate)
        wf.writeframes(audio_int16.tobytes())
    wav_bytes = buf.getvalue()

    try:
        proc = subprocess.Popen(
            ["aplay", "-q", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("  [TTS: aplay not found — install alsa-utils]")
        return

    with _proc_lock:
        _current_proc = proc

    try:
        proc.stdin.write(wav_bytes)
        proc.stdin.close()
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except Exception:
        pass
    finally:
        with _proc_lock:
            if _current_proc is proc:
                _current_proc = None
