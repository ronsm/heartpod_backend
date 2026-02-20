import argparse
import os

from robot import HealthRobotGraph


def main():
    parser = argparse.ArgumentParser(description="HeartPod health screening app")
    parser.add_argument(
        "--dummy",
        action="store_true",
        help="Use simulated sensor data instead of real BLE hardware",
    )
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-key-here'")
        return

    sensor_mode = "dummy" if args.dummy else "real"
    robot = HealthRobotGraph(sensor_mode=sensor_mode)
    robot.run()


if __name__ == "__main__":
    main()
