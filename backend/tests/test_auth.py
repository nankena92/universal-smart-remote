"""Auth tests: X-API-Key required everywhere except /health."""

from __future__ import annotations


def test_no_key_401_on_protected_endpoints(client):
    for method, path in [
        ("GET", "/devices"),
        ("GET", "/devices/discover"),
        ("GET", "/devices/connection-status"),
        ("GET", "/network/status"),
        ("POST", "/devices/connect"),
        ("POST", "/devices/pair"),
        ("POST", "/remote/up"),
        ("POST", "/remote/launch-app"),
    ]:
        res = client.request(method, path, json={})
        assert res.status_code == 401, f"{method} {path}"
        body = res.json()
        assert body["success"] is False
        assert "API key" in body["error"]


def test_no_key_401_on_disconnect(client):
    res = client.request("DELETE", "/devices/disconnect", json={})
    assert res.status_code == 401
    assert res.json()["success"] is False


def test_wrong_key_401(client):
    res = client.get("/devices", headers={"X-API-Key": "wrong-key"})
    assert res.status_code == 401
    assert res.json()["success"] is False


def test_correct_key_200(client, auth_headers):
    res = client.get("/devices", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_health_open_without_key(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
