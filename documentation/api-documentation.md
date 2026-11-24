# Universal Smart Remote — Backend API Documentation

Base URL: `http://<backend-host>:8000` (LAN only — the backend binds
`0.0.0.0:8000` so the phone can reach it over Wi-Fi; **never
port-forward port 8000**).

All responses are JSON. Success: `{"success": true, ...}` plus data.
Failure: `{"success": false, "error": "..."}`. Every endpoint except
`GET /health` requires the `X-API-Key` header; without it (or with a
wrong key) the response is `401 {"success": false, "error": "Missing or
invalid API key."}`.

Every endpoint that targets a TV rejects the request with `403` and
the exact message `"Your TV and smartphone must be connected to the
same local Wi-Fi network."` when the TV's IP is not on the same subnet
as the backend host. The check runs on connect and is re-run before
every command.

See [architecture.md](architecture.md) for the data flows behind these
endpoints and [supported-tvs.md](supported-tvs.md) for per-brand
behaviour. Contract source: `CONTRACTS.md` §2.

## Error codes

| Code | Meaning | Example `error` |
| --- | --- | --- |
| 400 | Bad input (missing required fields) | `"Provide device_id or ip (with brand) to connect."` |
| 401 | Missing or invalid `X-API-Key` | `"Missing or invalid API key."` |
| 403 | TV not on the same local subnet | `"Your TV and smartphone must be connected to the same local Wi-Fi network."` |
| 404 | No TV connected / unknown device id | `"No TV is connected. Connect to a TV first."` |
| 422 | Unsupported feature/app, or request validation failed | `"netflix is not supported/unknown for sony — no documented app id exists for this brand."` |
| 503 | Adapter unavailable, TV refused, timeout, unreachable | `"The TV refused the command."`, `"Timed out connecting to the TV at 192.168.1.50. ..."` |
| 500 | Unexpected internal error | `"Internal error: ..."` |

## `GET /health`

Unauthenticated liveness probe (lets the app find the backend).

**Request:** no headers, no body.

**Response — 200:**

```json
{"success": true, "status": "ok"}
```

## `GET /network/status`

Current network state of the backend host.

**Auth:** `X-API-Key` required.

**Response — 200:**

```json
{
  "success": true,
  "wifi_connected": true,
  "ssid": null,
  "phone_ip": null,
  "backend_ip": "192.168.1.20",
  "subnet": "192.168.1.0/24",
  "validation": "verified",
  "message": "Backend is on the local network."
}
```

Notes: `ssid` is best-effort (`iwgetid -r` on Linux) and `null` when
undeterminable; `phone_ip` is always `null` — the backend cannot know
the phone's IP and says so rather than guessing. `validation` is
`"verified"` when the host has a non-loopback interface, else
`"failed"` — and when it is `"failed"`, `message` is the exact
same-Wi-Fi error string (`"Your TV and smartphone must be connected
to the same local Wi-Fi network."`) so the app can display it
verbatim.

## `GET /devices/discover`

Run SSDP/mDNS discovery on the LAN and return discovered TVs.

**Auth:** `X-API-Key` required. Takes up to ~4 s (one SSDP sweep +
mDNS browse).

**Response — 200:**

```json
{
  "success": true,
  "data": [
    {
      "id": "discovered-192.168.1.50",
      "name": "Living Room TV",
      "brand": "samsung",
      "model": "QN90A",
      "ip": "192.168.1.50",
      "port": 8001,
      "mac": "",
      "paired": false,
      "source": "ssdp"
    }
  ]
}
```

`brand` is best-effort from discovery headers / description
documents; `"unknown"` when it cannot be determined. `paired` is true
when the TV is already saved in SQLite. An empty LAN returns
`"data": []` — discovery never invents a TV.

## `GET /devices`

Paired/saved devices from SQLite.

**Auth:** `X-API-Key` required.

**Response — 200:**

```json
{
  "success": true,
  "data": [
    {
      "id": "tv-192.168.1.50",
      "name": "Living Room TV",
      "brand": "samsung",
      "model": "QN90A",
      "ip": "192.168.1.50",
      "port": 8001,
      "mac": "",
      "paired": true,
      "pairing_token": "…",
      "last_connected": "2026-11-24T12:00:00+00:00"
    }
  ]
}
```

## `POST /devices/connect`

Connect to a TV via its brand adapter. Either `{device_id}` (a saved
device) or `{ip, brand, name?}`.

**Auth:** `X-API-Key` required.

