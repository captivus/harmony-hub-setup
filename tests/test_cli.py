from __future__ import annotations

import pathlib
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from harmony_hub_setup.cli import run_bluetooth_provision, wait_for_wifi_connection


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float):
        self.now += seconds


class FakeClient:
    def __init__(self, connect_responses: list[dict | None], status_responses: list[dict | None]):
        self.connect_responses = list(connect_responses)
        self.status_responses = list(status_responses)
        self.connect_calls = 0

    def wifi_connect(self, *, ssid: str, password: str, encryption: str) -> dict | None:
        self.connect_calls += 1
        if self.connect_responses:
            return self.connect_responses.pop(0)
        return None

    def wifi_status(self) -> dict | None:
        if self.status_responses:
            return self.status_responses.pop(0)
        return {
            "code": 200,
            "data": {
                "connect_status": "inactive",
            },
        }


class FakeProvisionClient:
    def __init__(self, response: dict | None):
        self.response = response
        self.provision_calls = 0

    def provision(self) -> dict | None:
        self.provision_calls += 1
        return self.response


class WaitForWifiConnectionTests(unittest.TestCase):
    def test_retries_after_early_500_until_connected(self):
        clock = FakeClock()
        client = FakeClient(
            connect_responses=[
                {"id": 1, "code": 500},
                {"id": 2, "code": 200},
            ],
            status_responses=[
                {"id": 3, "code": 200, "data": {"connect_status": "inactive"}},
                {
                    "id": 4,
                    "code": 200,
                    "data": {
                        "connect_status": "connected",
                        "ip_address": "192.0.2.200",
                    },
                },
            ],
        )

        with redirect_stdout(StringIO()):
            status = wait_for_wifi_connection(
                client=client,
                ssid="Network",
                password="secret",
                encryption="WPA2-PSK",
                max_wait=30.0,
                retry_interval=10.0,
                sleep_fn=clock.sleep,
                time_fn=clock.time,
            )

        self.assertEqual(status["ip_address"], "192.0.2.200")
        self.assertEqual(client.connect_calls, 2)

    def test_returns_false_when_wifi_never_connects(self):
        clock = FakeClock()
        client = FakeClient(
            connect_responses=[
                {"id": 1, "code": 500},
                {"id": 2, "code": 500},
            ],
            status_responses=[
                {"id": 3, "code": 200, "data": {"connect_status": "inactive"}},
                {"id": 4, "code": 200, "data": {"connect_status": "inactive"}},
            ],
        )

        with redirect_stdout(StringIO()):
            status = wait_for_wifi_connection(
                client=client,
                ssid="Network",
                password="secret",
                encryption="WPA2-PSK",
                max_wait=15.0,
                retry_interval=10.0,
                sleep_fn=clock.sleep,
                time_fn=clock.time,
            )

        self.assertIsNone(status)
        self.assertEqual(client.connect_calls, 2)


class RunBluetoothProvisionTests(unittest.TestCase):
    def test_accepts_successful_provision_response(self):
        client = FakeProvisionClient(response={"id": 1, "code": 200})

        with redirect_stdout(StringIO()):
            successful = run_bluetooth_provision(client=client)

        self.assertTrue(successful)
        self.assertEqual(client.provision_calls, 1)

    def test_rejects_failed_provision_response(self):
        client = FakeProvisionClient(response={"id": 1, "code": 500})

        with redirect_stdout(StringIO()):
            successful = run_bluetooth_provision(client=client)

        self.assertFalse(successful)
        self.assertEqual(client.provision_calls, 1)


if __name__ == "__main__":
    unittest.main()
