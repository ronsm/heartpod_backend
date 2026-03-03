import argparse
import time
from queue import Queue
from threading import Thread
from typing import Optional

# Imported for its side effect of silencing ALSA/JACK console warnings:
# https://github.com/Uberi/speech_recognition/issues/182
import sounddevice  # noqa: F401
import speech_recognition as sr

import asr


def listen(
    recognizer: sr.Recognizer,
    audio_queue: Queue,
    microphone: sr.Microphone,
    energy_threshold: Optional[int] = None,
) -> None:
    """Capture microphone input and enqueue audio chunks for recognition.

    Runs in a dedicated thread. Enqueues captured audio onto audio_queue
    for consumption by recognize() in a separate thread.
    """
    with microphone as source:
        if energy_threshold:
            recognizer.energy_threshold = energy_threshold
        else:
            print("Adjusting for ambient noise... Please be quiet")
            recognizer.adjust_for_ambient_noise(source)
        print("Listening... Say something!")
        try:
            while True:
                audio_queue.put((recognizer.listen(source), time.time()))
        except KeyboardInterrupt:
            pass

    print("Stopped listening")
    audio_queue.join()
    audio_queue.put((None, 0.0))  # signal recognize() that no more audio is coming


def recognize(
    recognizer: sr.Recognizer,
    audio_queue: Queue,
    action_queue: Queue,
) -> None:
    """Transcribe audio chunks and forward recognised text to action_queue.

    Runs in a dedicated thread. Discards known Whisper hallucinations and
    any audio captured while the ASR is muted (during TTS playback).
    """
    _hallucinations = {
        "",
        "Thank you for watching",
        "Thanks for watching",
        "Thank you for your attention",
        "Please subscribe",
        "Don't forget to like and subscribe",
        "Hit the bell icon",
        "You",
        "Subtitles by the Amara.org community",
        "MBC 뉴스",
        "Thank you.",
        "Thank you very much.",
        "Ready?",
        "I didn't quite catch that.",
        ".",
    }

    while True:
        audio, captured_at = audio_queue.get()

        if audio is None:
            audio_queue.task_done()
            break

        # Discard before transcription if ASR is currently muted, or if the
        # audio was captured before the most recent unmute (i.e. it was queued
        # during a muted window and only surfaced after the TTS finished).
        if asr.is_muted() or captured_at < asr.last_unmuted_at():
            audio_queue.task_done()
            print(f"  [speech suppressed (TTS active): captured during muted period]")
            continue

        try:
            utterance = recognizer.recognize_faster_whisper(  # type: ignore[attr-defined]
                audio, model="small.en", language="en"
            )

        except Exception as error:
            print(f"  [speech] recognition error: {error}")

        else:
            # Remove leading whitespace inserted by Whisper
            utterance = utterance.lstrip()

            # Reject hallucinations
            if utterance in _hallucinations:
                continue

            # Put the recognized speech on the action queue
            action_queue.put(utterance)
            print(f"  [speech] '{utterance}'")

        finally:
            audio_queue.task_done()


def main():
    """Run the speech-to-text interface standalone (for microphone testing)."""
    parser = argparse.ArgumentParser(
        description="Speech-to-text interface for the self-screening health station"
    )
    parser.add_argument(
        "-l", "--list-microphones",
        action="store_true",
        help="list all available microphones and exit",
    )
    parser.add_argument(
        "-m", "--microphone",
        metavar="M",
        type=int,
        help="use the specified microphone (default: system default)",
    )
    parser.add_argument(
        "-e", "--energy-threshold",
        metavar="N",
        type=int,
        help="initial energy threshold (0–4000; default: auto-calibrate)",
    )
    args = parser.parse_args()

    if args.list_microphones:
        for index, name in enumerate(sr.Microphone.list_microphone_names()):
            print(f"{index}: {name}")
        return

    mic_count = len(sr.Microphone.list_microphone_names())
    if args.microphone is not None and not 0 <= args.microphone <= mic_count - 1:
        parser.error(f"microphone index out of range (0–{mic_count - 1})")
    if args.energy_threshold is not None and not 0 <= args.energy_threshold <= 4000:
        parser.error("energy threshold must be between 0 and 4000")

    microphone = sr.Microphone(args.microphone)
    recognizer = sr.Recognizer()
    audio_queue = Queue()
    output_queue = Queue()

    worker = Thread(target=recognize, args=(recognizer, audio_queue, output_queue))
    worker.start()

    listen(recognizer, audio_queue, microphone, args.energy_threshold)
    worker.join()


if __name__ == "__main__":
    main()
