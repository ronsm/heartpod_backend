"""
Device reading queue.

External devices push readings onto `device_queue` as dicts:
    {"device": "oximeter", "value": {"hr": 72, "spo2": 98}}
    {"device": "bp",       "value": "125/82"}
    {"device": "scale",    "value": 74.2}

In production, replace `simulate_reading()` with your real hardware integration
and remove the call to it in robot.py's `_do_device_reading()`.
"""

import queue
import random
import threading

# Module-level queue shared across the whole app
device_queue: queue.Queue = queue.Queue()


def _generate_value(device: str):
    """Return a plausible fake reading for the given device."""
    if device == "oximeter":
        return {"hr": random.randint(60, 100), "spo2": random.randint(95, 100)}
    elif device == "bp":
        systolic = random.randint(110, 140)
        diastolic = random.randint(70, 90)
        return f"{systolic}/{diastolic}"
    elif device == "scale":
        return round(random.uniform(50, 120), 1)
    return None


def simulate_reading(device: str, delay: float = 2.0):
    """
    Push a fake reading onto device_queue after `delay` seconds.
    Remove this call from robot.py when real hardware is connected.
    """

    def _push():
        value = _generate_value(device)
        device_queue.put({"device": device, "value": value})

    threading.Timer(delay, _push).start()
