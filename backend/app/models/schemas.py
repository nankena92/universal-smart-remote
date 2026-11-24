"""Pydantic request models for the API (CONTRACTS.md §2)."""

from __future__ import annotations

from pydantic import BaseModel, field_validator

STREAMING_APPS = ("netflix", "prime", "youtube", "disney")


class ConnectRequest(BaseModel):
    """POST /devices/connect: {device_id} or {ip, brand, name?}."""

    device_id: str | None = None
    ip: str | None = None
    brand: str | None = None
    name: str | None = None
    model: str | None = None
    port: int | None = None
    mac: str | None = None


class PairRequest(BaseModel):
    """POST /devices/pair: {device_id, pin?}."""

    device_id: str
    pin: str | None = None


class DisconnectRequest(BaseModel):
    """DELETE /devices/disconnect: {device_id} (optional — else active)."""

    device_id: str | None = None


class RemoteRequest(BaseModel):
    """Remote-key bodies: {} or {"device_id": ...} (else active device)."""

    device_id: str | None = None


class LaunchAppRequest(BaseModel):
    """POST /remote/launch-app: {app, device_id?}."""

    app: str
    device_id: str | None = None

    @field_validator("app")
    @classmethod
    def _validate_app(cls, value: str) -> str:
        if value not in STREAMING_APPS:
            raise ValueError(
                f"Unknown app: {value!r}. "
                f"Supported apps: {', '.join(STREAMING_APPS)}."
            )
        return value
