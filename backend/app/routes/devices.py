"""Device routes (CONTRACTS.md §2). All require X-API-Key."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.models import database as db
from app.models.schemas import ConnectRequest, DisconnectRequest, PairRequest
from app.network.validation import SameWifiError
from app.security.auth import verify_api_key
from app.services import device_service as svc
from app.services import discovery

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SameWifiError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, svc.NotConnectedError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, svc.AdapterNotAvailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, svc.UnsupportedError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, svc.TvCommandError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Internal error: {exc}")


@router.get("/devices/discover")
async def discover_devices():
    """Run SSDP/mDNS discovery on the LAN; return discovered TVs."""
    devices = await asyncio.to_thread(discovery.discover_devices, 4.0)
    return {"success": True, "data": devices}


@router.get("/devices")
async def list_devices():
    """Paired/saved devices from SQLite."""
    return {"success": True, "data": db.list_devices()}


@router.post("/devices/connect")
async def connect_device(payload: ConnectRequest):
    """Connect via the brand adapter: {device_id} or {ip, brand, name?}."""
    if payload.device_id:
        row = db.get_device(payload.device_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No saved device with id {payload.device_id!r}.",
            )
        device = row
    elif payload.ip:
        device = {
            "id": None,
            "name": payload.name,
            "brand": payload.brand or "unknown",
            "model": payload.model or "",
            "ip": payload.ip,
            "port": payload.port or 0,
            "mac": payload.mac or "",
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide device_id or ip (with brand) to connect.",
        )
    try:
        status = await svc.connect_device(device)
    except Exception as exc:  # noqa: BLE001 - mapped to honest HTTP errors
        raise _http_error(exc) from exc
    return {"success": True, **status}


@router.post("/devices/pair")
async def pair_device(payload: PairRequest):
    """Complete PIN pairing where the brand requires it."""
    try:
        status = await svc.pair_device(payload.device_id, payload.pin)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {"success": True, **status}


@router.delete("/devices/disconnect")
async def disconnect_device(
    payload: DisconnectRequest | None = Body(default=None),
    device_id: str | None = Query(default=None),
):
    """Disconnect (and remove from active session, keep saved)."""
    target = (payload.device_id if payload else None) or device_id
    try:
        result = await svc.disconnect_device(target)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {"success": True, **result}


@router.get("/devices/connection-status")
async def connection_status():
    """{connected, device_id?, name?, brand?, ip?, last_error?}."""
    return {"success": True, **svc.get_connection_status()}
