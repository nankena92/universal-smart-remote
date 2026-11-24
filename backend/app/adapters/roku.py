"""Roku adapter — Roku ECP over HTTP (CONTRACTS.md §5).

Protocol (real, documented — no invented APIs), consistent with the Phase 1
direct-mode client (``mobile/src/services/direct/rokuDirect.ts``), which
uses the same endpoints and key names:

- Keys: ``POST http://<ip>:8060/keypress/<Key>`` where Key is one of
  ``Up|Down|Left|Right|Select|Back|Home|Info|Power|VolumeUp|VolumeDown|
  VolumeMute|ChannelUp|ChannelDown|Play|Pause|Stop|Rev|Fwd``.
- Launch: ``POST http://<ip>:8060/launch/<appid>``.
- Installed-app check: ``GET http://<ip>:8060/query/apps`` returns XML
  (``<apps><app id="12">Netflix</app>...</apps>``); :meth:`launch_app`
  refuses with an honest error when the app id is not in that list instead
  of sending a launch the TV will reject.
- Reachability check on connect: ``GET /query/device-info``.

No pairing is needed for ECP, so ``supports("pairing")`` is False.
Every network operation has a timeout; a ``CommandResult`` is successful
only when the TV actually answers with HTTP 2xx.
"""

from __future__ import annotations

import asyncio
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .base import CommandResult, DeviceInfo, RemoteKey, TvAdapter

ROKU_PORT = 8060
REQUEST_TIMEOUT = 8.0

# Same mapping as mobile/src/services/direct/rokuDirect.ts (Phase 1).
KEY_MAP = {
    RemoteKey.UP: "Up",
    RemoteKey.DOWN: "Down",
    RemoteKey.LEFT: "Left",
    RemoteKey.RIGHT: "Right",
    RemoteKey.OK: "Select",
    RemoteKey.BACK: "Back",
    RemoteKey.HOME: "Home",
    RemoteKey.MENU: "Info",
    RemoteKey.POWER: "Power",
    RemoteKey.VOLUME_UP: "VolumeUp",
    RemoteKey.VOLUME_DOWN: "VolumeDown",
    RemoteKey.MUTE: "VolumeMute",
    RemoteKey.CHANNEL_UP: "ChannelUp",
    RemoteKey.CHANNEL_DOWN: "ChannelDown",
    RemoteKey.PLAY: "Play",
    RemoteKey.PAUSE: "Pause",
    RemoteKey.STOP: "Stop",
    RemoteKey.REWIND: "Rev",
    RemoteKey.FAST_FORWARD: "Fwd",
}

_APP_RE = re.compile(r'<app[^>]*id="([^"]+)"[^>]*>([^<]*)</app>')


def _http(method: str, url: str, timeout: float = REQUEST_TIMEOUT):
    """Blocking HTTP request. Returns ``(status, body_bytes)``.

    HTTP error statuses are returned, not raised, so callers can report the
    TV's real response. Network failures raise :class:`ConnectionError`.
    """
    req = urllib.request.Request(
        url, data=b"" if method == "POST" else None, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ConnectionError(str(exc)) from exc


class RokuAdapter(TvAdapter):
    """Roku TV adapter over the External Control Protocol (ECP)."""

    brand = "roku"

    def __init__(self, device: DeviceInfo):
        super().__init__(device)
        self._last_error: Optional[str] = None

    def _url(self, path: str) -> str:
        return f"http://{self.device.ip}:{ROKU_PORT}{path}"

    async def connect(self) -> CommandResult:
        if self.connected:
            return CommandResult(True, "Already connected to Roku TV.")
        if not self.device.ip:
            return CommandResult(False, error="No IP address for Roku TV.")
        try:
            status, _ = await asyncio.to_thread(
                _http, "GET", self._url("/query/device-info")
            )
        except ConnectionError as exc:
            self._last_error = str(exc)
            return CommandResult(
                False,
                error=f"Could not reach Roku TV at {self.device.ip}. "
                f"Check the TV is on and on the same Wi-Fi. ({exc})",
            )
        if status != 200:
            self._last_error = f"HTTP {status}"
            return CommandResult(
                False,
                error=f"Roku TV at {self.device.ip} returned HTTP {status} "
                f"for /query/device-info; is this really a Roku TV?",
            )
        self.connected = True
        self.device.paired = True  # ECP needs no pairing step.
        return CommandResult(True, "Connected to Roku TV.")

    async def disconnect(self) -> None:
        self.connected = False

    async def _ensure_connected(self) -> Optional[CommandResult]:
        """Return None when connected, else the failed connect() result."""
        if self.connected:
            return None
        result = await self.connect()
        return None if result.success else result

    async def send_key(self, key: RemoteKey) -> CommandResult:
        ecp_key = KEY_MAP.get(key)
        if ecp_key is None:
            return CommandResult(
                False, error=f"Roku does not support key: {key.value}"
            )
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        try:
            status, _ = await asyncio.to_thread(
                _http, "POST", self._url(f"/keypress/{ecp_key}")
            )
        except ConnectionError as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Could not reach Roku TV at {self.device.ip}: {exc}"
            )
        if status != 200:
            return CommandResult(
                False,
                error=f"Roku keypress {ecp_key} failed: "
                f"TV returned HTTP {status}.",
            )
        return CommandResult(
            True,
            f"Sent {key.value} to Roku TV.",
            details={"roku_key": ecp_key},
        )

    async def query_apps(self) -> list[dict]:
        """Return the installed apps as ``[{id, name}]`` (ECP /query/apps)."""
        status, body = await asyncio.to_thread(
            _http, "GET", self._url("/query/apps")
        )
        if status != 200:
            raise ConnectionError(
                f"Roku /query/apps returned HTTP {status}."
            )
        xml = body.decode("utf-8", errors="replace")
        return [
            {"id": m.group(1), "name": m.group(2).strip()}
            for m in _APP_RE.finditer(xml)
        ]

    async def launch_app(self, app_id: str) -> CommandResult:
        if not app_id or not app_id.strip() or "/" in app_id:
            return CommandResult(
                False, error="No valid Roku app id given; refusing to guess one."
            )
        app_id = app_id.strip()
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        try:
            apps = await self.query_apps()
        except ConnectionError as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Could not reach Roku TV at {self.device.ip}: {exc}"
            )
        if not any(a["id"] == app_id for a in apps):
            return CommandResult(
                False,
                error=f"App {app_id} is not installed on this Roku TV, "
                f"so it cannot be launched. Installed apps: "
                + (
                    ", ".join(f"{a['name']} ({a['id']})" for a in apps)
                    or "none found"
                )
                + ".",
            )
        try:
            status, _ = await asyncio.to_thread(
                _http,
                "POST",
                self._url(f"/launch/{urllib.parse.quote(app_id, safe='')}"),
            )
        except ConnectionError as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Could not reach Roku TV at {self.device.ip}: {exc}"
            )
        if status != 200:
            return CommandResult(
                False,
                error=f"Roku launch of app {app_id} failed: "
                f"TV returned HTTP {status}.",
            )
        return CommandResult(
            True,
            f"Launch requested for app {app_id} on Roku TV.",
            details={"app_id": app_id},
        )

    def supports(self, feature: str) -> bool:
        # ECP needs no pairing; everything else works over HTTP.
        return feature in (
            "power",
            "volume",
            "mute",
            "channel",
            "media",
            "launch_app",
        )

    async def get_status(self) -> dict:
        status = await super().get_status()
        status.update({"ecp_port": ROKU_PORT, "last_error": self._last_error})
        return status
