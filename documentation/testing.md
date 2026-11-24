# Universal Smart Remote — Test Plan (Phase 11)

How to run the automated suite, what it actually proves, and what
still needs a real TV and a real phone. This document is deliberately
honest: **a green test suite does not mean the app works on a real
TV.** Every adapter is implemented against its brand's documented
protocol and unit-tested, but none has been exercised against real
hardware yet.

## Running the tests

```bash
cd backend
python3 -m venv /tmp/smart-remote-venv
/tmp/smart-remote-venv/bin/pip install -r requirements.txt
/tmp/smart-remote-venv/bin/python -m pytest tests/ -q
```

Result at Phase 11 completion: **147 passed** (143 from the
pre-existing suite + this phase's 13 integration tests, plus 4
two-request pairing tests added in parallel by the Phase 6 agent —
see `tests/test_pairing.py`). The suite uses `fastapi.testclient.TestClient` against the
real FastAPI app with a temporary SQLite DB (`SMART_REMOTE_DB` points
at a temp dir), `SMART_REMOTE_API_KEY=test-key-123`, and
`MOCK_TV=true`. Adapter tests use stub adapters injected via
`device_service.adapter_factory` or the real `MockAdapter`.

### Suite breakdown

| File | Tests | What it covers |
| --- | --- | --- |
| `tests/test_auth.py` | 5 | 401 on every protected endpoint without/wrong key; `/health` open |
| `tests/test_api.py` | 26 | Connect (by IP / by id / errors), remote keys, launch-app resolution + refusals, pairing, disconnect, discover (canned) |
| `tests/test_network.py` | 12 | Subnet membership boundaries, public/private rejection, loopback + `MOCK_TV` gate, network-status shape, connect-time 403 with exact message |
| `tests/test_adapters_samsung_lg.py` | 33 | Samsung + LG adapters: frames, token/client-key handling, power-on limits, unsupported keys — against recorded/expected protocol behaviour, no TV |
| `tests/test_adapters_other.py` | 54 | Android TV, Roku, Sony, TCL, Fire TV, Mock adapters + registry: delegation, ADB gating, IRCC, app-id table |
| `tests/test_integration.py` | 13 | **Phase 11:** full journeys end to end (see below) |
| `tests/test_pairing.py` | 4 | Two-request PIN pairing flow (Android TV): `connect()` reporting `pairing_required` saves the device unpaired and keeps the live adapter instance so `pair()` finishes the same session (Phase 6, added in parallel) |

### Phase 11 integration tests (`test_integration.py`)

- **Full journey (Roku stub):** discover (canned list) → connect →
  keys `up/down/ok/volume-up/volume-down/power` → launch all four
  apps (`netflix`→`12`, `prime`→`13`, `youtube`→`837`,
  `disney`→`291097`) → disconnect → saved device kept, session
  cleared, next key is 404.
- **Live discover endpoint:** the real SSDP/mDNS sweep runs against
  the sandbox LAN and returns `{"success": true, "data": [...]}` (an
  empty list here — no TVs on the sandbox LAN).
- **Full journey with the real `MockAdapter`** (`MOCK_TV=true`):
  connect → keys → launch-app honestly 422 (the `mock` brand has no
  app ids) → disconnect.
- **Auth rejection:** missing and wrong API key → 401 on connect,
  remote key and network status; `/health` stays open.
- **Same-subnet rejection:** connect to `8.8.8.8` → 403 with the exact
  message; and revalidation before every command — a connected TV
  whose saved IP is changed to a public address is refused with the
  exact 403 on the next key and the next launch.
- **404 when disconnected:** keys and launch-app before any connect,
  after disconnect, and after disconnect-then-reconnect (reconnect by
  saved id works).
- **Pairing flow:** pair-capable adapter completes with PIN `1234`
  (adapter sees the PIN) and without a PIN; adapter without `pair()`
  → honest 422 explaining pairing happens on the TV.
- **Unsupported-brand launch:** Sony + all four apps → 422
  `"not supported/unknown for sony"`; keys still work afterwards;
  unknown app name (`hulu`) → 422 validation error.
- **Network status mid-journey:** shape and `validation` value.

### Live smoke test (run 2026-11-24, sandbox)

Started the real backend with uvicorn
(`SMART_REMOTE_API_KEY=smoke-test-key MOCK_TV=true`, port 8123) and
curled it:

| Check | Result |
| --- | --- |
| `GET /health` (no key) | 200 `{"success": true, "status": "ok"}` |
| `GET /network/status` (no key) | 401 `{"success": false, "error": "Missing or invalid API key."}` |
| `GET /network/status` (correct key) | 200, `wifi_connected: true`, `backend_ip: 198.19.0.2`, `subnet: 198.19.0.0/30`, `validation: "verified"` |
| `GET /devices` (correct key) | 200 `{"success": true, "data": []}` |
| `GET /network/status` (wrong key) | 401 |

