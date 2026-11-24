# Universal Smart Remote — Shared Contracts

Read this file first. Every phase must conform to it so the pieces fit together.
Project root: `~/workspace/your_files/universal-smart-remote/`

## 1. Backend brand-adapter interface (exact)

File: `backend/app/adapters/base.py` — the adapters phase owns this file; the backend-core phase imports it verbatim. Do not change these names.

```python
from __future__ import annotations
import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

class RemoteKey(str, enum.Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    OK = "ok"
    BACK = "back"
    HOME = "home"
    MENU = "menu"
    POWER = "power"
    VOLUME_UP = "volume-up"
    VOLUME_DOWN = "volume-down"
    MUTE = "mute"
    CHANNEL_UP = "channel-up"
    CHANNEL_DOWN = "channel-down"
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"
    REWIND = "rewind"
    FAST_FORWARD = "fast-forward"

@dataclass
class CommandResult:
    success: bool
    message: str = ""
    error: Optional[str] = None
    details: dict = field(default_factory=dict)

@dataclass
class DeviceInfo:
    id: str
    name: str
    brand: str          # one of BRANDS keys below
    model: str = ""
    ip: str = ""
    port: int = 0
    mac: str = ""
    pairing_token: str = ""
    paired: bool = False

class TvAdapter(ABC):
    brand: str = ""

    def __init__(self, device: DeviceInfo):
        self.device = device
        self.connected = False

    @abstractmethod
    async def connect(self) -> CommandResult: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send_key(self, key: RemoteKey) -> CommandResult: ...

    @abstractmethod
    async def launch_app(self, app_id: str) -> CommandResult: ...

    def supports(self, feature: str) -> bool:
        """feature in: power, volume, mute, channel, media, launch_app, pairing."""
        return True

    async def get_status(self) -> dict:
        return {"brand": self.brand, "connected": self.connected, "ip": self.device.ip}
```

File: `backend/app/adapters/__init__.py` (adapters phase owns it) must expose:

```python
BRANDS = {
    "samsung": "Samsung (Tizen)",
    "lg": "LG (webOS)",
    "sony": "Sony Bravia",
    "androidtv": "Android TV",
    "googletv": "Google TV",
    "tcl": "TCL",
    "roku": "Roku TV",
    "firetv": "Amazon Fire TV",
    "mock": "Mock TV (testing only)",
}

def get_adapter(device: DeviceInfo) -> TvAdapter: ...
```

- `googletv` is an alias of the Android TV adapter.
- `tcl` delegates: Roku-OS models -> Roku adapter, Android/Google TV models -> Android TV adapter. Detect from the discovered `model`/`os` string; if the OS cannot be determined, `connect()` must fail with an honest error telling the user to pick the OS manually — never guess.
- `mock` is the testing adapter only. It must never be reachable unless the backend is started with `MOCK_TV=true`.

File: `backend/app/adapters/apps.py` (adapters phase) must expose:

```python
STREAMING_APPS = {
    "netflix": {"roku": "12", "samsung": "3201907018807", "lg": "netflix",
                "androidtv": "com.netflix.ninja", "firetv": "com.netflix.ninja",
                "sony": None, "tcl": None},
    "prime":   {"roku": "13", "samsung": "3201910019365", "lg": "amazon",
                "androidtv": "com.amazon.amazonvideo.livingroom",
                "firetv": "com.amazon.amazonvideo.livingroom",
                "sony": None, "tcl": None},
    "youtube": {"roku": "837", "samsung": "111299001912", "lg": "youtube",
                "androidtv": "com.google.android.youtube.tv",
                "firetv": "com.google.android.youtube.tv",
                "sony": None, "tcl": None},
    "disney":  {"roku": "291097", "samsung": None, "lg": None,
                "androidtv": "com.disney.disneyplus",
                "firetv": "com.disney.disneyplus",
                "sony": None, "tcl": None},
}
```

`None` means "no documented app id / not supported": `launch_app` must return
`CommandResult(success=False, error="... not supported/unknown for this brand ...")`, never a
guessed id. Verify every non-None id above against a documented source (web search) while
implementing; demote any id you cannot verify to `None` with a comment. For `tcl`, resolve
through the delegated adapter's brand.

