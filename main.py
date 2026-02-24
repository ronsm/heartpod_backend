import argparse
import os
import subprocess
import sys
import threading

from robot import HealthRobotGraph
from http_server import action_queue, start_http_server, DEFAULT_PORT


def _terminal_input_loop():
    """Forward terminal keystrokes into the same action queue as HTTP actions."""
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
        help=f"Port for the HTTP server (default: {DEFAULT_PORT})",
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
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-key-here'")
        return

    server = start_http_server(args.port)
    print(f"HTTP server listening on port {args.port}")
    print("  GET  /state  → current page")
    print("  POST /action → button press from app")
    print("Terminal input also accepted. Type 'quit' or 'exit' to stop.\n")

    listen_proc = None
    if not args.no_listen:
        listen_script = os.path.join(os.path.dirname(__file__), "listen.py")
        listen_proc = subprocess.Popen(
            [sys.executable, listen_script, "--port", str(args.port)],
        )
        print(f"Speech listener started (PID {listen_proc.pid})\n")

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
        if listen_proc is not None:
            listen_proc.terminate()
        server.shutdown()


if __name__ == "__main__":
    main()
