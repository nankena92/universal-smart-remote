# Universal Smart Remote — Architecture

> Status: Phases 1–12 complete (see the phase table in the root
> [README.md](../README.md)). Every adapter is implemented against the
> documented protocol for its brand, but **no adapter has been exercised
> against a real TV yet** — each one is marked
> `NEEDS ON-DEVICE VERIFICATION` until it has. See
> [supported-tvs.md](supported-tvs.md) and [testing.md](testing.md).

## System overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Phone (Android / iPhone) — React Native 0.73 + TypeScript      │
│                                                                 │
│  screens (10) → services → native bridge OR backend client      │
│     │                                                            │
│     ├─ backend mode: HTTP → FastAPI backend (this repo)         │
│     └─ direct mode: Roku ECP / Samsung / LG WebSocket from JS   │
└─────────────────────────────────────────────────────────────────┘
                    │  same Wi-Fi (subnet check, both sides)
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI backend (Python 3.12, backend/) — LAN only, :8000     │
│                                                                 │
│  routes → services → adapters → TV over its local protocol      │
│  routes: devices / remote / network                             │
│  services: device_service (commands), discovery (SSDP + mDNS)   │
│  security: X-API-Key auth; network: same-subnet validation      │
│  models: SQLite (saved devices + active session)                │
└─────────────────────────────────────────────────────────────────┘
                    │  brand protocol (LAN only)
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  TV: Samsung / LG / Sony / Android TV / Google TV / TCL /       │
│      Roku / Fire TV                                             │
└─────────────────────────────────────────────────────────────────┘
```

The backend is optional for the three direct-mode brands (Roku,
Samsung, LG) but is the only path for Sony, Android TV, Fire TV and
TCL, and the only path that enforces same-Wi-Fi validation
server-side. The native modules never send remote keys — they do
discovery + network info only (CONTRACTS.md §3).

## Components

### Mobile app (`mobile/`)

React Native 0.73.6 + TypeScript (strict), one shared codebase for
Android and iOS. Dark theme, 10 screens:

| Screen | Purpose |
| --- | --- |
| Welcome | First-run intro |
| Home | Connected TV + quick actions |
| Discovery | List of TVs found on the LAN |
| Connect TV | Manual IP / brand connect |
| Pairing | PIN / on-TV prompt pairing flow |
| Remote | Circular D-pad, power/home/back/menu, volume, channel, media |
| Streaming | Netflix / Prime Video / YouTube / Disney+ launch shortcuts |
| Settings | Backend URL + API key, backend/direct mode |
| Network Info | SSID, IP, subnet, validation state |
| Connection Error | Honest error when a command fails |

Key services (`mobile/src/services/`):

- `native.ts` — wraps the `SmartRemoteNative` bridge (discovery +
  network info), normalises Android/iOS payload shapes.
- `api.ts` — FastAPI REST client (all CONTRACTS.md §2 endpoints,
  `X-API-Key` header, request timeout).
- `remote.ts` — unified routing: picks backend vs direct mode and
  revalidates same-Wi-Fi (subnet check against the TV IP) before
  every command.
- `direct/` — `rokuDirect.ts` (ECP HTTP), `samsungDirect.ts`
  (Tizen WebSocket), `lgDirect.ts` (webOS WebSocket).
- `adapters/brandMeta.ts` — per-brand features + streaming app ids
  (mirrors `backend/app/adapters/apps.py`).

### Native modules (`mobile/android/`, `mobile/ios/`)

Module name on both platforms: `SmartRemoteNative`. Promise methods
`getNetworkInfo()`, `isWifiConnected()`, `startDiscovery()`,
`stopDiscovery()`; events `TvDiscovered`, `NetworkChanged`
(CONTRACTS.md §3).

- **Android** (`SmartRemoteNativeModule.java`): SSDP M-SEARCH over UDP
  multicast `239.255.255.250:1900`, Wi-Fi info via Android Wi-Fi APIs,
  network-change events. SSID/BSSID on Android 10+ need location
  permission (declared in `AndroidManifest.xml`, requested at runtime).
- **iOS** (`SmartRemoteNative.swift`, `Discovery.swift`,
  `NetworkInfoProvider.swift`): Bonjour (`NetServiceBrowser` for
  `_googlecast._tcp`, `_airplay._tcp`, `_http._tcp`) + SSDP where
  possible, `NWPathMonitor` for network changes, Local Network
  permission via `NSLocalNetworkUsageDescription`. See
  `mobile/ios/README.md` — **not compiled yet**: there is no
  `.xcodeproj` in this repo and the Swift has never been built against
  the React Native headers. It needs a Mac/Xcode before it can be
  trusted.

### Backend (`backend/`)

Python FastAPI app, entry point `backend/app.py` (the FastAPI
instance; `backend/app/__init__.py` re-exports it — the module and
the package share the name `app`).

| Layer | Files | Responsibility |
| --- | --- | --- |
| Routes | `app/routes/devices.py`, `remote.py`, `network.py` | HTTP endpoints, auth dependency, error mapping (see [api-documentation.md](api-documentation.md)) |
| Services | `app/services/device_service.py` | Command routing, per-command same-Wi-Fi revalidation, adapter loading, app-id resolution, timeouts, honest errors |
| Services | `app/services/discovery.py` | SSDP M-SEARCH + mDNS (zeroconf) discovery, brand guessing, description-XML fetch |
| Adapters | `app/adapters/*.py` | One adapter per brand, all implementing `TvAdapter` (CONTRACTS.md §1) |
| Security | `app/security/auth.py` | `X-API-Key` verification (constant-time compare) |
| Network | `app/network/validation.py` | Local interfaces, subnet membership, `SAME_WIFI_ERROR` |
| Models | `app/models/database.py`, `schemas.py` | SQLite persistence, Pydantic request models |

**SQLite** (`backend/smart_remote.db` by default, overridable with
`SMART_REMOTE_DB`): `devices` table (saved/paired TVs, incl.
`pairing_token` and `last_connected`) and a single-row active-session
pointer. Disconnect clears the session but keeps the saved device.

### Brand adapters (`backend/app/adapters/`)

All implement `TvAdapter` from `base.py`: `connect()`,
`disconnect()`, `send_key(key: RemoteKey)`, `launch_app(app_id)`,
`supports(feature)`, `get_status()`. Registry in `__init__.py`:
`BRANDS` + `get_adapter(device)` (lazy imports, honest errors for
unknown brands). `googletv` is an alias of the Android TV adapter.
`tcl` delegates to Roku or Android TV based on the discovered
model/OS string and refuses (honest error) when the OS cannot be
determined — it never guesses. `mock` is returned only when the
backend was started with `MOCK_TV=true`.

Streaming app ids live in `apps.py` (`STREAMING_APPS`,
`get_app_id()`); `None` means "no documented id / not supported" and
`launch_app` must return an honest error, never a guessed id. Per-brand
protocol details and limitations are in [supported-tvs.md](supported-tvs.md).

## Data flow

### Connect (backend mode)

```
App → POST /devices/connect {ip, brand}   (X-API-Key)
  → routes/devices.py: resolve saved device or build row
  → device_service.connect_device:
      1. assert_same_subnet(ip)          → 403 if off-LAN
      2. get_adapter(device)             → 503 if brand unknown/missing
      3. adapter.connect() (≤15 s)       → 503 on refusal/timeout
      4. save device + set active session in SQLite
  → {success, connected, device_id, name, brand, ip, message}
```

Pairing happens inside `connect()` for Samsung (on-TV Allow prompt,
token stored as `pairing_token`) and LG (register handshake,
`client-key` stored). Android TV pairing spans two requests:
`connect()` runs the Polo handshake up to the point the TV displays
its 6-character code and returns HTTP 200 with `{"success": true,
"connected": false, "pairing_required": true, ...}` — the device is
saved (unpaired) and the **live adapter instance is kept server-side**
(the pairing session lives on it), so `POST /devices/pair
{device_id, pin}` can finish the handshake on that same instance.
The app routes to the Pairing screen on `pairing_required`. The
session is in-memory only: a server restart loses it, and the user
must connect again for a fresh code (an honest error, not a stale
pairing attempt). Adapters without a `pair()` method (Samsung, LG,
Roku, Sony, Fire TV) make `/devices/pair` return an honest 422
explaining that pairing happens on the TV — never a fake success.

### Remote key (backend mode)

```
App → POST /remote/up {}                 (X-API-Key)
  → routes/remote.py → device_service.send_key("up"):
      1. resolve target (explicit device_id or active session)
         → 404 if nothing connected
      2. assert_same_subnet(device ip)   → 403 if the TV moved off-LAN
      3. adapter.supports(feature)       → 422 if unsupported
      4. adapter.send_key(RemoteKey.UP) (≤10 s)
         → 503 if the TV refuses / times out
  → {success, key, message}
```

`POST /remote/launch-app {app}` adds one step before the adapter
call: resolve the brand app id via `apps.py` → 422 when the brand has
no documented id for that app (e.g. any app on Sony, Disney+ on
Samsung/LG).

### Discovery

```
App → GET /devices/discover              (X-API-Key)
  → discovery.discover_devices(4.0 s):
      SSDP M-SEARCH (239.255.255.250:1900, ST ssdp:all) →
        fetch each LOCATION description XML (friendlyName,
        manufacturer, modelName) → guess brand from headers/text
      mDNS browse (_googlecast/_airplay/_http) via zeroconf →
        brand from TXT properties / service name
      dedupe by IP (SSDP wins); mark paired if saved in SQLite
  → {success, data: [{id, name, brand, model, ip, port, mac, paired}]}
```

`brand` is best-effort; `"unknown"` when it cannot be determined.
Discovery never invents a TV: an empty LAN returns an empty list.

### Network status

```
App → GET /network/status                (X-API-Key)
  → validation.network_status():
      local interfaces via `ip -o -f inet addr show`
      (socket fallback, /24 assumption, documented in code)
      ssid via `iwgetid -r` (Linux); phone_ip is always null —
      the backend cannot know the phone's IP, so it says so
  → {wifi_connected, ssid, phone_ip, backend_ip, subnet,
     validation: "verified"|"failed", message}
```

### Direct mode (no backend)

```
App → remote.ts → direct/rokuDirect.ts   → http://<tv>:8060/keypress/Up
              → direct/samsungDirect.ts → ws://<tv>:8001/... (or wss :8002)
              → direct/lgDirect.ts      → ws(s)://<tv>:3000|3001
```

Same-Wi-Fi is revalidated in `remote.ts` before every command
(subnet check, not just SSID match). Sony, Android TV, Fire TV and
TCL are honestly refused in direct mode.

## Module map

```
universal-smart-remote/
  CONTRACTS.md            Shared contracts (§1 adapter interface,
                          §2 API, §3 native bridge, §4 same-Wi-Fi,
                          §5 protocols, §6 ownership, §7 rules)
  README.md               Project overview + phase status
  documentation/          architecture.md (this file),
                          api-documentation.md, supported-tvs.md,
                          installation-guide.md, testing.md
  mobile/
    src/                  App, screens, components, services, hooks,
                          utils, theme, types, navigation
    android/              Java native module, manifest, gradle
                          (applicationId com.universalremote)
    ios/                  Swift native module, Info.plist, Podfile
                          (bundle id com.universalremote.UniversalSmartRemote)
  backend/
    app.py                FastAPI app + exception handlers + /health
    requirements.txt      fastapi, uvicorn, websockets, httpx,
                          pydantic, anyio, zeroconf, cryptography,
                          pytest, pytest-asyncio
    app/
      routes/             devices.py, remote.py, network.py
      services/           device_service.py, discovery.py
      adapters/           base.py, __init__.py (registry), apps.py,
                          samsung.py, lg.py, sony.py, android_tv.py,
                          roku.py, tcl.py, fire_tv.py, mock.py
      security/           auth.py
      network/            validation.py
      models/             database.py, schemas.py
    tests/                conftest.py + test_auth.py, test_api.py,
                          test_network.py, test_adapters_samsung_lg.py,
                          test_adapters_other.py, test_integration.py
```

## Security model

LAN-only by design (CONTRACTS.md §4). Nothing here is safe to expose
to the internet, and the code is written to assume it never is:

- **Same-subnet enforcement.** The backend only talks to TVs whose IP
  is in the same subnet as one of its own local interfaces
  (`ipaddress` module). Anything else is rejected with 403 and the
  exact message *"Your TV and smartphone must be connected to the same
  local Wi-Fi network."* The check runs on connect **and before every
  command** (the command service revalidates the connected device's IP
  against current interfaces on each call), so a TV that moves off the
  LAN mid-session is refused. Public IPs are never accepted; loopback
  is accepted only for the mock adapter (`MOCK_TV=true`). The mobile
  app does the same subnet check in `remote.ts` before every command.
- **API key.** Every endpoint except `GET /health` requires the
  `X-API-Key` header. The key comes from `SMART_REMOTE_API_KEY`; if
  unset, an ephemeral key is generated once per process and printed /
  logged at startup (a restart generates a new one). Comparison is
  constant-time (`secrets.compare_digest`). The key is a shared secret
  for the local network, not a substitute for keeping the backend off
  the internet: the server binds `0.0.0.0:8000` so the phone can reach
  it, and **must never be port-forwarded**.
- **No TLS on the backend.** Traffic is plain HTTP on the LAN by
  design; the threat model is "anyone on your Wi-Fi can already see
  your TVs". Do not run this on a network you do not trust, and do
  not put it behind a reverse proxy that reaches the internet.
- **Pairing credentials.** Samsung tokens and LG `client-key`s are
  stored in SQLite (`pairing_token`) so later connects reuse them
  without a new prompt. Android TV pairing certificates are stored
  the same way. They are LAN credentials for the user's own TVs, not
  passwords — but the DB file should still not be shared or published.
- **TV-side auth is never bypassed.** Sony requires a pre-shared key
  (PSK) configured on the TV; Fire TV requires ADB debugging enabled
  *and* authorised on the TV; Android TV requires the on-TV pairing
  code. Where a brand needs a prompt, the adapter surfaces it and
  waits; a denied prompt is an honest error, never a silent success.
  (Note: the command service wraps `connect()` in a 15 s timeout even
  though the Samsung/LG adapters allow up to 60 s for the prompt, so
  accept the prompt quickly or retry the connect.)
- **Self-signed TV certificates.** Samsung (`wss://:8002`) and LG
  (`wss://:3001`) use self-signed certificates, so those adapters use
  an unverified SSL context. This is LAN-only traffic to the user's
  own TV; the alternative (verifying a cert the TV generates itself)
  is not possible.
- **No cloud control.** No public-IP discovery, no commands over
  cellular, no account, no telemetry, no data leaves the LAN.

## Honest-error model

Every command returns the real result or a real error — never a fake
`success: true`. The mapping (routes `_http_error`):

| Situation | HTTP | Body |
| --- | --- | --- |
| Missing / wrong API key | 401 | `{"success": false, "error": "Missing or invalid API key."}` |
| TV off the LAN | 403 | `{"success": false, "error": "Your TV and smartphone must be connected to the same local Wi-Fi network."}` |
| No TV connected / unknown device id | 404 | `{"success": false, "error": "No TV is connected. Connect to a TV first."}` (or similar) |
| Bad input (missing fields, unknown app) | 400 / 422 | validation message |
| Feature / app not supported for the brand | 422 | `"<app> is not supported/unknown for <brand> — no documented app id exists for this brand."` etc. |
| Adapter missing / TV refuses / timeout / unreachable | 503 | the adapter's honest error, e.g. `"The TV refused the command."` |

The last error is also surfaced via `GET /devices/connection-status`
(`last_error`) so the app can show it without a new request.
