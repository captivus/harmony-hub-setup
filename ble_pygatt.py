"""Harmony Hub BLE communication using pygatt (proper notification handling)."""

import time
import pygatt

ADDR = "AA:BB:CC:DD:EE:FF"

UUID_WRITE_CMD = "7e220100-04c0-4909-bd23-665c48550a83"
UUID_READ_NOTIFY = "7e220101-04c0-4909-bd23-665c48550a83"
UUID_NOTIFY_ONLY = "7e220102-04c0-4909-bd23-665c48550a83"
UUID_WRITE_2 = "7e220103-04c0-4909-bd23-665c48550a83"

notification_log: list[tuple[float, str, bytes]] = []
start_time = time.time()


def notification_callback(handle: int, value: bytes):
    elapsed = time.time() - start_time
    notification_log.append((elapsed, f"0x{handle:04x}", value))
    try:
        text = value.decode("utf-8", errors="replace")
    except Exception:
        text = "<binary>"
    print(f"  [{elapsed:.1f}s] NOTIFICATION handle=0x{handle:04x} "
          f"len={len(value)} hex={value.hex(' ')} text={text!r}")


def hex_encode(text: str) -> str:
    return bytearray(text.encode())


def main():
    adapter = pygatt.GATTToolBackend()
    adapter.start()

    try:
        print(f"Connecting to {ADDR}...")
        device = adapter.connect(
            ADDR,
            address_type=pygatt.BLEAddressType.public,
            timeout=15,
        )
        print("Connected!")

        # Subscribe to notifications on both notify characteristics
        print("\nSubscribing to notifications...")
        device.subscribe(UUID_READ_NOTIFY, callback=notification_callback)
        print("  Subscribed to read/notify char")
        device.subscribe(UUID_NOTIFY_ONLY, callback=notification_callback)
        print("  Subscribed to notify-only char")

        # Wait a moment for any unsolicited notifications
        print("\nWaiting 5s for unsolicited notifications...")
        time.sleep(5)

        if notification_log:
            print(f"  Got {len(notification_log)} unsolicited notification(s)!")
        else:
            print("  No unsolicited notifications.")

        # Now send probes
        probes = [
            ("null byte", UUID_WRITE_CMD, b"\x00"),
            ("0x01", UUID_WRITE_CMD, b"\x01"),
            ("ASCII 'hello'", UUID_WRITE_CMD, b"hello"),
            ("ASCII 'discovery'", UUID_WRITE_CMD, b"discovery"),
            ("JSON get_setup_info", UUID_WRITE_CMD, b'{"cmd":"get_setup_info"}'),
            ("connect.discoveryinfo?get", UUID_WRITE_CMD, b"connect.discoveryinfo?get"),
            ("write2: 01000000", UUID_WRITE_2, b"\x01\x00\x00\x00"),
            ("write2: then write1 hello", UUID_WRITE_CMD, b"hello"),
        ]

        for label, uuid, data in probes:
            before_count = len(notification_log)
            print(f"\n--- {label} (to {uuid[-8:]}) ---")
            print(f"  Sending: {data.hex(' ')}")
            try:
                device.char_write(uuid, data, wait_for_response=True)
                print("  Write OK (with response)")
            except Exception as exc:
                print(f"  Write error: {exc}")
                try:
                    device.char_write(uuid, data, wait_for_response=False)
                    print("  Retry without response: OK")
                except Exception as exc2:
                    print(f"  Retry failed: {exc2}")
                    continue

            # Wait for notification response
            time.sleep(3)

            new_count = len(notification_log) - before_count
            if new_count > 0:
                print(f"  Got {new_count} notification(s) in response!")
                # Try to assemble the full response
                recent = notification_log[-new_count:]
                full_payload = b""
                for _, _, val in recent:
                    full_payload += val
                print(f"  Full response ({len(full_payload)} bytes):")
                print(f"    hex: {full_payload.hex(' ')}")
                try:
                    print(f"    txt: {full_payload.decode('utf-8', errors='replace')!r}")
                except Exception:
                    pass
            else:
                print("  No notification response.")

        # Final: try writing to both in rapid succession
        print("\n\n=== Rapid dual-write: write2 + write1 ===")
        before_count = len(notification_log)
        device.char_write(UUID_WRITE_2, b"\x01\x00\x00\x00", wait_for_response=False)
        device.char_write(UUID_WRITE_CMD, b"hello", wait_for_response=False)
        time.sleep(5)
        new_count = len(notification_log) - before_count
        print(f"  Got {new_count} notification(s)")

        # Summary
        print(f"\n\n=== SUMMARY ===")
        print(f"Total notifications received: {len(notification_log)}")
        for elapsed, handle, value in notification_log:
            print(f"  [{elapsed:.1f}s] {handle}: {value.hex(' ')} "
                  f"= {value.decode('utf-8', errors='replace')!r}")

    finally:
        adapter.stop()

    print("\nDone.")


if __name__ == "__main__":
    main()
