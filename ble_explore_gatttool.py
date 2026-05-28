"""Explore Harmony Hub BLE via gatttool subprocess (bypasses bluez D-Bus BR/EDR issue)."""

import subprocess
import time

HARMONY_ADDR = "AA:BB:CC:DD:EE:FF"

# Vendor-specific characteristic handles (from discovery)
HANDLE_WRITE_CMD = "0xfff6"    # 7e220100 - Write/WriteNoResp
HANDLE_READ_NOTIFY = "0xfff8"  # 7e220101 - Read/Notify
HANDLE_NOTIFY_ONLY = "0xfffb"  # 7e220102 - Notify
HANDLE_WRITE_2 = "0xfffe"     # 7e220103 - Write/WriteNoResp

# CCCD (Client Characteristic Configuration Descriptor) handles
# These are typically handle+1 after the value handle for notify chars
HANDLE_CCCD_READ_NOTIFY = "0xfff9"
HANDLE_CCCD_NOTIFY_ONLY = "0xfffc"


def gatttool_read(handle: str) -> str:
    result = subprocess.run(
        ["gatttool", "--device", HARMONY_ADDR, "--addr-type=public",
         "--char-read", f"--handle={handle}"],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip()


def gatttool_write(handle: str, value_hex: str, *, with_response: bool = True) -> str:
    cmd = ["gatttool", "--device", HARMONY_ADDR, "--addr-type=public"]
    if with_response:
        cmd.extend(["--char-write-req", f"--handle={handle}", f"--value={value_hex}"])
    else:
        cmd.extend(["--char-write", f"--handle={handle}", f"--value={value_hex}"])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=15,
    )
    return f"stdout={result.stdout.strip()} stderr={result.stderr.strip()} rc={result.returncode}"


def hex_encode(text: str) -> str:
    return text.encode().hex()


def hex_decode(hex_str: str) -> str:
    clean = hex_str.replace(" ", "")
    try:
        return bytes.fromhex(clean).decode("utf-8", errors="replace")
    except ValueError:
        return f"<invalid hex: {hex_str}>"


def main():
    print("=== Reading all handle values in the vendor service range ===")
    print(f"(Handles 0xfff4 through 0xfffe)")
    for h in range(0xfff4, 0xffff):
        handle = f"0x{h:04x}"
        try:
            result = gatttool_read(handle=handle)
            if "Characteristic value/descriptor:" in result:
                raw = result.split(":", 1)[1].strip()
                decoded = hex_decode(raw) if raw else "<empty>"
                print(f"  {handle}: hex=[{raw}] decoded={decoded!r}")
            else:
                print(f"  {handle}: {result}")
        except subprocess.TimeoutExpired:
            print(f"  {handle}: TIMEOUT")
        except Exception as exc:
            print(f"  {handle}: ERROR {exc}")

    print("\n=== Enabling notifications (writing 0x0100 to CCCDs) ===")
    for cccd_handle, name in [
        (HANDLE_CCCD_READ_NOTIFY, "read/notify CCCD"),
        (HANDLE_CCCD_NOTIFY_ONLY, "notify-only CCCD"),
    ]:
        result = gatttool_write(handle=cccd_handle, value_hex="0100")
        print(f"  {name} ({cccd_handle}): {result}")

    print("\n=== Probe 1: Writing 0x00 to command char ===")
    result = gatttool_write(handle=HANDLE_WRITE_CMD, value_hex="00")
    print(f"  Result: {result}")
    time.sleep(1)
    resp = gatttool_read(handle=HANDLE_READ_NOTIFY)
    print(f"  Response: {resp}")

    print("\n=== Probe 2: Writing ASCII 'discovery' to command char ===")
    result = gatttool_write(
        handle=HANDLE_WRITE_CMD,
        value_hex=hex_encode("discovery"),
    )
    print(f"  Result: {result}")
    time.sleep(1)
    resp = gatttool_read(handle=HANDLE_READ_NOTIFY)
    print(f"  Response: {resp}")

    print("\n=== Probe 3: Writing JSON query to command char ===")
    result = gatttool_write(
        handle=HANDLE_WRITE_CMD,
        value_hex=hex_encode('{"cmd":"get_setup_info"}'),
    )
    print(f"  Result: {result}")
    time.sleep(1)
    resp = gatttool_read(handle=HANDLE_READ_NOTIFY)
    print(f"  Response: {resp}")

    print("\n=== Probe 4: Writing to second write char ===")
    result = gatttool_write(handle=HANDLE_WRITE_2, value_hex="00")
    print(f"  Result: {result}")
    time.sleep(1)
    resp = gatttool_read(handle=HANDLE_READ_NOTIFY)
    print(f"  Response: {resp}")

    print("\n=== Probe 5: Short binary sequences to command char ===")
    for probe_name, probe_hex in [
        ("0x01", "01"),
        ("0x01 0x00", "0100"),
        ("0xff", "ff"),
        ("0x01 0x01", "0101"),
        ("'?'", hex_encode("?")),
        ("'help'", hex_encode("help")),
    ]:
        result = gatttool_write(handle=HANDLE_WRITE_CMD, value_hex=probe_hex)
        time.sleep(0.5)
        resp = gatttool_read(handle=HANDLE_READ_NOTIFY)
        raw = resp.split(":", 1)[1].strip() if ":" in resp else resp
        decoded = hex_decode(raw) if raw else "<empty>"
        print(f"  {probe_name}: write={result}")
        print(f"    response: hex=[{raw}] decoded={decoded!r}")

    print("\nDone.")


if __name__ == "__main__":
    main()
