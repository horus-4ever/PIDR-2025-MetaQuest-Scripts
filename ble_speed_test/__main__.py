import asyncio
from bleak import BleakClient, BleakScanner
from bleak.backends.scanner import AdvertisementData, BLEDevice
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from abc import abstractmethod
from struct import unpack
import matplotlib.pyplot as plt
import time
import numpy as np

# Define UUIDs and target device name
SERVICE_UUID = "19B10000-E8F2-537E-4F6C-D104768A1214"
CHARACTERISTIC_UUIDS = {
    "time": "19B10001-E8F2-537E-4F6C-D104768A1214",
}
TARGET_NAME = "MonArduinoBLE"

last_time = time.time_ns()
first_time = True
times = []


class Characteristic:
    @classmethod
    @abstractmethod
    def read_from(cls, data: bytearray) -> object:
        raise NotImplementedError("Not implemented")
    

class TimeCharacteristic(Characteristic):
    def __init__(self, time: int):
        self.time = time

    @classmethod
    def read_from(cls, data: bytearray) -> "TimeCharacteristic":
        time = unpack("<L", data)
        return cls(time)
    
    def __repr__(self):
        return f"(time: {self.time})"
    

class BLEManager:
    """
    A class to manage BLE operations such as scanning, connecting,
    and handling notifications for multiple characteristics.
    """
    def __init__(self, target_name: str, service_uuid: str, characteristic_uuids: dict):
        self.target_name = target_name
        self.service_uuid = service_uuid
        self.characteristic_uuids = characteristic_uuids
        self.device: BLEDevice | None = None
        self.client: BleakClient | None = None

    async def scan_for_device(self, timeout: float = 10.0) -> bool:
        """
        Scan for a BLE device matching the target name.
        """
        queue = asyncio.Queue()

        def detection_callback(device: BLEDevice, adv_data: AdvertisementData):
            if device.name == self.target_name:
                print(f"Found device: {device.name} ({device.address})")
                queue.put_nowait(device)

        print("Scanning for BLE devices...")
        async with BleakScanner(detection_callback):
            try:
                self.device = await asyncio.wait_for(queue.get(), timeout=timeout)
                print("Device successfully found.")
                return True
            except asyncio.TimeoutError:
                print("Device not found within the timeout period.")
                return False

    async def connect(self) -> bool:
        """
        Connect to the discovered BLE device and validate all characteristics.
        """
        if self.device is None:
            print("No device available to connect to.")
            return False

        self.client = BleakClient(self.device)
        try:
            await self.client.connect()
            print(f"Connected to {self.device.address}")

            # Validate that the desired characteristics are available
            services: BleakGATTServiceCollection = self.client.services
            for label, uuid in self.characteristic_uuids.items():
                if services.get_characteristic(uuid) is None:
                    print(f"Characteristic for {label} ({uuid}) not found in the device services.")
                    await self.client.disconnect()
                    return False

            print("✅ All required characteristics are available.")
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False

    async def start_notifications(self, callback):
        """
        Start notifications on each of the specified characteristics.
        The callback receives (measurement_type, sender, data).
        """
        for measurement, uuid in self.characteristic_uuids.items():
            async def __inner(sender, data, mtype=measurement):
                await callback(mtype, sender, data)
            await self.client.start_notify(uuid, __inner)
            print(f"Notification for {measurement} started.")

    async def stop_notifications(self):
        """
        Stop notifications on all the specified characteristics.
        """
        for uuid in self.characteristic_uuids.values():
            if self.client and self.client.is_connected:
                await self.client.stop_notify(uuid)
                print(f"Notification for {uuid} stopped.")

    async def disconnect(self):
        """
        Disconnect from the BLE device.
        """
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("Disconnected from the device.")

    async def run(self, notification_callback):
        """
        High-level method to run the complete BLE process: scanning, connecting,
        subscribing to notifications, and handling messages.
        """
        if not await self.scan_for_device():
            return

        if not await self.connect():
            return

        await self.start_notifications(notification_callback)

        print("Listening for BLE messages... Press Ctrl+C to exit.")
        try:
            while True:
                await asyncio.sleep(1)  # Keep the event loop running
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\nShutdown signal received. Exiting...")
        finally:
            await self.stop_notifications()
            await self.disconnect()

async def notification_handler(measurement_type: str, sender: int, data: bytearray):
    """
    Callback function triggered when sensor data is received.
    """
    global times, last_time, first_time
    if first_time:
        last_time = time.time_ns()
        first_time = False
    result = None
    match measurement_type:
        case "time":
            result = TimeCharacteristic.read_from(data)
        case _:
            raise Exception("Unreachable")
    current_time = time.time_ns()
    times.append((current_time - last_time) / 10**6)
    last_time = current_time

async def main():
    # Initialize BLEManager with the target name, service, and characteristic UUIDs.
    ble_manager = BLEManager(TARGET_NAME, SERVICE_UUID, CHARACTERISTIC_UUIDS)
    await ble_manager.run(notification_handler)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program terminated by user.")

    result = np.array(times)
    nb_more_16 = len(result[result > 32])
    print(f"-> Percentage > 32: {nb_more_16 / len(times) * 100}")
    print(f"-> Mean time: {np.mean(times)}")
    print(f"-> Median time: {np.median(times)}")

    xmin = 0   # Minimum value on x-axis
    xmax = round(np.max(times)) # Maximum value on x-axis
    interval = 1  # Bin width
    # Create bins with numpy.arange()
    bins = np.arange(xmin, xmax + interval, interval)
    plt.hist(times, bins=bins)
    plt.xlabel("time (ms)")
    plt.ylabel("number of packets")
    plt.title("Transmission time distribution")
    plt.show()
