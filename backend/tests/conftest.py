"""Shared fixtures for the backend-core tests.

Env vars are set BEFORE any app import (auth reads SMART_REMOTE_API_KEY at
request time, the DB path per call). The FastAPI app is imported lazily
inside fixtures so this conftest does not break the adapters-only test
suite (which does not need FastAPI): if the app cannot be imported, the
DB-cleanup fixture degrades to a no-op instead of failing collection.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SMART_REMOTE_API_KEY", "test-key-123")
os.environ.setdefault(
    "SMART_REMOTE_DB", str(Path(tempfile.mkdtemp()) / "test.db")
)
os.environ.setdefault("MOCK_TV", "true")

TEST_API_KEY = "test-key-123"


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient (lifespan runs once for the session)."""
    from fastapi.testclient import TestClient

    from app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"X-API-Key": TEST_API_KEY}


@pytest.fixture(autouse=True)
def _clean_db():
    """Wipe devices/session + last_error before and after every test."""
    try:
        from app.models import database as db
        from app.services import device_service as svc
    except Exception:
        yield
        return
    db.init_db()
    db.clear_all()
    svc._set_last_error(None)
    yield
    db.clear_all()
    svc._set_last_error(None)


# ---------------------------------------------------------------------------
# Stub adapters (injected via device_service.adapter_factory)
# ---------------------------------------------------------------------------

from app.adapters.base import CommandResult  # noqa: E402


class StubAdapter:
    """Happy-path stub: every call succeeds."""

    brand = "mock"

    def __init__(self, device):
        self.device = device
        self.connected = False
        self.keys: list = []
        self.launched: list = []

    async def connect(self):
        self.connected = True
        return CommandResult(success=True, message="Connected to Mock TV")

    async def disconnect(self):
        self.connected = False

    async def send_key(self, key):
        self.keys.append(key)
        return CommandResult(success=True, message=f"Sent {key.value}")

    async def launch_app(self, app_id):
        self.launched.append(app_id)
        return CommandResult(success=True, message=f"Launched {app_id}")

    def supports(self, feature):
        return True


class PairStubAdapter(StubAdapter):
    """Stub that also supports PIN pairing via a pair() method."""

    def __init__(self, device):
        super().__init__(device)
        self.pair_calls: list = []

    async def pair(self, pin=None):
        self.pair_calls.append(pin)
        return CommandResult(success=True, message="Paired")


class FailingStubAdapter(StubAdapter):
    """Stub whose TV refuses commands (tests the honest-error path)."""

    async def send_key(self, key):
        return CommandResult(
            success=False, error="The TV refused the command."
        )

    async def launch_app(self, app_id):
        return CommandResult(
            success=False, error="The TV refused the launch."
        )


@pytest.fixture
def stub_adapters(monkeypatch):
    """Route all adapter creation through StubAdapter; return instances."""
    from app.services import device_service as svc

    instances: list = []

    def factory(device):
        inst = StubAdapter(device)
        instances.append(inst)
        return inst

    monkeypatch.setattr(svc, "adapter_factory", factory)
    return instances


@pytest.fixture
def pair_stub_adapters(monkeypatch):
    from app.services import device_service as svc

    instances: list = []

    def factory(device):
        inst = PairStubAdapter(device)
        instances.append(inst)
        return inst

    monkeypatch.setattr(svc, "adapter_factory", factory)
    return instances


@pytest.fixture
def failing_stub_adapters(monkeypatch):
    from app.services import device_service as svc

    instances: list = []

    def factory(device):
        inst = FailingStubAdapter(device)
        instances.append(inst)
        return inst

    monkeypatch.setattr(svc, "adapter_factory", factory)
    return instances


@pytest.fixture
def real_adapters(monkeypatch):
    """Disable stub injection so the real adapter package is used."""
    from app.services import device_service as svc

    monkeypatch.setattr(svc, "adapter_factory", None)
    return svc
