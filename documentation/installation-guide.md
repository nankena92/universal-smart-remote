# Universal Smart Remote — Installation Guide

## Prerequisites

| Component | Required |
| --- | --- |
| Backend host | Any machine on the same Wi-Fi as the TV: Linux, macOS or Windows. Python 3.10+ (developed/tested on 3.12). |
| Phone | Android 5.0+ (minSdk 21) or iPhone (iOS 13+ target of the RN 0.73 template). The phone and the TV must be on the **same local Wi-Fi network**. |
| TV | One of the brands in [supported-tvs.md](supported-tvs.md), on the same Wi-Fi, with its brand-specific setup done (see "Per-brand TV setup"). |
| Build machine (mobile) | Node.js 18+ and npm. iOS: macOS with Xcode 15+ and CocoaPods. Android: Android Studio with SDK 34 (build tools 34.0.0, NDK 25.1.8937393). |
| Network | A single LAN (no guest-network isolation, no AP isolation). The backend binds `0.0.0.0:8000`; **never port-forward port 8000**. |

## Backend install & run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt`: fastapi, uvicorn, websockets, httpx, pydantic,
anyio, zeroconf, cryptography, pytest, pytest-asyncio.

### Start the server

```bash
# From backend/ — binds 0.0.0.0:8000, LAN only
SMART_REMOTE_API_KEY=<a-long-random-key> python app.py
# or equivalently:
SMART_REMOTE_API_KEY=<a-long-random-key> uvicorn app:app --host 0.0.0.0 --port 8000
```

- **Set `SMART_REMOTE_API_KEY`.** If it is unset, the backend
  generates an ephemeral key once per process and prints/logs it at
  startup. A restart generates a new key, and the phone app's saved
  key stops working — so set the env var for a stable key. Pick a
  long random value (e.g. `python3 -c "import secrets;
  print(secrets.token_urlsafe(32))"`).
- **Do not set `MOCK_TV=true` in normal use.** It enables the mock
  adapter (loopback only) and is for testing only.
- **Database:** devices are stored in SQLite at
  `backend/smart_remote.db` by default; override with
  `SMART_REMOTE_DB=/path/to/db.sqlite`. The file is created on first
  run.
- **Logs:** the server logs a `LAN ONLY. Do NOT port-forward port
  8000` warning at startup. If you see `SMART_REMOTE_API_KEY is not
  set — generated an ephemeral API key`, copy the printed key into
  the phone app's Settings.

### Verify the backend

```bash
curl http://<backend-ip>:8000/health
# {"success": true, "status": "ok"}

curl -H "X-API-Key: <key>" http://<backend-ip>:8000/network/status
# {"success": true, "wifi_connected": true, ...,
#  "validation": "verified", "message": "Backend is on the local network."}
```

If `validation` is `"failed"`, the host has no non-loopback network
interface — check it is actually connected to Wi-Fi/Ethernet on the
same LAN as the TV.

### Run the backend tests

```bash
cd backend
python -m pytest tests/ -q
# 147 passed (Phases 4–5, 7–9 unit tests + Phase 11 integration tests
# + Phase 6 two-request pairing tests)
```

See [testing.md](testing.md) for what the tests do and do not cover.

## Mobile install & run

```bash
cd mobile
npm install
npm start            # Metro bundler (keep running in its own terminal)
```

Then, in a second terminal:

```bash
npm run ios          # iOS simulator (macOS + Xcode only)
# or: npx react-native run-ios --simulator "iPhone 15"

npm run android      # Android emulator / USB-connected device
# or: npx react-native run-android
```

### First launch — point the app at the backend

1. Open **Settings** in the app.
2. Set the **backend URL** to `http://<backend-ip>:8000` (default is
   `http://192.168.1.100:8000` — change it to your backend host's LAN
   IP; `localhost` will not work from a real phone).
3. Enter the **API key** (the `SMART_REMOTE_API_KEY` value from the
   backend, or the ephemeral key printed at backend startup).
4. Choose the mode: `backend` (recommended — all brands, server-side
   Wi-Fi validation) or `direct` (Roku/Samsung/LG only, phone talks
   to the TV directly).

Then go to **Discovery**, pick your TV, accept any on-TV prompt, and
use the Remote screen.

### Verify the mobile code

```bash
cd mobile
npm run typecheck    # tsc --noEmit (strict)
npm run lint         # eslint
npm test             # jest (no tests in this phase)
```

## LAN setup notes

- **Same Wi-Fi, same subnet.** The phone, the backend host and the TV
  must all be on the same subnet. The backend rejects any TV IP
  outside its own subnets with 403 and the message *"Your TV and
  smartphone must be connected to the same local Wi-Fi network."*
  Guest networks, AP/client isolation and separate VLANs will break
  discovery and control — put everything on the main home Wi-Fi.
