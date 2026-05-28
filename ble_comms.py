"""Communicate with the Harmony Hub over BLE.

The hub responds via notifications on handle 0xfff8.
Response format: [0x80, 0x00] + JSON payload, split across BLE MTU-sized chunks.
The first write to 0xfff6 seems to trigger a response.
"""

import pexpect
import re
import sys
import time

ADDR = "AA:BB:CC:DD:EE:FF"
HANDLE_WRITE_CMD = "0xfff6"
HANDLE_READ_NOTIFY = "0xfff8"
HANDLE_WRITE_2 = "0xfffe"
HANDLE_CCCD_READ_NOTIFY = "0xfff9"
HANDLE_CCCD_NOTIFY_ONLY = "0xfffc"

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9]+[hl]|\x1b\[K")
NOTIF_RE = re.compile(r"Notification handle = (0x[0-9a-f]+) value: ([0-9a-f ]+)")


def hex_encode(text: str) -> str:
    return text.encode().hex()


def hex_to_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str.replace(" ", ""))


class HarmonyBLE:
    def __init__(self):
        self.child = None
        self.notification_buffer = []

    def connect(self):
        self.child = pexpect.spawn(
            f"gatttool --device={ADDR} --addr-type=public --interactive",
            encoding="utf-8", timeout=15,
        )
        self.child.expect(r"\[LE\]>")
        self.child.sendline("connect")
        time.sleep(4)

        # Enable notifications
        self.child.sendline(f"char-write-req {HANDLE_CCCD_READ_NOTIFY} 0100")
        time.sleep(0.5)
        self.child.sendline(f"char-write-req {HANDLE_CCCD_NOTIFY_ONLY} 0100")
        time.sleep(0.5)

        # Drain
        self._drain()
        print("Connected and notifications enabled.")

    def _drain(self):
        try:
            self.child.read_nonblocking(size=16384, timeout=1)
        except pexpect.TIMEOUT:
            pass

    def _collect_notifications(self, seconds: float) -> list[tuple[str, bytes]]:
        """Collect notifications for a given duration."""
        notifications = []
        start = time.time()
        while time.time() - start < seconds:
            try:
                raw = self.child.read_nonblocking(size=8192, timeout=0.5)
                clean = ANSI.sub("", raw)
                for match in NOTIF_RE.finditer(clean):
                    handle = match.group(1)
                    value_hex = match.group(2).strip()
                    value_bytes = hex_to_bytes(value_hex)
                    notifications.append((handle, value_bytes))
            except pexpect.TIMEOUT:
                pass
        return notifications

    def write_and_receive(
        self, handle: str, value_hex: str, label: str, wait: float = 5.0,
    ) -> list[tuple[str, bytes]]:
        """Write a value and collect notification responses."""
        self._drain()
        print(f"\n--- {label} ---")
        print(f"  Writing to {handle}: {value_hex}")

        self.child.sendline(f"char-write-req {handle} {value_hex}")
        time.sleep(0.3)

        notifications = self._collect_notifications(seconds=wait)

        if notifications:
            print(f"  Got {len(notifications)} notification(s):")
            full_payload = b""
            for notif_handle, data in notifications:
                print(f"    [{notif_handle}] hex: {data.hex(' ')}")
                # First notification has 2-byte header, subsequent ones might be continuations
                if data[:2] == b"\x80\x00":
                    full_payload += data[2:]
                elif data[0:1] == b"\x80":
                    full_payload += data[1:]
                else:
                    full_payload += data
            try:
                text = full_payload.decode("utf-8", errors="replace")
                print(f"  Decoded payload: {text}")
            except Exception:
                print(f"  Raw payload: {full_payload.hex(' ')}")
        else:
            print(f"  No notifications received in {wait}s")

        return notifications

    def close(self):
        if self.child:
            try:
                self.child.sendline("disconnect")
                self.child.sendline("exit")
                self.child.close()
            except Exception:
                pass


def main():
    hub = HarmonyBLE()
    hub.connect()

    # The previous test showed "hello" on 0xfff6 triggered a response.
    # Let's repeat it and collect the full response.
    hub.write_and_receive(
        handle=HANDLE_WRITE_CMD,
        value_hex=hex_encode("hello"),
        label="Repeat: ASCII 'hello' to write1",
        wait=8.0,
    )

    # Try different commands to see what responses we get
    commands = [
        ("empty byte", "00"),
        ("single 0x01", "01"),
        ("ASCII 'discovery'", hex_encode("discovery")),
        ("ASCII 'setup'", hex_encode("setup")),
        ("ASCII 'pair'", hex_encode("pair")),
        ("Harmony query: connect.discoveryinfo?get",
         hex_encode("connect.discoveryinfo?get")),
        ("JSON: get_setup_info",
         hex_encode('{"cmd":"get_setup_info"}')),
        ("JSON: get_current_state",
         hex_encode('{"cmd":"get_current_state"}')),
        ("Harmony: setup.account?getProvisionInfo",
         hex_encode("setup.account?getProvisionInfo")),
        ("JSON: wifi scan request",
         hex_encode('{"cmd":"wifi_scan"}')),
    ]

    for label, value_hex in commands:
        hub.write_and_receive(
            handle=HANDLE_WRITE_CMD,
            value_hex=value_hex,
            label=label,
            wait=5.0,
        )

    # Also try writing to write2 first, then write1
    print("\n\n=== Sequence: write2 init + write1 command ===")
    hub.write_and_receive(
        handle=HANDLE_WRITE_2,
        value_hex="01000000",
        label="Write2: init command",
        wait=3.0,
    )
    hub.write_and_receive(
        handle=HANDLE_WRITE_CMD,
        value_hex=hex_encode("hello"),
        label="Write1: hello (after write2 init)",
        wait=5.0,
    )

    hub.close()
    print("\n\nDone.")


if __name__ == "__main__":
    main()
