# Universal Smart Remote — Supported TVs

Per-brand support: protocol, port, pairing, what works and what does
not. Every adapter is implemented against the brand's documented local
protocol (CONTRACTS.md §5) — but **none of them has been exercised
against a real TV yet**. Items marked `NEEDS ON-DEVICE VERIFICATION`
are implemented and unit-tested, not proven on hardware. Do not treat
a green test suite as proof that a real TV will accept these commands.

Streaming-app ids are in `backend/app/adapters/apps.py`; `None` means
"no documented id / not supported" and `launch_app` returns an honest
error rather than guessing. The table below is derived from that file
plus each adapter's `supports()`.

## Summary

| Brand | Protocol | Port | Pairing | Power on from standby | Launch app | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Samsung (Tizen) | WebSocket | 8001 (ws) / 8002 (wss) | On-TV Allow prompt, token stored | No | Yes (Netflix, Prime, YouTube; **not Disney+**) | NEEDS ON-DEVICE VERIFICATION |
| LG (webOS) | WebSocket + ssap:// | 3000 (ws) / 3001 (wss) | Register handshake, `client-key` stored | No | Yes (Netflix, Prime, YouTube; **not Disney+**) | NEEDS ON-DEVICE VERIFICATION |
| Sony Bravia | IRCC-IP (SOAP over HTTP) | 80 | Pre-shared key (PSK) set on the TV | See notes | **No** | NEEDS ON-DEVICE VERIFICATION |
| Android TV / Google TV | Remote protocol v2 (mutual-TLS protobuf) | 6466 (remote) / 6467 (pairing) | 6-char code shown on TV | See notes | ADB only (needs `adb` on backend host) | NEEDS ON-DEVICE VERIFICATION |
| TCL | Delegates to Roku or Android TV | 8060 or 6466/6467 | Depends on delegated OS | Depends on delegate | Depends on delegate | NEEDS ON-DEVICE VERIFICATION |
| Roku TV | ECP (HTTP) | 8060 | None needed | Yes (ECP `Power` key) | Yes (all four apps) | NEEDS ON-DEVICE VERIFICATION |
| Amazon Fire TV | ADB only | 5555 | ADB authorisation on the TV | See notes | Yes (all four apps, via ADB) | NEEDS ON-DEVICE VERIFICATION |
| Mock TV | None (testing only) | — | None | n/a | n/a | Test-only, `MOCK_TV=true` |

## Samsung (Tizen)

- **Protocol:** WebSocket
  `ws://<ip>:8001/api/v2/channels/samsung.remote.control?name=<base64(name)>`,
  secure `wss://<ip>:8002` with token. Keys via `ms.remote.control`
  (`KEY_UP`, `KEY_DOWN`, `KEY_LEFT`, `KEY_RIGHT`, `KEY_ENTER`,
  `KEY_RETURN`, `KEY_HOME`, `KEY_MENU`, `KEY_POWER`, `KEY_VOLUP`,
  `KEY_VOLDOWN`, `KEY_MUTE`, `KEY_CHUP`, `KEY_CHDOWN`, `KEY_PLAY`,
  `KEY_PAUSE`, `KEY_STOP`, `KEY_REWIND`, `KEY_FF`). Launch via
  `ms.channel.emit` `ed.apps.launch` with the Tizen app id.
- **Pairing:** first connect (no token) shows an Allow prompt on the
  TV; accepting it returns a token, stored as `pairing_token` and
  reused on later connects. A denied prompt returns an honest error.
- **Features:** power, volume, mute, channel, media, launch_app,
  pairing — all `True` in `supports()`.
- **Honest limitations:**
  - **Power-on from standby is NOT supported.** Standby closes the
    control channel, so there is no open socket to send `KEY_POWER`
    on, and no Wake-on-LAN is implemented. `KEY_POWER` works only
    while connected (i.e. it powers the TV off). `get_status()`
    reports `power_on_from_standby: False`.
  - The TV uses a self-signed certificate, so the `wss` connection
    uses an unverified SSL context (LAN-only traffic to your own TV).
  - **Disney+ cannot be launched.** `apps.py` has `None` for Samsung
    Disney+ per the contract (a candidate id `3201901017640` exists in
    third-party lists but was deliberately not used), so launching
    Disney+ returns an honest 422.
  - In direct mode (phone → TV), React Native's `WebSocket` exposes
    no certificate bypass, so the secure `wss://:8002` connection may
    be rejected on-device. Backend mode is the reliable path.
- **NEEDS ON-DEVICE VERIFICATION:** no real Samsung TV was available
  while writing this. The handshake/key/launch frames follow the
  documented protocol and the Phase 1 direct-mode client, which uses
  the same frames.

## LG (webOS)

