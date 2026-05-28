"""Explore Harmony Hub BLE GATT services and characteristics."""

import asyncio
import sys
from bleak import BleakClient, BleakScanner

HARMONY_ADDR = "AA:BB:CC:DD:EE:FF"

VENDOR_SVC = "7e220000-04c0-4909-bd23-665c48550a83"
CHAR_WRITE_CMD = "7e220100-04c0-4909-bd23-665c48550a83"
CHAR_READ_NOTIFY = "7e220101-04c0-4909-bd23-665c48550a83"
CHAR_NOTIFY_ONLY = "7e220102-04c0-4909-bd23-665c48550a83"
CHAR_WRITE_2 = "7e220103-04c0-4909-bd23-665c48550a83"


def notification_handler(characteristic, data: bytearray):
    hex_str = data.hex(" ")
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = "<not utf-8>"
    print(f"  NOTIFY [{characteristic.uuid}]: hex={hex_str}")
    print(f"  NOTIFY [{characteristic.uuid}]: txt={text!r}")


async def main():
    print(f"Scanning for {HARMONY_ADDR} (LE only)...")
    device = await BleakScanner.find_device_by_address(
        device_identifier=HARMONY_ADDR,
        timeout=10.0,
        scanning_mode="active",
    )
    if not device:
        print("ERROR: Device not found")
        sys.exit(1)

    print(f"Found: {device.name} ({device.address})")
    print(f"  Details: {device.details}")

    async with BleakClient(device, timeout=20.0) as client:
        print(f"Connected: {client.is_connected}")
        print(f"MTU: {client.mtu_size}")

        print("\n=== All Services and Characteristics ===")
        for svc in client.services:
            print(f"\nService: {svc.uuid} [{svc.description}]")
            for char in svc.characteristics:
                props = ", ".join(char.properties)
                print(f"  Char: {char.uuid} | handle=0x{char.handle:04x} | {props}")
                for desc in char.descriptors:
                    desc_val = await client.read_gatt_descriptor(desc.handle)
                    print(f"    Desc: {desc.uuid} | handle=0x{desc.handle:04x} | val={desc_val.hex(' ')}")

        print("\n=== Reading readable characteristics ===")
        for svc in client.services:
            for char in svc.characteristics:
                if "read" in char.properties:
                    try:
                        val = await client.read_gatt_char(char)
                        hex_str = val.hex(" ")
                        try:
                            text = val.decode("utf-8", errors="replace")
                        except Exception:
                            text = "<binary>"
                        print(f"  {char.uuid}: hex={hex_str} txt={text!r}")
                    except Exception as exc:
                        print(f"  {char.uuid}: ERROR {exc}")

        print("\n=== Subscribing to notifications ===")
        for svc in client.services:
            for char in svc.characteristics:
                if "notify" in char.properties:
                    print(f"  Subscribing to {char.uuid}...")
                    await client.start_notify(char, notification_handler)

        print("\n=== Sending probe: empty byte ===")
        try:
            await client.write_gatt_char(CHAR_WRITE_CMD, b"\x00", response=True)
            print("  Write succeeded (with response)")
        except Exception as exc:
            print(f"  Write failed: {exc}")

        await asyncio.sleep(2)

        print("\n=== Sending probe: 'GetDeviceName' as ASCII ===")
        try:
            await client.write_gatt_char(
                CHAR_WRITE_CMD,
                b"GetDeviceName",
                response=True,
            )
            print("  Write succeeded")
        except Exception as exc:
            print(f"  Write failed: {exc}")

        await asyncio.sleep(2)

        print("\n=== Sending probe: Harmony-style query ===")
        try:
            await client.write_gatt_char(
                CHAR_WRITE_CMD,
                b'{"cmd":"get_setup_info"}',
                response=True,
            )
            print("  Write succeeded")
        except Exception as exc:
            print(f"  Write failed: {exc}")

        await asyncio.sleep(2)

        print("\n=== Reading response characteristic after probes ===")
        try:
            val = await client.read_gatt_char(CHAR_READ_NOTIFY)
            print(f"  hex={val.hex(' ')}")
            print(f"  txt={val.decode('utf-8', errors='replace')!r}")
        except Exception as exc:
            print(f"  ERROR: {exc}")

        print("\nWaiting 5 seconds for any delayed notifications...")
        await asyncio.sleep(5)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
