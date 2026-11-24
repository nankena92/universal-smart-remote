"""Tests for the Android TV, Roku, Sony, TCL, Fire TV and Mock adapters
(Phases 8-9).

Real TVs are replaced by fakes: ``urllib.request.urlopen`` is stubbed for
Roku/Sony HTTP, ``subprocess.run`` is stubbed for ADB, and the Android TV
TLS/protobuf sessions run over scripted in-memory streams. No network
access is needed. Covers connect / send_key / launch_app / supports /
get_status and the honest-error paths (TCL unknown OS, Sony launch_app,
Fire TV without ADB, Android TV pairing).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.adapters import BRANDS, get_adapter  # noqa: E402
from app.adapters import android_tv as android_tv_mod  # noqa: E402
from app.adapters import fire_tv as fire_tv_mod  # noqa: E402
from app.adapters import mock as mock_mod  # noqa: E402
from app.adapters import roku as roku_mod  # noqa: E402
from app.adapters import sony as sony_mod  # noqa: E402
from app.adapters import tcl as tcl_mod  # noqa: E402
from app.adapters.android_tv import AndroidTvAdapter  # noqa: E402
from app.adapters.base import (  # noqa: E402
    CommandResult,
    DeviceInfo,
    RemoteKey,
)
from app.adapters.fire_tv import FireTvAdapter  # noqa: E402
from app.adapters.mock import MockAdapter  # noqa: E402
from app.adapters.roku import RokuAdapter  # noqa: E402
from app.adapters.sony import SonyAdapter  # noqa: E402
from app.adapters.tcl import TclAdapter, detect_os  # noqa: E402


# --------------------------------------------------------------------------
# Fake HTTP plumbing (Roku ECP, Sony IRCC-IP / JSON-RPC)
# --------------------------------------------------------------------------

class FakeHTTPResponse:
    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHTTP:
    """Route fake ``urlopen`` calls; records (method, url, body, headers)."""

    def __init__(self):
        self.requests: list[dict] = []
        self.routes: list[tuple] = []  # (substring, method, response)

    def add(self, substring, method="GET", status=200, body=b""):
        self.routes.append((substring, method, (status, body)))

    def add_error(self, substring, method, exc):
        self.routes.append((substring, method, exc))

    def __call__(self, req, timeout=None):
        url = req.full_url
        method = req.get_method()
        self.requests.append(
            {
                "method": method,
                "url": url,
                "body": req.data or b"",
                "headers": {k.lower(): v for k, v in req.header_items()},
            }
        )
        for substring, route_method, response in self.routes:
            if substring in url and method == route_method:
                if isinstance(response, Exception):
                    raise response
                return FakeHTTPResponse(*response)
        raise AssertionError(f"Unexpected HTTP request: {method} {url}")

    def urls(self, substring=""):
        return [r["url"] for r in self.requests if substring in r["url"]]


ROKU_APPS_XML = (
    b'<?xml version="1.0" encoding="UTF-8" ?>'
    b"<apps>"
    b'<app id="12" type="appl">Netflix</app>'
    b'<app id="13" type="appl">Prime Video</app>'
    b'<app id="837" type="appl">YouTube</app>'
    b"</apps>"
)


def roku_device(**overrides):
    data = dict(id="roku1", name="Roku TV", brand="roku", ip="192.168.1.21")
    data.update(overrides)
    return DeviceInfo(**data)


def sony_device(**overrides):
    data = dict(id="sony1", name="Bravia", brand="sony", ip="192.168.1.22",
                pairing_token="PSK123")
    data.update(overrides)
    return DeviceInfo(**data)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

def test_get_adapter_other_brands():
    assert isinstance(get_adapter(sony_device()), SonyAdapter)
    assert isinstance(get_adapter(roku_device()), RokuAdapter)
    assert isinstance(
        get_adapter(DeviceInfo(id="t", name="T", brand="tcl",
                               ip="192.168.1.23")),
        TclAdapter,
    )
    assert BRANDS["mock"] == "Mock TV (testing only)"
    assert BRANDS["tcl"] == "TCL"
    # NOTE (registry mismatch, for the coordinator): app/adapters/__init__.py
    # maps "androidtv" -> module "androidtv" and "firetv" -> module
    # "firetv", but the adapter files are android_tv.py / fire_tv.py, so
    # get_adapter() raises "not implemented yet" for androidtv, googletv
    # and firetv until the registry is fixed. The classes themselves are
    # verified directly here instead.
    assert AndroidTvAdapter.brand == "androidtv"
    assert FireTvAdapter.brand == "firetv"
    assert isinstance(
        AndroidTvAdapter(DeviceInfo(id="a", name="A", brand="androidtv",
                                    ip="192.168.1.20")),
        AndroidTvAdapter,
    )
    assert isinstance(
        AndroidTvAdapter(DeviceInfo(id="g", name="G", brand="googletv",
                                    ip="192.168.1.20")),
        AndroidTvAdapter,
    )
    assert isinstance(
        FireTvAdapter(DeviceInfo(id="f", name="F", brand="firetv",
                                 ip="192.168.1.24")),
        FireTvAdapter,
    )


def test_get_adapter_mock_gated(monkeypatch):
    monkeypatch.delenv("MOCK_TV", raising=False)
    with pytest.raises(RuntimeError, match="MOCK_TV=true"):
        get_adapter(DeviceInfo(id="m", name="M", brand="mock",
                               ip="192.168.1.25"))
    monkeypatch.setenv("MOCK_TV", "true")
    assert isinstance(
        get_adapter(DeviceInfo(id="m", name="M", brand="mock",
                               ip="192.168.1.25")),
        MockAdapter,
    )


# --------------------------------------------------------------------------
# Mock adapter
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_connect_send_launch_status():
    adapter = MockAdapter(
        DeviceInfo(id="m", name="M", brand="mock", ip="192.168.1.25")
    )
    result = await adapter.connect()
    assert result.success, result.error
    assert adapter.connected
    assert "testing only" in result.message
    result = await adapter.send_key(RemoteKey.UP)
    assert result.success
    assert adapter.last_key == "up"
    result = await adapter.launch_app("com.netflix.ninja")
    assert result.success
    assert adapter.last_app == "com.netflix.ninja"
    status = await adapter.get_status()
    assert status["mock"] is True
    assert status["connected"] is True
    assert status["last_key"] == "up"
    assert adapter.supports("launch_app") is True
    assert adapter.supports("pairing") is True
    assert adapter.supports("teleport") is False
    await adapter.disconnect()
    assert not adapter.connected


@pytest.mark.asyncio
async def test_mock_launch_empty_id():
    adapter = MockAdapter(
        DeviceInfo(id="m", name="M", brand="mock", ip="192.168.1.25")
    )
    result = await adapter.launch_app("")
    assert not result.success
    assert "No mock app id" in result.error


# --------------------------------------------------------------------------
# Roku
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_roku_connect_success(monkeypatch):
    fake = FakeHTTP()
    fake.add("/query/device-info", "GET", 200, b"<device-info/>")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = RokuAdapter(roku_device())
    result = await adapter.connect()
    assert result.success, result.error
    assert adapter.connected
    assert fake.urls("/query/device-info") == [
        "http://192.168.1.21:8060/query/device-info"
    ]
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_roku_connect_unreachable(monkeypatch):
    fake = FakeHTTP()
    fake.add_error(
        "/query/device-info", "GET",
        urllib.error.URLError("connection refused"),
    )
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = RokuAdapter(roku_device())
    result = await adapter.connect()
    assert not result.success
    assert "Could not reach Roku TV" in result.error
    assert "192.168.1.21" in result.error
    assert not adapter.connected


@pytest.mark.asyncio
async def test_roku_connect_non_200(monkeypatch):
    fake = FakeHTTP()
    fake.add("/query/device-info", "GET", 500, b"error")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = RokuAdapter(roku_device())
    result = await adapter.connect()
    assert not result.success
    assert "HTTP 500" in result.error


@pytest.mark.asyncio
async def test_roku_send_key(monkeypatch):
    fake = FakeHTTP()
    fake.add("/query/device-info", "GET", 200, b"<device-info/>")
    fake.add("/keypress/", "POST", 200, b"")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = RokuAdapter(roku_device())
    # send_key auto-connects (like the Samsung adapter).
    result = await adapter.send_key(RemoteKey.UP)
    assert result.success, result.error
    assert result.details["roku_key"] == "Up"
    assert fake.urls("/keypress/Up") == [
        "http://192.168.1.21:8060/keypress/Up"
    ]
    cases = [
        (RemoteKey.DOWN, "Down"), (RemoteKey.LEFT, "Left"),
        (RemoteKey.RIGHT, "Right"), (RemoteKey.OK, "Select"),
        (RemoteKey.BACK, "Back"), (RemoteKey.HOME, "Home"),
        (RemoteKey.MENU, "Info"), (RemoteKey.POWER, "Power"),
        (RemoteKey.VOLUME_UP, "VolumeUp"),
        (RemoteKey.VOLUME_DOWN, "VolumeDown"),
        (RemoteKey.MUTE, "VolumeMute"),
        (RemoteKey.CHANNEL_UP, "ChannelUp"),
        (RemoteKey.CHANNEL_DOWN, "ChannelDown"),
        (RemoteKey.PLAY, "Play"), (RemoteKey.PAUSE, "Pause"),
        (RemoteKey.STOP, "Stop"), (RemoteKey.REWIND, "Rev"),
        (RemoteKey.FAST_FORWARD, "Fwd"),
    ]
    for key, ecp in cases:
        result = await adapter.send_key(key)
        assert result.success, (key, result.error)
        assert result.details["roku_key"] == ecp
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_roku_send_key_http_error_is_honest(monkeypatch):
    fake = FakeHTTP()
    fake.add("/query/device-info", "GET", 200, b"<device-info/>")
    fake.add("/keypress/Up", "POST", 500, b"boom")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = RokuAdapter(roku_device())
    result = await adapter.send_key(RemoteKey.UP)
    assert not result.success
    assert "HTTP 500" in result.error
    assert "keypress Up" in result.error


@pytest.mark.asyncio
async def test_roku_query_apps_parses_xml(monkeypatch):
    fake = FakeHTTP()
    fake.add("/query/apps", "GET", 200, ROKU_APPS_XML)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = RokuAdapter(roku_device())
    apps = await adapter.query_apps()
    assert apps == [
        {"id": "12", "name": "Netflix"},
        {"id": "13", "name": "Prime Video"},
        {"id": "837", "name": "YouTube"},
    ]


@pytest.mark.asyncio
async def test_roku_launch_app_installed(monkeypatch):
    fake = FakeHTTP()
    fake.add("/query/device-info", "GET", 200, b"<device-info/>")
    fake.add("/query/apps", "GET", 200, ROKU_APPS_XML)
    fake.add("/launch/12", "POST", 200, b"")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = RokuAdapter(roku_device())
    result = await adapter.launch_app("12")
    assert result.success, result.error
    assert fake.urls("/query/apps")
    assert fake.urls("/launch/12") == ["http://192.168.1.21:8060/launch/12"]
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_roku_launch_app_not_installed_is_honest(monkeypatch):
    fake = FakeHTTP()
    fake.add("/query/device-info", "GET", 200, b"<device-info/>")
    fake.add("/query/apps", "GET", 200, ROKU_APPS_XML)
    fake.add("/launch/999", "POST", 200, b"")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = RokuAdapter(roku_device())
    result = await adapter.launch_app("999")
    assert not result.success
    assert "not installed" in result.error
    assert "Netflix (12)" in result.error
    # The launch endpoint must never be hit for an uninstalled app.
    assert fake.urls("/launch/") == []
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_roku_launch_app_empty_id(monkeypatch):
    adapter = RokuAdapter(roku_device())
    result = await adapter.launch_app("")
    assert not result.success
    assert "No valid Roku app id" in result.error


def test_roku_supports_and_status():
    adapter = RokuAdapter(roku_device())
    assert adapter.supports("power") is True
    assert adapter.supports("volume") is True
    assert adapter.supports("launch_app") is True
    assert adapter.supports("pairing") is False  # ECP needs no pairing
    assert adapter.supports("teleport") is False


@pytest.mark.asyncio
async def test_roku_status():
    adapter = RokuAdapter(roku_device())
    status = await adapter.get_status()
    assert status["brand"] == "roku"
    assert status["connected"] is False
    assert status["ecp_port"] == 8060


# --------------------------------------------------------------------------
# Sony
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sony_connect_success_checks_psk(monkeypatch):
    fake = FakeHTTP()
    fake.add("/sony/system", "POST", 200,
             json.dumps({"result": [{"status": "active"}], "id": 1}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    device = sony_device()
    adapter = SonyAdapter(device)
    result = await adapter.connect()
    assert result.success, result.error
    assert adapter.connected
    assert device.paired
    req = fake.requests[0]
    assert req["headers"]["x-auth-psk"] == "PSK123"
    assert req["headers"]["content-type"] == "application/json"
    assert json.loads(req["body"])["method"] == "getPowerStatus"
    status = await adapter.get_status()
    assert status["power"] == "active"
    assert status["has_psk"] is True
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_sony_connect_no_psk_is_honest():
    adapter = SonyAdapter(sony_device(pairing_token=""))
    result = await adapter.connect()
    assert not result.success
    assert "pre-shared key" in result.error
    assert "IP Control" in result.error
    assert not adapter.connected


@pytest.mark.asyncio
async def test_sony_connect_bad_psk(monkeypatch):
    fake = FakeHTTP()
    fake.add("/sony/system", "POST", 401, b"Unauthorized")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = SonyAdapter(sony_device())
    result = await adapter.connect()
    assert not result.success
    assert "rejected the pre-shared key" in result.error
    assert "401" in result.error


@pytest.mark.asyncio
async def test_sony_connect_unreachable(monkeypatch):
    fake = FakeHTTP()
    fake.add_error("/sony/system", "POST",
                   urllib.error.URLError("connection refused"))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = SonyAdapter(sony_device())
    result = await adapter.connect()
    assert not result.success
    assert "Could not reach Sony TV" in result.error


@pytest.mark.asyncio
async def test_sony_send_key_soap(monkeypatch):
    fake = FakeHTTP()
    fake.add("/sony/system", "POST", 200,
             json.dumps({"result": [{"status": "active"}], "id": 1}).encode())
    fake.add("/sony/IRCC", "POST", 200, b"")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = SonyAdapter(sony_device())
    result = await adapter.send_key(RemoteKey.UP)
    assert result.success, result.error
    assert result.details["ircc_code"] == "AAAAAQAAAAEAAAB0Aw=="
    req = [r for r in fake.requests if "/sony/IRCC" in r["url"]][0]
    assert req["headers"]["x-auth-psk"] == "PSK123"
    assert req["headers"]["soapaction"] == (
        '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"'
    )
    assert b"<IRCCCode>AAAAAQAAAAEAAAB0Aw==</IRCCCode>" in req["body"]
    assert b"X_SendIRCC" in req["body"]
    cases = [
        (RemoteKey.POWER, "AAAAAQAAAAEAAAAVAw=="),
        (RemoteKey.VOLUME_UP, "AAAAAQAAAAEAAAASAw=="),
        (RemoteKey.VOLUME_DOWN, "AAAAAQAAAAEAAAATAw=="),
        (RemoteKey.MUTE, "AAAAAQAAAAEAAAAUAw=="),
        (RemoteKey.HOME, "AAAAAQAAAAEAAABgAw=="),
        (RemoteKey.BACK, "AAAAAgAAAJcAAAAjAw=="),
        (RemoteKey.MENU, "AAAAAgAAAMQAAABLAw=="),
        (RemoteKey.PLAY, "AAAAAgAAAJcAAAAaAw=="),
        (RemoteKey.PAUSE, "AAAAAgAAAJcAAAAZAw=="),
        (RemoteKey.CHANNEL_UP, "AAAAAQAAAAEAAAAQAw=="),
        (RemoteKey.CHANNEL_DOWN, "AAAAAQAAAAEAAAARAw=="),
        (RemoteKey.REWIND, "AAAAAgAAAJcAAAAbAw=="),
        (RemoteKey.FAST_FORWARD, "AAAAAgAAAJcAAAAcAw=="),
    ]
    for key, code in cases:
        result = await adapter.send_key(key)
        assert result.success, (key, result.error)
        assert result.details["ircc_code"] == code
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_sony_send_key_http_error_is_honest(monkeypatch):
    fake = FakeHTTP()
    fake.add("/sony/system", "POST", 200,
             json.dumps({"result": [{"status": "active"}], "id": 1}).encode())
    fake.add("/sony/IRCC", "POST", 500, b"error")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    adapter = SonyAdapter(sony_device())
    result = await adapter.send_key(RemoteKey.OK)
    assert not result.success
    assert "HTTP 500" in result.error


@pytest.mark.asyncio
async def test_sony_launch_app_is_honest():
    adapter = SonyAdapter(sony_device())
    result = await adapter.launch_app("com.netflix.ninja")
    assert not result.success
    assert "cannot launch apps by id" in result.error
    assert adapter.supports("launch_app") is False
    assert adapter.supports("pairing") is False
    assert adapter.supports("power") is True
    assert adapter.supports("media") is True


# --------------------------------------------------------------------------
# Fire TV (fake adb)
# --------------------------------------------------------------------------

# cryptography is imported here (module level, after the first section)
# because only the Android TV tests below need it.
from cryptography import x509 as _x509  # noqa: E402
from cryptography.hazmat.primitives import (  # noqa: E402
    serialization as _serialization,
)


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


FIRETV_IP = "192.168.1.30"
FIRETV_TARGET = "192.168.1.30:5555"


class FakeAdb:
    """Fake ``subprocess.run`` for adb; records every call."""

    def __init__(self):
        self.calls: list[list] = []
        self.connect_stdout = f"connected to {FIRETV_TARGET}\n"
        self.devices_stdout = (
            "List of devices attached\n" f"{FIRETV_TARGET}\tdevice\n"
        )
        self.shell_results: dict[tuple, FakeCompletedProcess] = {}

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        rest = list(args[1:])
        if rest[:1] == ["connect"]:
            return FakeCompletedProcess(0, self.connect_stdout)
        if rest == ["devices"]:
            return FakeCompletedProcess(0, self.devices_stdout)
        if rest[:2] == ["-s", FIRETV_TARGET] and rest[2] == "shell":
            key = tuple(rest[3:])
            return self.shell_results.get(key, FakeCompletedProcess(0, ""))
        raise AssertionError(f"Unexpected adb call: {args}")

    def adb_calls(self):
        return [c for c in self.calls if c[0] == "adb"]


def firetv_device(**overrides):
    data = dict(id="ftv1", name="Fire TV", brand="firetv", ip=FIRETV_IP)
    data.update(overrides)
    return DeviceInfo(**data)


@pytest.mark.asyncio
async def test_firetv_connect_success(monkeypatch):
    fake_adb = FakeAdb()
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.connect()
    assert result.success, result.error
    assert adapter.connected
    assert ["adb", "connect", FIRETV_TARGET] in fake_adb.calls
    assert ["adb", "devices"] in fake_adb.calls
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_firetv_connect_no_adb(monkeypatch):
    monkeypatch.setattr(fire_tv_mod, "adb_available", lambda: False)
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.connect()
    assert not result.success
    assert "adb" in result.error
    assert "not installed" in result.error
    assert not adapter.connected


@pytest.mark.asyncio
async def test_firetv_connect_refused(monkeypatch):
    fake_adb = FakeAdb()
    fake_adb.connect_stdout = (
        f"failed to connect to {FIRETV_TARGET}\n"
    )
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.connect()
    assert not result.success
    assert "Could not connect to Fire TV" in result.error
    assert "ADB Debugging" in result.error


@pytest.mark.asyncio
async def test_firetv_connect_unauthorized(monkeypatch):
    fake_adb = FakeAdb()
    fake_adb.devices_stdout = (
        "List of devices attached\n" f"{FIRETV_TARGET}\tunauthorized\n"
    )
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.connect()
    assert not result.success
    assert "unauthorized" in result.error
    assert "accept" in result.error


@pytest.mark.asyncio
async def test_firetv_connect_offline(monkeypatch):
    fake_adb = FakeAdb()
    fake_adb.devices_stdout = (
        "List of devices attached\n" f"{FIRETV_TARGET}\toffline\n"
    )
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.connect()
    assert not result.success
    assert "not ready for ADB" in result.error


@pytest.mark.asyncio
async def test_firetv_send_key(monkeypatch):
    fake_adb = FakeAdb()
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.send_key(RemoteKey.HOME)
    assert result.success, result.error
    assert result.details["keyevent"] == 3
    assert ["adb", "-s", FIRETV_TARGET, "shell", "input", "keyevent", "3"] \
        in fake_adb.calls
    cases = [
        (RemoteKey.UP, 19), (RemoteKey.OK, 23), (RemoteKey.BACK, 4),
        (RemoteKey.VOLUME_UP, 24), (RemoteKey.MUTE, 164),
        (RemoteKey.CHANNEL_UP, 166), (RemoteKey.PLAY, 126),
        (RemoteKey.PAUSE, 127), (RemoteKey.FAST_FORWARD, 90),
    ]
    for key, code in cases:
        result = await adapter.send_key(key)
        assert result.success, (key, result.error)
        assert result.details["keyevent"] == code
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_firetv_send_key_failure_is_honest(monkeypatch):
    fake_adb = FakeAdb()
    fake_adb.shell_results[("input", "keyevent", "19")] = (
        FakeCompletedProcess(1, "", "error: device '192.168.1.30:5555' "
                             "not found")
    )
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.send_key(RemoteKey.UP)
    assert not result.success
    assert "Failed to send up" in result.error
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_firetv_launch_app(monkeypatch):
    fake_adb = FakeAdb()
    fake_adb.shell_results[(
        "monkey", "-p", "com.netflix.ninja",
        "-c", "android.intent.category.LAUNCHER", "1",
    )] = FakeCompletedProcess(0, "Events injected: 1\n")
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.launch_app("com.netflix.ninja")
    assert result.success, result.error
    assert ["adb", "-s", FIRETV_TARGET, "shell", "monkey", "-p",
            "com.netflix.ninja", "-c",
            "android.intent.category.LAUNCHER", "1"] in fake_adb.calls
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_firetv_launch_app_not_installed(monkeypatch):
    fake_adb = FakeAdb()
    fake_adb.shell_results[(
        "monkey", "-p", "com.example.missing",
        "-c", "android.intent.category.LAUNCHER", "1",
    )] = FakeCompletedProcess(
        0, "No activities found to run, monkey aborted.\n"
    )
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.launch_app("com.example.missing")
    assert not result.success
    assert "not installed" in result.error


@pytest.mark.asyncio
async def test_firetv_launch_app_invalid_package(monkeypatch):
    fake_adb = FakeAdb()
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = FireTvAdapter(firetv_device())
    result = await adapter.launch_app("not a package!")
    assert not result.success
    assert "Invalid Android package name" in result.error
    # Nothing but connect/devices may have run; no shell command.
    assert not [c for c in fake_adb.calls if "shell" in c]


def test_firetv_supports():
    adapter = FireTvAdapter(firetv_device())
    assert adapter.supports("power") is True
    assert adapter.supports("launch_app") is True
    assert adapter.supports("pairing") is False  # ADB auth, not pairing
    assert adapter.supports("teleport") is False


# --------------------------------------------------------------------------
# Android TV (scripted fake TLS/protobuf streams)
# --------------------------------------------------------------------------

def _unframe(data: bytes) -> bytes:
    length, pos = android_tv_mod._read_varint(data, 0)
    assert pos + length == len(data)
    return data[pos:]


class FakeReader:
    """StreamReader stand-in fed by the test via ``feed``."""

    def __init__(self):
        self._buf = bytearray()
        self._eof = False
        self._cond = asyncio.Condition()

    async def feed(self, data: bytes):
        async with self._cond:
            self._buf += data
            self._cond.notify_all()

    async def readexactly(self, n):
        async with self._cond:
            while len(self._buf) < n:
                if self._eof:
                    raise asyncio.IncompleteReadError(
                        partial=bytes(self._buf), expected=n
                    )
                await self._cond.wait()
            out = bytes(self._buf[:n])
            del self._buf[:n]
            return out


class FakeWriter:
    """StreamWriter stand-in recording every frame written."""

    def __init__(self):
        self.sent: list[bytes] = []
        self.closed = False

    def write(self, data):
        self.sent.append(bytes(data))

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None

    def is_closing(self):
        return self.closed


class FakeTlsEndpoint:
    def __init__(self):
        self.reader = FakeReader()
        self.writer = FakeWriter()


async def _wait_for_sent(writer, count, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while len(writer.sent) < count:
        if loop.time() > deadline:
            raise AssertionError(
                f"Timed out waiting for {count} sent frames; "
                f"got {len(writer.sent)}."
            )
        await asyncio.sleep(0.01)


async def _wait_for_opened(opened, port, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while port not in opened:
        if loop.time() > deadline:
            raise AssertionError(
                f"Timed out waiting for a connection to port {port}; "
                f"opened so far: {opened}."
            )
        await asyncio.sleep(0.01)


async def _wait_until(predicate, timeout=5.0, message="condition"):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"Timed out waiting for {message}.")
        await asyncio.sleep(0.01)


def _outer(*parts: bytes) -> bytes:
    return android_tv_mod._frame(android_tv_mod._outer_message(*parts))


async def _begin_pairing_session(monkeypatch, *, server_sends_options=False):
    """Drive connect() up to the pairing_required step.

    Returns a dict with the adapter, endpoints, and the RSA numbers both
    sides use, so tests can compute the expected pairing secret.
    """
    client_cert, client_key = android_tv_mod._create_identity("test-client")
    server_cert, _sk = android_tv_mod._create_identity("test-tv")
    server_der = _x509.load_pem_x509_certificate(
        server_cert.encode("ascii")
    ).public_bytes(_serialization.Encoding.DER)
    pairing_ep = FakeTlsEndpoint()
    remote_ep = FakeTlsEndpoint()
    opened: list[int] = []

    async def fake_open_tls(_self, host, port, cert_pem, key_pem):
        opened.append(port)
        if port == android_tv_mod.PAIRING_PORT:
            return pairing_ep.reader, pairing_ep.writer, server_der
        return remote_ep.reader, remote_ep.writer, server_der

    monkeypatch.setattr(AndroidTvAdapter, "_open_tls", fake_open_tls)
    monkeypatch.setattr(
        android_tv_mod, "_create_identity",
        lambda name: (client_cert, client_key),
    )
    device = DeviceInfo(id="atv1", name="Test TV", brand="androidtv",
                        ip="192.168.1.20")
    adapter = AndroidTvAdapter(device)
    connect_task = asyncio.create_task(adapter.connect())
    try:
        await _wait_for_sent(pairing_ep.writer, 1)
        await pairing_ep.reader.feed(_outer(
            android_tv_mod._field_bytes(
                11, android_tv_mod._field_string(1, "Test TV")
            )
        ))
        await _wait_for_sent(pairing_ep.writer, 2)
        if server_sends_options:
            options = (
                android_tv_mod._field_bytes(
                    1, android_tv_mod._hex_encoding()
                )
                + android_tv_mod._field_bytes(
                    2, android_tv_mod._hex_encoding()
                )
            )
            await pairing_ep.reader.feed(_outer(
                android_tv_mod._field_bytes(20, options)
            ))
            await _wait_for_sent(pairing_ep.writer, 3)
        await pairing_ep.reader.feed(_outer(
            android_tv_mod._field_bytes(31, b"")
        ))
        result = await asyncio.wait_for(connect_task, timeout=5)
        assert not result.success
        assert result.details.get("pairing_required") is True
    except Exception:
        if not connect_task.done():
            connect_task.cancel()
        try:
            await adapter.disconnect()
        except Exception:
            pass
        raise
    client_n, client_e = android_tv_mod._cert_rsa_numbers(client_cert)
    server_n, server_e = android_tv_mod._peer_rsa_numbers(server_der)
    return {
        "adapter": adapter,
        "device": device,
        "pairing_ep": pairing_ep,
        "remote_ep": remote_ep,
        "opened": opened,
        "client_n": client_n,
        "client_e": client_e,
        "server_n": server_n,
        "server_e": server_e,
    }


async def _drive_pairing(monkeypatch, *, server_sends_options=False):
    """Run the full pairing flow; return (adapter, device, remote_ep).

    The adapter is left connected; callers must disconnect it.
    """
    ctx = await _begin_pairing_session(
        monkeypatch, server_sends_options=server_sends_options
    )
    adapter = ctx["adapter"]
    pairing_ep = ctx["pairing_ep"]
    remote_ep = ctx["remote_ep"]
    probe = android_tv_mod.compute_pairing_secret(
        ctx["client_n"], ctx["client_e"],
        ctx["server_n"], ctx["server_e"], "00B2C3",
    )
    code = f"{probe[0]:02X}B2C3"
    pair_task = asyncio.create_task(adapter.pair(code))
    try:
        expected_frames = 4 if server_sends_options else 3
        await _wait_for_sent(pairing_ep.writer, expected_frames)
        sent_secret_frame = pairing_ep.writer.sent[expected_frames - 1]
        sent_fields = android_tv_mod._parse_fields(
            _unframe(sent_secret_frame)
        )
        secret_bytes = android_tv_mod._bytes_field(sent_fields, 40)
        inner = android_tv_mod._parse_fields(secret_bytes)
        sent_secret = android_tv_mod._bytes_field(inner, 1)
        assert sent_secret == probe
        await pairing_ep.reader.feed(_outer(
            android_tv_mod._field_bytes(
                41, android_tv_mod._field_bytes(1, sent_secret)
            )
        ))
        await _wait_for_opened(ctx["opened"], android_tv_mod.REMOTE_PORT)
        # The TV speaks first: remote_configure with feature bitmask.
        configure = (
            android_tv_mod._field_varint(1, 615)
            + android_tv_mod._field_bytes(
                2, android_tv_mod._field_string(1, "TestModel")
            )
        )
        await remote_ep.reader.feed(android_tv_mod._frame(
            android_tv_mod._field_bytes(1, configure)
        ))
        await _wait_for_sent(remote_ep.writer, 2)
        pair_result = await asyncio.wait_for(pair_task, timeout=5)
        assert pair_result.success, pair_result.error
        assert adapter.connected
        return adapter, ctx["device"], remote_ep
    except Exception:
        if not pair_task.done():
            pair_task.cancel()
        try:
            await adapter.disconnect()
        except Exception:
            pass
        raise


def test_androidtv_protobuf_roundtrip():
    payload = android_tv_mod._remote_key_inject_message(19)
    fields = android_tv_mod._parse_fields(payload)
    assert 10 in fields
    inner = android_tv_mod._parse_fields(
        android_tv_mod._bytes_field(fields, 10)
    )
    assert android_tv_mod._varint_field(inner, 1) == 19
    assert android_tv_mod._varint_field(inner, 2) == 3  # SHORT
    framed = android_tv_mod._frame(payload)
    length, pos = android_tv_mod._read_varint(framed, 0)
    assert length == len(payload)
    assert framed[pos:] == payload


def test_androidtv_pairing_secret_and_checksum():
    secret = android_tv_mod.compute_pairing_secret(
        123456789, 65537, 987654321, 65537, "00B2C3"
    )
    expected = hashlib.sha256(
        android_tv_mod._rsa_number_bytes(123456789)
        + android_tv_mod._rsa_number_bytes(65537)
        + android_tv_mod._rsa_number_bytes(987654321)
        + android_tv_mod._rsa_number_bytes(65537)
        + bytes.fromhex("B2C3")
    ).digest()
    assert secret == expected
    good_code = f"{secret[0]:02X}B2C3"
    assert android_tv_mod.pairing_code_checksum_ok(secret, good_code)
    bad_code = f"{secret[0] ^ 0xFF:02X}B2C3"
    assert not android_tv_mod.pairing_code_checksum_ok(secret, bad_code)
    # Odd-length hex numbers are even-padded, as the reference does.
    assert android_tv_mod._rsa_number_bytes(0x10001) == bytes.fromhex("010001")


def test_androidtv_key_map():
    assert android_tv_mod.KEY_MAP[RemoteKey.UP] == 19
    assert android_tv_mod.KEY_MAP[RemoteKey.DOWN] == 20
    assert android_tv_mod.KEY_MAP[RemoteKey.OK] == 23
    assert android_tv_mod.KEY_MAP[RemoteKey.BACK] == 4
    assert android_tv_mod.KEY_MAP[RemoteKey.HOME] == 3
    assert android_tv_mod.KEY_MAP[RemoteKey.POWER] == 26
    assert android_tv_mod.KEY_MAP[RemoteKey.MUTE] == 164
    assert android_tv_mod.KEY_MAP[RemoteKey.CHANNEL_UP] == 166
    assert android_tv_mod.KEY_MAP[RemoteKey.CHANNEL_DOWN] == 167
    assert android_tv_mod.KEY_MAP[RemoteKey.PLAY] == 126
    assert android_tv_mod.KEY_MAP[RemoteKey.PAUSE] == 127
    assert len(android_tv_mod.KEY_MAP) == len(RemoteKey)
    assert android_tv_mod.REQUESTED_FEATURES == 615


def test_androidtv_message_builders():
    req = android_tv_mod._pairing_request_message("My TV")
    fields = android_tv_mod._parse_fields(req)
    assert android_tv_mod._varint_field(fields, 1) == 1  # protocol_version
    assert android_tv_mod._varint_field(fields, 2) == 200  # STATUS_OK
    inner = android_tv_mod._parse_fields(
        android_tv_mod._bytes_field(fields, 10)
    )
    assert android_tv_mod._bytes_field(inner, 1) == b"androidtvremote2"
    assert android_tv_mod._bytes_field(inner, 2) == b"My TV"
    opts = android_tv_mod._parse_fields(android_tv_mod._options_message())
    assert 20 in opts
    cfg = android_tv_mod._parse_fields(
        android_tv_mod._configuration_message()
    )
    assert 30 in cfg
    secret_msg = android_tv_mod._parse_fields(
        android_tv_mod._secret_message(b"\x01\x02")
    )
    assert android_tv_mod._bytes_field(
        android_tv_mod._parse_fields(
            android_tv_mod._bytes_field(secret_msg, 40)
        ),
        1,
    ) == b"\x01\x02"


def test_androidtv_identity_roundtrip():
    cert, key = android_tv_mod._create_identity("test")
    assert android_tv_mod._load_identity(
        json.dumps({"cert": cert, "key": key})
    ) == (cert, key)
    assert android_tv_mod._load_identity("not json") is None
    assert android_tv_mod._load_identity("") is None
    assert android_tv_mod._load_identity(
        json.dumps({"cert": "junk", "key": "junk"})
    ) is None


@pytest.mark.asyncio
async def test_androidtv_connect_without_cryptography(monkeypatch):
    def _boom(name):
        raise RuntimeError(
            "The 'cryptography' package is not installed; "
            "Android TV pairing needs it."
        )

    monkeypatch.setattr(android_tv_mod, "_create_identity", _boom)
    adapter = AndroidTvAdapter(DeviceInfo(
        id="a", name="A", brand="androidtv", ip="192.168.1.20"
    ))
    result = await adapter.connect()
    assert not result.success
    assert "cryptography" in result.error


@pytest.mark.asyncio
async def test_androidtv_pairing_flow(monkeypatch):
    adapter, device, remote_ep = await _drive_pairing(monkeypatch)
    try:
        assert device.paired
        token = json.loads(device.pairing_token)
        assert "cert" in token and "key" in token
        status = await adapter.get_status()
        assert status["server_features"] == 615
        assert status["needs_on_device_verification"] is True
        # send_key: the next frame must be a key inject for DPAD_UP.
        result = await adapter.send_key(RemoteKey.UP)
        assert result.success, result.error
        assert result.details["key_code"] == 19
        await _wait_for_sent(remote_ep.writer, 3)
        key_fields = android_tv_mod._parse_fields(
            _unframe(remote_ep.writer.sent[2])
        )
        inner = android_tv_mod._parse_fields(
            android_tv_mod._bytes_field(key_fields, 10)
        )
        assert android_tv_mod._varint_field(inner, 1) == 19
        assert android_tv_mod._varint_field(inner, 2) == 3
        # TV ping -> the client answers with the same val1.
        await remote_ep.reader.feed(android_tv_mod._frame(
            android_tv_mod._field_bytes(
                8,
                android_tv_mod._field_varint(1, 42)
                + android_tv_mod._field_varint(2, 7),
            )
        ))
        await _wait_for_sent(remote_ep.writer, 4)
        ping_fields = android_tv_mod._parse_fields(
            _unframe(remote_ep.writer.sent[3])
        )
        ping_inner = android_tv_mod._parse_fields(
            android_tv_mod._bytes_field(ping_fields, 9)
        )
        assert android_tv_mod._varint_field(ping_inner, 1) == 42
        # TV pushes volume state -> get_status reflects it.
        await remote_ep.reader.feed(android_tv_mod._frame(
            android_tv_mod._field_bytes(
                50,
                android_tv_mod._field_varint(6, 30)
                + android_tv_mod._field_varint(7, 12)
                + android_tv_mod._field_varint(8, 0),
            )
        ))
        await _wait_until(
            lambda: adapter._volume_level == 12, message="volume state"
        )
        status = await adapter.get_status()
        assert status["volume_level"] == 12
        assert status["volume_muted"] is False
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_androidtv_pairing_flow_server_options(monkeypatch):
    adapter, _device, _remote_ep = await _drive_pairing(
        monkeypatch, server_sends_options=True
    )
    try:
        assert adapter.connected
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_androidtv_pair_bad_checksum_sends_nothing(monkeypatch):
    ctx = await _begin_pairing_session(monkeypatch)
    adapter = ctx["adapter"]
    pairing_ep = ctx["pairing_ep"]
    try:
        probe = android_tv_mod.compute_pairing_secret(
            ctx["client_n"], ctx["client_e"],
            ctx["server_n"], ctx["server_e"], "00B2C3",
        )
        bad_code = f"{probe[0] ^ 0xFF:02X}B2C3"
        assert not android_tv_mod.pairing_code_checksum_ok(probe, bad_code)
        frames_before = len(pairing_ep.writer.sent)
        result = await adapter.pair(bad_code)
        assert not result.success
        assert "does not look right" in result.error
        assert len(pairing_ep.writer.sent) == frames_before
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_androidtv_pair_without_session():
    adapter = AndroidTvAdapter(DeviceInfo(
        id="a", name="A", brand="androidtv", ip="192.168.1.20"
    ))
    result = await adapter.pair("A1B2C3")
    assert not result.success
    assert "No pairing session is in progress" in result.error
    result = await adapter.pair("not-a-code")
    assert not result.success
    assert "6 hexadecimal" in result.error


@pytest.mark.asyncio
async def test_androidtv_connect_paired_goes_straight_to_remote(monkeypatch):
    cert, key = android_tv_mod._create_identity("paired-client")
    server_cert, _sk = android_tv_mod._create_identity("test-tv")
    server_der = _x509.load_pem_x509_certificate(
        server_cert.encode("ascii")
    ).public_bytes(_serialization.Encoding.DER)
    remote_ep = FakeTlsEndpoint()
    opened: list[int] = []

    async def fake_open_tls(_self, host, port, cert_pem, key_pem):
        opened.append(port)
        return remote_ep.reader, remote_ep.writer, server_der

    monkeypatch.setattr(AndroidTvAdapter, "_open_tls", fake_open_tls)
    device = DeviceInfo(
        id="atv1", name="Test TV", brand="androidtv", ip="192.168.1.20",
        pairing_token=json.dumps({"cert": cert, "key": key}),
    )
    adapter = AndroidTvAdapter(device)
    task = asyncio.create_task(adapter.connect())
    try:
        await _wait_for_opened(opened, android_tv_mod.REMOTE_PORT)
        configure = (
            android_tv_mod._field_varint(1, 611)
            + android_tv_mod._field_bytes(
                2, android_tv_mod._field_string(1, "M")
            )
        )
        await remote_ep.reader.feed(android_tv_mod._frame(
            android_tv_mod._field_bytes(1, configure)
        ))
        result = await asyncio.wait_for(task, timeout=5)
        assert result.success, result.error
        assert adapter.connected
        assert opened == [android_tv_mod.REMOTE_PORT]  # never touched 6467
        status = await adapter.get_status()
        assert status["server_features"] == 611
        assert status["paired"] is True
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_androidtv_send_key_unreachable(monkeypatch):
    async def fake_open_tls(_self, host, port, cert_pem, key_pem):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(AndroidTvAdapter, "_open_tls", fake_open_tls)
    adapter = AndroidTvAdapter(DeviceInfo(
        id="a", name="A", brand="androidtv", ip="192.168.1.20"
    ))
    result = await adapter.send_key(RemoteKey.HOME)
    assert not result.success
    assert "Could not reach Android TV" in result.error


def test_androidtv_supports(monkeypatch):
    adapter = AndroidTvAdapter(DeviceInfo(
        id="a", name="A", brand="androidtv", ip="192.168.1.20"
    ))
    assert adapter.supports("power") is True
    assert adapter.supports("pairing") is True
    assert adapter.supports("teleport") is False
    monkeypatch.setattr(fire_tv_mod, "adb_available", lambda: False)
    assert adapter.supports("launch_app") is False
    monkeypatch.setattr(fire_tv_mod, "adb_available", lambda: True)
    assert adapter.supports("launch_app") is True


@pytest.mark.asyncio
async def test_androidtv_launch_app_no_adb(monkeypatch):
    monkeypatch.setattr(fire_tv_mod, "adb_available", lambda: False)
    adapter = AndroidTvAdapter(DeviceInfo(
        id="a", name="A", brand="androidtv", ip="192.168.1.20"
    ))
    result = await adapter.launch_app("com.netflix.ninja")
    assert not result.success
    assert "needs ADB" in result.error
    assert adapter.supports("launch_app") is False


@pytest.mark.asyncio
async def test_androidtv_launch_app_via_adb(monkeypatch):
    fake_adb = FakeAdb()
    fake_adb.shell_results[(
        "monkey", "-p", "com.netflix.ninja",
        "-c", "android.intent.category.LAUNCHER", "1",
    )] = FakeCompletedProcess(0, "Events injected: 1\n")
    monkeypatch.setattr(subprocess, "run", fake_adb)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/adb")
    adapter = AndroidTvAdapter(DeviceInfo(
        id="a", name="A", brand="androidtv", ip=FIRETV_IP
    ))
    result = await adapter.launch_app("com.netflix.ninja")
    assert result.success, result.error
    assert ["adb", "connect", FIRETV_TARGET] in fake_adb.calls


# --------------------------------------------------------------------------
# TCL
# --------------------------------------------------------------------------

def test_tcl_detect_os():
    assert detect_os(DeviceInfo(
        id="t", name="TCL Roku TV", brand="tcl", model="55S535")) == "roku"
    assert detect_os(DeviceInfo(
        id="t", name="T", brand="tcl", model="TCL Roku TV")) == "roku"
    assert detect_os(DeviceInfo(
        id="t", name="TCL Google TV", brand="tcl",
        model="55P635")) == "androidtv"
    assert detect_os(DeviceInfo(
        id="t", name="T", brand="tcl", model="Android TV")) == "androidtv"
    assert detect_os(DeviceInfo(
        id="t", name="T", brand="tcl", model="55P635")) is None
    assert detect_os(DeviceInfo(
        id="t", name="TCL TV", brand="tcl", model="")) is None


@pytest.mark.asyncio
async def test_tcl_roku_delegates(monkeypatch):
    fake = FakeHTTP()
    fake.add("/query/device-info", "GET", 200, b"<device-info/>")
    fake.add("/keypress/Up", "POST", 200, b"")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    device = DeviceInfo(
        id="t", name="TCL Roku TV", brand="tcl", model="TCL Roku TV 55S535",
        ip="192.168.1.21",
    )
    adapter = TclAdapter(device)
    assert isinstance(adapter._delegate, RokuAdapter)
    assert adapter.supports("launch_app") is True
    assert adapter.supports("pairing") is False
    result = await adapter.connect()
    assert result.success, result.error
    result = await adapter.send_key(RemoteKey.UP)
    assert result.success, result.error
    assert fake.urls("/keypress/Up")
    status = await adapter.get_status()
    assert status["brand"] == "tcl"
    assert status["delegated_brand"] == "roku"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_tcl_unknown_os_is_honest():
    device = DeviceInfo(
        id="t", name="TCL TV", brand="tcl", model="55P635",
        ip="192.168.1.23",
    )
    adapter = TclAdapter(device)
    assert adapter._delegate is None
    assert adapter.supports("power") is False
    result = await adapter.connect()
    assert not result.success
    assert "Could not determine" in result.error
    assert "select the TV's operating system manually" in result.error
    result = await adapter.send_key(RemoteKey.UP)
    assert not result.success
    assert "manually" in result.error
    result = await adapter.launch_app("12")
    assert not result.success
    assert "manually" in result.error


def test_tcl_android_delegate_type():
    device = DeviceInfo(
        id="t", name="TCL Google TV", brand="tcl", model="Google TV",
        ip="192.168.1.20",
    )
    adapter = TclAdapter(device)
    assert isinstance(adapter._delegate, AndroidTvAdapter)
    assert adapter.supports("pairing") is True


@pytest.mark.asyncio
async def test_tcl_pair_roku_is_honest():
    device = DeviceInfo(
        id="t", name="TCL Roku TV", brand="tcl", model="Roku TV",
        ip="192.168.1.21",
    )
    adapter = TclAdapter(device)
    result = await adapter.pair("A1B2C3")
    assert not result.success
    assert "needs no pairing" in result.error


@pytest.mark.asyncio
async def test_tcl_unknown_os_status():
    device = DeviceInfo(
        id="t", name="TCL TV", brand="tcl", model="55P635",
        ip="192.168.1.23",
    )
    adapter = TclAdapter(device)
    status = await adapter.get_status()
    assert status["brand"] == "tcl"
    assert status["delegated_brand"] is None
    assert "delegate" not in status