- **Protocol:** WebSocket `wss://<ip>:3001` (required on firmware
  since ~2023), fallback `ws://<ip>:3000` for older sets. Register
  handshake (`forcePairing`, `PROMPT`, manifest, `client-key`).
  Buttons go over a second socket from
  `ssap://com.webos.service.networkinput/getPointerInputSocket` as
  plain text (`type:button\nname:UP\n\n`). Volume
  `ssap://audio/volumeUp` / `volumeDown` (the documented webOS calls —
  not the `ssap://audio/volume/up` form in early notes),
  `ssap://audio/setMute`, `ssap://audio/setVolume`,
  `ssap://system/turnOff`, `ssap://system.launcher/launch {"id":
  appId}`, channel `ssap://tv/channelUp` / `channelDown`, media
  `ssap://media.controls/play|pause|stop|rewind|fastForward`.
- **Pairing:** register handshake; the TV shows a pairing prompt and
  on accept returns a `client-key`, stored as `pairing_token` and
  reused on later connects.
- **Features:** power, volume, mute, channel, media, launch_app,
  pairing — all `True` in `supports()`.
- **Honest limitations:**
  - **Power-on is NOT supported** (needs Wake-on-LAN, not
    implemented). Power sends `ssap://system/turnOff` — off only.
    `get_status()` reports `power_on_from_standby: False`.
  - **Mute mutes; it does not toggle back.** Mute sends `setMute
    {mute: true}`; toggling needs a state query first, which the
    adapter does not do.
  - **Disney+ cannot be launched.** `apps.py` has `None` for LG
    Disney+ per the contract (third-party sources list
    `com.disney.disneyplus-prod`, deliberately not used), so launching
    Disney+ returns an honest 422.
  - The register manifest reuses LG's published sample signed block;
    whether current firmware accepts the backend's unsigned reuse of
    it must be confirmed on a real set.
  - Self-signed certificate on `wss://:3001` → unverified SSL context
    (LAN-only). Same direct-mode caveat as Samsung for `wss`.
- **NEEDS ON-DEVICE VERIFICATION.**

## Sony Bravia

- **Protocol:** IRCC-IP: `POST http://<ip>/sony/IRCC` with a SOAP
  body and `X-Auth-PSK` header, using the documented IRCC codes for
  power / volume / navigation / media.
- **Pairing:** none in the app — the TV must have a **pre-shared key
  (PSK)** configured on it (Settings → Network → Home Network Setup →
  IP Control → Pre-Shared Key). The backend needs that PSK; without
  it, `connect()` fails with an honest 503. `supports("pairing")` is
  `False`.
- **Features:** power, volume, mute, channel, media — `True`.
  `launch_app` — **`False`**.
- **Honest limitations:**
  - **No app launching at all.** IRCC-IP cannot launch arbitrary
    streaming apps by id. `launch_app` always returns an honest error
    telling the user to open the app from the TV's home screen (Home
    key + navigation). Every streaming app is `None` for Sony in
    `apps.py`, so `POST /remote/launch-app` returns 422 for any app.
  - Power behaviour depends on the set's IRCC implementation and
    network-standby settings; verify on the device.
- **NEEDS ON-DEVICE VERIFICATION.**

## Android TV / Google TV

- **Protocol:** Android TV Remote protocol v2 — mutual-TLS protobuf
  over TCP port **6466** (remote session), pairing over port **6467**
  (Google's Polo protocol). Framing is `[varint: length][protobuf:
  RemoteMessage]`; both sides present self-signed RSA-2048
  certificates. Keys are `remote_key_inject` messages with Android
  `KeyEvent` codes. Layouts follow the documented
  `tronikos/androidtvremote2` implementation and the AOSP pairing
  protocol (`polo.proto` / `remotemessage.proto`).
- **Pairing:** `connect()` on an unpaired TV runs the pairing
  handshake up to `configuration_ack`, at which point the TV displays
  a **6-character hex code**, and returns HTTP 200 with
  `connected: false, pairing_required: true` (the device is saved,
  unpaired, and the live adapter instance is kept server-side). The
  app then calls `POST /devices/pair {device_id, pin}` with that code
  and the adapter finishes the handshake on the same session; the
  adapter verifies the code locally first (the first two characters
  are a checksum of the SHA-256 secret). Certificates are stored as
  `pairing_token` for later connects. A server restart loses the live
  session — the user must connect again for a fresh code.
- **Features:** power, volume, mute, channel, media, pairing —
  `True`. `launch_app` is `True` **only when the `adb` command is
  installed on the backend host**; otherwise `supports("launch_app")`
  is `False` and launching returns an honest error.
- **Honest limitations:**
  - **App launch is ADB only** (`adb shell monkey -p <package>`-style
    launch via the same path as the Fire TV adapter). The remote
    protocol's `remote_app_link_launch_request` message exists but is
    deliberately not used (CONTRACTS.md §5). Without ADB on the
    backend host, no app can be launched.
  - The TV sends no acknowledgement for a key press; "success" means
    the frame was written to the live session.
  - Power-on from standby depends on the TV staying reachable on the
    network while asleep; verify on the device.
- **NEEDS ON-DEVICE VERIFICATION** — the whole adapter: the pairing
  handshake, TLS certificate handling and remote session have NOT
  been exercised against a real TV.

## TCL

- **Protocol:** none of its own — **delegates** (CONTRACTS.md §1).
  Roku-OS models → Roku adapter (ECP, port 8060). Android/Google TV
  models → Android TV adapter (ports 6466/6467). Detection is from
  the discovered `model`/`os` string.
- **Pairing / features / launch:** whatever the delegated adapter
  supports (see the Roku and Android TV sections above).
- **Honest limitations:**
  - **If the OS cannot be determined, `connect()` fails with an
    honest error** telling the user to pick the OS manually (Roku or
    Android TV). The adapter never guesses — sending the wrong
    protocol at the TV would fail confusingly.
  - No TCL-specific protocol is invented. A TCL set running some
    other OS is not supported.
  - Streaming-app ids are `None` for `tcl` directly in `apps.py`;
    launch resolves through the delegated adapter's brand.
- **NEEDS ON-DEVICE VERIFICATION.**

## Roku TV

- **Protocol:** ECP (External Control Protocol) — plain HTTP:
  `http://<ip>:8060/keypress/<Up|Down|Left|Right|Select|Back|Home|Power|VolumeUp|VolumeDown|VolumeMute|ChannelUp|ChannelDown|Play|Pause|Rev|Fwd>`,
  launch `POST /launch/<appid>`, `GET /query/apps` to check
  installation.