Note: `ssid` was `null` in the sandbox (no Wi-Fi interface —
`iwgetid` unavailable), which is the documented best-effort
behaviour, not a failure.

## Test plan — automated vs still needs a real device

Two columns per item: **Automated here** (what the suite actually
ran) vs **Still needs a real TV/device** (what no test in this repo
can prove).

### Android function

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| App builds / runs | TypeScript strict check + lint only (Phase 1; `npm run typecheck`, `npm run lint`). No Android build was run in this phase. | `npx react-native run-android` on an emulator and a real Android phone; Gradle release build; install from the signed APK/AAB. |
| Native module (SSDP discovery, Wi-Fi info, network-change events) | None — Java was read, not executed. | On a real Android phone: discovery finds a real TV; SSID/BSSID appear (location permission granted); `NetworkChanged` fires on Wi-Fi drop/rejoin. |
| Remote keys via backend | Full journey through the API with stub adapters (keys accepted, correct echo, 404/403 paths). | Same keys on a real phone → real backend → real TV: does the TV actually move / change volume / power off? |
| Direct mode (Roku ECP, Samsung/LG WebSocket from JS) | None — direct clients are JS only, untested against a TV. | Real phone on the same Wi-Fi: Roku ECP `keypress`, Samsung `ws://:8001` / `wss://:8002` (self-signed cert behaviour in RN WebSocket), LG `wss://:3001`. |

### iPhone function

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| App builds / runs | Nothing — no Mac/Xcode in this environment; the Swift has never been compiled. | Generate the `.xcodeproj` on a Mac (see `mobile/ios/README.md`), `pod install`, build in Xcode, run on a real iPhone. |
| Native module (Bonjour discovery, SSID, network-change) | None — Swift was read, not executed. | On a real iPhone: Bonjour finds a real TV; Local Network prompt appears and the deny path works (`LOCAL_NETWORK_DENIED`); SSID appears only with the Access WiFi Information capability; `NetworkChanged` via `NWPathMonitor`. |
| Remote keys / streaming via backend | Same backend journey as Android (shared API). | Real iPhone → backend → real TV, all keys and all four app launches. |
| Direct mode on iOS | None. | Same direct-mode checks as Android, on iOS (ATS `NSAllowsLocalNetworking` behaviour with cleartext LAN HTTP). |

### Same-Wi-Fi vs different-Wi-Fi

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| Same-subnet accept | Unit tests on the sandbox host's real interfaces (`198.19.0.2/30`); primary IP accepted; `.1` in-subnet, `.5` out. | Phone + backend + TV on one home Wi-Fi: connect and commands succeed. |
| Different-Wi-Fi / public IP reject | Connect to `8.8.8.8` → 403 exact message; public IPs (`8.8.8.8`, `1.1.1.1`, `203.0.113.10`) and other private subnets (`10.255.255.1`, `192.168.99.99`) rejected in unit tests; command-time revalidation tested by moving a saved device's IP off-LAN. | Phone on mobile data / a different Wi-Fi while the TV stays home: app must show the exact 403 message and refuse. Phone on a guest network with AP isolation: discovery empty + connect refused. |
| Network-change detection | None automated (no network-change simulation in the backend suite). | Real phone: switch Wi-Fi networks mid-session / drop Wi-Fi to cellular — the app must surface the network change (native `NetworkChanged` event) and the next command must fail with the 403 path, not a stale success. Backend side: restart the backend on a different subnet and confirm the saved TV is refused until reconnected. |

### Discovery

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| Endpoint shape / canned list | Canned discovery list returns the contract shape; live endpoint runs the real sweep and returns a list (empty on the sandbox LAN). | Real LAN with real TVs: SSDP responses parsed, description XML fetched, brand guessed correctly per brand (Samsung/LG/Roku/Sony/TCL/Fire TV/Android TV). |
| mDNS (Bonjour) path | Zeroconf browse runs (no services found in sandbox); graceful degradation to SSDP-only is code-reviewed, not exercised. | mDNS-only TVs (e.g. Chromecast/Android TV targets) discovered via `_googlecast._tcp`; brand from TXT properties. |
| Brand guessing | Unit-tested via `_BRAND_HINTS` in adapter tests. | A bare Chromecast must stay `"unknown"` (not guessed as Android TV); a Philips set must stay `"unknown"`. |
| iOS SSDP | Nothing. | Multicast entitlement granted → SSDP finds TVs; entitlement missing → SSDP finds nothing and Bonjour still works. |

### Pairing

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| Pair-capable adapter flow | `POST /devices/pair` with PIN `1234` completes; adapter receives the PIN; no-PIN pair completes; adapter without `pair()` → honest 422. | Android TV: real 6-char code from the TV screen completes pairing; wrong code is caught locally (checksum) and reported honestly. |
| Samsung Allow prompt | Token storage/reuse is unit-tested against recorded frames. | Real Samsung TV: Allow prompt appears, accept → token stored → later connects skip the prompt; deny → honest error. |
| LG register handshake | Client-key storage/reuse unit-tested. | Real LG TV: prompt appears, accept → `client-key` stored → later connects reuse it; confirm current firmware accepts the reused sample signed block. |
| Sony PSK | Refusal without PSK is unit-tested (honest 503). | Real Sony TV with PSK set: connect succeeds; wrong PSK → honest error. |
| Fire TV ADB authorisation | `unauthorized` state handling is unit-tested. | Real Fire TV: first connect shows the ADB authorisation prompt; accept → connect succeeds; revoke → honest error. |