## 2. Backend API (exact — backend-core phase owns the routes)

Base: `http://<backend-host>:8000`. All responses are JSON: `{"success": true|false, ...}` plus
data or `{"success": false, "error": "..."}`. Auth: `X-API-Key` header (key generated on first
run and printed/logged; configurable via `SMART_REMOTE_API_KEY` env). All endpoints reject
requests when the target TV is not on the same local subnet as the backend (see §4).

- `GET  /devices/discover` — run SSDP/mDNS discovery on the LAN, return discovered TVs
  `[{id, name, brand, model, ip, port, mac, paired}]`. `brand` is best-effort from discovery
  headers; `"unknown"` when it cannot be determined.
- `GET  /devices` — paired/saved devices from SQLite.
- `POST /devices/connect` `{device_id}` or `{ip, brand, name?}` — connect via the brand adapter.
- `POST /devices/pair` `{device_id, pin?}` — complete PIN pairing where the brand requires it.
- `DELETE /devices/disconnect` `{device_id}` — disconnect (and remove from active session, keep saved).
- `POST /remote/up|down|left|right|ok|back|home` — send the key to the connected TV.
- `POST /remote/power|volume-up|volume-down|mute|channel-up|channel-down|play|pause|rewind|fast-forward`
- `POST /remote/launch-app` `{app}` where app in `netflix|prime|youtube|disney` — resolve the
  brand app id via `apps.py`, check `supports("launch_app")`, send the real launch command.
- `GET  /network/status` — `{wifi_connected, ssid?, phone_ip?, backend_ip, subnet, validation: "verified"|"failed", message}`
- `GET  /devices/connection-status` — `{connected, device_id?, name?, brand?, ip?, last_error?}`
- `GET  /health` — `{"status": "ok"}` (extra, allowed).

Remote-command request bodies may be `{}` or `{"device_id": "..."}`; when omitted, use the
currently connected device. Every remote endpoint: 404 if no TV connected/selected, 400 on
bad input, 422/503 with a clear `error` when the TV rejects or is unreachable, never a fake
`success: true`.

## 3. React Native bridge (shared by mobile-UI, Android, iOS phases)

Native module name on both platforms: `SmartRemoteNative`. Promise-based methods:

```ts
type NetworkInfo = {
  connected: boolean; isWifi: boolean; isCellular: boolean;
  ssid: string | null; bssid: string | null;
  ipAddress: string | null; subnetMask: string | null; gateway: string | null;
};
type DiscoveredTv = { name: string; brand: string; model: string; ip: string; port: number; mac: string; source: 'ssdp' | 'bonjour' | 'manual' };

getNetworkInfo(): Promise<NetworkInfo>
startDiscovery(): Promise<void>          // emits 'TvDiscovered' events {tv: DiscoveredTv}
stopDiscovery(): Promise<void>
isWifiConnected(): Promise<boolean>
```

Events (via the platform event emitter, event names exactly): `TvDiscovered`, `NetworkChanged`
`{connected, ssid, ipAddress}`. Android implements SSDP M-SEARCH (UDP multicast
239.255.255.250:1900) + Wi-Fi APIs; iOS implements Bonjour (`NetServiceBrowser` for
`_googlecast._tcp`, `_airplay._tcp`, `_http._tcp`) + SSDP where possible + Local Network
permission handling (`NSLocalNetworkUsageDescription`). Both must request/handle the
relevant permissions and surface a clear error when denied.

The TypeScript side (`mobile/src/services/native.ts`) wraps these calls and normalises
results. The app must work in two modes: `backend` (commands go to the FastAPI backend,
§2) and `direct` (Roku ECP via `fetch`, Samsung/LG via WebSocket from JS). Native modules
do discovery + network only; they do not send remote keys.

## 4. Same-Wi-Fi validation (backend-core phase)

- The backend only talks to TVs whose IP is in the same subnet as one of the backend host's
  local interfaces (use `ipaddress` module). Reject anything else with a 403 and the exact
  message: `"Your TV and smartphone must be connected to the same local Wi-Fi network."`
- Revalidate before every command (the command service checks the connected device's IP
  against current interfaces on each call).
- Never use public IPs; never implement cloud control. Bind the server to `0.0.0.0` on the
  LAN only and document that it must not be port-forwarded.

