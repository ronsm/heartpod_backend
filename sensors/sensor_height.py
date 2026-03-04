import asyncio
from bleak import BleakScanner, BleakClient

DEVICE_NAME = "ESP32-HeightSensor"
CHARACTERISTIC_UUID = "6E400003-B5B4-F393-E0A9-E50E24DCCA9E"

def notification_handler(sender, data):
    print(f"Height received: {data.decode('utf-8').strip()}")

async def main():
    print("Scanning for ESP32-HeightSensor...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)

    if device is None:
        print("Device not found")
        return

    print(f"Found: {device.address}")

    async with BleakClient(device) as client:
        print("Connected. Waiting for readings...")
        await client.start_notify(CHARACTERISTIC_UUID, notification_handler)
        await asyncio.sleep(3600)  # stay connected for 1 hour, adjust as needed

asyncio.run(main())