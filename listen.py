import argparse
from queue import Queue
from threading import Thread
from typing import Optional

import numpy as np
# Import sounddevice to silence ALSA and JACK warnings:
# https://github.com/Uberi/speech_recognition/issues/182
import sounddevice
import speech_recognition as sr
from faster_whisper import WhisperModel


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


def recognize(audio_queue: Queue, action_queue: Queue) -> None:
    """Run speech recognition.

    This function must be run in a thread. It dequeues audio captured by
    listen() and puts recognised text directly onto action_queue.
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

    try:
        import ctranslate2
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        device = "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"Loading Whisper model on {device.upper()}...")
    model = WhisperModel("base.en", device=device, compute_type=compute_type)
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

            action_queue.put(utterance)
            print(f"  [speech] '{utterance}'")

        except Exception as error:
            print(f"  [speech] recognition error: {error}")

        finally:
            # Mark the audio processing job as completed in the queue
            audio_queue.task_done()


def main():
    """Run the speech-to-text interface standalone (for microphone testing)."""
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
    output_queue = Queue()  # standalone: just print, don't route anywhere

    worker = Thread(target=recognize, args=(audio_queue, output_queue))
    worker.start()

    listen(recognizer, audio_queue, microphone, args.energy_threshold)
    worker.join()


if __name__ == "__main__":
    main()
