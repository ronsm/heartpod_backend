import argparse
import asyncio
import json
from queue import Queue
from threading import Thread
from typing import Optional

import websockets

import numpy as np
# Import sounddevice to silence ALSA and JACK warnings:
# https://github.com/Uberi/speech_recognition/issues/182
import sounddevice
import speech_recognition as sr
from faster_whisper import WhisperModel


def parse_args() -> argparse.Namespace:
    """Parse the command-line arguments of this program."""
    parser = argparse.ArgumentParser(
        description="Speech-to-text interface for the self-screening health station"
    )
    parser.add_argument(
        "-l",
        "--list-microphones",
        action="store_true",
        help="list all available microphones and exit",
    )
    parser.add_argument(
        "-t",
        "--test-microphone",
        action="store_true",
        help="test microphone and exit",
    )
    parser.add_argument(
        "-m",
        "--microphone",
        metavar="M",
        type=int,
        help=(
            "use the specified microphone (if unspecified, the default "
            "microphone is used)"
        ),
    )
    parser.add_argument(
        "-e",
        "--energy-threshold",
        metavar="N",
        type=int,
        help=(
            "initial energy threshold for sounds (between 0 and 4000; "
            "if unspecified, automatic calibration is performed)"
        ),
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="hostname of the main.py HTTP server (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="port of the main.py HTTP server (default: 8000)",
    )
    args = parser.parse_args()

    # Ensure that the specified microphone exists
    if (
        args.microphone is not None
        and not 0 <= args.microphone <= get_microphone_count() - 1
    ):
        raise IndexError("Device index out of range")

    # Ensure that the specified energy threshold is valid
    if args.energy_threshold is not None and not 0 <= args.energy_threshold <= 4000:
        raise ValueError("Energy threshold out of 0-4000")

    return args


def get_microphone_count() -> int:
    """Return the number of available microphones."""
    return len(sr.Microphone.list_microphone_names())


def list_microphones() -> None:
    """List all available microphones."""
    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        print(f"{index}: {name}")


def test_microphone(device_index: Optional[int] = None) -> None:
    pass


def listen(
    recognizer: sr.Recognizer,
    audio_queue: Queue,
    microphone: sr.Microphone,
    energy_threshold: Optional[int] = None,
) -> None:
    """Capture microphone input.

    This function must be run in a thread. It enqueues the captured
    audio data in a message queue for consumption by the recognize()
    function in a different thread.
    """
    with microphone as source:
        # Set the initial energy threshold...
        if energy_threshold:
            # ...either by using the value specified by the user...
            recognizer.energy_threshold = energy_threshold
        else:
            # ...or by listening for 1 second (by default) to calibrate
            # the energy threshold for ambient noise levels
            print("Adjusting for ambient noise... Please be quiet")
            recognizer.adjust_for_ambient_noise(source)
        # Repeatedly listen for phrases until the user hits Ctrl+C and
        # put the resulting audio on the audio processing job queue
        print("Listening... Say something!")
        try:
            while True:
                audio_queue.put(recognizer.listen(source))
        except KeyboardInterrupt:
            pass

    print("Stopped listening")

    # Block until all current audio processing jobs are done (empty queue)
    audio_queue.join()

    # Tell the other thread that no other audio processing job is coming
    audio_queue.put(None)


async def _send_ws(ws_url: str, payload: str) -> None:
    """Open a WebSocket connection, send one message, then close."""
    async with websockets.connect(ws_url) as ws:
        await ws.send(payload)


def recognize(
    audio_queue: Queue, server_url: str
) -> None:
    """Run speech recognition.

    This function must be run in a thread. It dequeues from a message
    queue holding audio data captured by the listen() function in a
    different thread.
    """
    hallucinations = [
        # Empty string
        "",
        # Thank you phrases
        "Thank you for watching",
        "Thanks for watching",
        "Thank you for your attention",
        # Subscription/engagement prompts
        "Please subscribe",
        "Don't forget to like and subscribe",
        "Hit the bell icon",
        # Filler phrases
        "You",
        "Subtitles by the Amara.org community",
        # Korean broadcaster signature
        "MBC 뉴스",
    ]

    print("Loading Whisper model on GPU...")
    model = WhisperModel("base.en", device="cuda", compute_type="float16")
    print("Whisper model ready.")

    while True:
        # Retrieve an audio processing job from the queue
        audio = audio_queue.get()

        # Stop all audio processing if the other thread is done
        if audio is None:
            audio_queue.task_done()
            break

        try:
            # Convert sr.AudioData to float32 numpy array at 16 kHz
            raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
            audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            segments, _ = model.transcribe(audio_np, language="en")
            utterance = " ".join(segment.text for segment in segments)

            # Remove leading/trailing whitespace and punctuation added by Whisper
            utterance = utterance.strip().rstrip(".!?,;")

            # Reject hallucinations
            if utterance in hallucinations:
                continue

            if not utterance:
                continue

            # Send to the coordinator via WebSocket
            try:
                payload = json.dumps(
                    {"type": "action", "action": "answer", "data": {"answer": utterance}}
                )
                asyncio.run(_send_ws(server_url, payload))
            except Exception as error:
                print(f"  [speech] error: {error}")
            else:
                print(f"  [speech] '{utterance}'")

        except Exception as error:
            print(f"  [speech] recognition error: {error}")

        finally:
            # Mark the audio processing job as completed in the queue
            audio_queue.task_done()


def main():
    """Run the speech-to-text interface (this program)."""
    # Parse command-line arguments
    args = parse_args()

    if args.list_microphones:
        list_microphones()
        return

    if args.test_microphone:
        test_microphone(args.microphone)
        return

    server_url = f"ws://{args.host}:{args.port}"
    print(f"Sending recognized speech to {server_url}")

    microphone = sr.Microphone(args.microphone)
    recognizer = sr.Recognizer()

    # Audio processing job queue (FIFO) used for communication
    # between the listener thread and the recognizer thread
    audio_queue = Queue()

    # Start a new thread to recognize audio...
    worker = Thread(target=recognize, args=(audio_queue, server_url))
    worker.start()

    # ...while this thread focuses on listening
    listen(recognizer, audio_queue, microphone, args.energy_threshold)

    worker.join()


if __name__ == "__main__":
    main()
