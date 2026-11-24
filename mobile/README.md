# Universal Smart Remote — Mobile App (Phase 1)

React Native 0.73 + TypeScript mobile application for Android and iOS — one shared
codebase. This is **Phase 1** of the Universal Smart TV Remote project: the complete
application interface (all 10 screens, remote controls, streaming shortcuts, and the
services that wire the UI to TV discovery and control).

> Status: Phase 1 complete. Native modules (Phase 2 Android Java, Phase 3 iOS Swift)
> and the Python backend (Phase 4) are not built yet, so on-device discovery and
> network info will report an honest error until those phases land. Nothing in the
> app fakes a connection: it shows "disconnected" until a real connection exists.

## What is in this phase

- **10 screens**: Welcome, Home, Connect TV, Device Discovery, TV Pairing,
  Universal Remote, Streaming Shortcuts, Settings, Network Information,
  Connection Error.
- **Universal remote**: circular D-pad (Up / Down / Left / Right / OK), Power,
  Home, Back, Menu, Settings, Mute, Volume +/-, Channel +/-, media controls
  (Play, Pause, Stop, Rewind, Fast Forward).
- **Streaming shortcuts**: large branded buttons for Netflix, Prime Video,
  YouTube and Disney+. Launching checks the TV is connected, checks the app is
  installed where the protocol allows, sends the real launch command, and shows
  an error when it cannot be done — success is never simulated.
- **Same-Wi-Fi enforcement**: the phone's network is revalidated before every
  command (subnet check against the TV's IP, not just SSID match). On failure
  the app shows: *"Your TV and smartphone must be connected to the same local
  Wi-Fi network."*
- **Two control modes** (Settings screen):
  - `backend` — commands go to the Python FastAPI backend (Phase 4, not built
    yet in this milestone).
  - `direct` — the phone talks to the TV directly: Roku via ECP HTTP,
    Samsung via Tizen WebSocket, LG via webOS WebSocket. Sony, Android TV,
    Fire TV and TCL are honestly refused in direct mode until their native
    paths land.
- **Premium dark theme**: black/charcoal surfaces (`#0A0A0F` / `#1A1A22`), blue
  accent (`#2E7CF6`), rounded buttons, minimum 56px touch targets.

## Project layout

```
mobile/
  index.js                 App entry
  app.json                 App metadata
  package.json             Dependencies + scripts
  tsconfig.json            TypeScript (strict)
  babel.config.js / metro.config.js
  src/
    App.tsx                Navigation container + restore last TV
    theme.ts               Dark theme tokens
    types.ts               Shared types
    navigation/            AppNavigator (all 10 routes)
    screens/               The 10 screens
    components/            DPad, ControlButton, VolumeControl, ChannelControl,
                           MediaControls, StreamingButton, ConnectionBadge,
                           NetworkStatusCard, DeviceListItem, PinPad
    services/              native.ts (SmartRemoteNative bridge wrapper),
                           api.ts (FastAPI REST client),
                           remote.ts (unified routing + Wi-Fi revalidation),
                           direct/ (rokuDirect, samsungDirect, lgDirect)
    adapters/              brandMeta.ts (per-brand features + streaming app ids)
    hooks/                 useTvConnection, useNetworkStatus
    utils/                 network.ts (subnet helpers), storage.ts
```

See `../CONTRACTS.md` for the shared contracts (API endpoints, native bridge,
adapter interface) this code was built against.

## Prerequisites

- Node.js 18+ and npm
- For iOS: macOS with Xcode 15+ and CocoaPods
- For Android: Android Studio with SDK 34, a device or emulator
- React Native CLI (used via `npx`; no global install needed)

## Install

```bash
cd mobile
npm install
```

## Run

```bash
# Start Metro bundler
npm start

# iOS (macOS only) — in a second terminal
npm run ios
# or: npx react-native run-ios --simulator "iPhone 15"

# Android — emulator running or device connected via USB/adb
npm run android
# or: npx react-native run-android
```

First launch shows the Welcome screen. Go to **Settings** first if you want to
point the app at a backend: set the backend URL (default
`http://192.168.1.100:8000`) and the API key, and choose `backend` or `direct`
mode. Without native modules or a backend, discovery and commands will report
an honest error — that is expected in this milestone.

## Verify

```bash
npm run typecheck   # tsc --noEmit (strict)
npm run lint        # eslint
npm test            # jest (no tests in this phase)
```

## Known limitations (Phase 1)

- Native modules (`SmartRemoteNative`) do not exist yet — discovery, Wi-Fi
  info and network-change events come from Phases 2 (Android) and 3 (iOS).
  The app surfaces a clear error instead of fake data until then.
- Samsung (`wss://<tv>:8002`) and LG (`wss://<tv>:3001`) direct connections use
  self-signed certificates; React Native's `WebSocket` exposes no certificate
  bypass, so secure direct connections may be rejected on-device. Backend mode
  is the reliable path until verified on a real TV.
- Samsung power-on is not attempted in direct mode (a TV in standby closes
  the control channel; Wake-on-LAN is out of scope for the mobile app).
- LG volume uses the documented `ssap://audio/volumeUp` / `volumeDown` calls
  (not the `ssap://audio/volume/up` form listed in early notes).
- No tests are included in this phase yet.
