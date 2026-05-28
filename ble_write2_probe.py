"""Systematic probing of the Harmony Hub's second write characteristic (0xfffe).

We know:
- Minimum 4 bytes required (2 bytes rejected)
- 0x00000000 accepted
- 0x01010101 accepted
- 0xffffffff caused "unlikely error" and crashed connection
- This characteristic is actively processed by the hub firmware
"""

import pexpect
import re
import sys
import time

HARMONY_ADDR = "AA:BB:CC:DD:EE:FF"
HANDLE_WRITE_CMD = "0xfff6"
HANDLE_READ_NOTIFY = "0xfff8"
HANDLE_WRITE_2 = "0xfffe"
HANDLE_CCCD_READ_NOTIFY = "0xfff9"
HANDLE_CCCD_NOTIFY_ONLY = "0xfffc"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9]+[hl]|\x1b\[K")


def strip(text: str) -> str:
    return ANSI_RE.sub("", text)


def hex_encode(text: str) -> str:
    return text.encode().hex()


class GattSession:
    def __init__(self):
        self.child = None

    def connect(self):
        self.child = pexpect.spawn(
            f"gatttool --device={HARMONY_ADDR} --addr-type=public --interactive",
            encoding="utf-8", timeout=15,
        )
        self.child.expect(r"\[LE\]>")
        self.child.sendline("connect")
        time.sleep(3)
        buf = strip(self.child.before or "")
        if "successful" not in buf.lower():
            # Read more
            try:
                self.child.expect("successful", timeout=5)
            except pexpect.TIMEOUT:
                print("FAILED TO CONNECT")
                sys.exit(1)
        print("Connected.")

        # Enable notifications
        self.child.sendline(f"char-write-req {HANDLE_CCCD_READ_NOTIFY} 0100")
        time.sleep(0.5)
        self.child.sendline(f"char-write-req {HANDLE_CCCD_NOTIFY_ONLY} 0100")
        time.sleep(0.5)
        # Drain buffer
        try:
            self.child.read_nonblocking(size=4096, timeout=1)
        except pexpect.TIMEOUT:
            pass
        print("Notifications enabled.")

    def write_and_check(self, handle: str, value_hex: str, label: str) -> str:
        """Write a value and return the result category."""
        # Drain any pending output
        try:
            self.child.read_nonblocking(size=4096, timeout=0.2)
        except pexpect.TIMEOUT:
            pass

        self.child.sendline(f"char-write-req {handle} {value_hex}")
        time.sleep(1.0)

        # Read all output
        try:
            raw = self.child.read_nonblocking(size=4096, timeout=1.0)
        except pexpect.TIMEOUT:
            raw = ""

        clean = strip(raw).strip()

        # Classify result
        if "unlikely error" in clean.lower():
            return "UNLIKELY_ERROR"
        elif "invalid" in clean.lower():
            return "INVALID_LENGTH"
        elif "error" in clean.lower() or "failed" in clean.lower():
            return f"ERROR: {clean[-100:]}"
        elif "written successfully" in clean.lower():
            # Check for notifications in the output
            if "notification" in clean.lower():
                return f"OK+NOTIFY: {clean}"
            # Also read the response char
            self.child.sendline(f"char-read-hnd {HANDLE_READ_NOTIFY}")
            time.sleep(0.5)
            try:
                resp_raw = self.child.read_nonblocking(size=4096, timeout=1.0)
                resp_clean = strip(resp_raw)
                if "descriptor:" in resp_clean:
                    val_part = resp_clean.split("descriptor:")[1].split("[")[0].strip()
                    if val_part:
                        return f"OK+RESPONSE: {val_part}"
            except pexpect.TIMEOUT:
                pass
            return "OK"
        else:
            return f"UNKNOWN: {clean[-100:]}"

    def is_alive(self) -> bool:
        try:
            self.child.sendline("")
            time.sleep(0.3)
            raw = self.child.read_nonblocking(size=1024, timeout=0.5)
            return True
        except (pexpect.EOF, pexpect.TIMEOUT):
            return True  # TIMEOUT is OK, EOF means dead
        except Exception:
            return False

    def close(self):
        if self.child:
            try:
                self.child.sendline("disconnect")
                self.child.sendline("exit")
                self.child.close()
            except Exception:
                pass


def reconnect_if_needed(gatt: GattSession) -> GattSession:
    if not gatt.is_alive():
        print("  [reconnecting...]")
        gatt.close()
        new_gatt = GattSession()
        new_gatt.connect()
        return new_gatt
    return gatt


def main():
    gatt = GattSession()
    gatt.connect()

    results = []

    # Phase 1: Find which byte values are accepted in each position
    print("\n=== Phase 1: Single-byte sweep in 4-byte frames ===")
    print("Testing byte values in position 0 (rest zeros)")
    for b in range(0, 256, 16):  # step by 16 to be faster
        value = f"{b:02x}000000"
        label = f"byte0=0x{b:02x}"
        result = gatt.write_and_check(HANDLE_WRITE_2, value, label)
        print(f"  {label}: {result}")
        results.append((label, value, result))
        if "ERROR" in result and "UNLIKELY" not in result:
            gatt = reconnect_if_needed(gatt)

    print("\nTesting byte values in position 1 (rest zeros)")
    for b in [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0xff]:
        value = f"00{b:02x}0000"
        label = f"byte1=0x{b:02x}"
        result = gatt.write_and_check(HANDLE_WRITE_2, value, label)
        print(f"  {label}: {result}")
        results.append((label, value, result))
        if "UNLIKELY" in result:
            gatt = reconnect_if_needed(gatt)

    print("\nTesting byte values in position 2")
    for b in [0x00, 0x01, 0x02, 0x04, 0x10, 0x40, 0x80, 0xff]:
        value = f"0000{b:02x}00"
        label = f"byte2=0x{b:02x}"
        result = gatt.write_and_check(HANDLE_WRITE_2, value, label)
        print(f"  {label}: {result}")
        results.append((label, value, result))
        if "UNLIKELY" in result:
            gatt = reconnect_if_needed(gatt)

    print("\nTesting byte values in position 3")
    for b in [0x00, 0x01, 0x02, 0x04, 0x10, 0x40, 0x80, 0xff]:
        value = f"000000{b:02x}"
        label = f"byte3=0x{b:02x}"
        result = gatt.write_and_check(HANDLE_WRITE_2, value, label)
        print(f"  {label}: {result}")
        results.append((label, value, result))
        if "UNLIKELY" in result:
            gatt = reconnect_if_needed(gatt)

    # Phase 2: Try common command patterns
    print("\n=== Phase 2: Common command patterns ===")
    patterns = [
        ("version query", "00000100"),
        ("get info", "00010000"),
        ("init", "01000000"),
        ("start", "02000000"),
        ("scan wifi", "03000000"),
        ("get state", "04000000"),
        ("login", "05000000"),
        ("8-byte with payload", "0100000000000000"),
        ("cmd=1, sub=1", "01010000"),
        ("cmd=1, sub=2", "01020000"),
    ]

    for label, value in patterns:
        result = gatt.write_and_check(HANDLE_WRITE_2, value, label)
        print(f"  {label} ({value}): {result}")
        if "UNLIKELY" in result:
            gatt = reconnect_if_needed(gatt)

    # Phase 3: After write2, check if write1 now produces responses
    print("\n=== Phase 3: Write2 then Write1 sequence ===")
    for init_val in ["01000000", "00010000", "02000000"]:
        result1 = gatt.write_and_check(HANDLE_WRITE_2, init_val, f"init:{init_val}")
        print(f"  Write2 ({init_val}): {result1}")
        result2 = gatt.write_and_check(HANDLE_WRITE_CMD, hex_encode("hello"), "then write1")
        print(f"  Write1 (hello): {result2}")

    # Summary
    print("\n\n=== SUMMARY ===")
    errors = [(l, v, r) for l, v, r in results if "ERROR" in r or "UNLIKELY" in r]
    if errors:
        print("Values that caused errors:")
        for label, value, result in errors:
            print(f"  {label} ({value}): {result}")

    responses = [(l, v, r) for l, v, r in results if "RESPONSE" in r or "NOTIFY" in r]
    if responses:
        print("Values that got responses:")
        for label, value, result in responses:
            print(f"  {label} ({value}): {result}")

    if not errors and not responses:
        print("All writes accepted, none produced errors or responses.")

    gatt.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
