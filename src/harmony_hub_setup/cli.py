"""CLI for Harmony Hub Bluetooth setup."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass

from .client import HarmonyHubClient
from .lan_client import HarmonyHubLanClient, HarmonyHubLanError


ANDROID_PHASE1_MODE = "2"
BLUETOOTH_ADDRESS_RE = re.compile(r"^Device\s+([0-9A-Fa-f:]{17})(?:\s+(.*))?$")
HARMONY_NAME_PARTS = ("harmony", "logitech")


@dataclass(frozen=True)
class BluetoothDevice:
    address: str
    name: str

    @property
    def is_harmony_candidate(self) -> bool:
        normalized = self.name.lower()
        return any(part in normalized for part in HARMONY_NAME_PARTS)


class Progress:
    def __init__(self, *, total_steps: int):
        self.total_steps = total_steps
        self.current_step = 0

    def step(self, title: str) -> None:
        self.current_step += 1
        print(f"\n[{self.current_step}/{self.total_steps}] {title}")


def _is_success_code(value: object) -> bool:
    return value in (200, "200")


def run_bluetoothctl(*, arguments: list[str], timeout: float) -> str:
    try:
        result = subprocess.run(
            ["bluetoothctl", *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("bluetoothctl was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return f"{stdout}\n{stderr}"

    return f"{result.stdout}\n{result.stderr}"


def parse_bluetoothctl_devices(output: str) -> list[BluetoothDevice]:
    devices_by_address: dict[str, BluetoothDevice] = {}
    for line in output.splitlines():
        match = BLUETOOTH_ADDRESS_RE.match(line.strip())
        if match is None:
            continue
        address = match.group(1).upper()
        name = (match.group(2) or "").strip()
        devices_by_address[address] = BluetoothDevice(
            address=address,
            name=name,
        )
    return list(devices_by_address.values())


def discover_bluetooth_devices(
    *,
    scan_timeout: float,
    runner=run_bluetoothctl,
) -> list[BluetoothDevice]:
    scan_seconds = max(1, int(scan_timeout))
    scan_output = runner(
        arguments=["--timeout", str(scan_seconds), "scan", "on"],
        timeout=scan_timeout + 5.0,
    )
    devices_output = runner(
        arguments=["devices"],
        timeout=5.0,
    )

    devices_by_address: dict[str, BluetoothDevice] = {}
    for device in parse_bluetoothctl_devices(scan_output + "\n" + devices_output):
        devices_by_address[device.address] = device
    return list(devices_by_address.values())


def print_discovered_devices(*, devices: list[BluetoothDevice]) -> None:
    if not devices:
        print("No Bluetooth devices found.")
        return

    print("Bluetooth devices:")
    for device in devices:
        marker = "Harmony candidate" if device.is_harmony_candidate else "other"
        name = device.name or "(unnamed)"
        print(f"  {device.address}  {name}  [{marker}]")


def choose_setup_address(
    *,
    explicit_address: str | None,
    scan_timeout: float,
) -> str | None:
    if explicit_address:
        return explicit_address

    print("No Bluetooth address provided; scanning for Harmony Hub candidates...")
    try:
        devices = discover_bluetooth_devices(scan_timeout=scan_timeout)
    except RuntimeError as exc:
        print(f"  Auto-discovery failed: {exc}")
        return None

    candidates = [device for device in devices if device.is_harmony_candidate]
    print_discovered_devices(devices=devices)

    if len(candidates) == 1:
        candidate = candidates[0]
        print(f"\nUsing discovered Harmony Hub: {candidate.address} {candidate.name}")
        return candidate.address

    if len(candidates) > 1:
        print("\nMultiple Harmony Hub candidates found. Re-run setup with --address <MAC>.")
    else:
        print("\nNo Harmony Hub candidate found. Re-run setup with --address <MAC>.")
    return None


def validate_phase1_handoff_provision_info(
    provision_info: dict | None,
) -> tuple[bool, list[str]]:
    """Return whether provision info matches the pre-account Android handoff."""
    problems: list[str] = []
    if not provision_info:
        return False, ["provision info was empty"]

    if not _is_success_code(provision_info.get("code")):
        problems.append(f"response code was {provision_info.get('code')!r}")

    data = provision_info.get("data", {})
    if not isinstance(data, dict):
        return False, ["provision info data was not an object"]

    mode = str(data.get("mode", ""))
    if mode != ANDROID_PHASE1_MODE:
        problems.append(f"mode was {mode or 'not set'}, expected {ANDROID_PHASE1_MODE}")

    account_fields = ("accountId", "authToken", "email", "username", "activeRemoteId")
    for field in account_fields:
        if data.get(field):
            problems.append(f"{field} was already set")

    return not problems, problems


def require_phase1_handoff_provision_info(
    *,
    label: str,
    provision_info: dict | None,
) -> bool:
    valid, problems = validate_phase1_handoff_provision_info(
        provision_info=provision_info,
    )
    if valid:
        data = provision_info.get("data", {}) if provision_info else {}
        secure_value = data.get("se", "not set")
        print(f"  {label}: mode={data.get('mode')}, account=not set, secure={secure_value}")
        return True

    print(f"  {label}: invalid Phase 1 handoff state")
    for problem in problems:
        print(f"    - {problem}")
    return False


def _run_required_lan_probe(*, label: str, probe) -> dict | None:
    try:
        response = probe()
    except HarmonyHubLanError as exc:
        print(f"  {label} failed: {exc}")
        return None

    if response is None:
        print(f"  {label} returned a non-200 response.")
        return None

    print(f"  {label} OK.")
    return response


def wait_for_wifi_connection(
    client: HarmonyHubClient,
    *,
    ssid: str,
    password: str,
    encryption: str,
    max_wait: float = 180.0,
    retry_interval: float = 10.0,
    sleep_fn=time.sleep,
    time_fn=time.time,
) -> dict | None:
    """Retry Wi-Fi setup until the hub reports a connected network."""
    start = time_fn()
    attempt = 0
    last_response: dict | None = None

    while time_fn() - start < max_wait:
        attempt += 1
        resp = client.wifi_connect(
            ssid=ssid,
            password=password,
            encryption=encryption,
        )
        last_response = resp
        code = resp.get("code") if resp else None
        if code == 200:
            print(f"  Wi-Fi command accepted on attempt {attempt}.")
        elif resp:
            print(f"  Wi-Fi command attempt {attempt} returned code={code}; retrying.")
        else:
            print(f"  Wi-Fi command attempt {attempt} timed out; retrying.")

        status = client.wifi_status()
        data = status.get("data", {}) if status else {}
        if data.get("connect_status") == "connected":
            print(f"  Connected! IP: {data.get('ip_address', '?')}")
            return data

        remaining = max_wait - (time_fn() - start)
        if remaining <= 0:
            break
        sleep_fn(min(retry_interval, remaining))

    if last_response:
        print(f"  Last Wi-Fi response: {json.dumps(last_response, indent=2)}")
    return None


def run_android_local_network_phase(*, ip_address: str, progress: Progress | None = None) -> bool:
    """Run the Android app's first LAN setup probes against the hub."""
    lan_client = HarmonyHubLanClient(host=ip_address)

    if progress:
        progress.step("Verify local hub setup endpoint")
    else:
        print("\nVerify local hub setup endpoint")
    try:
        if not lan_client.ping():
            print("  LAN ping returned a non-200 response.")
            return False
    except HarmonyHubLanError as exc:
        print(f"  LAN ping failed: {exc}")
        return False
    print(f"  LAN ping OK: http://{ip_address}:8088")

    sys_info = _run_required_lan_probe(
        label="LAN system-info",
        probe=lan_client.sys_info,
    )
    if sys_info is None:
        return False
    sys_data = sys_info.get("data", {})
    print(f"  Hub firmware:    {sys_data.get('fw_ver', sys_data.get('hubSwVersion', 'unknown'))}")

    provision_info = _run_required_lan_probe(
        label="LAN provision-info",
        probe=lan_client.provision_info,
    )
    if provision_info is None:
        return False

    data = provision_info.get("data", {}) if isinstance(provision_info, dict) else {}
    print(f"  Provision mode: {data.get('mode', 'not set')}")
    print(f"  Account ID:      {data.get('accountId', 'not set')}")
    print(f"  Auth token:      {'set' if data.get('authToken') else 'not set'}")
    if not require_phase1_handoff_provision_info(
        label="LAN Phase 1 handoff",
        provision_info=provision_info,
    ):
        return False

    discovery_info = _run_required_lan_probe(
        label="LAN discovery-info",
        probe=lan_client.discovery_info,
    )
    if discovery_info is None:
        return False
    discovery_data = discovery_info.get("data", {})
    print(f"  Remote ID:       {discovery_data.get('remoteId', 'not set')}")
    print(f"  Hub ID:          {discovery_data.get('hubId', 'not set')}")

    device_info = _run_required_lan_probe(
        label="LAN paired-device info",
        probe=lan_client.rf_info,
    )
    if device_info is None:
        return False
    devices = device_info.get("data", {}).get("Devices")
    if isinstance(devices, list):
        print(f"  Paired devices:  {len(devices)}")

    firmware = _run_required_lan_probe(
        label="LAN firmware check",
        probe=lan_client.firmware_check,
    )
    if firmware is None:
        return False
    firmware_data = firmware.get("data", {})
    print(f"  Firmware status: {firmware_data.get('status', firmware_data.get('errorString', 'unknown'))}")
    return True


