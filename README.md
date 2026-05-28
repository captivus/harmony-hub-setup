# Harmony Hub Setup

Configure a factory-reset Logitech Harmony Hub far enough for the official
Harmony mobile app to finish account/profile restore.

This tool performs **Phase 1** only:

1. Connects to the hub over Bluetooth.
2. Finds the target Wi-Fi network.
3. Connects the hub to Wi-Fi.
4. Sends the dummy discovery provisioning command (`mode=2`).
5. Verifies the hub is still pre-account and reachable on the local network.

The official Harmony iPhone or Android app performs **Phase 2**:

1. Finds the hub on the network.
2. Logs in to the Logitech account.
3. Restores the hub's devices, activities, and account profile.

## Requirements

- Linux with Bluetooth support.
- `bluetoothctl` from BlueZ available on `PATH`.
- `uv` for running the project from source.
- A Harmony Hub that has been factory reset.
- The Wi-Fi network name and password for the network the hub should join.

## Discover the Hub

After factory reset, plug in the hub and wait for it to enter Bluetooth setup
mode. Then run:

```bash
uv run harmony-hub-setup discover
```

The command scans with `bluetoothctl` and prints nearby devices. A typical
result looks like:

```text
Bluetooth devices:
  AA:BB:CC:DD:EE:FF  Harmony Hub  [Harmony candidate]
```

If a Harmony candidate is listed, use that address with `--address`. If setup is
run without `--address`, it will auto-discover and use the address only when
exactly one Harmony-looking device is found.

## Phase 1 Setup

Run:

```bash
uv run harmony-hub-setup setup \
  --ssid "Your Wi-Fi Name" \
  --password "Your Wi-Fi Password" \
  --encryption WPA2-PSK
```

Or pass the Bluetooth address explicitly:

```bash
uv run harmony-hub-setup \
  --address AA:BB:CC:DD:EE:FF \
  setup \
  --ssid "Your Wi-Fi Name" \
  --password "Your Wi-Fi Password" \
  --encryption WPA2-PSK
```

The setup command prints numbered progress steps. Phase 1 is complete when it
prints:

```text
PHASE 1 COMPLETE
The hub is on Wi-Fi, in mode=2, and reachable through the local setup endpoint.
Open the Harmony mobile app and continue account/profile restore from there.
```

At that point, open the Harmony mobile app, select the hub found on the network,
log in to the Logitech account, and let the app restore the profile.

## What Success Means

Successful Phase 1 means:

- Bluetooth setup commands worked.
- The hub joined Wi-Fi and has a local IP address.
- Local setup probes work over `http://<hub-ip>:8088`.
- Provision info reports `mode=2`.
- Account ID, auth token, email, username, and active remote ID are not set.

It does **not** mean the hub has been fully account-provisioned. Full restore is
complete only after the Harmony mobile app finishes Phase 2.

## Troubleshooting

If discovery finds no Harmony candidate:

- Confirm the hub was factory reset.
- Keep the hub powered on and near the computer.
- Run `bluetoothctl scan on` manually to confirm Linux can see Bluetooth
  devices.
- Re-run setup with `--address` if you know the hub's Bluetooth address.

If setup fails during Wi-Fi connection:

- Confirm the SSID and password.
- Confirm the hub is close enough to the Wi-Fi access point.
- Re-run setup after another factory reset if the hub is in an unknown state.

If the mobile app cannot find the hub after Phase 1 completes:

- Confirm the phone is on the same network as the hub.
- Wait briefly for the hub to appear in the app.
- Run `harmony-hub-setup --address <address> status` while Bluetooth is still
  available to inspect the hub state.
