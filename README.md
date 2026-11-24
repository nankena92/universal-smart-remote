# Universal Smart Remote

A cross-platform smartphone application that controls Smart TVs over the local
Wi-Fi network — like a real physical remote, for Android and iPhone.

**Supported brands:** Samsung (Tizen), LG (webOS), Sony Bravia, Android TV,
Google TV, TCL, Roku TV, Amazon Fire TV — each through its own modular adapter
using the brand's documented local protocol. No cloud control: the phone and
the TV must be on the same local Wi-Fi network.

## Current status — Phases 1–12 complete

| Phase | Scope | Status |
|---|---|---|
| 1 | React Native + TypeScript mobile app (all 10 screens, remote, streaming shortcuts, services) | **Done — committed** |
| 2 | Android Java native modules (SSDP discovery, Wi-Fi info, network-change events) | **Done — committed** |
| 3 | iOS Swift native modules (Bonjour/mDNS discovery, Local Network permission, network-change events) | **Done — committed** (code written, **not compiled**: no `.xcodeproj`, needs a Mac/Xcode — see `mobile/ios/README.md`) |
| 4 | Python FastAPI backend (routes, services, SQLite, auth) | **Done — committed** |
| 5 | Same-Wi-Fi network validation (backend) | **Done — committed** |
| 6 | TV discovery & pairing (backend) | **Done** (backend committed; mobile-screen wiring in progress, uncommitted) |
| 7 | Samsung + LG adapters | **Done — committed** |
| 8 | Android TV + Google TV adapters | **Done — committed** |
| 9 | Roku, Sony, TCL, Fire TV, Mock adapters | **Done — committed** |
| 10 | Streaming shortcuts (backend-driven) | **Done** (backend committed; mobile-screen wiring in progress, uncommitted) |
| 11 | Integration testing | **Done** (147 backend tests green; see [documentation/testing.md](documentation/testing.md)) |
| 12 | Documentation + Android/iOS build preparation | **Done** |

> **Honest status:** all twelve phases are implemented and the backend test
> suite is green, but **no adapter has been exercised against a real TV
> yet** and the iOS native module has never been compiled. Every adapter is
> marked `NEEDS ON-DEVICE VERIFICATION` until it has been. See
> [documentation/testing.md](documentation/testing.md) for what was actually
> tested vs what still needs a real TV and a real phone.

## Project structure

```
universal-smart-remote/
  CONTRACTS.md        Shared contracts every phase builds against
                      (API endpoints, adapter interface, native bridge)
  README.md           This file
  documentation/      architecture.md, api-documentation.md,
                      supported-tvs.md, installation-guide.md, testing.md
  mobile/             React Native + TypeScript app (Phase 1)
    src/              components, screens, navigation, services,
                      adapters, hooks, utils
    android/          Java native modules (Phase 2) + gradle build
                      (applicationId com.universalremote)
    ios/              Swift native modules (Phase 3) + Info.plist
                      (bundle id com.universalremote.UniversalSmartRemote)
  backend/            Python FastAPI backend (Phases 4–5)
    app/              routes, services, adapters, models, security, network
    app.py
    requirements.txt
    tests/            143 tests (Phases 4–5, 7–9, 11)
```

## Run the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
SMART_REMOTE_API_KEY=<a-long-random-key> python app.py
# binds 0.0.0.0:8000 — LAN only, never port-forward port 8000
```

Verify: `curl http://<backend-ip>:8000/health` →
`{"success": true, "status": "ok"}`. Run the tests:
`python -m pytest tests/ -q` (147 passed).

## Run the mobile app

```bash
cd mobile
npm install
npm start          # Metro bundler
npm run ios        # iOS simulator (macOS + Xcode)
npm run android    # Android emulator / connected device
```

First launch: open **Settings**, set the backend URL to
`http://<backend-ip>:8000` and enter the API key, then go to
**Discovery** and pick your TV.

Verify the app code:

