"""Samsung Tizen adapter (CONTRACTS.md §5).

Protocol (real, documented — no invented APIs):
- WebSocket ``ws://<ip>:8001/api/v2/channels/samsung.remote.control?name=<base64(name)>``
  and secure ``wss://<ip>:8002`` with a token. The TV uses a self-signed
  certificate, so the ``wss`` connection uses an unverified SSL context;
  this is LAN-only traffic to the user's own TV (see CONTRACTS.md §4).
- First connect (no token) shows an Allow prompt on the TV; accepting it
  returns ``ms.channel.connect`` carrying a token, which is stored on
  ``device.pairing_token`` (the caller must persist the device record).
  A denied prompt returns ``ms.channel.unauthorized``.
- Keys: ``ms.remote.control`` ``{Cmd: "Click", DataOfCmd: KEY_*, Option:
  "false", TypeOfRemote: "SendRemoteKey"}``.
- Launch: ``ms.channel.emit`` ``{event: "ed.apps.launch", to: "host",
  data: {appId, action_type: "NATIVE_LAUNCH"}}``.

Power limitation (honest): power-ON from standby is NOT supported —
standby closes the control channel, so there is no open socket to send
``KEY_POWER`` on, and this adapter implements no Wake-on-LAN. ``send_key``
with POWER works only while connected (i.e. it powers the TV off).
``supports("power")`` stays True because the power key works while
connected; :meth:`get_status` reports ``power_on_from_standby: False``.

NEEDS ON-DEVICE VERIFICATION (CONTRACTS.md §7): no real Samsung TV was
available while writing this; the handshake/key/launch frames follow the
documented protocol and the Phase 1 direct-mode client
(``mobile/src/services/direct/samsungDirect.ts``), which uses the same
frames.
"""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
from typing import Optional

from .base import CommandResult, DeviceInfo, RemoteKey, TvAdapter

try:
    from websockets.asyncio.client import connect as _ws_connect
except Exception:  # pragma: no cover - websockets < 14 fallback
    try:
        from websockets import connect as _ws_connect  # type: ignore[no-redef]
    except Exception:
        _ws_connect = None  # type: ignore[assignment]

CONNECT_TIMEOUT = 60.0  # TV Allow prompt can take a while
SEND_TIMEOUT = 10.0
SECURE_PORT = 8002
PLAIN_PORT = 8001

KEY_MAP = {
    RemoteKey.UP: "KEY_UP",
    RemoteKey.DOWN: "KEY_DOWN",
    RemoteKey.LEFT: "KEY_LEFT",
    RemoteKey.RIGHT: "KEY_RIGHT",
    RemoteKey.OK: "KEY_ENTER",
    RemoteKey.BACK: "KEY_RETURN",
    RemoteKey.HOME: "KEY_HOME",
    RemoteKey.MENU: "KEY_MENU",
    RemoteKey.POWER: "KEY_POWER",
    RemoteKey.VOLUME_UP: "KEY_VOLUP",
    RemoteKey.VOLUME_DOWN: "KEY_VOLDOWN",
    RemoteKey.MUTE: "KEY_MUTE",
    RemoteKey.CHANNEL_UP: "KEY_CHUP",
    RemoteKey.CHANNEL_DOWN: "KEY_CHDOWN",
    RemoteKey.PLAY: "KEY_PLAY",
    RemoteKey.PAUSE: "KEY_PAUSE",
    RemoteKey.STOP: "KEY_STOP",
    RemoteKey.REWIND: "KEY_REWIND",
    RemoteKey.FAST_FORWARD: "KEY_FF",
}