- **Multicast matters for discovery.** SSDP discovery sends to
  `239.255.255.250:1900`; mDNS uses Bonjour. Routers that block
  multicast between wireless clients will make discovery return an
  empty list — use manual connect by IP in that case (Connect TV
  screen / `POST /devices/connect {"ip": ..., "brand": ...}`).
- **Static IP / DHCP reservation for the TV (recommended).** Saved
  devices are keyed by IP; if the TV's IP changes, reconnect it (the
  saved record is updated on the next successful connect).
- **Firewall on the backend host:** allow inbound TCP 8000 from the
  LAN only. Do not open it to the internet.

## Per-brand TV setup

| Brand | Before first connect |
| --- | --- |
| Samsung | TV on, on the same Wi-Fi. Accept the Allow prompt on the TV at first connect. |
| LG | TV on, on the same Wi-Fi. Accept the pairing prompt at first connect; the `client-key` is stored for later. |
| Sony | Set a PSK on the TV (Settings → Network → Home Network Setup → IP Control → Pre-Shared Key). The backend must be configured with it (see the Sony adapter notes). |
| Android TV / Google TV | TV on, on the same Wi-Fi. At first connect the TV shows a 6-character pairing code — enter it in the app's Pairing screen. |
| TCL | Know whether the set runs Roku OS or Android/Google TV (check Settings → About on the TV); if discovery cannot tell, the app asks you to pick. |
| Roku TV | TV on, on the same Wi-Fi. No pairing. For power-on from standby, enable "Fast TV Start" / network standby on the TV. |
| Fire TV | Enable ADB Debugging (Settings → My Fire TV → Developer Options → ADB Debugging) and accept the authorisation prompt on the TV the first time the backend connects. Install `adb` (Android platform-tools) on the backend host. |

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `401 Missing or invalid API key` | The key in the app's Settings does not match the backend's `SMART_REMOTE_API_KEY`, or the backend restarted without a stable key and generated a new one. Set `SMART_REMOTE_API_KEY` on the backend and re-enter the key in the app. |
| `403 Your TV and smartphone must be connected to the same local Wi-Fi network.` | Phone/backend/TV are not on the same subnet. Check the Wi-Fi network on each device; move off guest networks / VPNs. See `GET /network/status` (`backend_ip`, `subnet`). |
| Discovery finds nothing | No TV on the LAN, multicast blocked, or the TV's discovery service is off. Try manual connect by IP. On iOS, check the Local Network permission (Settings → Privacy & Security → Local Network) and the multicast entitlement note below. |
| Connect times out / 503 | TV off or unreachable; wrong IP/brand; on-TV prompt not accepted in time (connect wraps at 15 s — accept quickly and retry). Sony: PSK missing/wrong. Fire TV: ADB Debugging off or not authorised, or `adb` not installed on the backend host. Android TV: pairing code expired — reconnect to get a new code. |
| `422 … not supported/unknown for <brand>` | The app/feature genuinely is not supported for that brand (e.g. any app launch on Sony, Disney+ on Samsung/LG). See [supported-tvs.md](supported-tvs.md). Not a bug — do not retry. |
| `422 PIN pairing is not supported …` | That brand pairs on the TV during connect (Samsung/LG) or needs no pairing (Roku). No PIN step exists; connect instead. |
| Remote keys do nothing after connect | The TV may have gone to standby (Samsung/LG cannot be powered on remotely — turn it on with its physical remote first, then reconnect). Or the TV moved to a different subnet — reconnect. |
| Backend `validation: "failed"` | Backend host has no non-loopback interface. Check its network connection. |
| iOS: SSID shows as null | The **Access WiFi Information** capability is missing (see iOS checklist below). |
| iOS: SSDP finds nothing, Bonjour works | The **Multicast Networking** entitlement is missing (see below). |
| Android: SSID shows as null | Location permission not granted (Android 10+ requires it for SSID/BSSID). Grant it in the system prompt / app settings. |

## Build preparation

### Android — release signing

`mobile/android/app/build.gradle` contains a release-signing config
block that reads the keystore from `gradle.properties` (never commit
real credentials — see the commented guidance in the file). Steps to
ship a signed release APK/AAB:

1. Generate a keystore (once, keep it safe — losing it means you can
   never update the Play Store listing):
   ```bash
   keytool -genkeypair -v -keystore universal-smart-remote.keystore \
     -alias universal-smart-remote -keyalg RSA -keysize 2048 \
     -validity 10000
   ```
