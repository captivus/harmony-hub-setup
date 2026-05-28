# Hub Ready for App Provisioning

Timestamp: 2026-05-27T17:21:14-05:00

## Milestone

The Harmony Hub is in the post-Bluetooth setup, pre-account-linking state. It appears ready for the Harmony iPhone app, or another Harmony application flow, to complete account/profile provisioning.

## Observed State

- Hub LAN IP: `<HUB_IP>`
- Hub MAC address: `<HUB_MAC>`
- Local setup endpoint: `http://<HUB_IP>:8088`
- LAN `connect.ping`: successful
- Bluetooth status command: failed with `[Errno 112] Host is down`

## Provisioning Data

The LAN `setup.account?getProvisionInfo` response showed:

- `discoveryServer`: `https://svcs.myharmony.com/Discovery/Discovery.svc`
- `discoveryServerCF`: `https://cf-svcs.myharmony.com/Discovery/Discovery.svc`
- `susChannel`: `production`
- `mode`: `2`
- `email`: empty
- `username`: empty

This means the hub has the discovery/SUS provisioning metadata but is not yet account-linked.

## Discovery Data

The LAN `connect.discoveryinfo?get` response showed:

- `ip`: `<HUB_IP>`
- `port`: `5222`
- `productId`: `Pimento`
- `hubId`: `97`
- `friendlyName`: `Harmony Hub`
- `host_name`: `Harmony Hub`
- `current_fw_version`: `4.15.600`
- `mode`: `2`
- `setupStatus`: `-1`
- `setupSessionType`: `1`
- `setupSessionIsStale`: `false`
- `remoteId`: empty
- `accountId`: empty

## Firmware Check

The LAN `setup.firmware?check` response succeeded and reported:

- `currentVersion`: `4.15.600`
- `canUpdateOta`: `true`
- `status`: `1`

## Interpretation

At this milestone, the hub is reachable through the same local setup endpoint used by the Android app and has the expected discovery server and SUS channel values. It is not fully provisioned to a Logitech account because `email`, `username`, `accountId`, and `remoteId` are empty.

The next expected step is app-side account/profile provisioning.
