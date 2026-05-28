"""Low-level BLE probe: write-without-response, advertising data, and
second write characteristic (which has a minimum 4-byte length)."""

import pexpect
import re
import subprocess
import time

HARMONY_ADDR = "AA:BB:CC:DD:EE:FF"
HANDLE_WRITE_CMD = "0xfff6"     # 7e220100 - Write/WriteNoResp
HANDLE_READ_NOTIFY = "0xfff8"   # 7e220101 - Read/Notify
HANDLE_WRITE_2 = "0xfffe"      # 7e220103 - Write/WriteNoResp (min 4 bytes)
HANDLE_CCCD_READ_NOTIFY = "0xfff9"
HANDLE_CCCD_NOTIFY_ONLY = "0xfffc"

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9]+[hl]|\x1b\[K")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def hex_encode(text: str) -> str:
    return text.encode().hex()


def get_advertising_data():
    """Capture BLE advertising data using hcitool."""
    print("=== Capturing BLE Advertising Data ===")
    try:
        result = subprocess.run(
            ["hcitool", "lescan", "--duplicates"],
            capture_output=True, text=True, timeout=5,
        )
        print(f"  lescan: {result.stdout[:500]}")
    except subprocess.TimeoutExpired:
        print("  lescan timed out (expected)")
    except Exception as exc:
        print(f"  lescan error: {exc}")

    # Try to get more detailed scan response
    try:
        result = subprocess.run(
            ["hcitool", "leinfo", HARMONY_ADDR],
            capture_output=True, text=True, timeout=10,
        )
        print(f"  leinfo: {result.stdout}")
        if result.stderr:
            print(f"  leinfo stderr: {result.stderr}")
    except Exception as exc:
        print(f"  leinfo error: {exc}")


def main():
    get_advertising_data()

    print("\n=== Interactive session: write-without-response + second write char ===")
    child = pexpect.spawn(
        f"gatttool --device={HARMONY_ADDR} --addr-type=public --interactive",
        encoding="utf-8",
        timeout=15,
    )
    child.expect(r"\[LE\]>")

    child.sendline("connect")
    time.sleep(3)
    output = strip_ansi(child.before + (child.after or ""))
    print(f"  Connect: {output[-200:]}")

    # Enable notifications
    child.sendline(f"char-write-req {HANDLE_CCCD_READ_NOTIFY} 0100")
    time.sleep(1)
    child.sendline(f"char-write-req {HANDLE_CCCD_NOTIFY_ONLY} 0100")
    time.sleep(1)
    print("  Notifications enabled")

    # Try write-WITHOUT-response (char-write instead of char-write-req)
    print("\n--- Write-without-response probes to 0xfff6 ---")
    for label, value in [
        ("null", "00"),
        ("0x01", "01"),
        ("hello", hex_encode("hello")),
        ("JSON", hex_encode('{"cmd":"setup"}')),
    ]:
        child.sendline(f"char-write {HANDLE_WRITE_CMD} {value}")
        time.sleep(1.5)
        # Read response
        child.sendline(f"char-read-hnd {HANDLE_READ_NOTIFY}")
        time.sleep(1)
        try:
            child.expect(r"Characteristic value/descriptor:(.*?)(\[|$)", timeout=3)
            raw = strip_ansi(child.match.group(1)).strip()
            print(f"  {label}: response=[{raw}]")
        except pexpect.TIMEOUT:
            buf = strip_ansi(child.buffer) if child.buffer else ""
            print(f"  {label}: timeout, buffer=[{buf[-100:]}]")

    # Probe the second write characteristic (min 4 bytes)
    print("\n--- Probes to second write char 0xfffe (min 4 bytes) ---")
    probes_write2 = [
        ("4x 0x00", "00000000"),
        ("4x 0x01", "01010101"),
        ("4x 0xff", "ffffffff"),
        ("type=1 len=2 val=0000", "01020000"),
        ("'pair' padded", hex_encode("pair")),
        ("'wifi' padded", hex_encode("wifi")),
        ("'scan' padded", hex_encode("scan")),
        ("JSON short", hex_encode('{"c":1}')),
        # CSR GAIA-style: vendor=0x000a (Logitech?), cmd=0x0001, payload=none
        ("GAIA-like v1", "000a000100"),
        ("GAIA-like v2", "ff000001"),
    ]

    for label, value in probes_write2:
        if len(value) < 8:  # pad to minimum 4 bytes
            value = value.ljust(8, "0")
        child.sendline(f"char-write-req {HANDLE_WRITE_2} {value}")
        time.sleep(1)

        # Check for notification or response
        child.sendline(f"char-read-hnd {HANDLE_READ_NOTIFY}")
        time.sleep(1)
        try:
            child.expect(r"Characteristic value/descriptor:(.*?)(\[|$)", timeout=3)
            raw = strip_ansi(child.match.group(1)).strip()
            status = "DATA" if raw else "empty"
            print(f"  {label}: {status} [{raw}]")
        except pexpect.TIMEOUT:
            buf = strip_ansi(child.buffer) if child.buffer else ""
            # Check for write error
            if "Error" in buf or "invalid" in buf.lower():
                print(f"  {label}: WRITE ERROR [{buf[-150:]}]")
            else:
                print(f"  {label}: timeout [{buf[-100:]}]")

    # Try writing to BOTH characteristics in sequence
    print("\n--- Combined write: write2 then write1 ---")
    child.sendline(f"char-write-req {HANDLE_WRITE_2} 00000001")
    time.sleep(0.5)
    child.sendline(f"char-write-req {HANDLE_WRITE_CMD} {hex_encode('setup')}")
    time.sleep(2)
    child.sendline(f"char-read-hnd {HANDLE_READ_NOTIFY}")
    time.sleep(1)
    try:
        child.expect(r"Characteristic value/descriptor:(.*?)(\[|$)", timeout=3)
        raw = strip_ansi(child.match.group(1)).strip()
        print(f"  Response: [{raw}]")
    except pexpect.TIMEOUT:
        print(f"  Response: timeout")

    # Dump ALL readable handles in extended range
    print("\n--- Reading extended handle range 0xfff0-0xfffe ---")
    for h in range(0xfff0, 0xffff):
        handle = f"0x{h:04x}"
        child.sendline(f"char-read-hnd {handle}")
        time.sleep(0.5)
        try:
            child.expect(r"Characteristic value/descriptor:(.*?)(\[|$)", timeout=3)
            raw = strip_ansi(child.match.group(1)).strip()
            if raw:
                print(f"  {handle}: [{raw}]")
        except pexpect.TIMEOUT:
            pass

    child.sendline("disconnect")
    time.sleep(1)
    child.sendline("exit")
    child.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
