"""
Text-to-speech engine.

Modes:
  none  – silent (default)
  local – speak through the local machine's audio output by spawning a
          subprocess (macOS: say, Linux: espeak-ng / espeak);
          runs in a background thread so the robot loop is never blocked;
          the subprocess is terminated immediately when stop() is called
  temi  – send {"type": "tts", "text": "..."} to connected WebSocket clients
          for the Temi robot to handle
"""

import platform
import shutil
import subprocess
import threading

_mode: str = "none"
_lock = threading.Lock()
_proc: subprocess.Popen = None   # subprocess currently speaking
_stop_flag = threading.Event()


def _tts_command() -> list:
    """Return [binary, …] for the local TTS command, or [] if unavailable."""
    if platform.system() == "Darwin":
        return ["say"]
    for cmd in ("espeak-ng", "espeak"):
        if shutil.which(cmd):
            return [cmd]
    return []


def init(mode: str) -> None:
    """Validate mode and print a startup message. Call once before speak()."""
    global _mode
    if mode == "local":
        cmd = _tts_command()
        if cmd:
            _mode = "local"
            print(f"  [TTS: local ({cmd[0]})]")
        else:
            print("  [TTS: local unavailable — install espeak or espeak-ng]")
            _mode = "none"
    elif mode == "temi":
        _mode = "temi"
        print("  [TTS: temi (sending via WebSocket)]")
    else:
        _mode = "none"


def speak(text: str) -> None:
    """Start speaking text, interrupting any speech already in progress."""
    if _mode == "local":
        stop()
        _stop_flag.clear()
        threading.Thread(target=_speak_local, args=(text,), daemon=True).start()
    elif _mode == "temi":
        from ws_server import broadcast_tts
        broadcast_tts(text)


def stop() -> None:
    """Terminate any speech subprocess currently running."""
    global _proc
    _stop_flag.set()
    with _lock:
        proc, _proc = _proc, None
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            pass


def _speak_local(text: str) -> None:
    """Worker run on a daemon thread: spawn the TTS subprocess and wait."""
    global _proc
    if _stop_flag.is_set():
        return
    cmd = _tts_command() + [text]
    try:
        proc = subprocess.Popen(cmd)
        with _lock:
            _proc = proc
        # Guard: stop() might have fired between the is_set() check above and
        # setting _proc — terminate immediately in that case.
        if _stop_flag.is_set():
            proc.terminate()
            proc.wait(timeout=1)
            return
        proc.wait()
    finally:
        with _lock:
            if _proc is proc:
                _proc = None
