# iOS — Universal Smart Remote (Phase 3)

Swift native module `SmartRemoteNative` for the React Native 0.73.6 app:
discovery + network info only (CONTRACTS.md §3). It never sends remote keys.

> **Status: written, NOT compiled or run.** There is no Mac/Xcode on the
> machine this was written on (`swiftc` is not installed; see
> "Verification" below), so nothing here has been built against the React
> Native headers or tested on a real iPhone. **NEEDS ON-DEVICE
> VERIFICATION** before it can be trusted. Do not present it as working
> until the Xcode build + on-device test below have passed.

## Files

```
mobile/ios/
  Podfile                                  # stock React Native 0.73 Podfile
  README.md                                # this file
  UniversalSmartRemote/
    Info.plist                             # app plist incl. Local Network keys
    UniversalSmartRemote-Bridging-Header.h # exposes RCT headers to Swift
    SmartRemoteNative.swift                # RCTEventEmitter module (bridge)
    SmartRemoteNative.m                    # RCT_EXTERN_MODULE declarations
    NetworkInfoProvider.swift              # NWPathMonitor + SSID + getifaddrs
    Discovery.swift                        # Bonjour + SSDP discovery engine
```

There is deliberately **no `.xcodeproj`** in this repo: an Xcode project
cannot be produced without a Mac/Xcode. Generate it on a Mac as described
below, then copy these files into it.

## Bridge contract (CONTRACTS.md §3)

Module name (both platforms): `SmartRemoteNative`. Promise methods:

| Method | Result |
| --- | --- |
| `getNetworkInfo()` | `{connected, isWifi, isCellular, ssid, bssid, ipAddress, subnetMask, gateway}` — `null` where the OS does not permit the value, never invented |
| `isWifiConnected()` | `Bool` |
| `startDiscovery()` | resolves once browsing is confirmed running; emits `TvDiscovered` per TV found |
| `stopDiscovery()` | resolves once discovery is stopped |

Events (exact names): `TvDiscovered` `{tv: DiscoveredTv}`,
`NetworkChanged` `{connected, ssid, ipAddress}`.

Notes vs. the Android module (Phase 2):

- Android emits the `DiscoveredTv` map as the bare event payload; iOS
  emits `{tv: …}` per the §3 text. The TypeScript wrapper
  (`mobile/src/services/native.ts`) accepts both shapes, so the app
  behaves identically either way.
- `gateway` is always `null` on iOS: there is no public API for the
  default gateway. (A sysctl route-table dump could in principle recover
  it, but that pointer walk was deliberately not attempted without a Mac
  to test it against.)
- `ssid`/`bssid` are `null` unless the app has the **Access WiFi
  Information** capability — see below. The module never invents an SSID.

## Generating the Xcode project (on a Mac)

1. In a scratch directory (not this repo), scaffold a throwaway RN 0.73.6
   app with the same name, e.g.:
   `npx react-native@0.73.6 init UniversalSmartRemote --version 0.73.6`
   (or `npx @react-native-community/cli@11 init …`; either way, use the
   0.73.6 template so the versions match `mobile/package.json`).
2. Copy the scaffold's `ios/UniversalSmartRemote.xcodeproj`,
   `ios/UniversalSmartRemote/AppDelegate.mm`,
   `ios/UniversalSmartRemote/main.m`,
   `ios/UniversalSmartRemote/LaunchScreen.storyboard` and
   `ios/UniversalSmartRemoteTests/` into `mobile/ios/` (the `.xcodeproj`
   is the only part this repo cannot supply).
3. Copy this directory's files over the scaffold's `ios/`:
   `Podfile`, `UniversalSmartRemote/Info.plist`, and the four source files
   in `UniversalSmartRemote/`. In Xcode, confirm the four sources are
   members of the `UniversalSmartRemote` app target (Target Membership).
   The `Info.plist` here is the stock 0.73 template plist plus the
   Local Network keys; the scaffold's own `Info.plist` can be discarded.
4. In the target's **Build Settings**, set:
   - **Objective-C Bridging Header** to
     `UniversalSmartRemote/UniversalSmartRemote-Bridging-Header.h`
   - **Swift Language Version** to `Swift 5` (Xcode's default for a new
     Swift file is normally fine — just verify it).
   - **Product Bundle Identifier** to
     `com.universalremote.UniversalSmartRemote` (matches Android's
     `applicationId` `com.universalremote`).
5. `cd mobile/ios && pod install`, then open
   `UniversalSmartRemote.xcworkspace` (never the `.xcodeproj`) and build.

### Autolinking

The Swift module is part of the **app target**, not a pod or library, so
there is nothing for CocoaPods autolinking to do for it. Registration
happens through `RCT_EXTERN_MODULE(SmartRemoteNative, RCTEventEmitter)`
in `SmartRemoteNative.m` plus the `@objc(SmartRemoteNative)` Swift class;
React Native discovers the module at bridge startup. No `AppDelegate`
changes are needed.

## Capabilities / entitlements

- **Access WiFi Information** (`com.apple.developer.networking.wifi-info`) —
  **add this** in Xcode under Signing & Capabilities. Without it,
  `CNCopyCurrentNetworkInfo` and `NEHotspotNetwork.fetchCurrent` both
  return nothing on iOS 13+, so `ssid`/`bssid` are `null`. This is a
  standard capability (no Apple approval needed). With it, no location
  permission is required for the SSID, and the module does not request
  location at all. (No `NSLocationWhenInUseUsageDescription` is shipped
  for that reason; if the capability is ever dropped and SSID-via-location
  is wanted instead, that key plus a Core Location request flow would
  need adding — it is not implemented here.)
