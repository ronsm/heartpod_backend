import argparse
import os
import threading
from queue import Queue

import tts
from listen import listen, recognize
from robot import HealthRobotGraph
from ws_server import action_queue, start_ws_server, DEFAULT_PORT


def _terminal_input_loop():
    """Forward terminal keystrokes into the same action queue as WebSocket actions."""
    while True:
        try:
            line = input("You: ").strip()
        except EOFError:
            break
        if line.lower() in ("quit", "exit"):
            print("\nRobot: Goodbye! Come back anytime.")
            os.kill(os.getpid(), 2)  # SIGINT → KeyboardInterrupt in main thread
            break
        if line:
            action_queue.put(line)


def main():
    parser = argparse.ArgumentParser(description="HeartPod health screening app")
    parser.add_argument(
        "--dummy",
        action="store_true",
        help="Use simulated sensor data instead of real BLE hardware",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port for the WebSocket server (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-printer",
        action="store_true",
        help="Disable the thermal receipt printer (useful when running without hardware)",
    )
    parser.add_argument(
        "--no-listen",
        action="store_true",
        help="Disable the speech-to-text listener (useful when running without a microphone)",
    )
    parser.add_argument(
        "--tts",
        choices=["none", "local", "temi"],
        default="none",
        help=(
            "Text-to-speech mode: 'none' (silent), 'local' (speak on this machine via piper-tts), "
            "'temi' (send to the Android app via WebSocket) (default: none)"
        ),
    )
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-key-here'")
        return

    tts.init(args.tts)
    server = start_ws_server(args.port)
    print(f"WebSocket server listening on port {args.port}")
    print(f"  ws://0.0.0.0:{args.port}  – state push and action receive")
    print("Terminal input also accepted. Type 'quit' or 'exit' to stop.\n")

    if not args.no_listen:
        import speech_recognition as sr
        microphone = sr.Microphone()
        recognizer = sr.Recognizer()
        audio_queue = Queue()
        threading.Thread(target=listen, args=(recognizer, audio_queue, microphone), daemon=True).start()
        threading.Thread(target=recognize, args=(audio_queue, action_queue), daemon=True).start()
        print("Speech listener started\n")

    input_thread = threading.Thread(target=_terminal_input_loop, daemon=True)
    input_thread.start()

    sensor_mode = "dummy" if args.dummy else "real"
    robot = HealthRobotGraph(sensor_mode=sensor_mode, use_printer=not args.no_printer)
    try:
        robot.run()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
