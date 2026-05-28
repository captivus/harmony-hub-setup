# Android Provisioning Workflow

Timestamp: 2026-05-27T20:56:38-05:00

## Correction

The relevant Android workflow is not simply "local setup" followed by "phone app setup." The decompiled Android app has three connected setup/provisioning layers:

1. Bluetooth preparation and Wi-Fi attachment.
2. Pre-account hub interrogation over the setup WebView/JavaScript bridge.
3. Account provisioning and post-provision resource synchronization.

The user-facing "phase one / phase two" boundary should be derived from these layers, not from a generic local/app handoff.

## Layer 1: Bluetooth Preparation And Wi-Fi Attachment

Primary files:

- `<decompiled-app>/sources/com/logitech/harmonyhub/ui/setup/fragment/PrepareBTHelpher.java`
- `<decompiled-app>/sources/com/logitech/harmonyhub/sdk/HubSetupManager.java`
- `<decompiled-app>/sources/com/logitech/harmonyhub/ui/setup/fragment/SetupWiFiPasswordFragment.java`
- `<decompiled-app>/sources/com/logitech/harmonyhub/ui/setup/SetupWiFiPasswordActivity.java`

Observed sequence:

1. Pair/connect over Bluetooth.
2. `connect.ping` to read hub UID.
3. `wifi.networks` to scan available Wi-Fi.
4. `bt.nonce` to get the encryption nonce.
5. `wifi.connect` with SSID/password/encryption.
6. `wifi.connect` with no data is used as a status/IP query.
7. `setup.account?provision` with empty auth/email and `mode=2` is called after Wi-Fi success.

Source evidence:

- `PrepareBTHelpher` step constants define pair state, hub ID, Wi-Fi scan, and nonce as steps 1-5.
- `PrepareBTHelpher.onComplete` calls `HubSetupManager.getHubUID()`, `HubSetupManager.getWiFiNetworks(true)`, and `HubSetupManager.getBTNonce()` in order.
- `HubSetupManager` defines the exact Bluetooth command strings:
  - `connect.ping`
  - `wifi.networks`
  - `bt.nonce`
  - `wifi.connect`
  - `setup.account?getProvisionInfo`
  - `setup.account?provision`
- The dummy provisioning template is:

```json
{
  "cmd": "setup.account?provision",
  "data": {
    "provisionInfo": {
      "authToken": "",
      "discoveryServer": "***",
      "susChannel": "@@@",
      "email": "",
      "name": "Harmony Hub",
      "mode": "2"
    }
  },
  "id": 1
}
```

`SetupWiFiPasswordFragment.executeResult` and `SetupWiFiPasswordActivity.executeResult` both call `HubSetupManager.setProvision(...)` at result code `10`, after the Wi-Fi path has a hub IP.

## Layer 2: Pre-Account Hub Interrogation

Primary file:

- `<decompiled-app>/sources/com/logitech/harmonyhub/ui/setup/HubInfoHelper.java`

Observed sequence:

1. `home.hub.configure` with hub IP.
2. `home.hub.ping`.
3. `home.hub.getSysInfo`.
4. `home.hub.getProvisionInfo`.
5. `home.initialize`.
6. `home.product.checkGrayMarket`.
7. `home.hub.getPairings`.
8. Firmware update check.

This layer is the bridge from Bluetooth/Wi-Fi setup into the setup web app. It decides whether the hub is usable and gathers `sysInfo`, `provisionInfo`, and RF/device pairing information before account provisioning.

## Layer 3: Account Provisioning And Post-Provision Sync

Primary files:

- `<decompiled-app>/sources/com/logitech/harmonyhub/ui/fastsetup/PrepareHubHelper.java`
- `<decompiled-app>/sources/com/logitech/harmonyhub/sdk/core/fastsetup/communication/JavaScriptInterface.java`
- `<repo>/research/setup-webapp/en.main.js`

`PrepareHubHelper` names the account provisioning steps:

1. `PREPARE_STEP_UPDATE_SETUP_SESSION`
2. `PREPARE_STEP_SET_PROVISION`
3. `PREPARE_STEP_GET_HOUSEHOLD`
4. `PREPARE_STEP_SYNC`
5. `PREPARE_STEP_GET_POLICY`
6. `PREPARE_STEP_GET_CAPABILITIES`
7. `PREPARE_STEP_GET_AUTOMATION_CONFIG`
8. `PREPARE_STEP_GATEWAY_STATUS`
9. `PREPARE_STEP_MOOSEHEAD`
10. `PREPARE_STEP_COMPLETED`

The Android Java bridge method `JavaScriptInterface.setProvision(accountId, callback)` does not directly send a `setup.account?provision` payload itself. It builds:

```json
{
  "clientInfo": {
    "clientOS": "Android <version>",
    "appVersion": "<app version>",
    "clientDevice": "type:phone/tablet, manufacturer:<manufacturer>"
  },
  "accountId": "<account id>"
}
```

and calls the setup web app method `home.hub.provisionHub`.

The setup web app then performs hub-mode provisioning:

1. `getAuthenticatedUserAuthToken({ accountId })`
2. Builds provision info with:
   - `authToken: UserAuthToken`
   - `discoveryServer`
   - `susChannel`
   - `email`
   - `name`
   - `mode: RemoteMode.Hub` (`3`)
3. Sends `setup.account?provision` through `saveProvisionInfo`.
4. Fetches access policy.
5. Runs `setup.sync`.
6. Fetches household and hub resources.
7. Fetches automation config via `home.hub.automation.get`, which maps to `proxy.resource?get`.

## Secured Request Boundary

After hub-mode provisioning, `setup.account?getProvisionInfo` can return:

- `mode=3`
- `accountId`
- `activeRemoteId`
- `se=true`

At that point, the setup web app switches many hub requests from plaintext JSON to encrypted `application/octet-stream`.

The encryption branch in `research/setup-webapp/en.main.js`:

- Builds request JSON with `id`, `cmd`, optional `params`, and `timeout`.
- Uses AES-CBC with an all-zero IV.
- Uses key `hubSecret` from account policy if available, otherwise `btNonce`.
- Sends encrypted hex as `application/octet-stream`.

If neither policy hub secret nor Bluetooth nonce is available, the web app surfaces 417-style missing-data failures. This matches the live observation where plain JSON post-provision commands returned HTTP 417 while `setup.account?getProvisionInfo` still worked.

## Correct Phase Interpretation

The Android-derived phases should be:

### Phase 1: Bluetooth/Wi-Fi preparation plus dummy discovery provisioning

Ends when:

- Hub has joined Wi-Fi.
- Hub IP is known.
- Bluetooth nonce has been collected.
- Dummy `mode=2` discovery provisioning has succeeded.
- Basic pre-account hub interrogation can start.

### Phase 2: Hub account provisioning plus restore/sync/resource fetch

Starts with:

- Account selection/login.
- `home.hub.provisionHub(accountId, clientInfo)`.

Includes:

- `GetAuthenticatedUserAuthToken`
- hub-mode `setup.account?provision` with `mode=3`
- access policy retrieval
- `setup.sync`
- hub capabilities
- automation config fetch
- gateway status / Moosehead checks

E2014 belongs to Phase 2, specifically the automation config fetch path after sync, not Phase 1.

## Implications For The UV Tool

The UV tool currently covers much of Phase 1 and has started implementing Phase 2 primitives, but the Android workflow shows two important corrections:

1. Dummy `mode=2` provisioning is real Android behavior, but it is not the account provisioning step. It should be treated as the end of Phase 1, not as a partial replacement for Phase 2.
2. Phase 2 must go through `home.hub.provisionHub` semantics: get `UserAuthToken`, provision with `mode=3`, then handle secure local hub requests using policy hub secret or Bluetooth nonce.

The next implementation target should be a Phase 2 runner that preserves this order:

1. Login / obtain account id.
2. `GetAuthenticatedUserAuthToken(accountId)`.
3. Send hub-mode `setup.account?provision` with `mode=3` and Android-like `clientInfo`.
4. Fetch or retain encryption key (`hubSecret` or `btNonce`).
5. Run encrypted `setup.sync`.
6. Run encrypted `proxy.resource?get` for `dynamite://HomeAutomationService/Config/`.