2. Add to `mobile/android/local.properties` (git-ignored — never put
   these in the tracked `gradle.properties`, and never commit them):
   ```properties
   MYAPP_UPLOAD_STORE_FILE=universal-smart-remote.keystore
   MYAPP_UPLOAD_KEY_ALIAS=universal-smart-remote
   MYAPP_UPLOAD_STORE_PASSWORD=<store password>
   MYAPP_UPLOAD_KEY_PASSWORD=<key password>
   ```
   (A user-level `~/.gradle/gradle.properties` works too.)
3. Build:
   ```bash
   cd mobile/android
   ./gradlew bundleRelease      # AAB for the Play Store
   ./gradlew assembleRelease    # APK
   ```
   Until a real keystore is configured, the `release` buildType falls
   back to the debug keystore (stock React Native 0.73 template
   behaviour) — **do not distribute that build**.
4. The release build enables ProGuard only if
   `enableProguardInReleaseBuilds` is set to `true` in
   `mobile/android/app/build.gradle` (currently `false`); the stock
   `proguard-rules.pro` is present.

Current app identity: `applicationId "com.universalremote"`,
`versionCode 1`, `versionName "1.0"`, minSdk 21, target/compile SDK
34. Bump `versionCode`/`versionName` for each release.

### iOS — signing checklist

> There is **no `.xcodeproj` in this repo** — an Xcode project cannot
> be produced without a Mac. Generate it on a Mac first; the full
> procedure is in `mobile/ios/README.md` (scaffold a throwaway RN
> 0.73.6 app, copy its `.xcodeproj` + `AppDelegate.mm` + `main.m` +
> `LaunchScreen.storyboard` in, then copy this repo's `ios/` files
> over it). The Swift module has never been compiled — **NEEDS
> ON-DEVICE VERIFICATION**.

Checklist (in Xcode, target **UniversalSmartRemote**):

- [ ] **Bundle ID:** `com.universalremote.UniversalSmartRemote`
      (matches Android's `com.universalremote` applicationId family).
- [ ] **Signing:** select your Apple Developer team (Signing &
      Capabilities → Team). Automatic signing is fine for development;
      use a distribution certificate + provisioning profile for
      TestFlight / App Store.
- [ ] **Capability — Access WiFi Information**
      (`com.apple.developer.networking.wifi-info`): **required** for
      the SSID/BSSID. Without it, `CNCopyCurrentNetworkInfo` and
      `NEHotspotNetwork.fetchCurrent` return nothing on iOS 13+, so
      SSID is `null`. Standard capability, no Apple approval needed.
      With it, no location permission is required for the SSID.
- [ ] **Entitlement — Multicast Networking**
      (`com.apple.developer.networking.multicast`): **required for
      SSDP discovery.** On iOS 14+, sending/receiving IP multicast
      requires this entitlement, which Apple grants only on request
      (Certificates, Identifiers & Profiles → request it, justifying
      local device discovery). **Without it, SSDP silently finds
      nothing** — the socket cannot join `239.255.255.250` — and
      Bonjour is the only discovery path. The code handles that
      gracefully (logs, continues with Bonjour) and never fakes SSDP
      results. If Apple declines the entitlement, document Bonjour-only
      discovery.
- [ ] **Local Network usage:** `Info.plist` already carries
      `NSLocalNetworkUsageDescription` ("Universal Smart Remote
      discovers TVs on your Wi-Fi network using Bonjour and SSDP…")
      and `NSBonjourServices` (`_googlecast._tcp`, `_airplay._tcp`,
      `_http._tcp` — every type the module browses; iOS refuses
      unlisted types). The first Bonjour browse triggers the system
      Local Network prompt. If the user denies it, `startDiscovery()`
      rejects with `LOCAL_NETWORK_DENIED` and a message pointing at
      Settings → Privacy & Security → Local Network.
- [ ] **App Transport Security:** `Info.plist` sets
      `NSAllowsLocalNetworking` only — cleartext HTTP is allowed to
      local hosts (the FastAPI backend on `:8000`, Roku ECP on
      `:8060`) while remote hosts stay under full ATS.
- [ ] **Build Settings:** Objective-C Bridging Header →
      `UniversalSmartRemote/UniversalSmartRemote-Bridging-Header.h`;
      Swift Language Version → Swift 5; confirm the four Swift/Obj-C
      sources are members of the app target.
- [ ] `cd mobile/ios && pod install`, then open
      `UniversalSmartRemote.xcworkspace` (never the `.xcodeproj`) and
      build. Run on a real iPhone for discovery/network tests — the
      simulator cannot do Bonjour/SSDP to a LAN TV reliably, and the
      Local Network prompt behaves differently there.
- [ ] **Versioning:** `CFBundleShortVersionString` `1.0`,
      `CFBundleVersion` `1` in `Info.plist`; bump both per release.