def run_bluetooth_provision(client: HarmonyHubClient, *, progress: Progress | None = None) -> bool:
    if progress:
        progress.step("Set discovery provisioning over Bluetooth")
    else:
        print("\nSet discovery provisioning over Bluetooth")
    resp = client.provision()
    if not resp:
        print("  No response from setup.account?provision.")
        return False
    if resp.get("code") != 200:
        print(f"  Provision response was not successful: {json.dumps(resp, indent=2)}")
        return False
    print("  Provision command accepted.")
    return True


def cmd_scan(client: HarmonyHubClient, args: argparse.Namespace):
    print("Scanning for Wi-Fi networks...")
    networks = client.wifi_scan()
    if not networks:
        print("No networks found.")
        return

    seen: dict[str, dict] = {}
    for net in networks:
        ssid = net.get("ssid", "<hidden>")
        if ssid not in seen or net.get("signal_strength", 0) > seen[ssid].get("signal_strength", 0):
            seen[ssid] = net

    print(f"\n{len(seen)} network(s):\n")
    for i, net in enumerate(seen.values(), start=1):
        ssid = net.get("ssid", "<hidden>")
        signal = net.get("signal_strength", "?")
        security = net.get("encryption", ["?"])
        channel = net.get("channel", "?")
        if isinstance(security, list):
            security = ", ".join(security)
        print(f"  {i}. {ssid}  (signal={signal}, security={security}, channel={channel})")