```bash
cd mobile
npm run typecheck  # tsc --noEmit (strict)
npm run lint       # eslint
```

Full install/run instructions, per-brand TV setup, iOS signing
checklist and Android release-signing steps:
[documentation/installation-guide.md](documentation/installation-guide.md).
Mobile-specific notes: [mobile/README.md](mobile/README.md).

## Documentation

- [documentation/architecture.md](documentation/architecture.md) —
  system architecture, data flows, module map, security model.
- [documentation/api-documentation.md](documentation/api-documentation.md) —
  every backend endpoint with request/response examples and error codes.
- [documentation/supported-tvs.md](documentation/supported-tvs.md) —
  per-brand protocol, pairing, features and honest limitations.
- [documentation/installation-guide.md](documentation/installation-guide.md) —
  prerequisites, backend/mobile install, LAN setup, troubleshooting,
  Android release signing, iOS signing checklist.
- [documentation/testing.md](documentation/testing.md) — test plan:
  what was actually tested (automated) vs what still needs a real
  TV/device.
- [CONTRACTS.md](CONTRACTS.md) — the shared contracts all phases
  build against.

## Security model

- Local network only. The backend validates that the TV is on the same
  subnet as the phone/backend before every command — SSID matching alone
  is not trusted. The exact rejection message is: *"Your TV and
  smartphone must be connected to the same local Wi-Fi network."*
- No cloud remote control, no public-IP discovery, no commands over
  cellular. The backend binds to the LAN only and must never be
  port-forwarded.
- All endpoints except `GET /health` require the `X-API-Key` header
  (`SMART_REMOTE_API_KEY` env var; an ephemeral key is generated and
  printed at startup if unset).
- Pairing / authentication is never bypassed: Samsung (on-TV Allow
  prompt, token stored), LG (register handshake, `client-key` stored),
  Android TV (on-TV 6-character code), Sony (pre-shared key on the TV),
  Fire TV (ADB debugging enabled and authorised on the TV). Pairing
  credentials are stored in the local SQLite DB, never in plain text in
  the app.
- The mock TV adapter is reachable only when the backend is started
  with `MOCK_TV=true` (testing only).

## Honest limitations

- **No real TV has been controlled by this codebase yet.** Every
  adapter follows its brand's documented protocol and is unit-tested,
  but all of them are marked `NEEDS ON-DEVICE VERIFICATION`.
- **The iOS native module has never been compiled.** There is no
  `.xcodeproj` in this repo and no Mac was available; see
  `mobile/ios/README.md` for the steps to generate it and build.
- **Power-on from standby is not supported on Samsung or LG**
  (standby closes the control channel; no Wake-on-LAN is implemented).
  Power works while connected (i.e. power off). Roku power-on depends
  on the TV's network-standby setting.
- **Sony cannot launch streaming apps** (IRCC-IP has no app-launch
  capability) — launching any app on Sony returns an honest 422.
  Disney+ cannot be launched on Samsung or LG (no documented app id
  used, per the contract).
- **Android TV app launch needs ADB** installed on the backend host;
  without it, launching returns an honest error. Fire TV works only
  over ADB (debugging enabled and authorised on the TV).
- **TCL delegates by OS**: Roku-OS models use the Roku adapter,
  Android/Google TV models use the Android TV adapter. If the OS
  cannot be determined from discovery, connect fails with an honest
  error asking the user to pick the OS manually — it never guesses.
- **LG mute mutes only** (it does not toggle back); LG volume uses the
  documented `ssap://audio/volumeUp` / `volumeDown` calls.
- Samsung/LG direct secure WebSocket connections (`wss://`) use
  self-signed TV certificates; React Native's `WebSocket` exposes no
  certificate bypass, so secure direct connections may be rejected
  on-device. Backend mode is the reliable path until verified on a
  real TV.
- Features a brand does not support are reported as unsupported, never
  faked. Every command returns the real result or a real error.
