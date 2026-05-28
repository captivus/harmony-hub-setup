from __future__ import annotations

import json
import pathlib
import sys
import unittest
import urllib.error
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from harmony_hub_setup.lan_client import (
    HarmonyHubLanClient,
    HarmonyHubLanError,
)


class FakeHttpResponse:
    def __init__(self, *, status: int, body: bytes):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self.body


class HarmonyHubLanClientTests(unittest.TestCase):
    def test_ping_posts_android_style_command_to_8088(self):
        response = FakeHttpResponse(
            status=200,
            body=b'{"id":"124","code":200}',
        )
        client = HarmonyHubLanClient(host="192.0.2.200")

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.assertTrue(client.ping())

        request = urlopen.call_args.kwargs["url"]
        self.assertEqual(request.full_url, "http://192.0.2.200:8088")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "id": "124",
            "cmd": "connect.ping",
        })
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            request.get_header("Origin"),
            "http://localhost.nebula.myharmony.com",
        )
        self.assertEqual(
            request.get_header("Referer"),
            "http://localhost.nebula.myharmony.com/mobile-fat.html",
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 3.0)

    def test_provision_info_uses_android_command_and_longer_timeout(self):
        body = {
            "id": "124",
            "code": 200,
            "data": {
                "mode": "2",
                "accountId": "",
            },
        }
        response = FakeHttpResponse(
            status=200,
            body=json.dumps(body).encode("utf-8"),
        )
        client = HarmonyHubLanClient(host="192.0.2.200")

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(client.provision_info(), body)

        request = urlopen.call_args.kwargs["url"]
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "id": "124",
            "cmd": "setup.account?getProvisionInfo",
        })
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 15.0)

    def test_discovery_info_uses_android_discovery_command(self):
        body = {
            "id": "124",
            "code": 200,
            "data": {
                "remoteId": "12345678",
            },
        }
        response = FakeHttpResponse(
            status=200,
            body=json.dumps(body).encode("utf-8"),
        )
        client = HarmonyHubLanClient(host="192.0.2.200")

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(client.discovery_info(), body)

        request = urlopen.call_args.kwargs["url"]
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "id": "124",
            "cmd": "connect.discoveryinfo?get",
        })

    def test_sys_info_uses_web_app_system_info_command(self):
        body = {
            "id": "124",
            "code": 200,
            "data": {
                "fw_ver": "4.15.307",
            },
        }
        response = FakeHttpResponse(
            status=200,
            body=json.dumps(body).encode("utf-8"),
        )
        client = HarmonyHubLanClient(host="192.0.2.200")

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(client.sys_info(), body)

        request = urlopen.call_args.kwargs["url"]
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "id": "124",
            "cmd": "connect.sysinfo?get",
        })

    def test_firmware_check_uses_android_firmware_command(self):
        body = {
            "id": "124",
            "code": 200,
            "data": {
                "status": "ok",
            },
        }
        response = FakeHttpResponse(
            status=200,
            body=json.dumps(body).encode("utf-8"),
        )
        client = HarmonyHubLanClient(host="192.0.2.200")

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(client.firmware_check(), body)

        request = urlopen.call_args.kwargs["url"]
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "id": "124",
            "cmd": "setup.firmware?check",
        })

    def test_generic_command_posts_params_when_provided(self):
        body = {
            "id": "124",
            "code": 200,
            "data": {
                "ok": True,
            },
        }
        response = FakeHttpResponse(
            status=200,
            body=json.dumps(body).encode("utf-8"),
        )
        client = HarmonyHubLanClient(host="192.0.2.200")

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = client.command(
                command="harmony.test?probe",
                params={"option": "value"},
            )

        self.assertEqual(result, body)
        request = urlopen.call_args.kwargs["url"]
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "id": "124",
            "cmd": "harmony.test?probe",
            "params": {
                "option": "value",
            },
        })

    def test_rf_info_uses_web_app_device_info_command(self):
        body = {
            "id": "124",
            "code": 200,
            "data": {
                "Devices": [],
            },
        }
        response = FakeHttpResponse(
            status=200,
            body=json.dumps(body).encode("utf-8"),
        )
        client = HarmonyHubLanClient(host="192.0.2.200")

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(client.rf_info(), body)

        request = urlopen.call_args.kwargs["url"]
        self.assertEqual(json.loads(request.data.decode("utf-8")), {
            "id": "124",
            "cmd": "connect.rf?info",
        })




    def test_network_error_is_reported_as_lan_error(self):
        client = HarmonyHubLanClient(host="192.0.2.200")

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("No route to host"),
        ):
            with self.assertRaises(HarmonyHubLanError):
                client.ping()





if __name__ == "__main__":
    unittest.main()
