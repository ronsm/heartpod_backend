"""
Download the Piper TTS alba voice model into ./voices/.

Files downloaded:
  voices/en_GB-alba-medium.onnx       (~65 MB, ONNX model weights)
  voices/en_GB-alba-medium.onnx.json  (voice configuration)
"""

import os
import urllib.request

VOICES_DIR = os.path.join(os.path.dirname(__file__), "voices")
BASE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main"
    "/en/en_GB/alba/medium"
)
FILES = [
    "en_GB-alba-medium.onnx",
    "en_GB-alba-medium.onnx.json",
]


def _download(filename: str) -> None:
    url = f"{BASE_URL}/{filename}"
    dest = os.path.join(VOICES_DIR, filename)
    if os.path.isfile(dest):
        print(f"  already exists, skipping: {filename}")
        return
    print(f"  downloading {filename} ...", end="", flush=True)
    urllib.request.urlretrieve(url, dest)
    size_mb = os.path.getsize(dest) / 1_048_576
    print(f" done ({size_mb:.1f} MB)")


if __name__ == "__main__":
    os.makedirs(VOICES_DIR, exist_ok=True)
    print(f"Saving voice model to: {VOICES_DIR}")
    for f in FILES:
        _download(f)
    print("Alba voice ready. Run with: python main.py --tts local")
