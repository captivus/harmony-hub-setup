# App Provisioning E2014 Failure

Timestamp: 2026-05-27T17:28:17-05:00

## User-Observed State

- The Harmony app reports `E2014`.
- User-facing message: failed to retrieve home control device config settings.
- The hub light has gone green.
- The app cannot connect to the Harmony Hub.

## APK Mapping

The decompiled Android app maps `E2014` to:

> Retrieving devices has failed. Please try after sometime.

Relevant decompiled path:

- `tools/harmony-decompiled/sources/com/logitech/harmonyhub/ui/fastsetup/ErrorMessageHelper.java`
- `tools/harmony-decompiled/sources/com/logitech/harmonyhub/sdk/core/fastsetup/communication/JavaScriptInterface.java`
- `home.hub.getPairings` is exposed as `GET_DEVICE_INFO`

This indicates the error is later than Wi-Fi setup and initial LAN discovery. It is associated with retrieving devices/pairings/configuration.

## Live State After App Attempt

The earlier known-good hub endpoint was `<HUB_IP>:8088`.

After the app attempt:

- `<HUB_IP>` no longer responded to LAN setup probes.
- `connect.ping` over `http://<HUB_IP>:8088` timed out.
- Subsequent LAN requests returned `No route to host`.
- Bluetooth status failed with `[Errno 112] Host is down`.
- `ip neigh show` listed `<HUB_IP>` as `INCOMPLETE`.
- A subnet scan for TCP port `8088` found no open Harmony setup endpoint.

## Interpretation

The hub was previously in a measurable ready-for-app-provisioning state, but after the app attempted provisioning and showed `E2014`, the hub was no longer reachable through the local setup endpoint from this machine.

The error likely occurs after initial app discovery, during the app/WebView setup phase that retrieves devices or pairings. This points to a gap beyond basic Wi-Fi association and discovery metadata.