- **Multicast Networking** (`com.apple.developer.networking.multicast`) —
  only needed if SSDP discovery must work. On iOS 14+, sending/receiving
  IP multicast requires this entitlement, which Apple grants only on
  request (developer.apple.com → Certificates, Identifiers & Profiles →
  request the Multicast Networking entitlement, justifying local device
  discovery). **Without it, SSDP silently finds nothing** — the socket
  cannot join the 239.255.255.250 group — and Bonjour is the only
  discovery path. The code handles that gracefully (logs, continues with
  Bonjour) and never fakes SSDP results.

## Permissions at runtime (Local Network, iOS 14+)

- The first Bonjour browse triggers the system "Local Network" prompt.
  `Info.plist` carries `NSLocalNetworkUsageDescription` and
  `NSBonjourServices` (`_googlecast._tcp`, `_airplay._tcp`, `_http._tcp` —
  every type the module browses for; iOS refuses unlisted types).
- **Denied:** the browse fails via `netServiceBrowser(_:didNotSearch:)`
  and `startDiscovery()` rejects with code `LOCAL_NETWORK_DENIED` and a
  message pointing at Settings → Privacy & Security → Local Network.
  The promise has a 3-second grace period: it resolves as soon as
  browsing is confirmed running (first TV found, or the timeout), so if
  the user takes longer than 3 s to answer the prompt it still resolves
  and discovery continues; a denial after that surfaces on the next
  `startDiscovery` call, which fails immediately with no new prompt.
- The module requests no other permission. SSID does not need location
  (see above); discovery does not need Bluetooth or location.

## How discovery works

- **Bonjour** (`NetServiceBrowser`, one browser per type, on the main
  run loop): `_googlecast._tcp`, `_airplay._tcp`, `_http._tcp`, resolved
  with an 8 s timeout. Brand is best-effort from service name + TXT
  record (`md`/`model`/`fn`); `"unknown"` when indeterminable. A bare
  Cast receiver with no recognisable model is `"unknown"` — a Chromecast
  dongle is not an Android TV, and guessing would send the connect flow
  down the wrong adapter. AirPlay `deviceid` is used as `mac` only when
  it is shaped like a MAC address. IPv6-only services are skipped (the
  contract carries an IPv4 `ip`).
- **SSDP**: M-SEARCH (ST `ssdp:all`, `upnp:rootdevice`,
  `urn:samsung.com:device:RemoteControlReceiver:1`,
  `urn:dial-multiscreen-org:service:dial:1`) over a non-blocking UDP
  socket bound to :1900, re-sent every 4 s, responses parsed like the
  Android module (LOCATION → ip/port, SERVER/USN/ST → brand, description
  XML → friendlyName/modelName, 2 s timeout). `mac` is `null` — SSDP
  carries no MAC address. Requires the multicast entitlement (above).
- `NetworkChanged` is driven by `NWPathMonitor` and deduped on
  `(connected, ssid, ip)` so repeated callbacks do not spam the JS side.

## Verification

What was done on this (Linux) machine — and what was **not**:

- [x] Read `CONTRACTS.md` §3/§6/§7, `mobile/src/services/native.ts`,
      `mobile/src/types.ts`, and the Android module
      (`SmartRemoteNativeModule.java`) and matched the method/event names,
      payload shapes and error behaviour against them.
- [x] `Info.plist` parsed and validated with Python `plistlib`
      (well-formed XML, all keys present — see command below).
- [x] Manual self-review of the Swift against the `RCTEventEmitter` /
      `RCTBridgeModule` patterns (module name via `@objc`, `supportedEvents`,
      `requiresMainQueueSetup`, `RCT_EXTERN_METHOD` signatures matching the
      Swift `@objc` methods, Bonjour delegates on the main run loop, BSD
      socket lifecycle via `DispatchSource` cancel handlers).
- [ ] **NOT done — needs a Mac:** `swiftc` is not installed on this VM
      (verified: `which swiftc` → not found), so the Swift has never been
      type-checked, let alone compiled against the React Native headers.
      `ruby` is also absent, so the Podfile could not be syntax-checked
      either.
- [ ] **NOT done — needs an iPhone:** Xcode build, `pod install`, the
      Local Network prompt + deny path, Bonjour discovery against a real
      TV, SSDP with/without the multicast entitlement, SSID with/without
      the wifi-info capability, and `NetworkChanged` on Wi-Fi drop/rejoin.

To validate the plist on any machine with Python 3:

```sh
python3 -c "import plistlib; plistlib.load(open('mobile/ios/UniversalSmartRemote/Info.plist','rb')); print('Info.plist OK')"
```

## TODOs / known limitations

1. **Xcode build + on-device test** (above) — the single biggest item.
   Until then this is uncompiled code, however carefully reviewed.
2. `gateway` is always `null` (no public iOS API; see "Bridge contract").
3. SSDP is dead without the multicast entitlement — Bonjour only. If
   Apple declines the entitlement, consider dropping the SSDP path and
   documenting Bonjour-only discovery.
4. SSID/`bssid` are `null` without the wifi-info capability.
5. No removal event: a TV that goes offline stays in the JS list until
   the next discovery run (same as Android — no removal event exists in
   the §3 contract).
