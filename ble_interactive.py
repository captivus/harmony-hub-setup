"""Interactive BLE exploration of Harmony Hub via gatttool + pexpect.

Keeps a persistent BLE connection so we can receive async notifications.
"""

import pexpect
import sys
import time

HARMONY_ADDR = "AA:BB:CC:DD:EE:FF"

HANDLE_WRITE_CMD = "0xfff6"
HANDLE_READ_NOTIFY = "0xfff8"
HANDLE_NOTIFY_ONLY = "0xfffb"
HANDLE_WRITE_2 = "0xfffe"
HANDLE_CCCD_READ_NOTIFY = "0xfff9"
HANDLE_CCCD_NOTIFY_ONLY = "0xfffc"


def hex_encode(text: str) -> str:
    return text.encode().hex()


def hex_decode_str(hex_str: str) -> str:
    clean = hex_str.replace(" ", "")
    try:
        return bytes.fromhex(clean).decode("utf-8", errors="replace")
    except ValueError:
        return f"<invalid hex>"


class HarmonyBLE:
    def __init__(self):
        self.gatt = None

    def connect(self):
        print("Launching gatttool interactive session...")
        self.gatt = pexpect.spawn(
            f"gatttool --device={HARMONY_ADDR} --addr-type=public --interactive",
            encoding="utf-8",
            timeout=15,
        )
        self.gatt.logfile = sys.stdout
        self.gatt.expect(r"\[LE\]>")
        print("\n--- Got prompt, connecting... ---")

        self.gatt.sendline("connect")
        idx = self.gatt.expect(
            [r"Connection successful", r"Error", pexpect.TIMEOUT],
            timeout=15,
        )
        if idx == 0:
            print("\n--- Connected! ---")
        else:
            print(f"\n--- Connection failed (idx={idx}) ---")
            sys.exit(1)

        time.sleep(1)

    def enable_notifications(self):
        print("\n--- Enabling notifications on both notify characteristics ---")
        for handle, name in [
            (HANDLE_CCCD_READ_NOTIFY, "read/notify"),
            (HANDLE_CCCD_NOTIFY_ONLY, "notify-only"),
        ]:
            self.gatt.sendline(f"char-write-req {handle} 0100")
            self.gatt.expect(r"written successfully|Error", timeout=10)
            print(f"\n  {name} CCCD: done")
            time.sleep(0.5)

    def write_and_listen(self, handle: str, value_hex: str, label: str, wait: float = 3.0):
        print(f"\n--- Writing to {handle}: {label} (hex: {value_hex}) ---")
        self.gatt.sendline(f"char-write-req {handle} {value_hex}")
        try:
            self.gatt.expect(
                [r"written successfully", r"Error"],
                timeout=5,
            )
        except pexpect.TIMEOUT:
            print("\n  Write timed out")
            return

        print(f"\n  Write OK. Listening for notifications ({wait}s)...")
        start = time.time()
        while time.time() - start < wait:
            try:
                idx = self.gatt.expect(
                    [r"Notification handle = (0x[0-9a-f]+) value: (.+)", pexpect.TIMEOUT],
                    timeout=1,
                )
                if idx == 0:
                    handle_str = self.gatt.match.group(1)
                    value = self.gatt.match.group(2).strip()
                    decoded = hex_decode_str(value)
                    print(f"\n  >>> NOTIFICATION on {handle_str}: hex=[{value}]")
                    print(f"  >>> decoded: {decoded!r}")
            except pexpect.TIMEOUT:
                pass

    def read_char(self, handle: str, label: str):
        print(f"\n--- Reading {handle} ({label}) ---")
        self.gatt.sendline(f"char-read-hnd {handle}")
        try:
            self.gatt.expect(r"Characteristic value/descriptor: (.*)", timeout=5)
            value = self.gatt.match.group(1).strip()
            decoded = hex_decode_str(value) if value else "<empty>"
            print(f"\n  hex=[{value}] decoded={decoded!r}")
        except pexpect.TIMEOUT:
            print("\n  Read timed out")

    def disconnect(self):
        if self.gatt:
            self.gatt.sendline("disconnect")
            self.gatt.sendline("exit")
            self.gatt.close()


def main():
    hub = HarmonyBLE()

    try:
        hub.connect()
        hub.enable_notifications()

        # Read current state
        hub.read_char(HANDLE_READ_NOTIFY, "response char")

        # Probe: single null byte
        hub.write_and_listen(HANDLE_WRITE_CMD, "00", "null byte")

        # Probe: 0x01 (potential "hello" or init command)
        hub.write_and_listen(HANDLE_WRITE_CMD, "01", "0x01")

        # Probe: typical BLE serial framing - STX + command
        hub.write_and_listen(HANDLE_WRITE_CMD, "0200", "STX + 0x00")

        # Probe: ASCII "discovery"
        hub.write_and_listen(HANDLE_WRITE_CMD, hex_encode("discovery"), "ASCII 'discovery'")

        # Probe: JSON command
        hub.write_and_listen(
            HANDLE_WRITE_CMD,
            hex_encode('{"cmd":"get_setup_info"}'),
            "JSON get_setup_info",
        )

        # Probe: Harmony-style XMPP-like query
        hub.write_and_listen(
            HANDLE_WRITE_CMD,
            hex_encode("connect.discoveryinfo?get"),
            "Harmony discovery query",
        )

        # Probe second write char with different lengths
        for length in [2, 4, 8, 16, 20]:
            value = "00" * length
            hub.write_and_listen(
                HANDLE_WRITE_2, value,
                f"write2: {length} zero bytes",
                wait=1.0,
            )

        # Final read of response char
        hub.read_char(HANDLE_READ_NOTIFY, "final response check")

    finally:
        hub.disconnect()

    print("\n\nDone.")


if __name__ == "__main__":
    main()
