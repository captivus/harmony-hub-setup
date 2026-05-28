"""Harmony Hub Bluetooth RFCOMM setup tool.

Connects via classic Bluetooth RFCOMM to configure Wi-Fi on the hub.
Protocol reverse-engineered from the Harmony Android app (com.logitech.harmonyhub).
"""

import json
import socket
import sys
import time

HARMONY_ADDR = "AA:BB:CC:DD:EE:FF"
RFCOMM_CHANNEL = 1

# Binary frame header prefix (constant for all messages)
HEADER_PREFIX = bytes([0xFF, 0x08, 0x00, 0x01, 0x01, 0x02, 0x01])


class HarmonyBTClient:
    def __init__(self, address: str):
        self.address = address
        self.sock = None
        self.request_id = 0

    def connect(self):
        print(f"Connecting to {self.address} RFCOMM channel {RFCOMM_CHANNEL}...")
        self.sock = socket.socket(
            socket.AF_BLUETOOTH,
            socket.SOCK_STREAM,
            socket.BTPROTO_RFCOMM,
        )
        self.sock.connect((self.address, RFCOMM_CHANNEL))
        self.sock.settimeout(10.0)
        print("Connected!")

    def _build_frame(self, payload: str) -> bytes:
        """Build the binary frame header + payload."""
        payload_bytes = payload.encode("utf-8")
        length = len(payload_bytes)

        if length <= 62:
            header = HEADER_PREFIX + bytes([(length & 0x3F) | 0x80])
        else:
            msb = ((length >> 8) & 0x3F) | 0xC0
            lsb = length & 0xFF
            header = HEADER_PREFIX + bytes([msb, lsb])

        return header + payload_bytes

    def send_request(self, cmd_json: str) -> dict | None:
        """Send a JSON command and return the parsed response."""
        self.request_id += 1

        # Parse and inject our request ID
        cmd = json.loads(cmd_json)
        cmd["id"] = self.request_id
        payload = json.dumps(cmd)

        frame = self._build_frame(payload)
        print(f"\n  >> Sending: {payload}")
        print(f"     Frame ({len(frame)} bytes): {frame[:16].hex(' ')}...")

        self.sock.send(frame)

        # Read response
        return self._read_response()

    def _read_response(self) -> dict | None:
        """Read and parse the hub's response."""
        try:
            data = b""
            start = time.time()
            while time.time() - start < 15:
                try:
                    chunk = self.sock.recv(4096)
                    if chunk:
                        data += chunk
                        # Try to parse -- responses are JSON, possibly with a binary header
                        try:
                            response_text = self._extract_json(data)
                            if response_text:
                                parsed = json.loads(response_text)
                                print(f"  << Response: {json.dumps(parsed, indent=2)}")
                                return parsed
                        except json.JSONDecodeError:
                            # Need more data
                            continue
                except OSError as exc:
                    if "timed out" in str(exc):
                        if data:
                            continue
                        break
                    raise
            if data:
                print(f"  << Raw data ({len(data)} bytes): {data.hex(' ')}")
                try:
                    text = data.decode("utf-8", errors="replace")
                    print(f"  << Text: {text!r}")
                except Exception:
                    pass
            else:
                print("  << No response (timeout)")
            return None
        except Exception as exc:
            print(f"  << Error reading response: {exc}")
            return None

    def _extract_json(self, data: bytes) -> str | None:
        """Extract JSON from response, skipping any binary header."""
        # Find the first '{' character
        for i, b in enumerate(data):
            if b == ord("{"):
                text = data[i:].decode("utf-8", errors="replace")
                # Validate it's complete JSON
                json.loads(text)
                return text
        return None

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


def scan_wifi(client: HarmonyBTClient):
    """Scan for available Wi-Fi networks."""
    print("\n=== Scanning for Wi-Fi networks ===")
    response = client.send_request('{"cmd": "wifi.networks"}')
    if response and "data" in response:
        data = response["data"]
        networks = data if isinstance(data, list) else data.get("networks", [])
        # Deduplicate by SSID
        seen = {}
        for net in networks:
            ssid = net.get("ssid", "<hidden>")
            if ssid not in seen or net.get("signal_strength", 0) > seen[ssid].get("signal_strength", 0):
                seen[ssid] = net
        unique = list(seen.values())
        print(f"\nFound {len(unique)} unique network(s) ({len(networks)} total including duplicates):")
        for i, net in enumerate(unique):
            ssid = net.get("ssid", "<hidden>")
            signal = net.get("signal_strength", "?")
            security = net.get("encryption", ["?"])
            channel = net.get("channel", "?")
            print(f"  {i+1}. {ssid} (signal: {signal}, security: {security}, channel: {channel})")
        return unique
    return []


def connect_wifi(client: HarmonyBTClient, ssid: str, password: str, encryption: str):
    """Connect the hub to a Wi-Fi network."""
    print(f"\n=== Connecting to Wi-Fi: {ssid} ===")
    cmd = json.dumps({
        "cmd": "wifi.connect",
        "data": {
            "ssid": ssid,
            "password": password,
            "encryption": encryption,
        },
    })
    response = client.send_request(cmd)
    return response


def main():
    client = HarmonyBTClient(address=HARMONY_ADDR)

    try:
        client.connect()

        # Step 1: Ping the hub
        print("\n=== Step 1: Ping hub ===")
        client.send_request('{"cmd": "connect.ping"}')

        # Step 2: Check provisioning status
        print("\n=== Step 2: Check provisioning ===")
        client.send_request('{"cmd": "setup.account?getProvisionInfo"}')

        # Step 3: Get firmware status
        print("\n=== Step 3: Firmware status ===")
        client.send_request('{"cmd": "setup.firmware?status"}')

        # Step 4: Get current Wi-Fi status
        print("\n=== Step 4: Wi-Fi status ===")
        client.send_request('{"cmd": "wifi.connect"}')

        # Step 5: Scan for Wi-Fi networks
        print("\n=== Step 5: Scan Wi-Fi ===")
        networks = scan_wifi(client)

        if networks:
            print("\n\nWi-Fi scan complete. To connect, run this script with:")
            print("  --ssid 'YourNetwork' --password 'YourPassword' --encryption 'WPA2'")

    except (OSError, ConnectionError) as exc:
        print(f"\nBluetooth error: {exc}")
        print("Make sure the hub is powered on and within range.")
    finally:
        client.close()

    print("\nDone.")


if __name__ == "__main__":
    if "--ssid" in sys.argv:
        ssid_idx = sys.argv.index("--ssid") + 1
        pwd_idx = sys.argv.index("--password") + 1
        enc_idx = sys.argv.index("--encryption") + 1
        ssid = sys.argv[ssid_idx]
        password = sys.argv[pwd_idx]
        encryption = sys.argv[enc_idx]

        client = HarmonyBTClient(address=HARMONY_ADDR)
        try:
            client.connect()
            connect_wifi(
                client=client,
                ssid=ssid,
                password=password,
                encryption=encryption,
            )
        finally:
            client.close()
    else:
        main()
