"""Network-status route (CONTRACTS.md §2). Requires X-API-Key."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.network import validation
from app.security.auth import verify_api_key

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("/network/status")
async def network_status():
    """{wifi_connected, ssid?, phone_ip?, backend_ip, subnet, validation, message}."""
    return {"success": True, **validation.network_status()}
