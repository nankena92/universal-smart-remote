"""API endpoint tests (mocked adapters; no real TV needed)."""

from __future__ import annotations

import pytest

MOCK_TV = {"ip": "127.0.0.1", "brand": "mock", "name": "Mock TV"}


def _connect(client, headers, payload=None):
    return client.post(
        "/devices/connect", json=payload or MOCK_TV, headers=headers
    )


def test_health_no_auth(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"success": True, "status": "ok"}


def test_discover_returns_canned_list(client, auth_headers, monkeypatch):
    from app.routes.devices import discovery as discovery_mod

    canned = [
        {
            "id": "discovered-192.168.1.50",
            "name": "Living Room TV",
            "brand": "samsung",
            "model": "QN90A",
            "ip": "192.168.1.50",
            "port": 8001,
            "mac": "",
            "paired": False,
        }
    ]
    monkeypatch.setattr(
        discovery_mod, "discover_devices", lambda timeout=4.0: canned
    )
    res = client.get("/devices/discover", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"] == canned


def test_list_devices_empty_then_saved(client, auth_headers, stub_adapters):
    assert client.get("/devices", headers=auth_headers).json()["data"] == []
    res = _connect(client, auth_headers)
    assert res.status_code == 200
    devices = client.get("/devices", headers=auth_headers).json()["data"]
    assert len(devices) == 1
    assert devices[0]["ip"] == "127.0.0.1"
    assert devices[0]["paired"] is True


def test_connect_returns_status_and_activates(
    client, auth_headers, stub_adapters
):
    res = _connect(client, auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["connected"] is True
    assert body["device_id"]
    assert body["brand"] == "mock"
    assert body["ip"] == "127.0.0.1"
    status = client.get(
        "/devices/connection-status", headers=auth_headers
    ).json()
    assert status["connected"] is True
    assert status["device_id"] == body["device_id"]


def test_connect_by_saved_device_id(client, auth_headers, stub_adapters):
    first = _connect(client, auth_headers).json()
    client.request("DELETE", "/devices/disconnect", headers=auth_headers)
    res = client.post(
        "/devices/connect",
        json={"device_id": first["device_id"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["connected"] is True


def test_connect_unknown_device_id_404(client, auth_headers, stub_adapters):
    res = client.post(
        "/devices/connect",
        json={"device_id": "no-such-device"},
        headers=auth_headers,
    )
    assert res.status_code == 404
    assert res.json()["success"] is False


def test_connect_no_fields_400(client, auth_headers, stub_adapters):
    res = client.post("/devices/connect", json={}, headers=auth_headers)
    assert res.status_code == 400
    assert res.json()["success"] is False


def test_connect_tv_refusal_is_honest_503(
    client, auth_headers, real_adapters
):
    # The Sony adapter exists but refuses without a pre-shared key — the
    # backend must surface that honest 503, never a fake success.
    res = client.post(
        "/devices/connect",
        json={"ip": "127.0.0.1", "brand": "sony", "name": "Sony TV"},
        headers=auth_headers,
    )
    assert res.status_code == 503
    body = res.json()
    assert body["success"] is False
    assert "Sony" in body["error"]


def test_connect_missing_adapter_module_is_honest_503(
    client, auth_headers, real_adapters, monkeypatch
):
    # Adapter package (loader) absent entirely -> honest 503.
    from app.services import device_service as svc

    monkeypatch.setattr(svc, "_load_get_adapter", lambda: None)
    res = client.post(
        "/devices/connect",
        json={"ip": "127.0.0.1", "brand": "roku", "name": "Roku TV"},
        headers=auth_headers,
    )
    assert res.status_code == 503
    assert res.json()["success"] is False
    assert "not installed yet" in res.json()["error"]


def test_remote_key_success(client, auth_headers, stub_adapters):
    _connect(client, auth_headers)
    for key in ("up", "ok", "volume-up", "power", "play"):
        res = client.post(f"/remote/{key}", json={}, headers=auth_headers)
        assert res.status_code == 200, key
        assert res.json()["success"] is True
        assert res.json()["key"] == key


def test_remote_key_with_explicit_device_id(
    client, auth_headers, stub_adapters
):
    device_id = _connect(client, auth_headers).json()["device_id"]
    res = client.post(
        "/remote/down", json={"device_id": device_id}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["key"] == "down"


def test_remote_menu_and_stop_endpoints(client, auth_headers, stub_adapters):
    # Exposed because api.ts KEY_ENDPOINTS and RemoteKey both define them.
    _connect(client, auth_headers)
    for key in ("menu", "stop"):
        res = client.post(f"/remote/{key}", json={}, headers=auth_headers)
        assert res.status_code == 200, key
        assert res.json()["success"] is True


def test_remote_404_when_disconnected(client, auth_headers, stub_adapters):
    res = client.post("/remote/up", json={}, headers=auth_headers)
    assert res.status_code == 404
    body = res.json()
    assert body["success"] is False
    assert "No TV is connected" in body["error"]


def test_remote_404_for_unknown_device_id(
    client, auth_headers, stub_adapters
):
    _connect(client, auth_headers)
    res = client.post(
        "/remote/up", json={"device_id": "no-such-device"}, headers=auth_headers
    )
    assert res.status_code == 404


def test_remote_tv_refusal_is_503(client, auth_headers, failing_stub_adapters):
    _connect(client, auth_headers)
    res = client.post("/remote/up", json={}, headers=auth_headers)
    assert res.status_code == 503
    body = res.json()
    assert body["success"] is False
    assert "refused" in body["error"]


def test_launch_app_success_resolves_roku_id(
    client, auth_headers, stub_adapters
):
    res = client.post(
        "/devices/connect",
        json={"ip": "127.0.0.1", "brand": "roku", "name": "Roku TV"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    res = client.post(
        "/remote/launch-app", json={"app": "netflix"}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["app"] == "netflix"
    # Each command builds a fresh adapter, so the launch landed on the
    # most recent stub instance.
    assert stub_adapters[-1].launched == ["12"]  # Roku Netflix id


def test_launch_app_unknown_app_422(client, auth_headers, stub_adapters):
    _connect(client, auth_headers)
    res = client.post(
        "/remote/launch-app", json={"app": "hulu"}, headers=auth_headers
    )
    assert res.status_code == 422
    assert res.json()["success"] is False


def test_launch_app_unsupported_brand_422(
    client, auth_headers, stub_adapters
):
    # Sony has no documented app id for any streaming app (apps.py: None).
    client.post(
        "/devices/connect",
        json={"ip": "127.0.0.1", "brand": "sony", "name": "Sony TV"},
        headers=auth_headers,
    )
    res = client.post(
        "/remote/launch-app", json={"app": "netflix"}, headers=auth_headers
    )
    assert res.status_code == 422
    assert "not supported/unknown for sony" in res.json()["error"]


def test_launch_app_tv_refusal_is_503(
    client, auth_headers, failing_stub_adapters
):
    client.post(
        "/devices/connect",
        json={"ip": "127.0.0.1", "brand": "roku", "name": "Roku TV"},
        headers=auth_headers,
    )
    res = client.post(
        "/remote/launch-app", json={"app": "netflix"}, headers=auth_headers
    )
    assert res.status_code == 503
    assert res.json()["success"] is False


def test_launch_app_404_when_disconnected(client, auth_headers, stub_adapters):
    res = client.post(
        "/remote/launch-app", json={"app": "netflix"}, headers=auth_headers
    )
    assert res.status_code == 404


def test_pair_with_pair_capable_adapter(
    client, auth_headers, pair_stub_adapters
):
    device_id = _connect(client, auth_headers).json()["device_id"]
    res = client.post(
        "/devices/pair",
        json={"device_id": device_id, "pin": "1234"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["connected"] is True
    # Pairing builds a fresh adapter instance (see launch test above).
    assert pair_stub_adapters[-1].pair_calls == ["1234"]


def test_pair_without_pair_support_is_honest_422(
    client, auth_headers, stub_adapters
):
    # The adapter interface has no pair(): Samsung/LG pair via the on-TV
    # prompt during connect, so this must explain that, not fake success.
    device_id = _connect(client, auth_headers).json()["device_id"]
    res = client.post(
        "/devices/pair", json={"device_id": device_id}, headers=auth_headers
    )
    assert res.status_code == 422
    assert "not supported" in res.json()["error"]


def test_pair_unknown_device_404(client, auth_headers, stub_adapters):
    res = client.post(
        "/devices/pair", json={"device_id": "nope"}, headers=auth_headers
    )
    assert res.status_code == 404


def test_disconnect_clears_session_keeps_saved(
    client, auth_headers, stub_adapters
):
    device_id = _connect(client, auth_headers).json()["device_id"]
    res = client.request(
        "DELETE",
        "/devices/disconnect",
        json={"device_id": device_id},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["disconnected"] is True
    status = client.get(
        "/devices/connection-status", headers=auth_headers
    ).json()
    assert status["connected"] is False
    # Saved device is kept.
    assert len(client.get("/devices", headers=auth_headers).json()["data"]) == 1
    # And remote commands now 404.
    assert (
        client.post("/remote/up", json={}, headers=auth_headers).status_code
        == 404
    )


def test_disconnect_when_nothing_connected(client, auth_headers, stub_adapters):
    res = client.request(
        "DELETE", "/devices/disconnect", json={}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["disconnected"] is False


def test_connection_status_disconnected_shape(client, auth_headers):
    body = client.get(
        "/devices/connection-status", headers=auth_headers
    ).json()
    assert body["success"] is True
    assert body["connected"] is False