**Request — by IP:**

```json
{"ip": "192.168.1.50", "brand": "samsung", "name": "Living Room TV"}
```

Optional fields: `model`, `port`, `mac`. `brand` is one of `samsung`,
`lg`, `sony`, `androidtv`, `googletv`, `tcl`, `roku`, `firetv`,
`mock` (mock only when the backend runs with `MOCK_TV=true`).

**Request — by saved id:**

```json
{"device_id": "tv-192.168.1.50"}
```

**Response — 200:**

```json
{
  "success": true,
  "connected": true,
  "device_id": "tv-192.168.1.50",
  "name": "Living Room TV",
  "brand": "samsung",
  "ip": "192.168.1.50",
  "message": "Connected to Living Room TV."
}
```

On success the device is saved (or updated) in SQLite and becomes the
active session. Pairing material the adapter obtained (Samsung token,
LG `client-key`, Android TV pairing certificate) is stored as
`pairing_token` for later connects.

**Pairing-required response — 200** (Android TV: the TV is showing
its 6-character code; the app routes to the Pairing screen):

```json
{
  "success": true,
  "connected": false,
  "pairing_required": true,
  "device_id": "tv-192.168.1.50",
  "name": "Living Room TV",
  "brand": "androidtv",
  "ip": "192.168.1.50",
  "message": "Enter the pairing code shown on the TV."
}
```

The device is saved (unpaired) and the live adapter instance is kept
server-side so `POST /devices/pair` can finish the handshake on the
same session. A server restart loses that session — the user must
connect again for a fresh code.

**Errors:** `400` no `device_id` and no `ip`; `404` unknown
`device_id`; `403` TV off the LAN; `503` adapter missing, connect
refused, or timeout. Note: the command service wraps `connect()` in a
15 s timeout, so on-TV prompts that take longer than 15 s (Samsung/LG
allow up to 60 s internally) will surface as a 503 timeout — accept
the prompt quickly, or retry the connect.

## `POST /devices/pair`

Complete PIN pairing where the brand requires it (Android TV: the TV
shows a 6-character code after `connect()` reports
`pairing_required`; enter it here).

**Auth:** `X-API-Key` required.

**Request:**

```json
{"device_id": "tv-192.168.1.50", "pin": "123456"}
```

`pin` is optional — omit it for adapters whose `pair()` takes no
argument.

**Response — 200:**

```json
{
  "success": true,
  "connected": true,
  "device_id": "tv-192.168.1.50",
  "name": "Living Room TV",
  "brand": "androidtv",
  "ip": "192.168.1.50",
  "message": "Pairing completed."
}
```

**Errors:** `404` unknown `device_id`; `422` when the adapter has no
`pair()` method — e.g. Samsung/LG pair via the on-TV Allow/prompt
during `connect()`, Roku needs no pairing — with an error explaining
that pairing happens on the TV; `422`/`503` when there is no live
pairing session (e.g. the server restarted after `connect()` reported
`pairing_required`) — the user must connect again for a fresh code;
`503` pairing failed or timed out.

## `DELETE /devices/disconnect`

Disconnect the active TV (or a specific one) and clear the session.
The device stays saved in SQLite.

**Auth:** `X-API-Key` required.

**Request** — body (optional) or query parameter:

```json
{"device_id": "tv-192.168.1.50"}
```

or `DELETE /devices/disconnect?device_id=tv-192.168.1.50`. With
neither, the currently active device is disconnected.

**Response — 200:**

```json
{
  "success": true,
  "disconnected": true,
  "message": "Disconnected from Living Room TV."
}
```

If no TV was connected: `200 {"success": true, "disconnected": false,
"message": "No TV was connected."}`. Disconnect is best-effort on the
adapter side — even if the adapter teardown fails (TV gone, off-LAN),
the session is cleared. `404` for an unknown `device_id`.

## `GET /devices/connection-status`

Current connection state (what the Home screen shows).

**Auth:** `X-API-Key` required.

**Response — 200, connected:**

```json
{
  "success": true,
  "connected": true,
  "device_id": "tv-192.168.1.50",
  "name": "Living Room TV",
  "brand": "samsung",
  "ip": "192.168.1.50"
}
```

**Response — 200, not connected:**

```json
{"success": true, "connected": false, "last_error": "Timed out sending up to the TV."}
```

`last_error` is present only when a previous command failed; it is
cleared on the next success.

## Remote keys — `POST /remote/<key>`

Send one remote key to the connected TV. One endpoint per key:

