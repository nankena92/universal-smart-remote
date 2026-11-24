"""Mock TV adapter — TESTING ONLY (CONTRACTS.md §1).

Implements the :class:`~app.adapters.base.TvAdapter` interface with canned
success responses and no network access. It exists so the backend, the
mobile app and the test suite can exercise the command flow without a TV.

It must be unreachable in production: ``app.adapters.get_adapter`` only
returns it when the backend is started with ``MOCK_TV=true``. Never point
this adapter at a real device and never report its canned results as if a
real TV had acted.
"""

from __future__ import annotations

from typing import Optional

from .base import CommandResult, DeviceInfo, RemoteKey, TvAdapter


class MockAdapter(TvAdapter):
    """Testing-only adapter that pretends every command succeeds."""

    brand = "mock"

    def __init__(self, device: DeviceInfo):
        super().__init__(device)
        self.last_key: Optional[str] = None
        self.last_app: Optional[str] = None

    async def connect(self) -> CommandResult:
        if not self.device.ip:
            return CommandResult(
                False, error="Mock TV has no IP address configured."
            )
        self.connected = True
        self.device.paired = True
        return CommandResult(True, "Connected to mock TV (testing only).")

    async def disconnect(self) -> None:
        self.connected = False

    async def send_key(self, key: RemoteKey) -> CommandResult:
        if not self.connected:
            result = await self.connect()
            if not result.success:
                return result
        self.last_key = key.value
        return CommandResult(
            True,
            f"Mock TV accepted key {key.value} (testing only, no TV).",
            details={"key": key.value},
        )

    async def launch_app(self, app_id: str) -> CommandResult:
        if not app_id:
            return CommandResult(
                False, error="No mock app id given; refusing to guess one."
            )
        if not self.connected:
            result = await self.connect()
            if not result.success:
                return result
        self.last_app = app_id
        return CommandResult(
            True,
            f"Mock TV accepted launch of app {app_id} "
            "(testing only, no TV).",
            details={"app_id": app_id},
        )

    def supports(self, feature: str) -> bool:
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
                "mock": True,
                "last_key": self.last_key,
                "last_app": self.last_app,
            }
        )
        return status
