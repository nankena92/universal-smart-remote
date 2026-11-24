"""Remote-control routes (CONTRACTS.md §2). All require X-API-Key.

One endpoint per key, plus POST /remote/launch-app. Bodies may be {} or
{"device_id": ...}; omitted means the currently connected device. 404 if
no TV is connected/selected, never a fake success.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.models.schemas import LaunchAppRequest, RemoteRequest
from app.security.auth import verify_api_key
from app.services import device_service as svc
from app.services.device_service import (
    AdapterNotAvailableError,
    NotConnectedError,
    TvCommandError,
    UnsupportedError,
)
from app.network.validation import SameWifiError

router = APIRouter(dependencies=[Depends(verify_api_key)])

# CONTRACTS.md §2 lists these keys; menu/stop are also exposed because the
# mobile client (mobile/src/services/api.ts KEY_ENDPOINTS) and the adapter
# interface (RemoteKey, CONTRACTS.md §1) both define them.
REMOTE_KEYS = [
    "up", "down", "left", "right", "ok", "back", "home", "menu",
    "power", "volume-up", "volume-down", "mute", "channel-up",
    "channel-down", "play", "pause", "stop", "rewind", "fast-forward",
]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SameWifiError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, NotConnectedError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AdapterNotAvailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, UnsupportedError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, TvCommandError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Internal error: {exc}")


def _make_key_handler(key: str):
    async def _handler(payload: RemoteRequest | None = Body(default=None)):
        device_id = payload.device_id if payload else None
        try:
            result = await svc.send_key(key, device_id)
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc
        return {"success": True, **result}

    return _handler


for _key in REMOTE_KEYS:
    router.add_api_route(
        f"/remote/{_key}",
        _make_key_handler(_key),
        methods=["POST"],
    )


@router.post("/remote/launch-app")
async def launch_app(payload: LaunchAppRequest):
    """Launch a streaming app: {app in netflix|prime|youtube|disney}."""
    try:
        result = await svc.launch_app(payload.app, payload.device_id)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {"success": True, **result}
