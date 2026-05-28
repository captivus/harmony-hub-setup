"""BLE probe with pairing and clean ANSI stripping."""

import pexpect
import re
import sys
import time

HARMONY_ADDR = "AA:BB:CC:DD:EE:FF"
HANDLE_WRITE_CMD = "0xfff6"
HANDLE_READ_NOTIFY = "0xfff8"
HANDLE_CCCD_READ_NOTIFY = "0xfff9"
HANDLE_CCCD_NOTIFY_ONLY = "0xfffc"

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9]+[hl]|\x1b\[K")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def hex_encode(text: str) -> str:
    return text.encode().hex()


def hex_decode(hex_str: str) -> str:
    clean = hex_str.strip().replace(" ", "")
    if not clean:
        return "<empty>"
    try:
        return bytes.fromhex(clean).decode("utf-8", errors="replace")
    except ValueError:
        return f"<hex: {hex_str}>"


class GattSession:
    def __init__(self, sec_level: str = "low"):
        self.sec_level = sec_level
        self.child = None
        self.buffer = []

    def start(self):
        cmd = (
            f"gatttool --device={HARMONY_ADDR} --addr-type=public "
            f"--sec-level={self.sec_level} --interactive"
        )
        print(f"Launching: {cmd}")
        self.child = pexpect.spawn(cmd, encoding="utf-8", timeout=15)
        self.child.expect(r"\[LE\]>")
        print("Got prompt.")

    def send(self, command: str) -> str:
        self.child.sendline(command)
        time.sleep(0.3)
        # Read all available output
        try:
            self.child.expect(r"\[LE\]>", timeout=5)
        except pexpect.TIMEOUT:
            pass
        raw = self.child.before or ""
        clean = strip_ansi(raw).strip()
        return clean

    def collect_output(self, seconds: float) -> str:
        """Collect all output for a duration, looking for notifications."""
        collected = []
        start = time.time()
        while time.time() - start < seconds:
            try:
                self.child.expect(r".+", timeout=0.5)
                raw = self.child.match.group(0)
                clean = strip_ansi(raw).strip()
                if clean:
                    collected.append(clean)
            except pexpect.TIMEOUT:
                pass
        return "\n".join(collected)

    def close(self):
        if self.child:
            try:
                self.child.sendline("disconnect")
                time.sleep(0.5)
                self.child.sendline("exit")
                self.child.close()
            except Exception:
                pass


def probe_with_security(sec_level: str):
    print(f"\n{'='*60}")
    print(f"  Probing with security level: {sec_level}")
    print(f"{'='*60}")

    gatt = GattSession(sec_level=sec_level)
    try:
        gatt.start()

        # Connect
        print("\n--- Connecting ---")
        result = gatt.send("connect")
        print(f"  {result}")

        if "successful" not in result.lower():
            time.sleep(2)
            result = gatt.collect_output(3)
            print(f"  (delayed): {result}")
            if "successful" not in result.lower():
                print("  FAILED to connect")
                return

        time.sleep(1)

        # Enable notifications
        print("\n--- Enabling notifications ---")
        result = gatt.send(f"char-write-req {HANDLE_CCCD_READ_NOTIFY} 0100")
        print(f"  CCCD 1: {result}")
        result = gatt.send(f"char-write-req {HANDLE_CCCD_NOTIFY_ONLY} 0100")
        print(f"  CCCD 2: {result}")

        # Read response char baseline
        print("\n--- Baseline read of response char ---")
        result = gatt.send(f"char-read-hnd {HANDLE_READ_NOTIFY}")
        print(f"  {result}")

        # Write probes and collect ALL output
        probes = [
            ("null byte", "00"),
            ("0x01", "01"),
            ("ASCII 'pair'", hex_encode("pair")),
            ("ASCII 'setup'", hex_encode("setup")),
            ("ASCII 'hello'", hex_encode("hello")),
            ("Harmony XMPP mime", hex_encode("connect.discoveryinfo?get")),
            ("JSON cmd", hex_encode('{"cmd":"setup","params":{}}')),
            ("length-prefixed test", "0005" + hex_encode("hello")),
            ("TLV style: type=1 len=0", "010000"),
        ]

        for label, value_hex in probes:
            print(f"\n--- Probe: {label} ---")
            result = gatt.send(f"char-write-req {HANDLE_WRITE_CMD} {value_hex}")
            print(f"  Write: {result}")

            # Collect output for 2 seconds looking for notifications
            output = gatt.collect_output(2.0)
            if output:
                print(f"  Output: {output}")

            # Also read the response characteristic
            result = gatt.send(f"char-read-hnd {HANDLE_READ_NOTIFY}")
            clean = result.replace("Characteristic value/descriptor:", "").strip()
            if clean:
                decoded = hex_decode(clean)
                print(f"  Read response: hex=[{clean}] decoded={decoded!r}")
            else:
                print(f"  Read response: <empty>")

    finally:
        gatt.close()


def main():
    # Try low security first (no pairing)
    probe_with_security("low")

    # Try medium security (triggers pairing)
    probe_with_security("medium")

    # Try high security (triggers pairing with MITM protection)
    probe_with_security("high")

    print("\n\nAll probes complete.")


if __name__ == "__main__":
    main()
