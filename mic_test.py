"""Standalone microphone + Whisper transcription test.

Usage:
    python mic_test.py               # use default microphone
    python mic_test.py -m 2          # use microphone index 2
    python mic_test.py --list        # list available microphones
    python mic_test.py --model small # use a larger Whisper model

Press Ctrl+C to stop.
"""

import argparse

import numpy as np
import sounddevice  # silences ALSA/JACK warnings
import speech_recognition as sr
from faster_whisper import WhisperModel


def main():
    parser = argparse.ArgumentParser(description="Microphone transcription test")
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="list available microphones and exit",
    )
    parser.add_argument(
        "-m", "--microphone",
        metavar="M",
        type=int,
        help="microphone device index (default: system default)",
    )
    parser.add_argument(
        "--model",
        default="base.en",
        help="Whisper model to use (e.g. tiny.en, base.en, small, medium; default: base.en)",
    )
    parser.add_argument(
        "-e", "--energy-threshold",
        metavar="N",
        type=int,
        help="manual energy threshold 0-4000 (default: auto-calibrate)",
    )
    args = parser.parse_args()

    if args.list:
        print("Available microphones:")
        for i, name in enumerate(sr.Microphone.list_microphone_names()):
            print(f"  {i}: {name}")
        return

    recognizer = sr.Recognizer()
    microphone = sr.Microphone(device_index=args.microphone)

    with microphone as source:
        if args.energy_threshold:
            recognizer.energy_threshold = args.energy_threshold
            print(f"Energy threshold set to {args.energy_threshold}")
        else:
            print("Calibrating for ambient noise... please be quiet.")
            recognizer.adjust_for_ambient_noise(source)
            print(f"Energy threshold calibrated to {recognizer.energy_threshold:.0f}")

        print(f"\nLoading Whisper model '{args.model}' on GPU...")
        model = WhisperModel(args.model, device="cuda", compute_type="float16")
        print("Model ready. Listening... speak now. Press Ctrl+C to stop.\n")

        try:
            while True:
                print("[ waiting for speech ]")
                audio = recognizer.listen(source)
                print("[ processing... ]")
                raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
                audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                segments, _ = model.transcribe(audio_np, language="en")
                text = " ".join(s.text for s in segments).strip()
                if text:
                    print(f"  >> {text}\n")
                else:
                    print("  (silence or unclear)\n")
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
