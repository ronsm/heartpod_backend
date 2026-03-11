import asyncio

from bleak import BleakClient, BleakScanner


DEVICE_NAME = "ESP32-HeightSensor"

DEVICE_ADDRESS = None  # set to MAC address to skip scanning, e.g. "AA:BB:CC:DD:EE:FF"

CHARACTERISTIC_UUID = "6E400003-B5B4-F393-E0A9-E50E24DCCA9E"

LISTEN_SECONDS = 60

MAX_ATTEMPTS = 3


async def _find_device():
    if DEVICE_ADDRESS:
        device = await BleakScanner.find_device_by_address(DEVICE_ADDRESS, timeout=10.0)
        return device

    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=30.0)
    return device


async def get_reading():
    """Connect to the ESP32 height sensor and return height in metres, or None on failure."""
    print("Stand under the height sensor and stay still.")

    device = await _find_device()
    if not device:
        print(
            f"Could not find {DEVICE_NAME!r}. "
            f"Make sure the sensor is powered on and in range."
        )
        return None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            print(f"\nAttempt {attempt}/{MAX_ATTEMPTS} — stand still under the sensor.")

        print(f"Connecting to {device.address} ...")
        try:
            done = asyncio.Event()
            disconnected = asyncio.Event()
            result: list = [None]
            loop = asyncio.get_running_loop()

            def on_disconnect(_client):
                if result[0] is None:
                    print("\nDisconnected from height sensor.")
                    loop.call_soon_threadsafe(disconnected.set)
                    loop.call_soon_threadsafe(done.set)

            async with BleakClient(device, timeout=30.0, disconnected_callback=on_disconnect) as client:
                print("Connected. Please stand still under the sensor.")

                def handler(_sender, data: bytearray):
                    if result[0] is not None:
                        return
                    try:
                        height_mm = int(data.decode("utf-8").strip())
                        height_m = round(height_mm / 1000.0, 2)
                        print(f"Height reading: {height_m} m ({height_mm} mm)")
                        result[0] = height_m
                        loop.call_soon_threadsafe(done.set)
                    except (ValueError, UnicodeDecodeError):
                        pass

                await client.start_notify(CHARACTERISTIC_UUID, handler)
                try:
                    await asyncio.wait_for(done.wait(), timeout=LISTEN_SECONDS)
                except asyncio.TimeoutError:
                    print("Timed out waiting for a height reading.")
                    if not disconnected.is_set():
                        await client.stop_notify(CHARACTERISTIC_UUID)
                    continue

                if result[0] is None:
                    continue

                if not disconnected.is_set():
                    await client.stop_notify(CHARACTERISTIC_UUID)

        except Exception as e:
            print(f"Connection error: {e}")
            continue

        print("Done.")
        return result[0]

    print(f"\nFailed to get a reading after {MAX_ATTEMPTS} attempts.")
    return None


if __name__ == "__main__":
    asyncio.run(get_reading())