def _ssl_context() -> ssl.SSLContext:
    # The TV presents a self-signed certificate; LAN-only, user's own TV.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class SamsungAdapter(TvAdapter):
    """Samsung Tizen TV adapter over the remote-control WebSocket channel."""

    brand = "samsung"

    def __init__(self, device: DeviceInfo):
        super().__init__(device)
        self._ws = None
        self._recv_task: Optional[asyncio.Task] = None
        self._hs_ok = asyncio.Event()
        self._hs_error: Optional[str] = None
        self._last_error: Optional[str] = None
        self._secure = False

    # -- connection -----------------------------------------------------

    def _url(self, secure: bool) -> str:
        scheme = "wss" if secure else "ws"
        port = SECURE_PORT if secure else PLAIN_PORT
        name = base64.b64encode(
            (self.device.name or "Universal Smart Remote").encode("utf-8")
        ).decode("ascii")
        url = (
            f"{scheme}://{self.device.ip}:{port}"
            f"/api/v2/channels/samsung.remote.control?name={name}"
        )
        if self.device.pairing_token:
            url += f"&token={self.device.pairing_token}"
        return url

    async def connect(self) -> CommandResult:
        if self.connected and self._ws is not None:
            return CommandResult(True, "Already connected to Samsung TV.")
        if _ws_connect is None:
            return CommandResult(
                False,
                error="The 'websockets' package is not installed; "
                "cannot connect to a Samsung TV.",
            )
        if not self.device.ip:
            return CommandResult(False, error="No IP address for Samsung TV.")

        # Prefer the secure channel; fall back to plain ws://:8001 only if
        # the secure connection itself cannot be established (older sets).
        attempts = [(True, None), (False, None)]
        last_error = "could not connect"
        for secure, _ in attempts:
            url = self._url(secure)
            try:
                ws = await asyncio.wait_for(
                    _ws_connect(
                        url,
                        ssl=_ssl_context() if secure else None,
                        open_timeout=15,
                        close_timeout=5,
                    ),
                    timeout=20,
                )
            except Exception as exc:  # connection refused / TLS / timeout
                last_error = f"{url}: {exc}"
                continue
            self._ws = ws
            self._secure = secure
            self._hs_ok.clear()
            self._hs_error = None
            self._recv_task = asyncio.create_task(self._recv_loop())
            try:
                await asyncio.wait_for(self._wait_handshake(), CONNECT_TIMEOUT)
            except asyncio.TimeoutError:
                last_error = (
                    "Timed out waiting for the Samsung TV to accept the "
                    "connection. Check the TV shows an Allow prompt and "
                    "accept it."
                )
                await self.disconnect()
                return CommandResult(False, error=last_error)
            except ConnectionError as exc:
                last_error = str(exc)
                await self.disconnect()
                return CommandResult(False, error=last_error)
            self.connected = True
            self.device.paired = True
            return CommandResult(
                True,
                "Connected to Samsung TV.",
                details={
                    "secure": secure,
                    "token_stored": bool(self.device.pairing_token),
                },
            )
        self._last_error = last_error
        return CommandResult(
            False,
            error=f"Could not connect to Samsung TV at {self.device.ip}. "
            f"Check the TV is on, on the same Wi-Fi, and IP Remote is "
            f"enabled. Last error: {last_error}",
        )

    async def _wait_handshake(self) -> None:
        while not self._hs_ok.is_set() and self._hs_error is None:
            await asyncio.sleep(0.02)
        if self._hs_error is not None:
            raise ConnectionError(self._hs_error)

    async def _recv_loop(self) -> None:
        try:
            while True:
                raw = await self._ws.recv()
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                event = msg.get("event")
                if event == "ms.channel.connect":
                    token = (msg.get("data") or {}).get("token")
                    if token:
                        # Persist on the device; the caller saves the record.
                        self.device.pairing_token = str(token)
                    self._hs_ok.set()
                elif event == "ms.channel.unauthorized":
                    self._hs_error = (
                        "Samsung TV refused the connection. The Allow "
                        "prompt was denied, or this phone/backend is "
                        "blocked in the TV's Device Connection Manager."
                    )
                    self._hs_ok.clear()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # socket closed / recv error
            self.connected = False
            if not self._hs_ok.is_set() and self._hs_error is None:
                self._hs_error = f"Samsung TV closed the connection: {exc}"
            self._last_error = str(exc)

    async def disconnect(self) -> None:
        self.connected = False
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
            self._recv_task = None
        if self._ws is not None:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=5)
            except Exception:
                pass
            self._ws = None

    # -- commands -------------------------------------------------------

    async def _ensure_connected(self) -> Optional[CommandResult]:
        """Return None when connected, else the failed connect() result."""
        if self.connected and self._ws is not None:
            return None
        result = await self.connect()
        return None if result.success else result

    async def send_key(self, key: RemoteKey) -> CommandResult:
        samsung_key = KEY_MAP.get(key)
        if samsung_key is None:
            return CommandResult(
                False, error=f"Samsung does not support key: {key.value}"
            )
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        if key is RemoteKey.POWER:
            # Honest note: this only powers off; power-on from standby is
            # impossible over a closed channel (see module docstring).
            pass
        payload = {
            "method": "ms.remote.control",
            "params": {
                "Cmd": "Click",
                "DataOfCmd": samsung_key,
                "Option": "false",
                "TypeOfRemote": "SendRemoteKey",
            },
        }
        try:
            await asyncio.wait_for(
                self._ws.send(json.dumps(payload)), timeout=SEND_TIMEOUT
            )
        except asyncio.TimeoutError:
            return CommandResult(
                False, error="Timed out sending key to Samsung TV."
            )
        except Exception as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Failed to send key to Samsung TV: {exc}"
            )
        return CommandResult(
            True,
            f"Sent {key.value} to Samsung TV.",
            details={"samsung_key": samsung_key},
        )

    async def launch_app(self, app_id: str) -> CommandResult:
        if not app_id:
            return CommandResult(
                False, error="No Samsung app id given; refusing to guess one."
            )
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        payload = {
            "method": "ms.channel.emit",
            "params": {
                "event": "ed.apps.launch",
                "to": "host",
                "data": {"appId": app_id, "action_type": "NATIVE_LAUNCH"},
            },
        }
        try:
            await asyncio.wait_for(
                self._ws.send(json.dumps(payload)), timeout=SEND_TIMEOUT
            )
        except asyncio.TimeoutError:
            return CommandResult(
                False, error="Timed out launching app on Samsung TV."
            )
        except Exception as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Failed to launch app on Samsung TV: {exc}"
            )
        return CommandResult(
            True,
            f"Launch requested for app {app_id} on Samsung TV.",
            details={"app_id": app_id},
        )

    # -- capabilities / status ------------------------------------------

    def supports(self, feature: str) -> bool:
        # Every feature works while connected. Power-on from standby is NOT
        # supported (standby closes the control channel); see module
        # docstring and get_status()["power_on_from_standby"].
        return feature in (
            "power",
            "volume",
            "mute",
            "channel",
            "media",
            "launch_app",
            "pairing",
        )

    async def get_status(self) -> dict:
        status = await super().get_status()
        status.update(
            {
                "secure_channel": self._secure,
                "has_pairing_token": bool(self.device.pairing_token),
                "power_on_from_standby": False,
                "last_error": self._last_error,
            }
        )
        return status
