import argparse
from multiprocessing.connection import Connection, Listener
from queue import Queue
from string import punctuation
from threading import Event, Thread

# Import sounddevice to silence ALSA and JACK warnings:
# https://github.com/Uberi/speech_recognition/issues/182
import sounddevice
import speech_recognition as sr


ADDRESS = (HOST, PORT) = ("localhost", 61000)
"""Network interface and TCP port to listen on.

The network interface can be a hostname (such as localhost), an IP
address (such as 127.0.0.1), or an emptry string (to bind the listening
socket to all the available interfaces).

Choose a port number in the private range and ideally outside the
operating system's range for ephemeral ports (in /proc/sys/net/ipv4/
ip_local_port_range).
"""


START = "Start STT"
"""Client command to request the server start listening to the user."""


STOP = "Stop STT"
"""Client command to request the server stop listening to the user."""


HALLUCINATIONS = {
    # Thank you phrases
    "thank you",
    "thank you very much",
    "thank you for watching",
    "thanks for watching",
    "thank you for your attention",
    # Subscription/engagement prompts
    "please subscribe",
    "don t forget to like and subscribe",
    "hit the bell icon",
    # Filler phrases
    "you",
    "subtitles by the amara org community",
}
"""Whisper hallucinations.

Sentences produced by the model when it is fed silence or very
low-energy audio.

More? See community dataset on Hugging Face:
https://huggingface.co/datasets/sachaarbonel/whisper-hallucinations
"""


def suppress_hallucinations(text: str) -> str:
    """Filter out an hallucinated sentence.

    Return the empty string if the input text is a known Whisper
    hallucination, otherwise return the input text.

    Matching is performed in lowercase, with punctuation characters
    replaced with a single space, and whitespace normalized.
    """
    punctuation_to_space = str.maketrans(punctuation, len(punctuation) * " ")
    return (
        ""
        if " ".join(text.lower().translate(punctuation_to_space).split())
        in HALLUCINATIONS
        else text
    )


