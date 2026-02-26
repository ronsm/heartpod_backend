"""
Standalone test script for the Holfenry JKS50CL pulse oximeter.

Usage:
    python test_oximeter.py

Put the oximeter on your finger before or just after running.
The script will connect, wait for a stable reading, print it, then exit.
"""

import asyncio
from datetime import datetime
from bleak import BleakClient, BleakScanner


TARGET_NAME_SUBSTRING = "OXIMETER"  # Holfenry JKS50CL advertises as "OXIMETER"

DEVICE_ADDRESS = "CB:31:33:32:1F:8F"  # Holfenry JKS50CL

NOTIFY_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

LISTEN_SECONDS = 60  # how long to wait for a reading before giving up

# Number of consecutive matching frames required before accepting as stable
STABLE_FRAMES_REQUIRED = 1

MAX_ATTEMPTS = 3


def _parse_oximeter_frame(data: bytearray):
    """
    Parse a raw BLE notification from the Holfenry JKS50CL.

    Known frame format (6+ bytes):
        byte 0-1: ff 44 (header)
        byte 4:   SpO2  (0-100 %)
        byte 5:   pulse (bpm)

    Returns dict with spo2/pulse, or None if the frame is not recognised.
    """
    if len(data) < 6:
        return None
    if data[0] != 0xFF or data[1] != 0x44:
        return None

    spo2 = data[4]
    pulse = data[5]

    # Ignore obviously invalid values (pulse=255 means no finger detected)
    if spo2 == 0 or pulse == 0 or pulse == 255 or spo2 > 100:
        return None

    return {"spo2": spo2, "pulse": pulse}


async def _find_device():
    """Scan and return the BLEDevice object (not just the address)."""
    if DEVICE_ADDRESS:
        # When address is hardcoded, still return a proper BLEDevice via a targeted scan
        device = await BleakScanner.find_device_by_address(DEVICE_ADDRESS, timeout=10.0)
        return device

    print(f"Scanning for '{TARGET_NAME_SUBSTRING}' ...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: d.name and TARGET_NAME_SUBSTRING.lower() in d.name.lower(),
        timeout=10.0,
    )
    if device:
        print(f"Found: {device.name}  ({device.address})")
    return device


async def get_reading():
    """Connect to the oximeter and return {"spo2": int, "pulse": int}, or None on failure."""
    print("Press the ON button on the oximeter and place your finger inside it.")
    device = await _find_device()
    if not device:
        print(
            f"Could not find the oximeter. "
            f"Make sure it is on your finger and advertising, then re-run.\n"
            f"(Looking for device name containing '{TARGET_NAME_SUBSTRING}')"
        )
        return None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            print(f"\nAttempt {attempt}/{MAX_ATTEMPTS} — place the oximeter firmly on your finger and keep still.")

        print(f"Connecting to {device.address} ...")
        try:
            done = asyncio.Event()
            disconnected = asyncio.Event()
            result = [None]
            loop = asyncio.get_running_loop()

            def on_disconnect(_client):
                if result[0] is None:
                    print("\nDisconnected. Place the oximeter on your finger and try again.")
                    loop.call_soon_threadsafe(disconnected.set)
                    loop.call_soon_threadsafe(done.set)

            async with BleakClient(device, timeout=20.0, disconnected_callback=on_disconnect) as client:
                print("Connected. Getting reading — keep the oximeter still on your finger.")

                stable_count = [0]
                last_reading = [None]

                def handler(_sender, data: bytearray):
                    if result[0] is not None:
                        return
                    reading = _parse_oximeter_frame(data)
                    if reading is None:
                        stable_count[0] = 0
                        last_reading[0] = None
                        return

                    if reading == last_reading[0]:
                        stable_count[0] += 1
                    else:
                        stable_count[0] = 1
                        last_reading[0] = reading

                    if stable_count[0] >= STABLE_FRAMES_REQUIRED:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        print(
                            f"[{ts}]  SpO2 = {reading['spo2']} %    "
                            f"Pulse = {reading['pulse']} bpm"
                        )
                        result[0] = {"spo2": reading["spo2"], "pulse": reading["pulse"]}
                        done.set()

                await client.start_notify(NOTIFY_CHAR_UUID, handler)
                try:
                    await asyncio.wait_for(done.wait(), timeout=LISTEN_SECONDS)
                except asyncio.TimeoutError:
                    print("Timed out. Make sure the oximeter is firmly on your finger.")
                    if not disconnected.is_set():
                        await client.stop_notify(NOTIFY_CHAR_UUID)
                    continue

                if result[0] is None:
                    continue

                await client.stop_notify(NOTIFY_CHAR_UUID)

        except Exception as e:
            print(f"Connection error: {e}")
            continue

        print("Done.")
        return result[0]

    print(f"\nFailed to get a reading after {MAX_ATTEMPTS} attempts.")
    return None


if __name__ == "__main__":
    asyncio.run(get_reading())
