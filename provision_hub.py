"""Complete Harmony Hub setup: Wi-Fi + provisioning in one Bluetooth session.

Run this immediately after factory reset, before the hub connects to Wi-Fi
and shuts down Bluetooth.

Configure via environment variables:
    HARMONY_ADDR     -- the hub's Bluetooth MAC (AA:BB:CC:DD:EE:FF)
    HARMONY_SSID     -- target Wi-Fi network name
    HARMONY_PASSWORD -- target Wi-Fi password
"""

import json
import os
import socket
import time
import sys

HARMONY_ADDR = os.environ.get("HARMONY_ADDR", "AA:BB:CC:DD:EE:FF")
HARMONY_SSID = os.environ.get("HARMONY_SSID", "your-wifi-ssid")
HARMONY_PASSWORD = os.environ.get("HARMONY_PASSWORD", "your-wifi-password")
HEADER_PREFIX = bytes([0xFF, 0x08, 0x00, 0x01, 0x01, 0x02, 0x01])


def build_frame(payload: str) -> bytes:
    p = payload.encode("utf-8")
    length = len(p)
    if length <= 62:
        return HEADER_PREFIX + bytes([(length & 0x3F) | 0x80]) + p
    return HEADER_PREFIX + bytes([((length >> 8) & 0x3F) | 0xC0, length & 0xFF]) + p


def send_cmd(sock, cmd: dict, timeout: float = 30.0) -> dict | None:
    payload = json.dumps(cmd)
    print(f"\n  >> {cmd.get('cmd', '?')}")
    sock.send(build_frame(payload))

    data = b""
    start = time.time()
    while time.time() - start < timeout:
        try:
            chunk = sock.recv(4096)
            if chunk:
                data += chunk
                for i, b in enumerate(data):
                    if b == ord("{"):
                        try:
                            text = data[i:].decode("utf-8", errors="replace")
                            parsed = json.loads(text)
                            print(f"  << code={parsed.get('code', '?')}")
                            return parsed
                        except json.JSONDecodeError:
                            continue
        except (TimeoutError, OSError):
            if data:
                continue
            break
    print("  << timeout")
    return None


def main():
    print("Waiting for Harmony Hub Bluetooth...")
    print("(Factory reset the hub now if you haven't already)\n")

    # Retry connection until hub appears
    req_id = 0
    connected = False
    for attempt in range(60):
        try:
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.settimeout(5)
            sock.connect((HARMONY_ADDR, 1))
            connected = True
            print(f"Connected on attempt {attempt + 1}!")
            break
        except OSError:
            sys.stdout.write(".")
            sys.stdout.flush()
            sock.close()
            time.sleep(3)

    if not connected:
        print("\nFailed to connect. Is the hub powered on and factory reset?")
        sys.exit(1)

    sock.settimeout(10)

    # Step 1: Ping
    req_id += 1
    print("\n=== Step 1: Ping ===")
    resp = send_cmd(sock, {"cmd": "connect.ping", "id": req_id})

    # Step 2: Connect Wi-Fi
    req_id += 1
    print("\n=== Step 2: Connect Wi-Fi ===")
    resp = send_cmd(sock, {
        "cmd": "wifi.connect",
        "data": {
            "ssid": HARMONY_SSID,
            "password": HARMONY_PASSWORD,
            "encryption": "WPA2-PSK",
        },
        "id": req_id,
    })

    # Step 3: Wait for Wi-Fi to establish
    print("\n=== Step 3: Waiting 15s for Wi-Fi... ===")
    time.sleep(15)

    # Step 4: Verify Wi-Fi
    req_id += 1
    print("\n=== Step 4: Verify Wi-Fi ===")
    resp = send_cmd(sock, {"cmd": "wifi.connect", "id": req_id})
    if resp and resp.get("data", {}).get("connect_status") == "connected":
        ip = resp["data"].get("ip_address", "?")
        print(f"  Wi-Fi connected! IP: {ip}")
    else:
        print("  WARNING: Wi-Fi may not be connected yet")

    # Step 5: Provision hub (exact format from decompiled app)
    # The hub contacts Logitech's servers itself after receiving this.
    req_id += 1
    print("\n=== Step 5: Provision hub ===")
    print("  (Hub will contact Logitech servers -- this can take a while...)")
    sock.settimeout(30)
    resp = send_cmd(sock, {
        "cmd": "setup.account?provision",
        "data": {
            "provisionInfo": {
                "authToken": "",
                "discoveryServer": "https://svcs.myharmony.com/Discovery/Discovery.svc",
                "susChannel": "production",
                "email": "",
                "name": "Harmony Hub",
                "mode": "2",
            }
        },
        "id": req_id,
    }, timeout=120)

    if resp:
        print(f"\n  Full response: {json.dumps(resp, indent=2)}")
    else:
        print("  No parsed response. Trying raw socket read...")
        try:
            sock.settimeout(60)
            raw = sock.recv(8192)
            print(f"  Raw ({len(raw)} bytes): {raw.hex(' ')}")
            print(f"  Text: {raw.decode('utf-8', errors='replace')!r}")
        except Exception as exc:
            print(f"  Raw read: {exc}")

    # Step 6: Poll provisioning status over BT (keep connection alive)
    print("\n=== Step 6: Polling provisioning status ===")
    sock.settimeout(10)
    for i in range(18):
        time.sleep(10)
        req_id += 1
        resp = send_cmd(sock, {"cmd": "setup.account?getProvisionInfo", "id": req_id})
        if resp:
            data = resp.get("data", {})
            email = data.get("email", "")
            username = data.get("username", "")
            if email or username:
                print(f"\n  *** Provisioned! email={email} username={username} ***")
                print(f"  Full: {json.dumps(resp, indent=2)}")
                break
        elapsed = (i + 1) * 10
        print(f"  ({elapsed}s) Not yet linked to account...")

    # Step 7: Final state check
    req_id += 1
    print("\n=== Step 7: Final state ===")
    resp = send_cmd(sock, {"cmd": "connect.statedigest?get", "id": req_id})
    if resp:
        print(f"  {json.dumps(resp, indent=2)}")

    sock.close()
    print("\nDone. Try the Harmony app now.")


if __name__ == "__main__":
    main()
