"""Amazon Fire TV adapter — local ADB only (CONTRACTS.md §5).

Protocol (real, documented — no invented APIs):

- ``adb connect <ip>:5555``, then ``adb -s <ip>:5555 shell input
  keyevent <code>`` (Android key codes) and app launch by package with
  ``adb -s <ip>:5555 shell monkey -p <package> -c
  android.intent.category.LAUNCHER 1``.
- Only works when ADB debugging is enabled on the Fire TV (Settings ->
  My Fire TV -> Developer Options -> ADB Debugging) and the authorization
  prompt on the TV has been accepted. If ``adb`` is not installed, the TV
  is unreachable, or the device shows as ``unauthorized``,
  :meth:`connect` fails with an honest error explaining what to do.
- Every ``adb`` invocation uses an argument list (never a shell) with a
  timeout, and package names are validated before use, so no unsanitized
  input ever reaches a shell.

Note on app launch: CONTRACTS.md §5 sketches ``adb shell am start -n
<package>``, but ``am start -n`` needs a full component name
(``package/activity``), not a bare package. ``monkey -p <package>`` is the
documented Android tool that launches an app by package name alone, so it
is used instead; the intent (launch by package) is unchanged.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from typing import Optional

from .base import CommandResult, DeviceInfo, RemoteKey, TvAdapter

ADB_PORT = 5555
ADB_TIMEOUT = 10.0
CONNECT_TIMEOUT = 15.0

# Android KeyEvent codes (android.view.KeyEvent).
KEY_MAP = {
    RemoteKey.UP: 19,  # KEYCODE_DPAD_UP
    RemoteKey.DOWN: 20,  # KEYCODE_DPAD_DOWN
    RemoteKey.LEFT: 21,  # KEYCODE_DPAD_LEFT
    RemoteKey.RIGHT: 22,  # KEYCODE_DPAD_RIGHT
    RemoteKey.OK: 23,  # KEYCODE_DPAD_CENTER
    RemoteKey.BACK: 4,  # KEYCODE_BACK
    RemoteKey.HOME: 3,  # KEYCODE_HOME
    RemoteKey.MENU: 82,  # KEYCODE_MENU
    RemoteKey.POWER: 26,  # KEYCODE_POWER
    RemoteKey.VOLUME_UP: 24,  # KEYCODE_VOLUME_UP
    RemoteKey.VOLUME_DOWN: 25,  # KEYCODE_VOLUME_DOWN
    RemoteKey.MUTE: 164,  # KEYCODE_VOLUME_MUTE
    RemoteKey.CHANNEL_UP: 166,  # KEYCODE_CHANNEL_UP
    RemoteKey.CHANNEL_DOWN: 167,  # KEYCODE_CHANNEL_DOWN
    RemoteKey.PLAY: 126,  # KEYCODE_MEDIA_PLAY
    RemoteKey.PAUSE: 127,  # KEYCODE_MEDIA_PAUSE
    RemoteKey.STOP: 86,  # KEYCODE_MEDIA_STOP
    RemoteKey.REWIND: 89,  # KEYCODE_MEDIA_REWIND
    RemoteKey.FAST_FORWARD: 90,  # KEYCODE_MEDIA_FAST_FORWARD
}

# A bare Android package name: dotted identifiers, no slashes or spaces.
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


# --------------------------------------------------------------------------
# Shared ADB helpers (also used by the Android TV adapter, which launches
# apps the same way). All subprocess calls use argument lists and timeouts.
# --------------------------------------------------------------------------

def adb_available() -> bool:
    """True when an ``adb`` binary is on PATH."""
    return shutil.which("adb") is not None


def _run_adb(args: list, timeout: float = ADB_TIMEOUT):
    """Run ``adb`` with an argument list. Returns ``(rc, stdout, stderr)``.

    Raises :class:`FileNotFoundError` when ``adb`` is not installed and
    :class:`subprocess.TimeoutExpired` on timeout.
    """
    proc = subprocess.run(
        ["adb"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def adb_target(ip: str) -> str:
    return f"{ip}:{ADB_PORT}"


def adb_connect(ip: str) -> tuple[bool, str]:
    """``adb connect <ip>:5555``. Returns ``(ok, human-readable detail)``."""
    try:
        _, out, err = _run_adb(
            ["connect", adb_target(ip)], timeout=CONNECT_TIMEOUT
        )
    except FileNotFoundError:
        return False, "adb is not installed"
    except subprocess.TimeoutExpired:
        return False, f"timed out connecting to {adb_target(ip)}"
    text = (out + err).strip()
    if "already connected" in text or f"connected to {adb_target(ip)}" in text:
        return True, text
    if "failed to connect" in text or "Connection refused" in text:
        return False, text or "connection refused"
    if "cannot connect" in text:
        return False, text
    # adb prints "connected to <ip>:5555" on success; anything else is
    # treated as a failure rather than assumed success.
    return False, text or "adb connect gave no output"


def adb_device_state(ip: str) -> Optional[str]:
    """State of ``<ip>:5555`` in ``adb devices``: "device", "unauthorized",
    "offline", or None when the target is not listed at all."""
    try:
        _, out, _ = _run_adb(["devices"], timeout=ADB_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == adb_target(ip):
            return parts[1]
    return None


def adb_shell(ip: str, *args: str, timeout: float = ADB_TIMEOUT):
    """``adb -s <ip>:5555 shell <args>``. Returns ``(rc, stdout, stderr)``."""
    return _run_adb(["-s", adb_target(ip), "shell", *args], timeout=timeout)


def adb_launch_package(ip: str, package: str) -> tuple[bool, str]:
    """Launch an app by package name with ``monkey``.

    Returns ``(ok, detail)``. ``package`` is validated before use.
    """
    if not _PACKAGE_RE.match(package or ""):
        return False, f"Invalid Android package name: {package!r}"
    try:
        rc, out, err = adb_shell(
            ip, "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
    except FileNotFoundError:
        return False, "adb is not installed"
    except subprocess.TimeoutExpired:
        return False, f"timed out launching {package}"
    text = (out + err).strip()
    if rc == 0 and "Events injected: 1" in out:
        return True, text
    if rc == 0 and "No activities found" in text:
        return False, (
            f"Package {package} is not installed (or has no launcher "
            f"activity) on this Fire TV."
        )
    return False, text or f"adb exited with status {rc}"


class FireTvAdapter(TvAdapter):
    """Amazon Fire TV adapter over local ADB."""

    brand = "firetv"

    def __init__(self, device: DeviceInfo):
        super().__init__(device)
        self._last_error: Optional[str] = None

    async def connect(self) -> CommandResult:
        if self.connected:
            return CommandResult(True, "Already connected to Fire TV.")
        if not self.device.ip:
            return CommandResult(False, error="No IP address for Fire TV.")
        if not adb_available():
            return CommandResult(
                False,
                error="The 'adb' command is not installed on the backend "
                "host, so Fire TV cannot be controlled. Install Android "
                "platform-tools (which provides adb) on the machine running "
                "the backend and try again.",
            )
        ok, detail = await asyncio.to_thread(adb_connect, self.device.ip)
        if not ok:
            self._last_error = detail
            return CommandResult(
                False,
                error=f"Could not connect to Fire TV at {self.device.ip} "
                f"over ADB ({detail}). On the Fire TV, enable Settings -> "
                f"My Fire TV -> Developer Options -> ADB Debugging, and "
                f"make sure the TV is on the same Wi-Fi as the backend.",
            )
        state = await asyncio.to_thread(adb_device_state, self.device.ip)
        if state == "unauthorized":
            self._last_error = "unauthorized"
            return CommandResult(
                False,
                error="Fire TV shows this backend as unauthorized for ADB. "
                "Look at the Fire TV screen and accept the 'Allow USB "
                "debugging?' prompt, then try again.",
            )
        if state != "device":
            self._last_error = f"adb state: {state}"
            return CommandResult(
                False,
                error=f"Fire TV at {self.device.ip} is not ready for ADB "
                f"(adb devices state: {state or 'not listed'}). Check ADB "
                f"Debugging is enabled on the TV and try again.",
            )
        self.connected = True
        self.device.paired = True  # ADB authorization accepted on the TV.
        return CommandResult(True, "Connected to Fire TV over ADB.")

    async def disconnect(self) -> None:
        self.connected = False
        # Deliberately do not run `adb disconnect`: other tools may share
        # the adb server, and disconnecting would drop their sessions too.

    async def _ensure_connected(self) -> Optional[CommandResult]:
        """Return None when connected, else the failed connect() result."""
        if self.connected:
            return None
        result = await self.connect()
        return None if result.success else result

    async def send_key(self, key: RemoteKey) -> CommandResult:
        code = KEY_MAP.get(key)
        if code is None:
            return CommandResult(
                False, error=f"Fire TV does not support key: {key.value}"
            )
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        try:
            rc, out, err = await asyncio.to_thread(
                adb_shell, self.device.ip, "input", "keyevent", str(code)
            )
        except FileNotFoundError:
            return CommandResult(False, error="adb is not installed.")
        except subprocess.TimeoutExpired:
            return CommandResult(
                False, error=f"Timed out sending {key.value} to Fire TV."
            )
        if rc != 0:
            self.connected = False
            return CommandResult(
                False,
                error=f"Failed to send {key.value} to Fire TV: "
                f"{(err or out).strip() or f'adb exited with status {rc}'}.",
            )
        return CommandResult(
            True,
            f"Sent {key.value} to Fire TV.",
            details={"keyevent": code},
        )

    async def launch_app(self, app_id: str) -> CommandResult:
        # Here app_id is an Android package name (see apps.py).
        if not app_id:
            return CommandResult(
                False, error="No Fire TV package name given; refusing to guess one."
            )
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        ok, detail = await asyncio.to_thread(
            adb_launch_package, self.device.ip, app_id
        )
        if not ok:
            return CommandResult(
                False, error=f"Could not launch {app_id} on Fire TV: {detail}"
            )
        return CommandResult(
            True,
            f"Launch requested for {app_id} on Fire TV.",
            details={"app_id": app_id},
        )

    def supports(self, feature: str) -> bool:
        # ADB authorization is accepted on the TV, not a PIN pairing flow.
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
        status.update(
            {
                "adb_target": adb_target(self.device.ip) if self.device.ip else "",
                "adb_available": adb_available(),
                "last_error": self._last_error,
            }
        )
        return status
