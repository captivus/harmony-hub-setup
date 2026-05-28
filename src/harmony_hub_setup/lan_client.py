"""Local-network Harmony Hub setup client.

The Android app's setup flow probes a newly Wi-Fi-connected hub by POSTing
JSON commands to http://<hub-ip>:8088 before it continues account/profile setup.

This module covers the Phase 1 pre-account probes only: ping, sysinfo,
provisionInfo, discoveryInfo, firmware check. Account-linked commands
(state digest, sync, proxy.resource) require encrypted payloads and are
handled separately on the Phase 2 research branch.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


HARMONY_ORIGIN = "http://localhost.nebula.myharmony.com"
HARMONY_REFERER = "http://localhost.nebula.myharmony.com/mobile-fat.html"
DEFAULT_LAN_PORT = 8088
DEFAULT_LAN_TIMEOUT = 3.0
PROVISION_INFO_TIMEOUT = 15.0


class HarmonyHubLanError(RuntimeError):
    """Raised when the hub cannot be reached through the local setup endpoint."""


class HarmonyHubLanClient:
    """HTTP client for the hub's local setup endpoint."""

    def __init__(
        self,
        *,
        host: str,
        port: int = DEFAULT_LAN_PORT,
        timeout: float = DEFAULT_LAN_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _post(
        self,
        *,
        command: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        request_body: dict[str, Any] = {"id": "124", "cmd": command}
        if params is not None:
            request_body["params"] = params

        payload = json.dumps(
            request_body,
            separators=(",", ":"),
        ).encode("utf-8")

        request = urllib.request.Request(
            url=self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "charset": "utf-8",
                "Content-Length": str(len(payload)),
                "Origin": HARMONY_ORIGIN,
                "Referer": HARMONY_REFERER,
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                url=request,
                timeout=self.timeout if timeout is None else timeout,
            ) as response:
                status = response.getcode()
                body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read()
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            raise HarmonyHubLanError(str(exc)) from exc

        if not body:
            return status, None

        try:
            parsed = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HarmonyHubLanError(f"Invalid JSON from hub: {exc}") from exc

        if not isinstance(parsed, dict):
            raise HarmonyHubLanError("Hub returned a non-object JSON response")

        return status, parsed

    def command(
        self,
        *,
        command: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        status, body = self._post(
            command=command,
            params=params,
            timeout=timeout,
        )
        if status != 200:
            return None
        return body

    def ping(self) -> bool:
        status, _ = self._post(command="connect.ping")
        return status == 200

    def provision_info(self) -> dict[str, Any] | None:
        status, body = self._post(
            command="setup.account?getProvisionInfo",
            timeout=PROVISION_INFO_TIMEOUT,
        )
        if status != 200:
            return None
        return body

    def discovery_info(self) -> dict[str, Any] | None:
        status, body = self._post(command="connect.discoveryinfo?get")
        if status != 200:
            return None
        return body

    def sys_info(self) -> dict[str, Any] | None:
        status, body = self._post(command="connect.sysinfo?get")
        if status != 200:
            return None
        return body

    def firmware_check(self) -> dict[str, Any] | None:
        status, body = self._post(command="setup.firmware?check")
        if status != 200:
            return None
        return body

    def rf_info(self) -> dict[str, Any] | None:
        status, body = self._post(command="connect.rf?info")
        if status != 200:
            return None
        return body
