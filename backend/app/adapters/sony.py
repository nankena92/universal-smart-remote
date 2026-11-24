"""Sony Bravia adapter — IRCC-IP (CONTRACTS.md §5).

Protocol (real, documented — no invented APIs):

- Keys: ``POST http://<ip>/sony/IRCC`` with a SOAP body
  (``X_SendIRCC`` / ``IRCCCode``) and headers ``Content-Type: text/xml``,
  ``SOAPACTION: "urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"`` and
  ``X-Auth-PSK: <pre-shared key>``.
- The pre-shared key is the one configured on the TV itself (Settings ->
  Network -> Home Network Setup -> IP Control -> Authentication ->
  Pre-Shared Key). It is read from ``device.pairing_token``; with no key
  stored, :meth:`connect` fails with an honest error explaining where to
  set it instead of sending unauthenticated requests.
- Connect verifies reachability and the PSK with a read-only JSON-RPC
  call, ``POST /sony/system`` ``{"method": "getPowerStatus", ...}`` — no
  button is pressed to check the connection.
- IRCC codes below are the documented Bravia codes (e.g. the
  ``trugamr/bravia`` API package): Power ``AAAAAQAAAAEAAAAVAw==``,
  VolumeUp ``AAAAAQAAAAEAAAASAw==``, VolumeDown
  ``AAAAAQAAAAEAAAATAw==``, Mute ``AAAAAQAAAAEAAAAUAw==``, Up
  ``AAAAAQAAAAEAAAB0Aw==``, Down ``AAAAAQAAAAEAAAB1Aw==``, Left
  ``AAAAAQAAAAEAAAA0Aw==``, Right ``AAAAAQAAAAEAAAAzAw==``, Confirm
  ``AAAAAQAAAAEAAABlAw==``, Return ``AAAAAgAAAJcAAAAjAw==``, Home
  ``AAAAAQAAAAEAAABgAw==``, ActionMenu ``AAAAAgAAAMQAAABLAw==``,
  ChannelUp ``AAAAAQAAAAEAAAAQAw==``, ChannelDown
  ``AAAAAQAAAAEAAAARAw==``, Play ``AAAAAgAAAJcAAAAaAw==``, Pause
  ``AAAAAgAAAJcAAAAZAw==``, Stop ``AAAAAgAAAJcAAAAYAw==``, Rewind
  ``AAAAAgAAAJcAAAAbAw==``, Forward ``AAAAAgAAAJcAAAAcAw==``.

Launch limitation (honest, CONTRACTS.md §5): IRCC-IP emulates remote
buttons and cannot launch an arbitrary streaming app by id, so
``supports("launch_app")`` is False and :meth:`launch_app` always returns
an honest error.

Note the IRCC Power code is a toggle: there is no separate power-on /
power-off over IRCC-IP.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Optional

from .base import CommandResult, DeviceInfo, RemoteKey, TvAdapter

REQUEST_TIMEOUT = 8.0

# Documented Sony Bravia IRCC codes (see module docstring).
IRCC_MAP = {
    RemoteKey.UP: "AAAAAQAAAAEAAAB0Aw==",
    RemoteKey.DOWN: "AAAAAQAAAAEAAAB1Aw==",
    RemoteKey.LEFT: "AAAAAQAAAAEAAAA0Aw==",
    RemoteKey.RIGHT: "AAAAAQAAAAEAAAAzAw==",
    RemoteKey.OK: "AAAAAQAAAAEAAABlAw==",  # Confirm
    RemoteKey.BACK: "AAAAAgAAAJcAAAAjAw==",  # Return
    RemoteKey.HOME: "AAAAAQAAAAEAAABgAw==",
    RemoteKey.MENU: "AAAAAgAAAMQAAABLAw==",  # ActionMenu
    RemoteKey.POWER: "AAAAAQAAAAEAAAAVAw==",  # Power toggle
    RemoteKey.VOLUME_UP: "AAAAAQAAAAEAAAASAw==",
    RemoteKey.VOLUME_DOWN: "AAAAAQAAAAEAAAATAw==",
    RemoteKey.MUTE: "AAAAAQAAAAEAAAAUAw==",
    RemoteKey.CHANNEL_UP: "AAAAAQAAAAEAAAAQAw==",
    RemoteKey.CHANNEL_DOWN: "AAAAAQAAAAEAAAARAw==",
    RemoteKey.PLAY: "AAAAAgAAAJcAAAAaAw==",
    RemoteKey.PAUSE: "AAAAAgAAAJcAAAAZAw==",
    RemoteKey.STOP: "AAAAAgAAAJcAAAAYAw==",
    RemoteKey.REWIND: "AAAAAgAAAJcAAAAbAw==",
    RemoteKey.FAST_FORWARD: "AAAAAgAAAJcAAAAcAw==",
}

_SOAP_TEMPLATE = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body>"
    '<u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1">'
    "<IRCCCode>{code}</IRCCCode>"
    "</u:X_SendIRCC>"
    "</s:Body>"
    "</s:Envelope>"
)


def _http(method: str, url: str, body: bytes, headers: dict,
          timeout: float = REQUEST_TIMEOUT):
    """Blocking HTTP request. Returns ``(status, body_bytes)``.

    HTTP error statuses are returned, not raised, so callers can report the
    TV's real response. Network failures raise :class:`ConnectionError`.
    """
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ConnectionError(str(exc)) from exc


class SonyAdapter(TvAdapter):
    """Sony Bravia TV adapter over IRCC-IP."""

    brand = "sony"

    def __init__(self, device: DeviceInfo):
        super().__init__(device)
        self._last_error: Optional[str] = None
        self._last_power: Optional[str] = None

    @property
    def _psk(self) -> str:
        return (self.device.pairing_token or "").strip()

    def _url(self, path: str) -> str:
        return f"http://{self.device.ip}{path}"

    def _auth_headers(self, extra: Optional[dict] = None) -> dict:
        headers = {"X-Auth-PSK": self._psk}
        if extra:
            headers.update(extra)
        return headers

    async def connect(self) -> CommandResult:
        if self.connected:
            return CommandResult(True, "Already connected to Sony TV.")
        if not self.device.ip:
            return CommandResult(False, error="No IP address for Sony TV.")
        if not self._psk:
            return CommandResult(
                False,
                error="No pre-shared key stored for this Sony TV. On the TV, "
                "go to Settings -> Network -> Home Network Setup -> IP "
                "Control -> Authentication, set it to Pre-Shared Key (or "
                "Normal and Pre-Shared Key), enter a key, and save the same "
                "key for this device before connecting.",
            )
        payload = json.dumps(
            {"method": "getPowerStatus", "params": [], "id": 1,
             "version": "1.0"}
        ).encode("utf-8")
        try:
            status, body = await asyncio.to_thread(
                _http,
                "POST",
                self._url("/sony/system"),
                payload,
                self._auth_headers({"Content-Type": "application/json"}),
            )
        except ConnectionError as exc:
            self._last_error = str(exc)
            return CommandResult(
                False,
                error=f"Could not reach Sony TV at {self.device.ip}. "
                f"Check the TV is on and on the same Wi-Fi. ({exc})",
            )
        if status in (401, 403):
            self._last_error = f"HTTP {status}"
            return CommandResult(
                False,
                error="Sony TV rejected the pre-shared key (HTTP "
                f"{status}). Check the key set on the TV under Settings -> "
                "Network -> Home Network Setup -> IP Control.",
            )
        if status != 200:
            self._last_error = f"HTTP {status}"
            return CommandResult(
                False,
                error=f"Sony TV at {self.device.ip} returned HTTP {status} "
                f"for getPowerStatus; is this really a Sony Bravia TV?",
            )
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
            results = data.get("result") or []
            if results:
                self._last_power = str(results[0].get("status", ""))
        except (ValueError, AttributeError, IndexError):
            pass
        self.connected = True
        self.device.paired = True  # PSK auth accepted by the TV.
        return CommandResult(True, "Connected to Sony TV.")

    async def disconnect(self) -> None:
        self.connected = False

    async def _ensure_connected(self) -> Optional[CommandResult]:
        """Return None when connected, else the failed connect() result."""
        if self.connected:
            return None
        result = await self.connect()
        return None if result.success else result

    async def send_key(self, key: RemoteKey) -> CommandResult:
        code = IRCC_MAP.get(key)
        if code is None:
            return CommandResult(
                False, error=f"Sony does not support key: {key.value}"
            )
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        body = _SOAP_TEMPLATE.format(code=code).encode("utf-8")
        try:
            status, _ = await asyncio.to_thread(
                _http,
                "POST",
                self._url("/sony/IRCC"),
                body,
                self._auth_headers(
                    {
                        "Content-Type": "text/xml; charset=UTF-8",
                        "SOAPACTION": (
                            '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"'
                        ),
                    }
                ),
            )
        except ConnectionError as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Could not reach Sony TV at {self.device.ip}: {exc}"
            )
        if status in (401, 403):
            self.connected = False
            return CommandResult(
                False,
                error="Sony TV rejected the pre-shared key (HTTP "
                f"{status}). Check the key set on the TV.",
            )
        if status != 200:
            return CommandResult(
                False,
                error=f"Sony IRCC {key.value} failed: "
                f"TV returned HTTP {status}.",
            )
        return CommandResult(
            True,
            f"Sent {key.value} to Sony TV.",
            details={"ircc_code": code},
        )

    async def launch_app(self, app_id: str) -> CommandResult:
        # IRCC-IP can only press remote buttons; there is no documented way
        # to launch an arbitrary streaming app by id (CONTRACTS.md §5).
        return CommandResult(
            False,
            error="Sony Bravia IRCC-IP cannot launch apps by id. IRCC-IP "
            "only emulates remote-control buttons, so open the app from the "
            "TV's home screen (or with the Home key and navigation) "
            "instead. No app was launched.",
        )

    def supports(self, feature: str) -> bool:
        # launch_app is not possible over IRCC-IP; PSK auth is configured
        # on the TV, not a pairing flow, so "pairing" is False too.
        return feature in ("power", "volume", "mute", "channel", "media")

    async def get_status(self) -> dict:
        status = await super().get_status()
        status.update(
            {
                "has_psk": bool(self._psk),
                "power": self._last_power,
                "last_error": self._last_error,
            }
        )
        return status