### Navigation, volume, media

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| All 18 keys through the API | Full journey (up/down/ok/volume/power) + unit tests for every key endpoint incl. `menu`/`stop`; 404/403/503 paths covered. | Each key on each brand on a real TV: does Up actually move the cursor, does Volume Up change the volume, does Play/Pause control playback? |
| LG mute toggle | Code-reviewed: mute sends `setMute {mute: true}` — mutes only. | Confirm on a real LG set that a second Mute press does not unmute (documented limitation) and decide whether a state-query toggle is wanted. |
| Channel keys | Endpoints + adapter mapping unit-tested. | Channel up/down on a real tuner-equipped set (Roku TV / Samsung / LG / Sony); Fire TV has no tuner — confirm the behaviour is a harmless no-op or honest error, not a crash. |

### Netflix / Prime Video launches (and YouTube / Disney+)

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| App-id resolution | All four apps × Roku resolve to the documented ids (`12`/`13`/`837`/`291097`) and reach the stub adapter; Sony → 422 for all four; unknown app (`hulu`) → 422. | Each app actually opens on each brand: Netflix/Prime/YouTube on Samsung (`3201907018807`/`3201910019365`/`111299001912`), LG (`netflix`/`amazon`/`youtube`), Android/Fire TV (package names), Roku (channel ids). |
| Disney+ | Resolution to Roku `291097` and Android/Fire TV `com.disney.disneyplus` tested; Samsung/LG → honest 422 (no id used, per contract). | Disney+ opens on Roku and Android/Fire TV; on Samsung/LG confirm the honest 422 is what the user sees (and, if wanted, revisit the candidate ids `3201901017640` / `com.disney.disneyplus-prod` — deliberately not used). |
| LG YouTube id | `youtube` used per ioBroker.lgtv docs. | If `youtube` fails on a real LG set, try the canonical `youtube.leanback.v4` and update `apps.py`. |
| Android TV launch | `supports("launch_app")` gating on `adb` presence is unit-tested. | Real Android TV: launch via ADB works when `adb` is installed on the backend host; honest error when it is not. |
| Fire TV launch | ADB launch path unit-tested with a fake `adb`. | Real Fire TV: `am start -n <package>` opens each app. |

### Disconnect

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| Session cleared, device kept | Full journey: disconnect → `connection-status` false → device still in `GET /devices` → next key 404 → reconnect by id works. | Real TV: disconnect closes the Samsung/LG WebSocket and the Android TV session cleanly; the TV does not stay "connected" to a dead client; reconnect reuses the stored token/client-key without a new prompt. |
| Disconnect when TV already gone | Best-effort teardown is code-reviewed (session still cleared on adapter failure). | Power the TV off mid-session, then disconnect: the app must report a clean disconnect, not hang or error. |

### Unsupported-TV handling

| Item | Automated here | Still needs a real device |
| --- | --- | --- |
| Unknown brand | Registry raises an honest error; connect → 503. | A TV whose discovery brand is `"unknown"`: the app must ask the user to pick a brand (or connect manually) rather than guessing. |
| TCL with undetectable OS | Adapter returns the honest "pick the OS manually" error; unit-tested. | Real TCL set with an ambiguous model string: connect fails with that message; user picks Roku vs Android TV and connect succeeds. |
| Sony launch | 422 for every app, unit + integration tested. | Real Sony TV: user sees the honest error and is told to use Home + navigation instead. |
| Fire TV without ADB | `connect()` honest error when `adb` missing/unreachable; unit-tested. | Real Fire TV with ADB Debugging off: connect fails with the message telling the user exactly where to enable it. |

## Known gaps (not covered anywhere yet)

1. **No real TV has ever been controlled by this codebase.** That is
   the single biggest gap; everything above marked `NEEDS ON-DEVICE
   VERIFICATION` is waiting on it.
2. **No real phone has ever run the app.** The iOS Swift has never
   been compiled; the Android Java has never been built into an APK.
   The mobile app has only passed `tsc --noEmit` and `eslint`.
3. **No concurrency/load testing.** Two phones controlling one TV,
   rapid key repeats, or a TV that drops mid-command have not been
   exercised.
4. **No long-session test.** Token/client-key reuse across backend
   restarts (SQLite persistence) is unit-tested at the DB layer but
   not against a real TV over days.
5. **Discovery on a busy LAN** (many devices, slow description
   fetches, duplicate responses) has not been exercised — only the
   empty sandbox LAN and canned lists.
