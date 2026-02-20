import asyncio
import struct
from datetime import datetime

from bleak import BleakClient, BleakScanner


DEVICE_ADDRESS = "F0:A1:62:ED:E6:A9"

BP_MEASUREMENT_CHAR_UUID = "00002a35-0000-1000-8000-00805f9b34fb"
CURRENT_TIME_CHAR_UUID   = "00002a2b-0000-1000-8000-00805f9b34fb"
OMRON_WRITE_CHAR_UUID    = "db5b55e0-aee7-11e1-965e-0002a5d5c51b"

MAX_ATTEMPTS = 3


def sfloat_to_float(sfloat_val):
    exponent = sfloat_val >> 12
    mantissa = sfloat_val & 0x0FFF
    if exponent >= 8: exponent = -((0x000F + 1) - exponent)
    if mantissa >= 2048: mantissa = -((0x0FFF + 1) - mantissa)
    return mantissa * (10 ** exponent)


async def get_reading():
    """Connect to the Omron BP monitor and return {"systolic": float, "diastolic": float}, or None on failure."""
    print("Press the BT button on the blood pressure monitor to start a reading.")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            print(f"\nAttempt {attempt}/{MAX_ATTEMPTS} — press the BT button on the monitor.")
            await asyncio.sleep(6)

        print("Searching for Omron BP monitor...")
        device = await BleakScanner.find_device_by_address(DEVICE_ADDRESS, timeout=60.0)
        if not device:
            print("Device not found. Press the BT button on the monitor and try again.")
            continue

        print(f"Found {device.name}. Connecting...")
        try:
            done = asyncio.Event()
            disconnected = asyncio.Event()
            result = [None]
            connected = [False]
            loop = asyncio.get_running_loop()

            def on_disconnect(_client):
                if connected[0] and result[0] is None:
                    print("\nDisconnected. Press the BT button on the monitor and try again.")
                    loop.call_soon_threadsafe(disconnected.set)
                    loop.call_soon_threadsafe(done.set)

            async with BleakClient(device, timeout=20.0, disconnected_callback=on_disconnect) as client:
                connected[0] = True
                print("Connected. Sending handshake...")

                def handler(_sender, data: bytearray):
                    if result[0] is not None:
                        return
                    systolic  = round(sfloat_to_float(int.from_bytes(data[1:3], "little")), 1)
                    diastolic = round(sfloat_to_float(int.from_bytes(data[3:5], "little")), 1)
                    print(f"  Systolic={systolic}, Diastolic={diastolic} mmHg")
                    result[0] = {"systolic": systolic, "diastolic": diastolic}
                    done.set()

                await client.start_notify(BP_MEASUREMENT_CHAR_UUID, handler)

                now = datetime.now()
                time_payload = struct.pack(
                    '<HBBBBBBBB',
                    now.year, now.month, now.day,
                    now.hour, now.minute, now.second,
                    now.weekday() + 1, 0, 0
                )
                await client.write_gatt_char(CURRENT_TIME_CHAR_UUID, time_payload)
                await client.write_gatt_char(OMRON_WRITE_CHAR_UUID, b'\x01\x00', response=True)

                print("Waiting for reading...")
                try:
                    await asyncio.wait_for(done.wait(), timeout=60)
                except asyncio.TimeoutError:
                    print("Timed out waiting for a reading.")
                    if not disconnected.is_set():
                        await client.stop_notify(BP_MEASUREMENT_CHAR_UUID)
                    continue

                if result[0] is None:
                    continue

                await client.stop_notify(BP_MEASUREMENT_CHAR_UUID)

        except Exception as e:
            print(f"Connection error: {e}")
            continue

        print("Done.")
        return result[0]

    print(f"\nFailed to get a reading after {MAX_ATTEMPTS} attempts.")
    return None


if __name__ == "__main__":
    try:
        asyncio.run(get_reading())
    except KeyboardInterrupt:
        pass
