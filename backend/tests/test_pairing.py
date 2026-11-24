"""Tests for the two-request PIN pairing flow (Android TV).

Regression test for the bug found in the Phase 6 review: ``connect()``
returning ``pairing_required`` used to raise without saving the device, so
``POST /devices/pair`` 404'd — and ``pair()`` built a FRESH adapter, so
the in-progress pairing session was gone ("No pairing session is in
progress"). The service must save the device (unpaired) and keep the LIVE
adapter instance across the two requests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.adapters.base import CommandResult  # noqa: E402
from app.models import database as db  # noqa: E402
from app.services import device_service as svc  # noqa: E402

TV_IP = "127.0.0.1"  # loopback passes subnet validation under MOCK_TV=true


class PairingSessionAdapter:
    """Mimics the Android TV pairing flow: connect() opens a pairing
    session and reports pairing_required; pair() only works on the SAME
    instance that ran connect() (a fresh instance has no session)."""

    brand = "androidtv"

    def __init__(self, device):
        self.device = device
        self.connected = False
        self._session_open = False
        self.pair_calls: list = []

    async def connect(self):
        self._session_open = True
        return CommandResult(
            success=False,
            message="A 6-character pairing code is now shown on the TV.",
            error="Pairing required: enter the code shown on the TV.",
            details={"pairing_required": True},
        )

    async def pair(self, code=None):
        self.pair_calls.append(code)
        if not self._session_open:
            return CommandResult(
                success=False,
                error="No pairing session is in progress. Connect to the "
                "TV first so it shows a pairing code, then enter the code.",
            )
        if code != "1A2B3C":
            return CommandResult(
                success=False, error="That code does not look right."
            )
        self.device.pairing_token = "test-token-123"
        self.connected = True
        return CommandResult(success=True, message="Pairing completed.")

    async def disconnect(self):
        self.connected = False
        self._session_open = False

    def supports(self, feature):
        return True


@pytest.fixture
def pairing_adapters(monkeypatch):
    """Route adapter creation through PairingSessionAdapter; track instances."""
    instances: list = []

    def factory(device):
        inst = PairingSessionAdapter(device)
        instances.append(inst)
        return inst

    monkeypatch.setattr(svc, "adapter_factory", factory)
    svc._pairing_adapters.clear()
    yield instances
    svc._pairing_adapters.clear()


@pytest.mark.asyncio
async def test_connect_saves_pairing_required_device(pairing_adapters):
    result = await svc.connect_device(
        {"ip": TV_IP, "brand": "androidtv", "name": "Test TV"}
    )
    assert result["connected"] is False
    assert result["pairing_required"] is True
    assert result["device_id"] == f"tv-{TV_IP}"
    row = db.get_device(f"tv-{TV_IP}")
    assert row is not None
    assert row["paired"] is False


@pytest.mark.asyncio
async def test_pair_reuses_live_session(pairing_adapters):
    await svc.connect_device(
        {"ip": TV_IP, "brand": "androidtv", "name": "Test TV"}
    )
    result = await svc.pair_device(f"tv-{TV_IP}", "1A2B3C")
    assert result["connected"] is True
    # Pair ran on the SAME adapter instance created by connect() — only
    # one instance was ever built, so the live session was reused.
    assert len(pairing_adapters) == 1
    assert pairing_adapters[0].pair_calls == ["1A2B3C"]
    row = db.get_device(f"tv-{TV_IP}")
    assert row["paired"] is True
    assert row["pairing_token"] == "test-token-123"


@pytest.mark.asyncio
async def test_pair_without_connect_is_not_found(pairing_adapters):
    with pytest.raises(svc.NotConnectedError):
        await svc.pair_device("tv-9.9.9.9", "1A2B3C")


@pytest.mark.asyncio
async def test_pair_after_session_lost_is_honest(pairing_adapters):
    await svc.connect_device(
        {"ip": TV_IP, "brand": "androidtv", "name": "Test TV"}
    )
    # Simulate a server restart: the live session is gone.
    svc._pairing_adapters.clear()
    with pytest.raises(svc.TvCommandError, match="No pairing session"):
        await svc.pair_device(f"tv-{TV_IP}", "1A2B3C")
