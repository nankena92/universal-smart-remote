"""Same-Wi-Fi validation tests (CONTRACTS.md §4)."""

from __future__ import annotations

from app.network.validation import (
    SAME_WIFI_ERROR,
    get_local_networks,
    get_primary_ip,
    is_same_subnet,
    network_status,
)


def test_local_networks_detected():
    networks = get_local_networks()
    assert networks, "expected at least one non-loopback local network"


def test_primary_ip_is_same_subnet():
    primary = get_primary_ip()
    assert primary is not None
    assert is_same_subnet(primary) is True


def test_same_subnet_boundaries():
    # Sandbox host sits on 198.19.0.2/30; .1 is in-subnet, .5 is not.
    primary = get_primary_ip()
    assert primary is not None
    assert primary.startswith("198.19.0.")
    assert is_same_subnet("198.19.0.1") is True
    assert is_same_subnet("198.19.0.5") is False


def test_public_ip_rejected():
    assert is_same_subnet("8.8.8.8") is False
    assert is_same_subnet("203.0.113.10") is False
    assert is_same_subnet("1.1.1.1") is False


def test_other_private_subnet_rejected():
    assert is_same_subnet("10.255.255.1") is False
    assert is_same_subnet("192.168.99.99") is False


def test_invalid_ip_rejected():
    assert is_same_subnet("not-an-ip") is False
    assert is_same_subnet("") is False


def test_loopback_only_with_mock_tv(monkeypatch):
    monkeypatch.setenv("MOCK_TV", "true")
    assert is_same_subnet("127.0.0.1") is True
    monkeypatch.delenv("MOCK_TV", raising=False)
    assert is_same_subnet("127.0.0.1") is False


def test_network_status_shape(client, auth_headers):
    body = client.get("/network/status", headers=auth_headers).json()
    assert body["success"] is True
    assert isinstance(body["wifi_connected"], bool)
    assert isinstance(body["backend_ip"], str)
    assert isinstance(body["subnet"], str)
    assert body["validation"] in ("verified", "failed")
    assert isinstance(body["message"], str)
    assert "ssid" in body and "phone_ip" in body


def test_network_status_unit_shape():
    status = network_status()
    assert status["validation"] in ("verified", "failed")
    assert status["backend_ip"] == (get_primary_ip() or "unknown")


def test_connect_public_ip_403_exact_message(client, auth_headers):
    res = client.post(
        "/devices/connect",
        json={"ip": "8.8.8.8", "brand": "roku", "name": "Far Away TV"},
        headers=auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["success"] is False
    assert res.json()["error"] == SAME_WIFI_ERROR


def test_connect_other_subnet_403(client, auth_headers):
    res = client.post(
        "/devices/connect",
        json={"ip": "10.255.255.1", "brand": "roku", "name": "Other LAN TV"},
        headers=auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["error"] == SAME_WIFI_ERROR


def test_remote_revalidates_subnet_every_command(
    client, auth_headers, stub_adapters, monkeypatch
):
    # Connect while the mock (loopback) is allowed, then revoke MOCK_TV:
    # the next command must 403 with the exact message.
    res = client.post(
        "/devices/connect",
        json={"ip": "127.0.0.1", "brand": "mock", "name": "Mock TV"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    monkeypatch.delenv("MOCK_TV", raising=False)
    res = client.post("/remote/up", json={}, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["error"] == SAME_WIFI_ERROR