def parse_args() -> argparse.Namespace:
    """Parse the command-line arguments of this program."""
    parser = argparse.ArgumentParser(description="Speech-to-text server for HeartPod")
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
            "use the specified microphone (if unspecified, the default microphone is "
            "used)"
        ),
    )
    parser.add_argument(
        "-t",
        "--threshold",
        metavar="N",
        type=int,
        help=(
            "energy threshold for sounds (if unspecified, automatic calibration is "
            "performed before listening and the threshold is further adjusted "
            "automatically while listening)"
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print everything Whisper thinks you said, including hallucinations",
    )
    args = parser.parse_args()

    # Ensure that the specified microphone exists
    if (
        args.microphone is not None
        and not 0 <= args.microphone <= get_microphone_count() - 1
    ):
        raise IndexError("Device index out of range")

    # Ensure that the specified energy threshold is valid
    if args.threshold is not None and args.threshold < 0:
        raise ValueError("Energy threshold cannot be negative")

    return args


def get_microphone_count() -> int:
    """Return the number of available microphones."""
    return len(sr.Microphone.list_microphone_names())


def list_microphones() -> None:
    """List all available microphones."""
    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        print(f"{index}: {name}")


class STT:
    """Multi-threaded speech-to-text pipeline.

    Input from a microphone. Output to a socket. Usage:

    stt = STT(<microphone config>)
    stt.start(<connection object>)
    stt.stop()
    """

    microphone: sr.Microphone
    recognizer: sr.Recognizer
    worker: dict[str, Thread]
    queue: dict[str, Queue]
    halt: Event
    running: bool

    def __init__(self, microphone_id: int | None, energy_threshold: int | None, verbose: bool) -> None:
        """Prep microphone and threads."""
        self.microphone = sr.Microphone(microphone_id)
        self.recognizer = sr.Recognizer()

        # Set the initial energy threshold
        if energy_threshold is not None:
            # Either by using the value specified by the user
            self.recognizer.energy_threshold = energy_threshold
            self.recognizer.dynamic_energy_threshold = False  # Default: True
        else:
            # Or by listening for 1 second (by default) to calibrate the
            # energy threshold for ambient noise levels
            print("Adjusting for ambient noise... Please be quiet")
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source)
        print(f"Initial energy threshold: {self.recognizer.energy_threshold}")

        # Structures for holding threads and inter-thread communications
        self.worker = dict()
        self.queue = dict()

        # Threading event used by the main thread to stop the worker
        # threads
        self.halt = Event()

        # Keep track of whether the threads are running
        self.running = False

        # Verbosity
        self.verbose = verbose

    def start(self, connection: Connection) -> None:
        """Start worker threads.

        No-op if already started.
        """
        if self.running:
            return

        # Threads for listening to the user, recognizing their speech,
        # and sending the recognized speech to the client
        self.worker["listener"] = Thread(target=self.listen)
        self.worker["recognizer"] = Thread(target=self.recognize)
        self.worker["sender"] = Thread(target=self.send, args=(connection,))

        # Task queues (FIFO) for passing audio processing jobs from the
        # listener thread to the recognizer thread and text sending jobs
        # from the recognizer thread to the sender thread
        self.queue["audio"] = Queue()
        self.queue["text"] = Queue()

        self.worker["listener"].start()
        self.worker["recognizer"].start()
        self.worker["sender"].start()

        self.running = True

    def stop(self) -> None:
        """Stop worker threads.

        Blocks until all worker threads are stopped. No-op if already
        stopped.
        """
        if not self.running:
            return

        # Stop the listener thread (the other threads are stopped in a
        # cascade)
        self.halt.set()

        # Wait for all worker threads to be over
        self.worker["listener"].join()
        self.worker["recognizer"].join()
        self.worker["sender"].join()

        # Reset the threading event
        self.halt.clear()

        self.running = False

    def listen(self) -> None:
        """Capture microphone input.

        This function must be run in a thread. It enqueues the captured
        audio data in a message queue for consumption by the recognize()
        function in the recognizer thread.
        """
        with self.microphone as source:
            # Repeatedly listen for phrases until the thread receives
            # the stop event. Put the recorded audio on the audio
            # processing job queue. Note that a stop event received
            # mid-sentence won't stop recording that sentence but will
            # stop the sentence from being processed.
            print("Listening... Say something!")
            while True:
                try:
                    audio = self.recognizer.listen(source, timeout=1)
                except sr.WaitTimeoutError:
                    if self.halt.is_set():
                        break
                    continue
                if self.halt.is_set():
                    break
                self.queue["audio"].put(audio)

        print("Stopped listening")

        # Use None as a signal to the recognizer thread that no more
        # audio jobs are coming
        self.queue["audio"].put(None)

        # Block until all audio processing jobs are done (empty queue)
        self.queue["audio"].join()

    def recognize(self) -> None:
        """Run speech recognition.

        This function must be run in a thread. It dequeues audio data
        from a message queue fed by the listen() function in the
        listener thread.
        """
        while True:
            # Retrieve an audio processing job from the queue
            audio = self.queue["audio"].get()

            # Stop all audio processing when told that no more audio
            # jobs are coming
            if audio is None:
                self.queue["audio"].task_done()
                break

            # Don't bother performing speech recognition if the stop
            # event is on
            if self.halt.is_set():
                self.queue["audio"].task_done()
                continue

            # Perform speech recognition using (Faster) Whisper
            #
            # SpeechRecognition provides:
            #
            # * sr.Recognizer.recognize_whisper(...)
            # * sr.Recognizer.recognize_faster_whisper(...)
            #
            # Pick "model" from the output of:
            #
            # >>> import whisper
            # >>> print(whisper.available_models())
            #
            # Default is "base". See also:
            #
            # * https://github.com/openai/whisper#available-models-and-languages
            #
            # Pick "language" from the full language list at:
            #
            # * https://github.com/openai/whisper/blob/main/whisper/tokenizer.py
            # * https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/tokenizer.py
            #
            # If not set, (Faster) Whisper will automatically detect the
            # language.
            try:
                utterance = self.recognizer.recognize_faster_whisper(  # type: ignore[attr-defined]
                    audio, model="small.en", language="en"
                )

            except sr.UnknownValueError:
                # Speech was unintelligible
                print("Whisper could not understand audio")

            except sr.RequestError as error:
                # Whisper was unreachable or unresponsive - is it missing,
                # corrupt, or otherwise incompatible?
                print(f"Could not request results from Whisper: {error}")

            else:
                # Remove leading whitespace inserted by Whisper
                utterance = utterance.lstrip()

                # Reject hallucinations
                if suppress_hallucinations(utterance) == "":
                    if self.verbose:
                        print(f"Rejected: {utterance}")
                    continue

                # Put the recognized speech on the sending queue, unless
                # a stop event was received during speech recognition,
                # in which case the recognized speech shouldn't be sent
                print(f"Recognized: {utterance}")
                if not self.halt.is_set():
                    self.queue["text"].put(utterance)

            finally:
                # Mark the audio processing job as completed in the queue
                self.queue["audio"].task_done()

        print("Stopped recognizing speech")

        # Use None as a signal to the sender thread that no more
        # recognized speech is coming
        self.queue["text"].put(None)

        # Block until all sending jobs are done (empty queue)
        self.queue["text"].join()

    def send(self, connection: Connection) -> None:
        """Send recognized speech to connected client.

        This function must be run in a thread. It dequeues text data
        from a message queue fed by the recognize() function in the
        recognizer thread.
        """
        while True:
            # Retrieve recognized speech from the queue
            utterance = self.queue["text"].get()

            # Stop all sending when told that no more recognized speech
            # is coming
            if utterance is None:
                self.queue["text"].task_done()
                break

            # Don't bother sending anything if the stop event is on
            if self.halt.is_set():
                self.queue["text"].task_done()
                continue

            # Send recognized speech over the connection
            try:
                connection.send(utterance)
            except ValueError as error:
                print(f"Could not send utterance to client: {error}")
            else:
                print(f"Sent to client: {utterance}")
            finally:
                self.queue["text"].task_done()

        print("Stopped sending recognized speech to client")


def main():
    """Run speech-to-text server."""
    # Parse command-line arguments
    args = parse_args()

    if args.list_microphones:
        list_microphones()
        return

    # Listen for incoming connections
    with Listener(ADDRESS) as listener:
        print(f"Listening for connections on {listener.address}")

        while True:
            stt = STT(args.microphone, args.threshold, args.verbose)

            try:
                print(f"Waiting for an incoming connection on {listener.address}")
                # The next line blocks until there is an incoming connection
                with listener.accept() as connection:
                    print(f"Connection accepted from {listener.last_accepted}")

                    while True:
                        try:
                            # The next line blocks until there is something to receive
                            request = connection.recv()

                        except EOFError:
                            # There is nothing left to receive and the other end was closed
                            stt.stop()
                            break

                        else:
                            print(f"Request received: {request}")

                            if request == START:
                                stt.start(connection)
                            elif request == STOP:
                                stt.stop()
                            else:
                                pass

                print("Connection closed")

            except KeyboardInterrupt:
                # The user hit Ctrl+C
                stt.stop()
                break

    print("Stopped listening for connections")


if __name__ == "__main__":
    main()
