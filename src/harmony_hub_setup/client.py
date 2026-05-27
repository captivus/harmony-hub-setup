"""Harmony Hub Bluetooth RFCOMM client.

Implements the binary-framed JSON protocol used by the Harmony Hub
for Bluetooth-based setup and configuration.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .bt_socket import RFCOMMSocket

RFCOMM_CHANNEL = 1
HEADER_PREFIX = bytes([0xFF, 0x08, 0x00, 0x01, 0x01, 0x02, 0x01])
DEFAULT_SOCKET_TIMEOUT = 10.0
SETUP_REQUEST_TIMEOUT = 90.0


class HarmonyHubClient:
    """Bluetooth RFCOMM client for Logitech Harmony Hub."""

    def __init__(self, address: str, channel: int = RFCOMM_CHANNEL):
        self.address = address
        self.channel = channel
        self._sock: RFCOMMSocket | None = None
        self._request_id = 0

    def connect(self, timeout: float = DEFAULT_SOCKET_TIMEOUT):
        self._sock = RFCOMMSocket()
        self._sock.settimeout(timeout)
        self._sock.connect(self.address, self.channel)
        self._sock.settimeout(DEFAULT_SOCKET_TIMEOUT)

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def _build_frame(self, payload: str) -> bytes:
        header, payload_bytes = self._build_frame_parts(payload=payload)
        return header + payload_bytes

    def _build_frame_parts(self, payload: str) -> tuple[bytes, bytes]:
        payload_bytes = payload.encode("utf-8")
        length = len(payload_bytes)
        if length <= 62:
            header = HEADER_PREFIX + bytes([(length & 0x3F) | 0x80])
        else:
            msb = ((length >> 8) & 0x3F) | 0xC0
            lsb = length & 0xFF
            header = HEADER_PREFIX + bytes([msb, lsb])
        return header, payload_bytes

    def _send_all(self, frame: bytes) -> None:
        if self._sock is None:
            raise RuntimeError("Not connected")

        view = memoryview(frame)
        while view:
            sent = self._sock.send(bytes(view))
            if sent == 0:
                raise OSError("Bluetooth socket connection broken during send")
            view = view[sent:]

    @staticmethod
    def _extract_response(recv_data: bytes, request_id: int) -> dict | None:
        """Extract the response JSON for request_id from a noisy BT stream."""
        text = recv_data.decode("utf-8", errors="replace")
        decoder = json.JSONDecoder()

        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            response_id = parsed.get("id")
            if response_id is None or response_id == request_id:
                return parsed
        return None

    def command(self, cmd: str, data: dict | None = None,
                timeout: float = DEFAULT_SOCKET_TIMEOUT) -> dict | None:
        """Send a command and return the parsed JSON response.

        Matches the proven send_cmd() logic from provision_hub.py:
        set socket timeout to match command timeout, inline JSON
        extraction, catch (TimeoutError, OSError).
        """
        self._request_id += 1
        request_id = self._request_id
        if data is None:
            msg: dict[str, Any] = {"cmd": cmd, "id": request_id}
        else:
            msg = {"cmd": cmd, "data": data, "id": request_id}
        payload = json.dumps(msg)

        header, payload_bytes = self._build_frame_parts(payload=payload)
        self._send_all(frame=header)
        self._send_all(frame=payload_bytes)

        self._sock.settimeout(timeout)
        try:
            recv_data = b""
            start = time.time()
            while time.time() - start < timeout:
                try:
                    chunk = self._sock.recv(4096)
                    if chunk:
                        recv_data += chunk
                        response = self._extract_response(
                            recv_data=recv_data,
                            request_id=request_id,
                        )
                        if response is not None:
                            return response
                except (TimeoutError, OSError):
                    if recv_data:
                        continue
                    break
            return None
        finally:
            self._sock.settimeout(DEFAULT_SOCKET_TIMEOUT)

    def ping(self) -> dict | None:
        return self.command("connect.ping")

    def wifi_status(self) -> dict | None:
        return self.command("wifi.connect")

    def wifi_scan(self) -> list[dict]:
        resp = self.command("wifi.networks", timeout=SETUP_REQUEST_TIMEOUT)
        if resp and "data" in resp:
            data = resp["data"]
            return data if isinstance(data, list) else data.get("networks", [])
        return []

    def wifi_connect(self, ssid: str, password: str,
                     encryption: str = "WPA2-PSK") -> dict | None:
        return self.command(
            cmd="wifi.connect",
            data={"ssid": ssid, "password": password, "encryption": encryption},
            timeout=SETUP_REQUEST_TIMEOUT,
        )

    def firmware_status(self) -> dict | None:
        return self.command("setup.firmware?status")

    def bt_nonce(self) -> dict | None:
        return self.command("bt.nonce")

    def rf_info(self) -> dict | None:
        return self.command("rf.info")

    def provision_info(self) -> dict | None:
        return self.command("setup.account?getProvisionInfo")

    def provision(self, discovery_server: str = "https://svcs.myharmony.com/Discovery/Discovery.svc",
                  sus_channel: str = "production") -> dict | None:
        return self.command(
            cmd="setup.account?provision",
            data={
                "provisionInfo": {
                    "authToken": "",
                    "discoveryServer": discovery_server,
                    "susChannel": sus_channel,
                    "email": "",
                    "name": "Harmony Hub",
                    "mode": "2",
                }
            },
            timeout=120.0,
        )

    def state_digest(self) -> dict | None:
        return self.command("connect.statedigest?get")
