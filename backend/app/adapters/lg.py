"""LG webOS adapter (CONTRACTS.md §5).

Protocol (real, documented — no invented APIs):
- WebSocket ``wss://<ip>:3001`` (self-signed cert; required on firmware
  since ~2023), fallback ``ws://<ip>:3000`` for older sets. The TV uses a
  self-signed certificate, so the ``wss`` connection uses an unverified SSL
  context; this is LAN-only traffic to the user's own TV (§4).
- Register handshake: ``{type: "register", id: "register_0", payload:
  {forcePairing, pairingType: "PROMPT", manifest, "client-key"?}}``. The
  TV shows a pairing prompt; on accept it answers ``type: "registered"``
  with a ``client-key`` in the payload, stored on
  ``device.pairing_token`` (the caller must persist the device record)
  and reused on later connects.
- Buttons are NOT ssap:// calls: they go over a second socket obtained
  via ``ssap://com.webos.service.networkinput/getPointerInputSocket``,
  as plain text ``type:button\\nname:UP\\n\\n``. Verified against the
  documented webOS / lgtv2 protocol (see also Phase 1
  ``mobile/src/services/direct/lgDirect.ts`` and the asyncwebostv
  pointer-protocol design doc).
- Verified ssap:// calls used here (CONTRACTS.md §5 lists volume as
  ``ssap://audio/volume/up|down``; the documented webOS API uses
  ``volumeUp``/``volumeDown``, which is what is implemented):
  ``ssap://audio/volumeUp``, ``ssap://audio/volumeDown``,
  ``ssap://audio/setMute``, ``ssap://audio/setVolume``,
  ``ssap://system/turnOff``, ``ssap://system.launcher/launch {"id": appId}``,
  ``ssap://tv/channelUp``, ``ssap://tv/channelDown``,
  ``ssap://media.controls/play|pause|stop|rewind|fastForward``.

Honest limitations:
- MUTE sends ``setMute {mute: true}`` — it mutes; it does not toggle back
  (toggling needs a state query first, which this adapter does not do).
- POWER sends ``ssap://system/turnOff`` — power off only. Power-ON is
  NOT supported by this adapter (it needs Wake-on-LAN, not implemented
  here); ``get_status()`` reports ``power_on_from_standby: False``.

NEEDS ON-DEVICE VERIFICATION (CONTRACTS.md §7): no real LG TV was
available while writing this. In particular the register manifest below
carries LG's published sample signed block (copied from the Phase 1
direct-mode client); whether the backend's unsigned reuse of it is
accepted by current firmware must be confirmed on a real set.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from typing import Dict, Optional

from .base import CommandResult, DeviceInfo, RemoteKey, TvAdapter

try:
    from websockets.asyncio.client import connect as _ws_connect
except Exception:  # pragma: no cover - websockets < 14 fallback
    try:
        from websockets import connect as _ws_connect  # type: ignore[no-redef]
    except Exception:
        _ws_connect = None  # type: ignore[assignment]

REGISTER_TIMEOUT = 60.0  # on-screen pairing prompt
REQUEST_TIMEOUT = 10.0
SECURE_PORT = 3001
PLAIN_PORT = 3000

# Navigation / menu keys go over the pointer-input socket (verified).
BUTTON_MAP = {
    RemoteKey.UP: "UP",
    RemoteKey.DOWN: "DOWN",
    RemoteKey.LEFT: "LEFT",
    RemoteKey.RIGHT: "RIGHT",
    RemoteKey.OK: "ENTER",
    RemoteKey.BACK: "BACK",
    RemoteKey.HOME: "HOME",
    RemoteKey.MENU: "MENU",
}

# Everything else is a verified ssap:// request (uri, payload).
SSAP_KEY_MAP = {
    RemoteKey.VOLUME_UP: ("ssap://audio/volumeUp", {}),
    RemoteKey.VOLUME_DOWN: ("ssap://audio/volumeDown", {}),
    RemoteKey.MUTE: ("ssap://audio/setMute", {"mute": True}),
    RemoteKey.POWER: ("ssap://system/turnOff", {}),
    RemoteKey.CHANNEL_UP: ("ssap://tv/channelUp", {}),
    RemoteKey.CHANNEL_DOWN: ("ssap://tv/channelDown", {}),
    RemoteKey.PLAY: ("ssap://media.controls/play", {}),
    RemoteKey.PAUSE: ("ssap://media.controls/pause", {}),
    RemoteKey.STOP: ("ssap://media.controls/stop", {}),
    RemoteKey.REWIND: ("ssap://media.controls/rewind", {}),
    RemoteKey.FAST_FORWARD: ("ssap://media.controls/fastForward", {}),
}

# LG's published sample manifest (same as Phase 1 lgDirect.ts).
# NEEDS ON-DEVICE VERIFICATION: the signed block is LG's sample, not a
# signature for this app.
REGISTER_MANIFEST = {
    "manifest": {
        "manifestVersion": 1,
        "appVersion": "1.0.0",
        "signed": {
            "created": "20240101",
            "appId": "com.universal.smartremote",
            "vendorId": "com.universal.smartremote",
            "localizedAppNames": {"": "Universal Smart Remote"},
            "localizedVendorNames": {"": "Universal Smart Remote"},
            "permissions": [
                "LAUNCH",
                "LAUNCH_WEBAPP",
                "APP_TO_APP",
                "CLOSE",
                "CONTROL_AUDIO",
                "CONTROL_INPUT_MEDIA_PLAYBACK",
                "CONTROL_INPUT_TV",
                "CONTROL_MOUSE_AND_KEYBOARD",
                "CONTROL_POWER",
                "READ_CURRENT_CHANNEL",
                "READ_INSTALLED_APPS",
                "READ_RUNNING_APPS",
                "READ_TV_CHANNEL_LIST",
                "WRITE_NOTIFICATION_TOAST",
            ],
            "serial": "00000000000000000000000000000000",
        },
        "permissions": [
            "LAUNCH",
            "LAUNCH_WEBAPP",
            "APP_TO_APP",
            "CLOSE",
            "CONTROL_AUDIO",
            "CONTROL_INPUT_MEDIA_PLAYBACK",
            "CONTROL_INPUT_TV",
            "CONTROL_MOUSE_AND_KEYBOARD",
            "CONTROL_POWER",
            "READ_CURRENT_CHANNEL",
            "READ_INSTALLED_APPS",
            "READ_RUNNING_APPS",
            "READ_TV_CHANNEL_LIST",
            "WRITE_NOTIFICATION_TOAST",
        ],
        "signatures": [],
    },
}


def _ssl_context() -> ssl.SSLContext:
    # The TV presents a self-signed certificate; LAN-only, user's own TV.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class LgAdapter(TvAdapter):
    """LG webOS TV adapter over SSAP WebSockets."""

    brand = "lg"

    def __init__(self, device: DeviceInfo):
        super().__init__(device)
        self._ws = None
        self._input_ws = None
        self._recv_task: Optional[asyncio.Task] = None
        self._next_id = 1
        self._pending: Dict[str, asyncio.Future] = {}
        self._registered = asyncio.Event()
        self._register_error: Optional[str] = None
        self._last_error: Optional[str] = None
        self._secure = False

    # -- connection -----------------------------------------------------

    async def connect(self) -> CommandResult:
        if self.connected and self._ws is not None:
            return CommandResult(True, "Already connected to LG TV.")
        if _ws_connect is None:
            return CommandResult(
                False,
                error="The 'websockets' package is not installed; "
                "cannot connect to an LG TV.",
            )
        if not self.device.ip:
            return CommandResult(False, error="No IP address for LG TV.")

        # Prefer wss://:3001; fall back to ws://:3000 only if the secure
        # connection itself cannot be established (older sets). A register
        # refusal on an established socket is terminal, not a fallback.
        last_error = "could not connect"
        for secure in (True, False):
            port = SECURE_PORT if secure else PLAIN_PORT
            scheme = "wss" if secure else "ws"
            url = f"{scheme}://{self.device.ip}:{port}"
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
            except Exception as exc:
                last_error = f"{url}: {exc}"
                continue
            self._ws = ws
            self._secure = secure
            self._registered.clear()
            self._register_error = None
            self._recv_task = asyncio.create_task(self._recv_loop())
            payload: dict = {
                "forcePairing": False,
                "pairingType": "PROMPT",
                **REGISTER_MANIFEST,
            }
            if self.device.pairing_token:
                payload["client-key"] = self.device.pairing_token
            try:
                await asyncio.wait_for(
                    self._ws.send(
                        json.dumps(
                            {"type": "register", "id": "register_0",
                             "payload": payload}
                        )
                    ),
                    timeout=REQUEST_TIMEOUT,
                )
                await asyncio.wait_for(self._wait_registered(), REGISTER_TIMEOUT)
            except asyncio.TimeoutError:
                last_error = (
                    "Timed out waiting for the LG TV pairing prompt. "
                    "Accept the prompt on the TV, or check the TV is on "
                    "and on the same Wi-Fi."
                )
                await self.disconnect()
                return CommandResult(False, error=last_error)
            except ConnectionError as exc:
                last_error = str(exc)
                await self.disconnect()
                return CommandResult(False, error=last_error)
            except Exception as exc:
                last_error = str(exc)
                await self.disconnect()
                return CommandResult(False, error=last_error)
            self.connected = True
            self.device.paired = True
            return CommandResult(
                True,
                "Connected to LG TV.",
                details={
                    "secure": secure,
                    "client_key_stored": bool(self.device.pairing_token),
                },
            )
        self._last_error = last_error
        return CommandResult(
            False,
            error=f"Could not connect to LG TV at {self.device.ip} "
            f"(ports 3001/3000). Check the TV is on, on the same Wi-Fi, "
            f"and LG Connect Apps / Mobile TV On is enabled. "
            f"Last error: {last_error}",
        )

    async def _wait_registered(self) -> None:
        while not self._registered.is_set() and self._register_error is None:
            await asyncio.sleep(0.02)
        if self._register_error is not None:
            raise ConnectionError(self._register_error)

    async def _recv_loop(self) -> None:
        try:
            while True:
                raw = await self._ws.recv()
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                msg_type = msg.get("type")
                msg_id = msg.get("id")
                if msg_type == "registered":
                    client_key = (msg.get("payload") or {}).get("client-key")
                    if client_key:
                        # Persist on the device; caller saves the record.
                        self.device.pairing_token = str(client_key)
                    self._registered.set()
                    continue
                if msg_type == "error" and msg_id == "register_0":
                    self._register_error = (
                        f"LG TV refused registration: "
                        f"{msg.get('error') or 'unknown error'}. Accept the "
                        f"pairing prompt on the TV and try again."
                    )
                    continue
                if msg_id and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        if msg_type == "error":
                            fut.set_exception(
                                RuntimeError(
                                    "LG TV returned an error: "
                                    f"{msg.get('error') or 'unknown error'}"
                                )
                            )
                        else:
                            fut.set_result(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # socket closed / recv error
            self.connected = False
            self._last_error = str(exc)
            if not self._registered.is_set() and self._register_error is None:
                self._register_error = f"LG TV closed the connection: {exc}"
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(
                        ConnectionError(f"LG TV connection lost: {exc}")
                    )
            self._pending.clear()

    async def disconnect(self) -> None:
        self.connected = False
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
            self._recv_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        if self._input_ws is not None:
            try:
                await asyncio.wait_for(self._input_ws.close(), timeout=5)
            except Exception:
                pass
            self._input_ws = None
        if self._ws is not None:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=5)
            except Exception:
                pass
            self._ws = None

    # -- SSAP requests ----------------------------------------------------

    async def _request(self, uri: str, payload: dict) -> dict:
        """Send one SSAP request and return the response message dict."""
        if self._ws is None:
            raise ConnectionError("Not connected to an LG TV. Connect first.")
        req_id = f"req_{self._next_id}"
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        try:
            await asyncio.wait_for(
                self._ws.send(
                    json.dumps(
                        {"type": "request", "id": req_id, "uri": uri,
                         "payload": payload}
                    )
                ),
                timeout=REQUEST_TIMEOUT,
            )
        except Exception:
            self._pending.pop(req_id, None)
            raise
        try:
            return await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT)
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"LG TV did not respond to {uri}.") from exc

    async def _get_input_socket(self):
        """Open (or reuse) the pointer-input socket for button presses."""
        if self._input_ws is not None:
            return self._input_ws
        res = await self._request(
            "ssap://com.webos.service.networkinput/getPointerInputSocket", {}
        )
        socket_path = (res.get("payload") or {}).get("socketPath")
        if not isinstance(socket_path, str) or not socket_path:
            raise RuntimeError(
                "LG TV did not return a pointer-input socket path."
            )
        use_ssl = socket_path.startswith("wss://")
        try:
            sock = await asyncio.wait_for(
                _ws_connect(
                    socket_path,
                    ssl=_ssl_context() if use_ssl else None,
                    open_timeout=15,
                    close_timeout=5,
                ),
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as exc:
            raise ConnectionError(
                f"Could not open the LG input socket: {exc}"
            ) from exc
        self._input_ws = sock
        return sock

    async def _send_button(self, button_name: str) -> None:
        for attempt in range(2):
            sock = await self._get_input_socket()
            try:
                await asyncio.wait_for(
                    sock.send(f"type:button\nname:{button_name}\n\n"),
                    timeout=REQUEST_TIMEOUT,
                )
                return
            except Exception:
                # Socket may have gone stale; drop it and re-acquire once.
                self._input_ws = None
                try:
                    await sock.close()
                except Exception:
                    pass
                if attempt == 1:
                    raise

    # -- commands -------------------------------------------------------

    async def _ensure_connected(self) -> Optional[CommandResult]:
        """Return None when connected, else the failed connect() result."""
        if self.connected and self._ws is not None:
            return None
        result = await self.connect()
        return None if result.success else result

    async def send_key(self, key: RemoteKey) -> CommandResult:
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        try:
            button = BUTTON_MAP.get(key)
            if button is not None:
                await self._send_button(button)
                return CommandResult(
                    True,
                    f"Sent {key.value} to LG TV.",
                    details={"button": button},
                )
            ssap = SSAP_KEY_MAP.get(key)
            if ssap is not None:
                uri, payload = ssap
                await self._request(uri, payload)
                note = ""
                if key is RemoteKey.MUTE:
                    note = " (mute only; does not unmute)"
                elif key is RemoteKey.POWER:
                    note = " (power off only; power-on is not supported)"
                return CommandResult(
                    True,
                    f"Sent {key.value} to LG TV{note}.",
                    details={"uri": uri},
                )
        except (TimeoutError, ConnectionError, RuntimeError) as exc:
            return CommandResult(False, error=str(exc))
        except Exception as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Failed to send key to LG TV: {exc}"
            )
        return CommandResult(
            False, error=f"LG does not support key: {key.value}"
        )

    async def launch_app(self, app_id: str) -> CommandResult:
        if not app_id:
            return CommandResult(
                False, error="No LG app id given; refusing to guess one."
            )
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        try:
            await self._request(
                "ssap://system.launcher/launch", {"id": app_id}
            )
        except (TimeoutError, ConnectionError, RuntimeError) as exc:
            return CommandResult(False, error=str(exc))
        except Exception as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Failed to launch app on LG TV: {exc}"
            )
        return CommandResult(
            True,
            f"Launch requested for app {app_id} on LG TV.",
            details={"app_id": app_id},
        )

    # -- capabilities / status ------------------------------------------

    def supports(self, feature: str) -> bool:
        # Every feature works while connected. Power is power-OFF only
        # (power-on needs Wake-on-LAN, not implemented); see module
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
                "has_client_key": bool(self.device.pairing_token),
                "input_socket_connected": self._input_ws is not None,
                "power_on_from_standby": False,
                "last_error": self._last_error,
            }
        )
        return status
