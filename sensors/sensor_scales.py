import asyncio

from datetime import datetime

from bleak import BleakClient, BleakScanner


TARGET_NAME_SUBSTRING = "Vitafit Body Fat"

DEVICE_ADDRESS = "ED:67:3B:48:AA:68"  # set to None to find by name


CHAR_FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"


LISTEN_SECONDS = 180

MAX_ATTEMPTS = 3


def _parse_vitafit_frame(hexstr: str):
    b = bytes.fromhex(hexstr)

    # minimal framing checks
    if len(b) < 6 or b[0] != 0x5A:
        return None

    length = b[1]  # appears to be payload length-ish (you saw 0x0A and 0x0B)
    cmd1, cmd2 = b[2], b[3]  # 0x26 0x10 or 0x26 0x11 in your captures

    # Weight frame: 5A 0A 26 10 ... ... ... ... WW WW .. ..
    if len(b) == 12 and cmd1 == 0x26 and cmd2 == 0x10:
        # bytes 8..9 are weight*100, big-endian (matches 0x1B49 -> 6985 -> 69.85 kg)
        w_raw = int.from_bytes(b[8:10], "big")
        kg = w_raw / 100.0
        stable = b[4] == 0x02  # 0x00=starting, 0x01=measuring, 0x02=final stable
        return {"type": "weight", "kg": kg, "raw": w_raw, "len": len(b), "length": length, "stable": stable}

    # Status/other frame: 5A 0B 26 11 ...
    if cmd1 == 0x26 and cmd2 == 0x11:
        return {"type": "status", "len": len(b), "length": length}

    return {"type": "other", "cmd": f"{cmd1:02x}{cmd2:02x}", "len": len(b), "length": length}


async def _find_device():
    if DEVICE_ADDRESS:
        device = await BleakScanner.find_device_by_address(DEVICE_ADDRESS, timeout=30.0)
        return device.address if device else None

    devices = await BleakScanner.discover(timeout=10.0)
    for d in devices:
        if d.name and TARGET_NAME_SUBSTRING.lower() in d.name.lower():
            return d.address

    return None


async def get_reading():
    """Connect to the Vitafit scale and return the weight in kg, or None on failure."""
    print("Step on the scale to turn it on, then stay on until a reading is obtained.")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            print(f"\nAttempt {attempt}/{MAX_ATTEMPTS} — step on the scale to turn it on.")

        print("Waiting for scale to turn on...")
        addr = await _find_device()
        if not addr:
            print("Could not find the Vitafit scale. Make sure it is on and try again.")
            continue

        print(f"Connecting to {addr} ...")
        try:
            done = asyncio.Event()
            disconnected = asyncio.Event()
            result = [None]
            connected = [False]
            loop = asyncio.get_running_loop()

            def on_disconnect(_client):
                if connected[0] and result[0] is None:
                    print("\nDisconnected. Please step on the scale.")
                    loop.call_soon_threadsafe(disconnected.set)
                    loop.call_soon_threadsafe(done.set)

            async with BleakClient(addr, timeout=20.0, disconnected_callback=on_disconnect) as client:
                connected[0] = True
                print("Connected. Stay still on the scale.")

                def handler(_sender, data: bytearray):
                    if result[0] is not None:
                        return
                    hexstr = bytes(data).hex()
                    decoded = _parse_vitafit_frame(hexstr)
                    if decoded and decoded.get("type") == "weight" and decoded.get("stable"):
                        kg = decoded["kg"]
                        print(f"Final Reading = {kg:.2f} kg")
                        result[0] = kg
                        done.set()

                await client.start_notify(CHAR_FFF1, handler)
                try:
                    await asyncio.wait_for(done.wait(), timeout=LISTEN_SECONDS)
                except asyncio.TimeoutError:
                    print("Timed out waiting for a stable reading.")
                    if not disconnected.is_set():
                        await client.stop_notify(CHAR_FFF1)
                    continue

                if result[0] is None:
                    continue

                await client.stop_notify(CHAR_FFF1)

        except Exception as e:
            print(f"Connection error: {e}")
            continue

        print("Done.")
        return result[0]

    print(f"\nFailed to get a reading after {MAX_ATTEMPTS} attempts.")
    return None


if __name__ == "__main__":
    asyncio.run(get_reading())