| Endpoint | Key |
| --- | --- |
| `POST /remote/up` | Up |
| `POST /remote/down` | Down |
| `POST /remote/left` | Left |
| `POST /remote/right` | Right |
| `POST /remote/ok` | OK / Enter / Select |
| `POST /remote/back` | Back |
| `POST /remote/home` | Home |
| `POST /remote/menu` | Menu |
| `POST /remote/power` | Power (off; power-on from standby is not supported — see [supported-tvs.md](supported-tvs.md)) |
| `POST /remote/volume-up` | Volume up |
| `POST /remote/volume-down` | Volume down |
| `POST /remote/mute` | Mute |
| `POST /remote/channel-up` | Channel up |
| `POST /remote/channel-down` | Channel down |
| `POST /remote/play` | Play |
| `POST /remote/pause` | Pause |
| `POST /remote/stop` | Stop |
| `POST /remote/rewind` | Rewind |
| `POST /remote/fast-forward` | Fast forward |

**Auth:** `X-API-Key` required.

**Request body** — `{}` or `{"device_id": "..."}`; omitted means the
currently connected device:

```json
{}
```

**Response — 200:**

```json
{"success": true, "key": "up", "message": "Sent up."}
```

**Errors:** `404` no TV connected/selected (or unknown `device_id`);
`403` TV off the LAN (revalidated before every command); `422` the
key's feature is not supported on this brand (e.g. a brand whose
`supports()` returns False for it); `503` the TV refused the command
or it timed out (10 s limit). Never a fake `success: true`.

## `POST /remote/launch-app`

Launch a streaming app on the connected TV.

**Auth:** `X-API-Key` required.

**Request:**

```json
{"app": "netflix"}
```

`app` must be one of `netflix`, `prime`, `youtube`, `disney`
(anything else is a `422` request-validation error). Optional
`"device_id"` targets a specific device instead of the active one.

**Response — 200:**

```json
{"success": true, "app": "netflix", "message": "Launched netflix."}
```

The backend resolves the brand-specific app id from
`backend/app/adapters/apps.py` (e.g. Netflix on Roku is channel `12`,
on Samsung `3201907018807`, on LG `netflix`, on Android/Fire TV
`com.netflix.ninja`) and sends the brand's real launch command.

**Errors:** `404` no TV connected; `422` the app has no documented id
for this brand — e.g. any app on Sony (IRCC-IP cannot launch apps),
Disney+ on Samsung/LG — with
`"<app> is not supported/unknown for <brand> — no documented app id
exists for this brand."`; `422` when the adapter reports
`supports("launch_app") == False` (Android TV without ADB installed);
`503` the TV refused the launch or it timed out.

## `curl` examples

```bash
BASE=http://192.168.1.20:8000
KEY=your-api-key

curl -s $BASE/health

curl -s -H "X-API-Key: $KEY" $BASE/network/status

curl -s -H "X-API-Key: $KEY" $BASE/devices/discover

curl -s -H "X-API-Key: $KEY" -X POST $BASE/devices/connect \
  -H "Content-Type: application/json" \
  -d '{"ip": "192.168.1.50", "brand": "roku", "name": "Living Room TV"}'

curl -s -H "X-API-Key: $KEY" -X POST $BASE/remote/up \
  -H "Content-Type: application/json" -d '{}'

curl -s -H "X-API-Key: $KEY" -X POST $BASE/remote/launch-app \
  -H "Content-Type: application/json" -d '{"app": "netflix"}'

curl -s -H "X-API-Key: $KEY" $BASE/devices/connection-status

curl -s -H "X-API-Key: $KEY" -X DELETE $BASE/devices/disconnect \
  -H "Content-Type: application/json" -d '{}'
```

## Notes for client implementers

- Always send `X-API-Key` (except `/health`). A `401` means the key
  in the app's Settings does not match the backend's
  `SMART_REMOTE_API_KEY` (or the backend restarted without a stable
  key set — see [installation-guide.md](installation-guide.md)).
- Treat `403` as "wrong Wi-Fi": show the exact message to the user
  and point them at the Network Info screen.
- Treat `404` on a remote endpoint as "not connected": route to the
  Connect TV screen.
- Never retry a `422` — the feature genuinely is not supported for
  that brand/app. Show the error.
- A `503` is transient (TV off, unreachable, refused): show the
  error and let the user retry or reconnect.
- Remote bodies may be `{}`; `device_id` is only needed to target a
  non-active saved device.
