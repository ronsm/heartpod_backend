import os

from robot import HealthRobotGraph


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Set it with: export OPENAI_API_KEY='your-key-here'")
        return

    robot = HealthRobotGraph()
    robot.run()


if __name__ == "__main__":
    main()
