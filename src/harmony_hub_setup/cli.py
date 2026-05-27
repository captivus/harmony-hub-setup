"""CLI for Harmony Hub Bluetooth setup."""

from __future__ import annotations

import argparse
import json
import sys
import time

from .client import HarmonyHubClient
from .lan_client import HarmonyHubLanClient, HarmonyHubLanError


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


def run_android_local_network_phase(*, ip_address: str) -> bool:
    """Run the Android app's first LAN setup probes against the hub."""
    lan_client = HarmonyHubLanClient(host=ip_address)

    print("\nStep 7: Verify local hub setup endpoint")
    try:
        if not lan_client.ping():
            print("  LAN ping returned a non-200 response.")
            return False
    except HarmonyHubLanError as exc:
        print(f"  LAN ping failed: {exc}")
        return False
    print(f"  LAN ping OK: http://{ip_address}:8088")

    try:
        provision_info = lan_client.provision_info()
    except HarmonyHubLanError as exc:
        print(f"  LAN provision-info request failed: {exc}")
        return False

    if provision_info is None:
        print("  LAN provision-info request returned a non-200 response.")
        return False

    data = provision_info.get("data", {}) if isinstance(provision_info, dict) else {}
    print(f"  Provision mode: {data.get('mode', 'not set')}")
    print(f"  Account ID:      {data.get('accountId', 'not set')}")
    print(f"  Auth token:      {'set' if data.get('authToken') else 'not set'}")

    try:
        discovery_info = lan_client.discovery_info()
    except HarmonyHubLanError as exc:
        print(f"  LAN discovery-info request failed: {exc}")
        return False
    if discovery_info is None:
        print("  LAN discovery-info request returned a non-200 response.")
        return False
    discovery_data = discovery_info.get("data", {})
    print(f"  Remote ID:       {discovery_data.get('remoteId', 'not set')}")
    print(f"  Hub ID:          {discovery_data.get('hubId', 'not set')}")

    try:
        firmware = lan_client.firmware_check()
    except HarmonyHubLanError as exc:
        print(f"  LAN firmware check skipped: {exc}")
        return True
    if firmware is None:
        print("  LAN firmware check returned a non-200 response; continuing.")
        return True
    firmware_data = firmware.get("data", {})
    print(f"  Firmware status: {firmware_data.get('status', firmware_data.get('errorString', 'unknown'))}")
    return True


def run_bluetooth_provision(client: HarmonyHubClient) -> bool:
    print("\nStep 5: Set discovery provisioning over Bluetooth")
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
    print("\nStep 1: Ping")
    ping = client.ping()
    if not ping or ping.get("code") != 200:
        print("  Hub not responding.")
        return False
    print(f"  Hub alive (uuid={ping.get('data', {}).get('uuid', '?')})")

    print("\nStep 2: Scan Wi-Fi")
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

    print("\nStep 3: Get Bluetooth nonce")
    nonce = client.bt_nonce()
    if nonce and nonce.get("code") == 200:
        value = nonce.get("data", {}).get("nonce", "")
        print(f"  Nonce received ({len(value)} chars).")
    else:
        print(f"  Nonce request did not return code=200: {json.dumps(nonce, indent=2)}")
        return False

    print(f"\nStep 4: Connect Wi-Fi ({args.ssid})")
    connected_wifi = wait_for_wifi_connection(
        client=client,
        ssid=args.ssid,
        password=args.password,
        encryption=args.encryption,
    )
    if not connected_wifi:
        print("  Wi-Fi did not reach connected state; aborting setup.")
        return False

    if not run_bluetooth_provision(client=client):
        return False

    print("\nStep 6: Read setup gates")
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

    return run_android_local_network_phase(ip_address=data["ip_address"])


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

    print("\nHub passed Bluetooth Wi-Fi setup and Android-style LAN setup probes.")
    print("Open the Harmony app and continue account/profile setup using the hub on the network.")


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
        "--address", required=True,
        help="Bluetooth MAC address of the Harmony Hub (e.g. AA:BB:CC:DD:EE:FF)",
    )
    parser.add_argument(
        "--channel", type=int, default=1,
        help="RFCOMM channel (default: 1)",
    )

    sub = parser.add_subparsers(dest="subcommand", required=True)

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
        help="Full setup: Wi-Fi + provision in one session (run after factory reset)",
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

    raw_parser = sub.add_parser("raw", help="Send a raw command to the hub")
    raw_parser.add_argument("command", help="Command string (e.g. connect.ping)")

    args = parser.parse_args()

    dispatch = {
        "status": cmd_status,
        "scan": cmd_scan,
        "connect": cmd_connect,
        "provision": cmd_provision,
        "setup": cmd_setup,
        "raw": cmd_raw,
    }

    client = HarmonyHubClient(address=args.address, channel=args.channel)

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
        print(f"Connecting to Harmony Hub at {args.address}...")
        try:
            client.connect()
            print("Connected.\n")
            dispatch[args.subcommand](client, args)
        except OSError as exc:
            print(f"\nBluetooth error: {exc}", file=sys.stderr)
            sys.exit(1)
        finally:
            client.close()
