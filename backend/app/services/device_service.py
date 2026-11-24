"""Command service: routes remote calls through the brand adapters.

- Revalidates same-Wi-Fi before EVERY command (CONTRACTS.md §4).
- The adapter package is imported lazily: if it is not present (yet), the
  service raises an honest 503 instead of a fake success.
- Launch-app resolves the brand app id via ``adapters/apps.py``
  (``STREAMING_APPS``) when present, else an honest error.
- ``adapter_factory`` / ``streaming_apps_override`` are module-level
  injection points used by the tests (a stub/mock adapter); production code
  always goes through the real ``get_adapter``.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from datetime import datetime, timezone

from app.models import database as db
from app.network.validation import SameWifiError, assert_same_subnet

logger = logging.getLogger(__name__)

try:  # The adapters phase owns this interface (CONTRACTS.md §1).
    from app.adapters.base import CommandResult, DeviceInfo, RemoteKey
except Exception:  # pragma: no cover - base.py is created verbatim
    from dataclasses import dataclass, field as _field
    from enum import Enum as _Enum

    class RemoteKey(str, _Enum):  # type: ignore[no-redef]
        UP = "up"

    @dataclass
    class CommandResult:  # type: ignore[no-redef]
        success: bool
        message: str = ""
        error: str | None = None
        details: dict = _field(default_factory=dict)

    @dataclass
    class DeviceInfo:  # type: ignore[no-redef]
        id: str
        name: str
        brand: str
        model: str = ""
        ip: str = ""
        port: int = 0
        mac: str = ""
        pairing_token: str = ""
        paired: bool = False


CONNECT_TIMEOUT = 15.0
COMMAND_TIMEOUT = 10.0

# Live adapter instances with an in-progress pairing session, keyed by
# device id. connect() stores the instance when it returns
# pairing_required; pair() reuses it because the pairing session lives on
# that instance (e.g. Android TV's Polo writer/reader). Cleared on pair
# success and on disconnect. In-memory only: a server restart loses the
# session and the user must connect again for a fresh code (honest error).
_pairing_adapters: dict = {}

# Test injection points (see module docstring). Production leaves both None.
adapter_factory = None
streaming_apps_override = None

_last_error: str | None = None


# ---------------------------------------------------------------------------
# Errors (routes map these to HTTP statuses; never a fake success)
# ---------------------------------------------------------------------------

class NotConnectedError(Exception):
    """No TV connected/selected (maps to 404)."""


class AdapterNotAvailableError(Exception):
    """Adapter package / feature not installed or unreachable (maps to 503)."""


class UnsupportedError(Exception):
    """Operation not supported for this brand/app (maps to 422)."""


class TvCommandError(Exception):
    """The TV rejected the command or is unreachable (maps to 503)."""


# ---------------------------------------------------------------------------
# Lazy adapter / app-table loading
# ---------------------------------------------------------------------------

def _load_get_adapter():
    if adapter_factory is not None:
        return adapter_factory
    for module_name in ("app.adapters", "backend.app.adapters"):
        try:
            module = importlib.import_module(module_name)
            return module.get_adapter
        except (ImportError, AttributeError):
            continue
    return None


def _load_streaming_apps():
    if streaming_apps_override is not None:
        return streaming_apps_override
    for module_name in ("app.adapters.apps", "backend.app.adapters.apps"):
        try:
            return importlib.import_module(module_name)
        except ImportError:
            continue
    return None


def _device_info(row: dict) -> DeviceInfo:
    return DeviceInfo(
        id=row.get("id", ""),
        name=row.get("name", ""),
        brand=row.get("brand", "unknown"),
        model=row.get("model", ""),
        ip=row.get("ip", ""),
        port=int(row.get("port") or 0),
        mac=row.get("mac", ""),
        pairing_token=row.get("pairing_token", ""),
        paired=bool(row.get("paired")),
    )


def _build_adapter(row: dict):
    """Validate subnet, then return the brand adapter for a device row."""
    ip = (row.get("ip") or "").strip()
    if not ip:
        raise ValueError("Cannot talk to a TV without an IP address.")
    assert_same_subnet(ip)
    factory = _load_get_adapter()
    if factory is None:
        raise AdapterNotAvailableError(
            "The brand adapter package is not installed yet "
            "(backend/app/adapters). Cannot control the TV."
        )
    try:
        return factory(_device_info(row))
    except ValueError:
        raise
    except RuntimeError as exc:
        # Unknown brand module / mock gate / not-implemented adapter.
        raise AdapterNotAvailableError(str(exc)) from exc


def _resolve_target(device_id: str | None) -> dict:
    """The device a command targets: explicit id, else the active session."""
    if device_id:
        row = db.get_device(device_id)
        if row is None:
            raise NotConnectedError(
                f"No device found with id {device_id!r}. Connect to a TV first."
            )
        return row
    row = db.get_active()
    if row is None:
        raise NotConnectedError("No TV is connected. Connect to a TV first.")
    return row


def _set_last_error(message: str | None) -> None:
    global _last_error
    _last_error = message


def get_connection_status() -> dict:
    active = db.get_active()
    if active is None:
        status: dict = {"connected": False}
        if _last_error:
            status["last_error"] = _last_error
        return status
    return {
        "connected": True,
        "device_id": active["id"],
        "name": active.get("name", ""),
        "brand": active.get("brand", ""),
        "ip": active.get("ip", ""),
    }


# ---------------------------------------------------------------------------
# Connect / pair / disconnect
# ---------------------------------------------------------------------------

async def connect_device(device: dict) -> dict:
    """Connect via the brand adapter; on success save + activate the device."""
    ip = (device.get("ip") or "").strip()
    if not ip:
        raise ValueError("Cannot connect: no IP address given.")
    brand = (device.get("brand") or "unknown").strip().lower() or "unknown"
    device_id = device.get("id") or f"tv-{ip}"
    row = {
        "id": device_id,
        "name": device.get("name") or device_id,
        "brand": brand,
        "model": device.get("model", ""),
        "ip": ip,
        "port": int(device.get("port") or 0),
        "mac": device.get("mac", ""),
        "paired": True,
        "pairing_token": device.get("pairing_token", ""),
        "last_connected": None,
    }
    saved = db.get_device(device_id)
    if saved and saved.get("pairing_token"):
        row["pairing_token"] = saved["pairing_token"]
    adapter = _build_adapter(row)
    try:
        result = await asyncio.wait_for(adapter.connect(), timeout=CONNECT_TIMEOUT)
    except asyncio.TimeoutError as exc:
        _set_last_error(f"Timed out connecting to {ip}.")
        raise TvCommandError(
            f"Timed out connecting to the TV at {ip}. Check it is on and "
            "on the same Wi-Fi network."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - adapter errors are honest 503s
        _set_last_error(str(exc))
        raise TvCommandError(f"Could not connect to the TV at {ip}: {exc}") from exc
    if result is None or not getattr(result, "success", False):
        message = (
            getattr(result, "error", None)
            or getattr(result, "message", "")
            or "The TV refused the connection."
        )
        details = getattr(result, "details", None) or {}
        if isinstance(details, dict) and details.get("pairing_required"):
            # Pairing spans two HTTP requests: save the device (unpaired)
            # so POST /devices/pair can find it, and keep the LIVE adapter
            # instance — the pairing session lives on it (e.g. Android TV's
            # Polo writer/reader). The mobile app routes to the Pairing
            # screen on pairing_required.
            row["paired"] = False
            db.upsert_device(row)
            _pairing_adapters[device_id] = adapter
            _set_last_error(None)
            return {
                "connected": False,
                "pairing_required": True,
                "device_id": device_id,
                "name": row["name"],
                "brand": brand,
                "ip": ip,
                "message": message
                or "Enter the pairing code shown on the TV.",
            }
        _set_last_error(message)
        raise TvCommandError(message)
    if getattr(adapter.device, "pairing_token", ""):
        row["pairing_token"] = adapter.device.pairing_token
    row["last_connected"] = datetime.now(timezone.utc).isoformat()
    db.upsert_device(row)
    db.set_active(device_id)
    _set_last_error(None)
    return {
        "connected": True,
        "device_id": device_id,
        "name": row["name"],
        "brand": brand,
        "ip": ip,
        "message": getattr(result, "message", "") or f"Connected to {row['name']}.",
    }


async def pair_device(device_id: str, pin: str | None = None) -> dict:
    """Complete PIN pairing where the brand requires it.

    The adapter interface (CONTRACTS.md §1) has no ``pair()`` method —
    Samsung/LG pair via the on-TV Allow/pairing prompt during ``connect()``.
    Adapters that do expose ``pair()`` are used; otherwise this returns an
    honest 422 explaining that pairing happens on the TV, never a fake ok.
    """
    row = db.get_device(device_id)
    if row is None:
        raise NotConnectedError(
            f"No device found with id {device_id!r}. Connect to a TV first."
        )
    # Revalidate same-Wi-Fi even when reusing a live pairing session.
    assert_same_subnet((row.get("ip") or "").strip())
    adapter = _pairing_adapters.get(device_id)
    if adapter is None:
        # No live session (e.g. server restarted): build a fresh adapter.
        # Its pair() will honestly report "no pairing session in
        # progress" and the user must connect again for a fresh code.
        adapter = _build_adapter(row)
    pair_fn = getattr(adapter, "pair", None)
    if not callable(pair_fn):
        raise UnsupportedError(
            "PIN pairing is not supported by the "
            f"{row.get('brand', 'unknown')} adapter — pairing happens on "
            "the TV when you connect (accept the Allow/pairing prompt on "
            "the TV screen)."
        )
    try:
        if pin is not None:
            try:
                result = await asyncio.wait_for(pair_fn(pin), timeout=COMMAND_TIMEOUT)
            except TypeError:
                result = await asyncio.wait_for(pair_fn(), timeout=COMMAND_TIMEOUT)
        else:
            result = await asyncio.wait_for(pair_fn(), timeout=COMMAND_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise TvCommandError("Timed out while pairing with the TV.") from exc
    except Exception as exc:  # noqa: BLE001
        raise TvCommandError(f"Pairing failed: {exc}") from exc
    if result is not None and not getattr(result, "success", True):
        message = (
            getattr(result, "error", None)
            or getattr(result, "message", "")
            or "Pairing failed."
        )
        raise TvCommandError(message)
    if getattr(adapter.device, "pairing_token", ""):
        db.set_paired(device_id, True, adapter.device.pairing_token)
    else:
        db.set_paired(device_id, True)
    _pairing_adapters.pop(device_id, None)
    db.set_active(device_id)
    return {
        "connected": True,
        "device_id": device_id,
        "name": row.get("name", ""),
        "brand": row.get("brand", ""),
        "ip": row.get("ip", ""),
        "message": "Pairing completed.",
    }


async def disconnect_device(device_id: str | None = None) -> dict:
    """Disconnect (best-effort adapter teardown) and clear the session."""
    if device_id:
        row = db.get_device(device_id)
        if row is None:
            raise NotConnectedError(
                f"No device found with id {device_id!r}."
            )
    else:
        row = db.get_active()
    if row is None:
        return {"disconnected": False, "message": "No TV was connected."}
    _pairing_adapters.pop(row["id"], None)
    try:
        adapter = _build_adapter(row)
    except (AdapterNotAvailableError, SameWifiError, ValueError) as exc:
        # Still clear the session: the TV is gone/unreachable either way.
        logger.warning("Disconnecting without adapter teardown: %s", exc)
        adapter = None
    if adapter is not None:
        try:
            await asyncio.wait_for(adapter.disconnect(), timeout=COMMAND_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - disconnect is best-effort
            logger.warning("Adapter disconnect failed for %s: %s", row["id"], exc)
    active = db.get_active()
    if active is None or active["id"] == row["id"]:
        db.set_active(None)
    return {"disconnected": True, "message": f"Disconnected from {row.get('name', row['id'])}."}


# ---------------------------------------------------------------------------
# Remote keys / app launch
# ---------------------------------------------------------------------------

_KEY_FEATURES = {
    "power": "power",
    "volume-up": "volume",
    "volume-down": "volume",
    "mute": "mute",
    "channel-up": "channel",
    "channel-down": "channel",
    "play": "media",
    "pause": "media",
    "stop": "media",
    "rewind": "media",
    "fast-forward": "media",
}


async def send_key(key: str, device_id: str | None = None) -> dict:
    """Send one remote key to the target TV (revalidates same-Wi-Fi)."""
    try:
        remote_key = RemoteKey(key)
    except ValueError as exc:
        raise ValueError(f"Unknown remote key: {key!r}.") from exc
    row = _resolve_target(device_id)
    adapter = _build_adapter(row)
    feature = _KEY_FEATURES.get(key)
    if feature and not adapter.supports(feature):
        raise UnsupportedError(
            f"{key} is not supported on {row.get('brand', 'unknown')}."
        )
    try:
        result = await asyncio.wait_for(
            adapter.send_key(remote_key), timeout=COMMAND_TIMEOUT
        )
    except asyncio.TimeoutError as exc:
        _set_last_error(f"Timed out sending {key} to the TV.")
        raise TvCommandError(
            f"Timed out sending {key} to the TV. Check it is on and on "
            "the same Wi-Fi network."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        _set_last_error(str(exc))
        raise TvCommandError(f"Failed to send {key} to the TV: {exc}") from exc
    if result is None or not getattr(result, "success", False):
        message = (
            getattr(result, "error", None)
            or getattr(result, "message", "")
            or f"The TV rejected the {key} command."
        )
        _set_last_error(message)
        raise TvCommandError(message)
    _set_last_error(None)
    return {
        "key": key,
        "message": getattr(result, "message", "") or f"Sent {key}.",
    }


async def launch_app(app_name: str, device_id: str | None = None) -> dict:
    """Launch a streaming app by resolving its brand app id (apps.py)."""
    row = _resolve_target(device_id)
    brand = (row.get("brand") or "unknown").strip().lower()
    apps = _load_streaming_apps()
    if apps is None:
        raise AdapterNotAvailableError(
            "Streaming app ids are not available yet "
            "(backend/app/adapters/apps.py is not installed). Cannot launch "
            "apps."
        )
    # googletv is an alias of the Android TV adapter (CONTRACTS.md §1).
    lookup_brand = "androidtv" if brand == "googletv" else brand
    get_app_id = getattr(apps, "get_app_id", None)
    if callable(get_app_id):
        app_id = get_app_id(app_name, lookup_brand)
    else:
        table = getattr(apps, "STREAMING_APPS", apps)
        app_id = table.get(app_name, {}).get(lookup_brand)
    if app_id is None:
        raise UnsupportedError(
            f"{app_name} is not supported/unknown for {brand} — no "
            "documented app id exists for this brand."
        )
    adapter = _build_adapter(row)
    if not adapter.supports("launch_app"):
        raise UnsupportedError(
            f"Launching apps is not supported on {brand}."
        )
    try:
        result = await asyncio.wait_for(
            adapter.launch_app(app_id), timeout=COMMAND_TIMEOUT
        )
    except asyncio.TimeoutError as exc:
        _set_last_error(f"Timed out launching {app_name}.")
        raise TvCommandError(
            f"Timed out launching {app_name}. Check the TV is on and on "
            "the same Wi-Fi network."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        _set_last_error(str(exc))
        raise TvCommandError(f"Failed to launch {app_name}: {exc}") from exc
    if result is None or not getattr(result, "success", False):
        message = (
            getattr(result, "error", None)
            or getattr(result, "message", "")
            or f"The TV rejected the launch of {app_name}."
        )
        _set_last_error(message)
        raise TvCommandError(message)
    _set_last_error(None)
    return {
        "app": app_name,
        "message": getattr(result, "message", "") or f"Launched {app_name}.",
    }
