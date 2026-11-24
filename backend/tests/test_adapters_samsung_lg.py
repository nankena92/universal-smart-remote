"""Tests for the Samsung (Tizen) and LG (webOS) adapters (Phase 7).

The real TV is replaced by fake WebSocket endpoints: ``_ws_connect`` is
monkeypatched on each adapter module, so no network access is needed.
Covers connect / send_key / launch_app / supports / get_status and the
honest error paths (refused pairing, unreachable TV, timeouts, bad input).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.adapters import BRANDS, get_adapter  # noqa: E402
from app.adapters import apps as apps_mod  # noqa: E402
from app.adapters import lg as lg_mod  # noqa: E402
from app.adapters import samsung as samsung_mod  # noqa: E402
from app.adapters.base import (  # noqa: E402
    CommandResult,
    DeviceInfo,
    RemoteKey,
    TvAdapter,
)
from app.adapters.lg import LgAdapter  # noqa: E402
from app.adapters.samsung import SamsungAdapter  # noqa: E402


# --------------------------------------------------------------------------
# Fake WebSocket plumbing
# --------------------------------------------------------------------------

class FakeWebSocket:
    """Minimal stand-in for a websockets client connection."""

    def __init__(self):
        self.sent: list[str] = []
        self.closed = False
        self.close_calls = 0
        self._recv_queue: asyncio.Queue = asyncio.Queue()
        self.on_send = None  # optional callable(msg_dict) -> dict to enqueue

    def queue_message(self, msg: dict) -> None:
        self._recv_queue.put_nowait(json.dumps(msg))

    async def send(self, message: str) -> None:
        if self.closed:
            raise ConnectionError("fake socket is closed")
        self.sent.append(message)
        if self.on_send is not None:
            try:
                parsed = json.loads(message)
            except ValueError:
                return
            reply = self.on_send(parsed)
            if reply is not None:
                self.queue_message(reply)

    async def recv(self) -> str:
        return await self._recv_queue.get()

    async def close(self) -> None:
        self.closed = True
        self.close_calls += 1

    def sent_json(self) -> list[dict]:
        return [json.loads(m) for m in self.sent]


def lg_auto_responder(socket_path: str):
    """Auto-reply to SSAP requests; getPointerInputSocket yields a path."""
    def _respond(msg: dict):
        if msg.get("type") != "request":
            return None
        payload: dict = {}
        if msg.get("uri") == (
            "ssap://com.webos.service.networkinput/getPointerInputSocket"
        ):
            payload = {"socketPath": socket_path}
        return {"type": "response", "id": msg.get("id"), "payload": payload}
    return _respond


class FakeConnector:
    """Fake ``_ws_connect`` recording URLs and routing by URL."""

    def __init__(self, fail_urls=(), samsung_token="SAMSUNG-TOKEN-1",
                 lg_client_key="LG-CLIENT-KEY-1"):
        self.urls: list[str] = []
        self.fail_urls = tuple(fail_urls)
        self.samsung = FakeWebSocket()
        self.lg_main = FakeWebSocket()
        self.lg_input = FakeWebSocket()
        self.samsung_token = samsung_token
        self.lg_client_key = lg_client_key

    def _fails(self, url: str) -> bool:
        return any(f in url for f in self.fail_urls)

    async def __call__(self, url, **kwargs):
        self.urls.append(url)
        if self._fails(url):
            raise ConnectionError(f"fake connection refused: {url}")
        if "8001" in url or "8002" in url:
            return self.samsung
        if "netinput" in url or "pointer.sock" in url:
            return self.lg_input
        return self.lg_main


def samsung_device(**overrides):
    data = dict(id="tv1", name="Living Room TV", brand="samsung",
                ip="192.168.1.10")
    data.update(overrides)
    return DeviceInfo(**data)


def lg_device(**overrides):
    data = dict(id="tv2", name="Bedroom TV", brand="lg", ip="192.168.1.11")
    data.update(overrides)
    return DeviceInfo(**data)


# --------------------------------------------------------------------------
# base.py / registry / apps.py
# --------------------------------------------------------------------------

def test_remote_key_values():
    assert RemoteKey.UP.value == "up"
    assert RemoteKey.FAST_FORWARD.value == "fast-forward"
    assert len(RemoteKey) == 19


def test_command_result_defaults():
    r = CommandResult(success=True)
    assert r.message == "" and r.error is None and r.details == {}


def test_brands_registry():
    assert BRANDS["samsung"] == "Samsung (Tizen)"
    assert BRANDS["lg"] == "LG (webOS)"
    assert BRANDS["googletv"] == "Google TV"
    assert set(BRANDS) == {
        "samsung", "lg", "sony", "androidtv", "googletv", "tcl",
        "roku", "firetv", "mock",
    }


def test_get_adapter_samsung_and_lg():
    assert isinstance(get_adapter(samsung_device()), SamsungAdapter)
    assert isinstance(get_adapter(lg_device()), LgAdapter)


def test_get_adapter_unknown_brand():
    with pytest.raises(ValueError, match="Unknown TV brand"):
        get_adapter(DeviceInfo(id="x", name="X", brand="nope", ip="1.2.3.4"))


def test_get_adapter_missing_brand_is_honest(monkeypatch):
    # Unknown brands still fail honestly.
    with pytest.raises(ValueError, match="Unknown TV brand"):
        get_adapter(
            DeviceInfo(id="x", name="X", brand="not-a-brand", ip="1.2.3.4")
        )
    # Brands implemented in Phases 8-9 now resolve to real adapters.
    from app.adapters.android_tv import AndroidTvAdapter
    from app.adapters.fire_tv import FireTvAdapter
    from app.adapters.roku import RokuAdapter
    from app.adapters.sony import SonyAdapter

    assert isinstance(
        get_adapter(DeviceInfo(id="x", name="X", brand="sony", ip="1.2.3.4")),
        SonyAdapter,
    )
    assert isinstance(
        get_adapter(DeviceInfo(id="x", name="X", brand="roku", ip="1.2.3.4")),
        RokuAdapter,
    )
    assert isinstance(
        get_adapter(
            DeviceInfo(id="x", name="X", brand="googletv", ip="1.2.3.4")
        ),
        AndroidTvAdapter,
    )
    assert isinstance(
        get_adapter(
            DeviceInfo(id="x", name="X", brand="androidtv", ip="1.2.3.4")
        ),
        AndroidTvAdapter,
    )
    assert isinstance(
        get_adapter(
            DeviceInfo(id="x", name="X", brand="firetv", ip="1.2.3.4")
        ),
        FireTvAdapter,
    )


def test_get_adapter_mock_gated(monkeypatch):
    monkeypatch.delenv("MOCK_TV", raising=False)
    with pytest.raises(RuntimeError, match="MOCK_TV=true"):
        get_adapter(DeviceInfo(id="x", name="X", brand="mock", ip="1.2.3.4"))
    # With the gate open the mock adapter now exists and resolves.
    from app.adapters.mock import MockAdapter

    monkeypatch.setenv("MOCK_TV", "true")
    assert isinstance(
        get_adapter(DeviceInfo(id="x", name="X", brand="mock", ip="1.2.3.4")),
        MockAdapter,
    )


def test_streaming_apps_contract_values():
    assert apps_mod.STREAMING_APPS["netflix"]["samsung"] == "3201907018807"
    assert apps_mod.STREAMING_APPS["netflix"]["roku"] == "12"
    assert apps_mod.STREAMING_APPS["prime"]["samsung"] == "3201910019365"
    assert apps_mod.STREAMING_APPS["youtube"]["samsung"] == "111299001912"
    assert apps_mod.STREAMING_APPS["disney"]["roku"] == "291097"
    assert apps_mod.STREAMING_APPS["netflix"]["lg"] == "netflix"
    assert apps_mod.STREAMING_APPS["prime"]["lg"] == "amazon"
    assert apps_mod.STREAMING_APPS["netflix"]["androidtv"] == "com.netflix.ninja"
    assert apps_mod.STREAMING_APPS["disney"]["samsung"] is None
    assert apps_mod.STREAMING_APPS["disney"]["lg"] is None
    assert apps_mod.STREAMING_APPS["netflix"]["sony"] is None


def test_get_app_id_helper():
    assert apps_mod.get_app_id("netflix", "samsung") == "3201907018807"
    assert apps_mod.get_app_id("disney", "samsung") is None
    assert apps_mod.get_app_id("netflix", "tcl") is None
    assert apps_mod.get_app_id("nosuchapp", "samsung") is None
    assert apps_mod.get_app_id("netflix", "nosuchbrand") is None


def test_base_supports_and_status():
    adapter = SamsungAdapter(samsung_device())
    assert isinstance(adapter, TvAdapter)
    assert adapter.supports("power") is True
    assert adapter.supports("launch_app") is True
    assert adapter.supports("teleport") is False


# --------------------------------------------------------------------------
# Samsung
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_samsung_connect_success_stores_token(monkeypatch):
    fake = FakeConnector()
    fake.samsung.queue_message(
        {"event": "ms.channel.connect",
         "data": {"token": "SAMSUNG-TOKEN-1"}})
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    device = samsung_device()
    adapter = SamsungAdapter(device)
    result = await adapter.connect()
    assert result.success, result.error
    assert adapter.connected
    assert device.pairing_token == "SAMSUNG-TOKEN-1"
    assert device.paired
    assert fake.urls[0].startswith("wss://192.168.1.10:8002/")
    assert "samsung.remote.control" in fake.urls[0]
    name_b64 = base64.b64encode(b"Living Room TV").decode("ascii")
    assert f"name={name_b64}" in fake.urls[0]
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_samsung_connect_reuses_token(monkeypatch):
    fake = FakeConnector()
    fake.samsung.queue_message({"event": "ms.channel.connect", "data": {}})
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    adapter = SamsungAdapter(samsung_device(pairing_token="OLD-TOKEN"))
    result = await adapter.connect()
    assert result.success, result.error
    assert "token=OLD-TOKEN" in fake.urls[0]
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_samsung_connect_unauthorized(monkeypatch):
    fake = FakeConnector()
    fake.samsung.queue_message({"event": "ms.channel.unauthorized"})
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    adapter = SamsungAdapter(samsung_device())
    result = await adapter.connect()
    assert not result.success
    assert "refused" in result.error
    assert not adapter.connected


@pytest.mark.asyncio
async def test_samsung_connect_unreachable(monkeypatch):
    fake = FakeConnector(fail_urls=("8002", "8001"))
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    adapter = SamsungAdapter(samsung_device())
    result = await adapter.connect()
    assert not result.success
    assert "192.168.1.10" in result.error
    assert not adapter.connected


@pytest.mark.asyncio
async def test_samsung_connect_timeout(monkeypatch):
    fake = FakeConnector()  # never sends ms.channel.connect
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    monkeypatch.setattr(samsung_mod, "CONNECT_TIMEOUT", 0.2)
    adapter = SamsungAdapter(samsung_device())
    result = await adapter.connect()
    assert not result.success
    assert "Timed out" in result.error
    assert not adapter.connected


@pytest.mark.asyncio
async def test_samsung_send_key(monkeypatch):
    fake = FakeConnector()
    fake.samsung.queue_message(
        {"event": "ms.channel.connect", "data": {"token": "T"}})
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    adapter = SamsungAdapter(samsung_device())
    result = await adapter.send_key(RemoteKey.UP)
    assert result.success, result.error
    sent = fake.samsung.sent_json()
    assert sent[-1]["method"] == "ms.remote.control"
    assert sent[-1]["params"]["DataOfCmd"] == "KEY_UP"
    assert sent[-1]["params"]["TypeOfRemote"] == "SendRemoteKey"
    assert sent[-1]["params"]["Cmd"] == "Click"
    result = await adapter.send_key(RemoteKey.VOLUME_DOWN)
    assert fake.samsung.sent_json()[-1]["params"]["DataOfCmd"] == "KEY_VOLDOWN"
    result = await adapter.send_key(RemoteKey.FAST_FORWARD)
    assert fake.samsung.sent_json()[-1]["params"]["DataOfCmd"] == "KEY_FF"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_samsung_send_key_auto_connects(monkeypatch):
    fake = FakeConnector()
    fake.samsung.queue_message({"event": "ms.channel.connect", "data": {}})
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    adapter = SamsungAdapter(samsung_device())
    assert not adapter.connected
    result = await adapter.send_key(RemoteKey.HOME)
    assert result.success, result.error
    assert adapter.connected


@pytest.mark.asyncio
async def test_samsung_send_key_failure_is_honest(monkeypatch):
    fake = FakeConnector()
    fake.samsung.queue_message({"event": "ms.channel.connect", "data": {}})
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    adapter = SamsungAdapter(samsung_device())
    assert (await adapter.connect()).success

    async def _boom(message):
        raise RuntimeError("socket blew up")

    monkeypatch.setattr(fake.samsung, "send", _boom)
    result = await adapter.send_key(RemoteKey.OK)
    assert not result.success
    assert "Failed to send key" in result.error
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_samsung_launch_app(monkeypatch):
    fake = FakeConnector()
    fake.samsung.queue_message({"event": "ms.channel.connect", "data": {}})
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    adapter = SamsungAdapter(samsung_device())
    result = await adapter.launch_app("3201907018807")
    assert result.success, result.error
    sent = fake.samsung.sent_json()[-1]
    assert sent["method"] == "ms.channel.emit"
    assert sent["params"]["event"] == "ed.apps.launch"
    assert sent["params"]["data"]["appId"] == "3201907018807"
    assert sent["params"]["data"]["action_type"] == "NATIVE_LAUNCH"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_samsung_launch_app_empty_id(monkeypatch):
    adapter = SamsungAdapter(samsung_device())
    result = await adapter.launch_app("")
    assert not result.success
    assert "No Samsung app id" in result.error


@pytest.mark.asyncio
async def test_samsung_disconnect_and_status(monkeypatch):
    fake = FakeConnector()
    fake.samsung.queue_message({"event": "ms.channel.connect", "data": {}})
    monkeypatch.setattr(samsung_mod, "_ws_connect", fake)
    adapter = SamsungAdapter(samsung_device())
    assert (await adapter.connect()).success
    status = await adapter.get_status()
    assert status["connected"] is True
    assert status["brand"] == "samsung"
    assert status["power_on_from_standby"] is False
    await adapter.disconnect()
    assert not adapter.connected
    assert fake.samsung.close_calls >= 1
    status = await adapter.get_status()
    assert status["connected"] is False


# --------------------------------------------------------------------------
# LG
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lg_connect_success_stores_client_key(monkeypatch):
    fake = FakeConnector()
    fake.lg_main.queue_message(
        {"type": "registered",
         "payload": {"client-key": "LG-CLIENT-KEY-1"}})
    monkeypatch.setattr(lg_mod, "_ws_connect", fake)
    device = lg_device()
    adapter = LgAdapter(device)
    result = await adapter.connect()
    assert result.success, result.error
    assert adapter.connected
    assert device.pairing_token == "LG-CLIENT-KEY-1"
    assert device.paired
    assert fake.urls[0] == "wss://192.168.1.11:3001"
    register = json.loads(fake.lg_main.sent[0])
    assert register["type"] == "register"
    assert register["payload"]["pairingType"] == "PROMPT"
    assert register["payload"]["forcePairing"] is False
    assert "client-key" not in register["payload"]
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lg_connect_reuses_client_key(monkeypatch):
    fake = FakeConnector()
    fake.lg_main.queue_message({"type": "registered", "payload": {}})
    monkeypatch.setattr(lg_mod, "_ws_connect", fake)
    adapter = LgAdapter(lg_device(pairing_token="OLD-KEY"))
    result = await adapter.connect()
    assert result.success, result.error
    register = json.loads(fake.lg_main.sent[0])
    assert register["payload"]["client-key"] == "OLD-KEY"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lg_connect_falls_back_to_plain_ws(monkeypatch):
    fake = FakeConnector(fail_urls=("3001",))
    fake.lg_main.queue_message({"type": "registered", "payload": {}})
    monkeypatch.setattr(lg_mod, "_ws_connect", fake)
    adapter = LgAdapter(lg_device())
    result = await adapter.connect()
    assert result.success, result.error
    assert fake.urls[0] == "wss://192.168.1.11:3001"
    assert fake.urls[1] == "ws://192.168.1.11:3000"
    status = await adapter.get_status()
    assert status["secure_channel"] is False
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lg_connect_register_refused(monkeypatch):
    fake = FakeConnector()
    fake.lg_main.queue_message(
        {"type": "error", "id": "register_0", "error": "denied"})
    monkeypatch.setattr(lg_mod, "_ws_connect", fake)
    adapter = LgAdapter(lg_device())
    result = await adapter.connect()
    assert not result.success
    assert "refused registration" in result.error
    assert not adapter.connected


@pytest.mark.asyncio
async def test_lg_connect_unreachable(monkeypatch):
    fake = FakeConnector(fail_urls=("3001", "3000"))
    monkeypatch.setattr(lg_mod, "_ws_connect", fake)
    adapter = LgAdapter(lg_device())
    result = await adapter.connect()
    assert not result.success
    assert "192.168.1.11" in result.error
    assert not adapter.connected


@pytest.mark.asyncio
async def test_lg_connect_timeout(monkeypatch):
    fake = FakeConnector()  # never sends "registered"
    monkeypatch.setattr(lg_mod, "_ws_connect", fake)
    monkeypatch.setattr(lg_mod, "REGISTER_TIMEOUT", 0.2)
    adapter = LgAdapter(lg_device())
    result = await adapter.connect()
    assert not result.success
    assert "Timed out" in result.error
    assert not adapter.connected


async def _connected_lg(monkeypatch, fake):
    fake.lg_main.queue_message({"type": "registered", "payload": {}})
    fake.lg_main.on_send = lg_auto_responder(
        "wss://192.168.1.11:3001/resources/netinput.pointer.sock")
    monkeypatch.setattr(lg_mod, "_ws_connect", fake)
    adapter = LgAdapter(lg_device())
    result = await adapter.connect()
    assert result.success, result.error
    return adapter


@pytest.mark.asyncio
async def test_lg_send_button_key(monkeypatch):
    fake = FakeConnector()
    adapter = await _connected_lg(monkeypatch, fake)
    result = await adapter.send_key(RemoteKey.UP)
    assert result.success, result.error
    assert result.details["button"] == "UP"
    assert fake.lg_input.sent == ["type:button\nname:UP\n\n"]
    result = await adapter.send_key(RemoteKey.OK)
    assert fake.lg_input.sent[-1] == "type:button\nname:ENTER\n\n"
    result = await adapter.send_key(RemoteKey.MENU)
    assert fake.lg_input.sent[-1] == "type:button\nname:MENU\n\n"
    # Input socket is cached: only one socket open, no extra SSAP request.
    assert len(fake.urls) == 2  # main + input socket
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lg_send_ssap_keys(monkeypatch):
    fake = FakeConnector()
    adapter = await _connected_lg(monkeypatch, fake)
    cases = [
        (RemoteKey.VOLUME_UP, "ssap://audio/volumeUp"),
        (RemoteKey.VOLUME_DOWN, "ssap://audio/volumeDown"),
        (RemoteKey.MUTE, "ssap://audio/setMute"),
        (RemoteKey.POWER, "ssap://system/turnOff"),
        (RemoteKey.CHANNEL_UP, "ssap://tv/channelUp"),
        (RemoteKey.CHANNEL_DOWN, "ssap://tv/channelDown"),
        (RemoteKey.PLAY, "ssap://media.controls/play"),
        (RemoteKey.PAUSE, "ssap://media.controls/pause"),
        (RemoteKey.STOP, "ssap://media.controls/stop"),
        (RemoteKey.REWIND, "ssap://media.controls/rewind"),
        (RemoteKey.FAST_FORWARD, "ssap://media.controls/fastForward"),
    ]
    for key, uri in cases:
        result = await adapter.send_key(key)
        assert result.success, (key, result.error)
        assert result.details["uri"] == uri
    sent = fake.lg_main.sent_json()
    mute = [m for m in sent if m.get("uri") == "ssap://audio/setMute"][0]
    assert mute["payload"] == {"mute": True}
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lg_send_key_no_response_is_honest(monkeypatch):
    fake = FakeConnector()  # no auto-responder: SSAP request never answered
    fake.lg_main.queue_message({"type": "registered", "payload": {}})
    monkeypatch.setattr(lg_mod, "_ws_connect", fake)
    monkeypatch.setattr(lg_mod, "REQUEST_TIMEOUT", 0.2)
    adapter = LgAdapter(lg_device())
    assert (await adapter.connect()).success
    result = await adapter.send_key(RemoteKey.VOLUME_UP)
    assert not result.success
    assert "did not respond" in result.error
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lg_launch_app(monkeypatch):
    fake = FakeConnector()
    adapter = await _connected_lg(monkeypatch, fake)
    result = await adapter.launch_app("netflix")
    assert result.success, result.error
    launch = [m for m in fake.lg_main.sent_json()
              if m.get("uri") == "ssap://system.launcher/launch"]
    assert len(launch) == 1
    assert launch[0]["payload"] == {"id": "netflix"}
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_lg_launch_app_empty_id(monkeypatch):
    adapter = LgAdapter(lg_device())
    result = await adapter.launch_app("")
    assert not result.success
    assert "No LG app id" in result.error


@pytest.mark.asyncio
async def test_lg_supports_status_disconnect(monkeypatch):
    fake = FakeConnector()
    adapter = await _connected_lg(monkeypatch, fake)
    assert adapter.supports("launch_app") is True
    assert adapter.supports("pairing") is True
    assert adapter.supports("teleport") is False
    status = await adapter.get_status()
    assert status["brand"] == "lg"
    assert status["connected"] is True
    assert status["power_on_from_standby"] is False
    assert status["has_client_key"] is False
    # Open the input socket first (a button key), so disconnect has one.
    assert (await adapter.send_key(RemoteKey.UP)).success
    assert fake.lg_input.sent == ["type:button\nname:UP\n\n"]
    await adapter.disconnect()
    assert not adapter.connected
    assert fake.lg_main.close_calls >= 1
    assert fake.lg_input.close_calls >= 1