## 5. Protocols (adapters phase — real documented protocols only)

- Samsung Tizen: WebSocket `ws://<ip>:8001/api/v2/channels/samsung.remote.control?name=<base64(name)>`
  (and `wss://<ip>:8002` secure with token). Keys `KEY_UP`, `KEY_DOWN`, `KEY_LEFT`,
  `KEY_RIGHT`, `KEY_ENTER`, `KEY_RETURN`, `KEY_HOME`, `KEY_MENU`, `KEY_POWER`, `KEY_VOLUP`,
  `KEY_VOLDOWN`, `KEY_MUTE`, `KEY_CHUP`, `KEY_CHDOWN`, `KEY_PLAY`, `KEY_PAUSE`, `KEY_STOP`,
  `KEY_REWIND`, `KEY_FF`. Launch: `ms.channel.emit` `ed.apps.launch` with the Tizen app id.
- LG webOS: WebSocket `ws://<ip>:3000` / `wss://<ip>:3001`, register handshake with
  `forcePairing`/`PROMPT` and client-key persistence. Keys via the documented webOS key
  API; volume `ssap://audio/volume/up|down`, `ssap://audio/setVolume`, `ssap://audio/setMute`;
  power off `ssap://system/turnOff`; launch `ssap://system.launcher/launch {"id": appId}`.
  Verify the key-sending call against a documented source while implementing; if a
  particular key path cannot be verified, implement the verified calls and have
  `send_key` return an honest error for the unverified ones instead of guessing.
- Roku: ECP HTTP `http://<ip>:8060/keypress/<Up|Down|Left|Right|Select|Back|Home|Power|VolumeUp|VolumeDown|VolumeMute|ChannelUp|ChannelDown|Play|Pause|Rev|Fwd>`,
  launch `POST /launch/<appid>`, `GET /query/apps` to check installation.
- Android TV / Google TV: remote pairing + protobuf remote protocol over TLS, port 6466
  (as used by the documented androidtv remote libraries). Implement pairing handshake and
  key events. App launch: via ADB when available, else `supports("launch_app") == False`
  with an honest error. Mark the whole adapter "needs on-device verification".
- Fire TV: local ADB only (`adb connect <ip>:5555`, `adb shell input keyevent <code>`,
  `adb shell am start -n <package>`), only when ADB debugging is enabled and authorized
  on the TV. If ADB is unavailable/unreachable, `connect()` fails with an honest error.
- Sony Bravia: IRCC-IP: `POST http://<ip>/sony/IRCC` with SOAP body and `X-Auth-PSK`
  header; documented IRCC codes for power/volume/navigation/media. Launch: IRCC-IP cannot
  launch arbitrary streaming apps by id — `supports("launch_app")` is False and
  `launch_app` returns an honest error.
- TCL: delegate per §1. No TCL-specific protocol is invented.

## 6. Ownership (who writes what — do not touch other phases' files)

- mobile-UI: `mobile/src/**`, `mobile/package.json`, `mobile/tsconfig.json`,
  `mobile/babel.config.js`, `mobile/metro.config.js`, `mobile/index.js`, `mobile/app.json`.
- android: `mobile/android/**` (Java native modules, AndroidManifest, gradle files).
- ios: `mobile/ios/**` (Swift native modules, Info.plist entries, Podfile).
- backend-core: `backend/app.py`, `backend/requirements.txt`, `backend/app/routes/**`,
  `backend/app/services/**`, `backend/app/models/**`, `backend/app/security/**`,
  `backend/app/network/**`, `backend/tests/**`.
- adapters: `backend/app/adapters/**`.
- coordinator (me): `README.md`, `documentation/**`, `CONTRACTS.md`, git repo.

## 7. Rules for all phases

- Real working code for the core paths. No fake success: every command returns the real
  result or a real error. Where a full implementation cannot be verified without a device,
  implement it completely and mark it clearly `NEEDS ON-DEVICE VERIFICATION`.
- Never invent a TV API. If you cannot verify a protocol detail, implement what is
  documented and return an honest error for the rest.
- Do not create a git repo and do not push anything. Do not edit files outside your
  ownership. Report the list of files you created and any TODOs/unverified items.