def cmd_connect(client: HarmonyHubClient, args: argparse.Namespace):
    print(f"Connecting hub to Wi-Fi network: {args.ssid}")
    resp = client.wifi_connect(
        ssid=args.ssid,
        password=args.password,
        encryption=args.encryption,
    )
    if resp and resp.get("code") == 200:
        print("Command accepted. Waiting for connection...")
        time.sleep(10)
        status = client.wifi_status()
        if status and "data" in status:
            info = status["data"]
            print(f"\n  Status:  {info.get('connect_status')}")
            print(f"  SSID:    {info.get('ssid')}")
            print(f"  IP:      {info.get('ip_address')}")
            print(f"  Error:   {info.get('error_code')}")
    else:
        print(f"Unexpected response: {json.dumps(resp, indent=2)}")


def cmd_provision(client: HarmonyHubClient, args: argparse.Namespace):
    print("Sending provisioning command...")
    resp = client.provision()
    if resp:
        print(f"Response: {json.dumps(resp, indent=2)}")
    else:
        print("No response (timeout).")


def run_android_style_setup(client: HarmonyHubClient, args: argparse.Namespace) -> bool:
    progress = Progress(total_steps=8)

    progress.step("Verify Bluetooth command channel")
    ping = client.ping()
    if not ping or ping.get("code") != 200:
        print("  Hub not responding.")
        return False
    print(f"  Hub alive (uuid={ping.get('data', {}).get('uuid', '?')})")

    progress.step("Scan for target Wi-Fi network")
    networks = client.wifi_scan()
    matching_networks = [
        network for network in networks
        if network.get("ssid") == args.ssid
    ]
    if not matching_networks:
        print(f"  Target SSID not found: {args.ssid}")
        return False
    strongest = max(
        matching_networks,
        key=lambda network: network.get("signal_strength", 0),
    )
    security = strongest.get("encryption", "?")
    if isinstance(security, list):
        security = ", ".join(security)
    print(
        f"  Found target SSID (signal={strongest.get('signal_strength', '?')}, "
        f"security={security}, channel={strongest.get('channel', '?')})"
    )

    progress.step("Get Bluetooth nonce")
    nonce = client.bt_nonce()
    if nonce and nonce.get("code") == 200:
        value = nonce.get("data", {}).get("nonce", "")
        print(f"  Nonce received ({len(value)} chars).")
    else:
        print(f"  Nonce request did not return code=200: {json.dumps(nonce, indent=2)}")
        return False

    progress.step(f"Connect hub to Wi-Fi ({args.ssid})")
    connected_wifi = wait_for_wifi_connection(
        client=client,
        ssid=args.ssid,
        password=args.password,
        encryption=args.encryption,
    )
    if not connected_wifi:
        print("  Wi-Fi did not reach connected state; aborting setup.")
        return False

    if not run_bluetooth_provision(client=client, progress=progress):
        return False

    progress.step("Confirm pre-account Phase 1 handoff state over Bluetooth")
    provision_info = client.provision_info()
    if not require_phase1_handoff_provision_info(
        label="Bluetooth provision-info",
        provision_info=provision_info,
    ):
        return False

    progress.step("Read Bluetooth setup gates")
    rf = client.rf_info()
    if rf:
        print(f"  RF info response: code={rf.get('code')}")
    fw = client.firmware_status()
    if fw and "data" in fw:
        version = fw["data"].get("currentVersion")
        print(f"  Firmware: {version or fw['data'].get('errorString', 'unknown')}")

    status = client.wifi_status()
    data = status.get("data", {}) if status else connected_wifi
    print(f"  Wi-Fi: {data.get('connect_status')}")
    print(f"  SSID:  {data.get('ssid')}")
    print(f"  IP:    {data.get('ip_address')}")
    if data.get("connect_status") != "connected" or not data.get("ip_address"):
        return False

    return run_android_local_network_phase(
        ip_address=data["ip_address"],
        progress=progress,
    )


