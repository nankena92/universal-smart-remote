"""TCL adapter — delegates by detected OS (CONTRACTS.md §1, §5).

TCL sells TVs running two different operating systems, and there is no
TCL-specific control protocol to invent:

- Roku-OS models -> :class:`app.adapters.roku.RokuAdapter` (ECP, port 8060).
- Android / Google TV models -> :class:`app.adapters.android_tv.AndroidTvAdapter`
  (Remote protocol v2, port 6466, plus ADB for app launch).

Detection is from the discovered ``model``/``name`` string. If the OS
cannot be determined, :meth:`connect` fails with an honest error telling
the user to pick the OS manually — it never guesses, because guessing
would send the wrong protocol at the TV. ``supports`` and the command
methods delegate to the detected adapter; with no detected OS they
report nothing supported and return honest errors.
"""

from __future__ import annotations

import dataclasses
from typing import Optional

from .android_tv import AndroidTvAdapter
from .base import CommandResult, DeviceInfo, RemoteKey, TvAdapter
from .roku import RokuAdapter


def detect_os(device: DeviceInfo) -> Optional[str]:
    """Detect the TCL TV's OS from its model/name string.

    Returns ``"roku"`` or ``"androidtv"``, or None when the OS cannot be
    determined from the information available.
    """
    haystack = f"{device.model or ''} {device.name or ''}".lower()
    if "roku" in haystack:
        return "roku"
    if "android" in haystack or "google tv" in haystack or "googletv" in haystack:
        return "androidtv"
    return None


class TclAdapter(TvAdapter):
    """TCL TV adapter delegating to the Roku or Android TV adapter."""

    brand = "tcl"

    def __init__(self, device: DeviceInfo):
        super().__init__(device)
        self._delegate: Optional[TvAdapter] = None
        self._delegated_brand: Optional[str] = None
        os_name = detect_os(device)
        if os_name == "roku":
            self._delegate = RokuAdapter(
                dataclasses.replace(device, brand="roku")
            )
            self._delegated_brand = "roku"
        elif os_name == "androidtv":
            self._delegate = AndroidTvAdapter(
                dataclasses.replace(device, brand="androidtv")
            )
            self._delegated_brand = "androidtv"

    def _no_os_error(self) -> CommandResult:
        return CommandResult(
            False,
            error="Could not determine whether this TCL TV runs Roku OS or "
            "Android/Google TV from the discovered model information "
            f"(model: {self.device.model or 'unknown'}). Please select the "
            "TV's operating system manually (Roku or Android TV) and try "
            "again. No command was sent.",
        )

    def _sync_back(self) -> None:
        """Copy pairing material the delegate stored back onto our device.

        The delegate works on a copy of the DeviceInfo; if it stored a
        certificate/token (Android TV pairing), the caller must persist
        our record too.
        """
        if self._delegate is not None:
            self.device.pairing_token = self._delegate.device.pairing_token
            self.device.paired = self._delegate.device.paired

    async def connect(self) -> CommandResult:
        if self._delegate is None:
            return self._no_os_error()
        result = await self._delegate.connect()
        self.connected = self._delegate.connected
        self._sync_back()
        return result

    async def disconnect(self) -> None:
        self.connected = False
        if self._delegate is not None:
            await self._delegate.disconnect()

    async def pair(self, code: str) -> CommandResult:
        """Pairing passthrough (only the Android TV delegate pairs)."""
        if self._delegate is None:
            return self._no_os_error()
        if isinstance(self._delegate, AndroidTvAdapter):
            result = await self._delegate.pair(code)
            self.connected = self._delegate.connected
            self._sync_back()
            return result
        return CommandResult(
            False,
            error="This TCL TV runs Roku OS, which needs no pairing. "
            "Connect it directly instead.",
        )

    async def send_key(self, key: RemoteKey) -> CommandResult:
        if self._delegate is None:
            return self._no_os_error()
        result = await self._delegate.send_key(key)
        self.connected = self._delegate.connected
        return result

    async def launch_app(self, app_id: str) -> CommandResult:
        if self._delegate is None:
            return self._no_os_error()
        result = await self._delegate.launch_app(app_id)
        self.connected = self._delegate.connected
        return result

    def supports(self, feature: str) -> bool:
        if self._delegate is None:
            return False
        return self._delegate.supports(feature)

    async def get_status(self) -> dict:
        status = await super().get_status()
        status.update({"delegated_brand": self._delegated_brand})
        if self._delegate is not None:
            delegate_status = await self._delegate.get_status()
            delegate_status.pop("brand", None)
            status["delegate"] = delegate_status
        return status