- **Pairing:** none needed for ECP. `supports("pairing")` is `False`.
- **Features:** power, volume, mute, channel, media, launch_app —
  all `True`. **All four streaming apps launch** (Netflix `12`, Prime
  `13`, YouTube `837`, Disney+ `291097`).
- **Honest limitations:**
  - Power-on via ECP works only if the TV is listening on the network
    in standby (Roku's "Fast TV Start" / network standby setting);
    verify on the device.
  - ECP is unauthenticated plain HTTP on the LAN — anyone on your
    Wi-Fi can send keys to a Roku TV. That is Roku's protocol design,
    not something this app adds; keep the TV on a trusted network.
- **NEEDS ON-DEVICE VERIFICATION.**

## Amazon Fire TV

- **Protocol:** local **ADB only**: `adb connect <ip>:5555`,
  `adb shell input keyevent <code>`, `adb shell am start -n
  <package>` for app launch.
- **Pairing:** none in the app — the Fire TV must have **ADB
  Debugging enabled** (Settings → My Fire TV → Developer Options →
  ADB Debugging) **and** must authorise the backend host the first
  time it connects (on-TV prompt). An `unauthorized` state returns an
  honest error telling the user to accept the prompt on the TV.
- **Features:** power, volume, mute, channel, media, launch_app —
  all `True` in `supports()`. All four streaming apps launch via ADB
  (`com.netflix.ninja`, `com.amazon.amazonvideo.livingroom`,
  `com.google.android.youtube.tv`, `com.disney.disneyplus`).
- **Honest limitations:**
  - **If ADB is unavailable or unreachable, `connect()` fails with an
    honest error.** That includes: the `adb` command not installed on
    the backend host (install Android platform-tools), ADB Debugging
    off on the TV, or the TV not authorising the host.
  - Power-on from standby depends on the Fire TV staying reachable
    over ADB while asleep; verify on the device.
  - Key events are injected as Android key codes; behaviour for
    channel keys on a Fire TV (no tuner) is device-dependent.
- **NEEDS ON-DEVICE VERIFICATION.**

## Mock TV (testing only)

- **Protocol:** none — canned success responses, no network access.
- **Pairing:** none. `supports()` returns `True` for every feature.
- **Availability:** the mock adapter is returned by `get_adapter`
  **only** when the backend is started with `MOCK_TV=true`. It is
  never reachable in a normal run, and its canned results must never
  be reported as if a real TV had acted.
- **Limitation:** the `mock` brand has no streaming-app ids, so
  `POST /remote/launch-app` on a mock TV honestly returns 422.

## Streaming-app ids (from `backend/app/adapters/apps.py`)

| App | Roku | Samsung | LG | Android TV / Fire TV | Sony | TCL |
| --- | --- | --- | --- | --- | --- | --- |
| Netflix | `12` | `3201907018807` | `netflix` | `com.netflix.ninja` | — | via delegate |
| Prime Video | `13` | `3201910019365` | `amazon` | `com.amazon.amazonvideo.livingroom` | — | via delegate |
| YouTube | `837` | `111299001912` | `youtube` | `com.google.android.youtube.tv` | — | via delegate |
| Disney+ | `291097` | — | — | `com.disney.disneyplus` | — | via delegate |

`—` = `None` in the table: no documented id, launch returns an honest
422. Verification notes (from `apps.py`): Samsung ids confirmed via
homebridge-samsung-tizen / Home Assistant sources; Roku ids confirmed
via a real `/query/apps` dump; LG ids via ioBroker.lgtv / lgtv2
(note: the canonical webOS YouTube id is `youtube.leanback.v4` — if
`youtube` fails on a set, try that); Android/Fire TV package names via
Home Assistant androidtv_remote docs. No non-`None` id had to be
demoted during implementation.