def wait_for_account_link(client: HarmonyHubClient) -> None:
    print("\nHolding BT connection (up to 3 minutes)...")
    start_poll = time.time()
    for _ in range(18):
        time.sleep(10)
        resp = client.provision_info()
        if resp:
            data = resp.get("data", {})
            email = data.get("email", "")
            username = data.get("username", "")
            if email or username:
                print(f"\n  Hub linked to account: {email or username}")
                break
        elapsed = int(time.time() - start_poll)
        print(f"  ({elapsed}s) Waiting...")


def cmd_setup(client: HarmonyHubClient, args: argparse.Namespace):
    """Prepare a factory-reset hub for the app's account/profile setup."""
    # This command manages its own connection -- close the one main() opened
    client.close()

    print("Waiting for Harmony Hub Bluetooth...")
    print("(Factory reset the hub if you haven't already)\n")

    connected = False
    for attempt in range(60):
        try:
            client.connect(timeout=5.0)
            connected = True
            print(f"Connected on attempt {attempt + 1}!")
            break
        except OSError:
            client.close()
            sys.stdout.write(".")
            sys.stdout.flush()
            time.sleep(3)

    if not connected:
        print("\nFailed to connect after 60 attempts.")
        return

    if not run_android_style_setup(client=client, args=args):
        return

    if args.wait_for_account_link:
        wait_for_account_link(client=client)

    print("\nFinal state")
    prov = client.provision_info()
    if prov:
        data = prov.get("data", {})
        print(f"  Discovery server: {data.get('discoveryServer', 'not set')}")
        print(f"  SUS channel:      {data.get('susChannel', 'not set')}")
        print(f"  Mode:             {data.get('mode', 'not set')}")

    state = client.state_digest()
    if state:
        data = state.get("data", {})
        print(f"  Setup complete:   {data.get('isSetupComplete')}")
        print(f"  Firmware:         {data.get('hubSwVersion')}")
        print(f"  Wi-Fi status:     {data.get('wifiStatus')}")

    print("\nPHASE 1 COMPLETE")
    print("The hub is on Wi-Fi, in mode=2, and reachable through the local setup endpoint.")
    print("Open the Harmony mobile app and continue account/profile restore from there.")


