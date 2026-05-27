from __future__ import annotations

import json
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from harmony_hub_setup.client import HEADER_PREFIX, HarmonyHubClient


class PartialSendSocket:
    def __init__(self, chunks: list[bytes], max_send_size: int = 5):
        self.chunks = list(chunks)
        self.max_send_size = max_send_size
        self.sent = bytearray()
        self.writes: list[bytes] = []
        self.timeouts: list[float] = []

    def send(self, data: bytes) -> int:
        sent = min(len(data), self.max_send_size)
        self.sent.extend(data[:sent])
        self.writes.append(bytes(data[:sent]))
        return sent

    def recv(self, bufsize: int = 4096) -> bytes:
        if not self.chunks:
            raise TimeoutError("recv timed out")
        return self.chunks.pop(0)

    def settimeout(self, seconds: float):
        self.timeouts.append(seconds)


class HarmonyHubClientTests(unittest.TestCase):
    def test_data_commands_preserve_known_good_key_order(self):
        client = HarmonyHubClient(address="AA:BB:CC:DD:EE:FF")
        response = {"id": 1, "code": 200, "data": {}}
        fake_socket = PartialSendSocket(
            chunks=[json.dumps(response).encode("utf-8")],
        )
        client._sock = fake_socket

        result = client.wifi_connect(
            ssid="Network",
            password="secret",
            encryption="WPA2-PSK",
        )

        self.assertEqual(result, response)
        payload = bytes(fake_socket.sent).split(HEADER_PREFIX, maxsplit=1)[1]
        if payload[0] & 0xC0 == 0xC0:
            json_payload = payload[2:]
        else:
            json_payload = payload[1:]
        self.assertLess(
            json_payload.index(b'"data"'),
            json_payload.index(b'"id"'),
        )

    def test_command_sends_complete_frame_when_socket_partially_sends(self):
        client = HarmonyHubClient(address="AA:BB:CC:DD:EE:FF")
        response = {"id": 1, "code": 200}
        fake_socket = PartialSendSocket(
            chunks=[json.dumps(response).encode("utf-8")],
            max_send_size=3,
        )
        client._sock = fake_socket

        client.ping()

        expected_payload = json.dumps({"cmd": "connect.ping", "id": 1})
        expected_frame = client._build_frame(payload=expected_payload)
        self.assertEqual(bytes(fake_socket.sent), expected_frame)

    def test_command_writes_header_before_json_payload(self):
        client = HarmonyHubClient(address="AA:BB:CC:DD:EE:FF")
        response = {"id": 1, "code": 200}
        fake_socket = PartialSendSocket(
            chunks=[json.dumps(response).encode("utf-8")],
            max_send_size=4096,
        )
        client._sock = fake_socket

        client.ping()

        self.assertEqual(fake_socket.writes[0], HEADER_PREFIX + b"\xa0")
        self.assertEqual(
            fake_socket.writes[1],
            json.dumps({"cmd": "connect.ping", "id": 1}).encode("utf-8"),
        )

    def test_command_ignores_stale_response_id(self):
        client = HarmonyHubClient(address="AA:BB:CC:DD:EE:FF")
        stale = HEADER_PREFIX + b'\x9d{"id":99,"code":200}'
        current = HEADER_PREFIX + b'\x9c{"id":1,"code":200}'
        fake_socket = PartialSendSocket(chunks=[stale, current])
        client._sock = fake_socket

        result = client.ping()

        self.assertEqual(result, {"id": 1, "code": 200})


if __name__ == "__main__":
    unittest.main()