def cmd_discover(args: argparse.Namespace) -> None:
    print(f"Scanning for Bluetooth devices for {int(args.timeout)} seconds...")
    try:
        devices = discover_bluetooth_devices(scan_timeout=args.timeout)
    except RuntimeError as exc:
        print(f"Discovery failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print_discovered_devices(devices=devices)
    candidates = [device for device in devices if device.is_harmony_candidate]
    if len(candidates) == 1:
        print(f"\nUse this address with setup: {candidates[0].address}")
    elif len(candidates) > 1:
        print("\nMultiple candidates found. Use the address for the hub you factory reset.")
    else:
        print("\nNo Harmony-named device found. Factory reset the hub and try again.")


def cmd_status(client: HarmonyHubClient, args: argparse.Namespace):
    print("Querying hub status...\n")

    ping = client.ping()
    if ping and "data" in ping:
        d = ping["data"]
        print(f"  Hub:          {d.get('status')}")
        print(f"  UUID:         {d.get('uuid')}")

    wifi = client.wifi_status()
    if wifi and "data" in wifi:
        d = wifi["data"]
        print(f"  Wi-Fi:        {d.get('connect_status')}")
        print(f"  SSID:         {d.get('ssid')}")
        print(f"  IP:           {d.get('ip_address')}")
        print(f"  Encryption:   {d.get('encryption')}")

    prov = client.provision_info()
    if prov and "data" in prov:
        d = prov["data"]
        if d.get("errorCode") == "200":
            auth_token = d.get("authToken")
            account_id = d.get("accountId")
            mode = str(d.get("mode", ""))
            provisioned = bool(auth_token) or (bool(account_id) and mode == "3")
            print(f"  Provisioned:  {'yes' if provisioned else 'no'}")
        else:
            print(f"  Provisioned:  no ({d.get('errorString', d.get('errorCode'))})")

    fw = client.firmware_status()
    if fw and "data" in fw:
        d = fw["data"]
        version = d.get("currentVersion")
        if version:
            print(f"  Firmware:     {version}")
        else:
            print(f"  Firmware:     unknown ({d.get('errorString', '')})")


def cmd_raw(client: HarmonyHubClient, args: argparse.Namespace):
    resp = client.command(cmd=args.command)
    print(json.dumps(resp, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="harmony-hub-setup",
        description="Configure a Logitech Harmony Hub over Bluetooth.",
    )
    parser.add_argument(
        "--address",
        help="Bluetooth MAC address of the Harmony Hub (e.g. AA:BB:CC:DD:EE:FF)",
    )
    parser.add_argument(
        "--channel", type=int, default=1,
        help="RFCOMM channel (default: 1)",
    )

    sub = parser.add_subparsers(dest="subcommand", required=True)

    discover_parser = sub.add_parser("discover", help="Find nearby Harmony Hub Bluetooth addresses")
    discover_parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Bluetooth scan duration in seconds (default: 20)",
    )

    sub.add_parser("status", help="Show hub status, Wi-Fi, and firmware info")
    sub.add_parser("scan", help="Scan for available Wi-Fi networks")
    sub.add_parser("provision", help="Send provisioning command (sets discovery server)")

    connect_parser = sub.add_parser("connect", help="Connect hub to a Wi-Fi network")
    connect_parser.add_argument("--ssid", required=True, help="Wi-Fi network name")
    connect_parser.add_argument("--password", required=True, help="Wi-Fi password")
    connect_parser.add_argument(
        "--encryption", default="WPA2-PSK",
        help="Encryption type (default: WPA2-PSK)",
    )

    setup_parser = sub.add_parser(
        "setup",
        help="Phase 1 handoff setup: Wi-Fi + dummy discovery provisioning",
    )
    setup_parser.add_argument("--ssid", required=True, help="Wi-Fi network name")
    setup_parser.add_argument("--password", required=True, help="Wi-Fi password")
    setup_parser.add_argument(
        "--encryption", default="WPA2-PSK",
        help="Encryption type (default: WPA2-PSK)",
    )
    setup_parser.add_argument(
        "--wait-for-account-link",
        action="store_true",
        help="Keep the Bluetooth connection open while waiting for app account linking",
    )
    setup_parser.add_argument(
        "--discover-timeout",
        type=float,
        default=20.0,
        help="Bluetooth auto-discovery scan duration in seconds when --address is omitted",
    )

    raw_parser = sub.add_parser("raw", help="Send a raw command to the hub")
    raw_parser.add_argument("command", help="Command string (e.g. connect.ping)")

    args = parser.parse_args()

    if args.subcommand == "discover":
        cmd_discover(args=args)
        return

    dispatch = {
        "status": cmd_status,
        "scan": cmd_scan,
        "connect": cmd_connect,
        "provision": cmd_provision,
        "setup": cmd_setup,
        "raw": cmd_raw,
    }

    address = args.address
    if args.subcommand == "setup":
        address = choose_setup_address(
            explicit_address=address,
            scan_timeout=args.discover_timeout,
        )
        if not address:
            sys.exit(1)
    elif not address:
        parser.error(f"{args.subcommand} requires --address")

    client = HarmonyHubClient(address=address, channel=args.channel)

    if args.subcommand == "setup":
        # setup manages its own connection with retry logic
        try:
            dispatch[args.subcommand](client, args)
        except OSError as exc:
            print(f"\nBluetooth error: {exc}", file=sys.stderr)
            sys.exit(1)
        finally:
            client.close()
    else:
        print(f"Connecting to Harmony Hub at {address}...")
        try:
            client.connect()
            print("Connected.\n")
            dispatch[args.subcommand](client, args)
        except OSError as exc:
            print(f"\nBluetooth error: {exc}", file=sys.stderr)
            sys.exit(1)
        finally:
            client.close()
