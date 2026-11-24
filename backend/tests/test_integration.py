"""Phase 11 integration tests — end-to-end journeys against the real
FastAPI app (TestClient, real routes/services/DB) with mocked adapters
and a mock TV. No real TV is involved: the stub adapters stand in for
the TV, and the MockAdapter test below uses the real mock adapter.

What these tests DO prove:
- the full HTTP journey (discover -> connect -> keys -> launch-app ->
  disconnect) works through the real routes, auth, same-Wi-Fi
  validation, DB persistence and error mapping;
- auth rejection, same-subnet rejection (exact 403 message), 404 when
  disconnected, and the pairing flow behave as CONTRACTS.md requires.

What they do NOT prove (see documentation/testing.md): that any real TV
accepts these commands. That still needs a real TV and a real phone.
"""

from __future__ import annotations

from app.network.validation import SAME_WIFI_ERROR

# The mock TV used for the whole journey: loopback, Roku brand (so the
# streaming-app table resolves real Roku channel ids), stub adapter.
MOCK_TV = {"ip": "127.0.0.1", "brand": "roku", "name": "Living Room Roku"}

# Roku channel ids from backend/app/adapters/apps.py (verified ids).
ROKU_APP_IDS = {
    "netflix": "12",
    "prime": "13",
    "youtube": "837",
    "disney": "291097",
}


def _connect(client, headers, payload=None):
    return client.post(
        "/devices/connect", json=payload or MOCK_TV, headers=headers
    )


def _status(client, headers):
    return client.get("/devices/connection-status", headers=headers).json()


# ---------------------------------------------------------------------------
# Full journey
# ---------------------------------------------------------------------------

def test_full_journey_discover_connect_keys_launch_disconnect(
    client, auth_headers, stub_adapters, monkeypatch
):
    """discover -> connect -> keys -> launch all 4 apps -> disconnect.

    Discovery runs the real SSDP/mDNS sweep on the sandbox LAN (no TVs
    here, so the list is empty — the point is the endpoint works end to
    end and returns the contract shape).
    """
    from app.routes.devices import discovery as discovery_mod

    # Discover: stub the sweep so the journey does not wait ~4 s on the
    # multicast socket in CI, but still exercises the real route. The
    # un-stubbed endpoint is covered by test_discover_endpoint_live below.
    canned = [
        {
            "id": "discovered-127.0.0.1",
            "name": "Living Room Roku",
            "brand": "roku",
            "model": "Roku TV",
            "ip": "127.0.0.1",
            "port": 8060,
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
    discovered = body["data"][0]
    assert discovered["brand"] == "roku"
    assert discovered["ip"] == "127.0.0.1"

    # Connect to the discovered TV.
    res = _connect(client, auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["connected"] is True
    assert body["brand"] == "roku"
    assert body["ip"] == "127.0.0.1"
    device_id = body["device_id"]

    # The TV is now saved and active.
    assert _status(client, auth_headers)["connected"] is True
    saved = client.get("/devices", headers=auth_headers).json()["data"]
    assert len(saved) == 1
    assert saved[0]["id"] == device_id
    assert saved[0]["paired"] is True

    # Navigation + volume + power keys, in remote order.
    for key in ("up", "down", "ok", "volume-up", "volume-down", "power"):
        res = client.post(f"/remote/{key}", json={}, headers=auth_headers)
        assert res.status_code == 200, key
        assert res.json()["success"] is True
        assert res.json()["key"] == key
    # The last command built a fresh stub instance; it saw the power key.
    assert stub_adapters[-1].keys[-1].value == "power"

    # Launch every streaming app; each resolves to the real Roku id.
    for app_name, app_id in ROKU_APP_IDS.items():
        res = client.post(
            "/remote/launch-app",
            json={"app": app_name},
            headers=auth_headers,
        )
        assert res.status_code == 200, app_name
        assert res.json()["success"] is True
        assert res.json()["app"] == app_name
        assert stub_adapters[-1].launched == [app_id]

    # Disconnect: session cleared, device kept saved.
    res = client.request("DELETE", "/devices/disconnect", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["disconnected"] is True
    assert _status(client, auth_headers)["connected"] is False
    saved = client.get("/devices", headers=auth_headers).json()["data"]
    assert len(saved) == 1  # kept saved after disconnect
    assert saved[0]["id"] == device_id

    # After disconnect, commands are 404 — never a fake success.
    res = client.post("/remote/up", json={}, headers=auth_headers)
    assert res.status_code == 404
    assert res.json()["success"] is False


def test_discover_endpoint_live(client, auth_headers):
    """The real discover endpoint (SSDP/mDNS sweep) returns a list.

    No TV is on the sandbox LAN, so the list is empty; the assertion is
    that the endpoint runs the real sweep and honours the contract shape
    (``{success, data: [...]}``) instead of erroring.
    """
    res = client.get("/devices/discover", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


def test_full_journey_with_real_mock_adapter(client, auth_headers, real_adapters):
    """Same journey through the REAL MockAdapter (MOCK_TV=true).

    The mock brand has no streaming-app ids, so launch-app is honestly
    422 here — that is the contract (no id is ever guessed). Keys and
    disconnect still go through the real adapter.
    """
    res = client.post(
        "/devices/connect",
        json={"ip": "127.0.0.1", "brand": "mock", "name": "Mock TV"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["connected"] is True

    for key in ("up", "ok", "volume-up", "power"):
        res = client.post(f"/remote/{key}", json={}, headers=auth_headers)
        assert res.status_code == 200, key
        assert res.json()["success"] is True

    res = client.post(
        "/remote/launch-app", json={"app": "netflix"}, headers=auth_headers
    )
    assert res.status_code == 422
    assert "not supported/unknown for mock" in res.json()["error"]

    res = client.request("DELETE", "/devices/disconnect", headers=auth_headers)
    assert res.status_code == 200
    assert _status(client, auth_headers)["connected"] is False


# ---------------------------------------------------------------------------
# Auth rejection
# ---------------------------------------------------------------------------

def test_journey_rejects_missing_and_wrong_api_key(client, stub_adapters):
    for headers in (None, {"X-API-Key": "wrong-key"}):
        res = client.post("/devices/connect", json=MOCK_TV, headers=headers)
        assert res.status_code == 401
        assert res.json()["success"] is False
        res = client.post("/remote/up", json={}, headers=headers)
        assert res.status_code == 401
        res = client.get("/network/status", headers=headers)
        assert res.status_code == 401
    # /health stays open without a key (liveness probe for the app).
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Same-Wi-Fi rejection (CONTRACTS.md §4) — connect-time AND command-time
# ---------------------------------------------------------------------------

def test_same_subnet_rejection_on_connect_exact_message(
    client, auth_headers, stub_adapters
):
    res = client.post(
        "/devices/connect",
        json={"ip": "8.8.8.8", "brand": "roku", "name": "Far Away TV"},
        headers=auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["success"] is False
    assert res.json()["error"] == SAME_WIFI_ERROR


def test_same_subnet_revalidation_before_every_command(
    client, auth_headers, stub_adapters
):
    """A TV that moves off the LAN after connecting is refused per command.

    Simulates the TV leaving the network by changing the saved device's
    IP to a public address after a successful connect, then sending a
    key: the command service must revalidate and return the exact 403.
    """
    from app.models import database as db

    device_id = _connect(client, auth_headers).json()["device_id"]
    # Key works while the TV is on the LAN.
    assert client.post("/remote/up", json={}, headers=auth_headers).status_code == 200

    # TV "moves" off the LAN (saved IP changed underneath the session).
    row = db.get_device(device_id)
    row["ip"] = "203.0.113.10"
    db.upsert_device(row)

    res = client.post("/remote/up", json={}, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["error"] == SAME_WIFI_ERROR
    res = client.post(
        "/remote/launch-app", json={"app": "netflix"}, headers=auth_headers
    )
    assert res.status_code == 403
    assert res.json()["error"] == SAME_WIFI_ERROR


# ---------------------------------------------------------------------------
# 404 when disconnected
# ---------------------------------------------------------------------------

def test_404_when_disconnected_for_keys_and_launch(
    client, auth_headers, stub_adapters
):
    for key in ("up", "down", "ok", "volume-up", "power"):
        res = client.post(f"/remote/{key}", json={}, headers=auth_headers)
        assert res.status_code == 404, key
        assert res.json()["success"] is False
        assert "No TV is connected" in res.json()["error"]
    res = client.post(
        "/remote/launch-app", json={"app": "netflix"}, headers=auth_headers
    )
    assert res.status_code == 404
    assert res.json()["success"] is False


def test_404_after_disconnect_then_reconnect_works(
    client, auth_headers, stub_adapters
):
    device_id = _connect(client, auth_headers).json()["device_id"]
    client.request("DELETE", "/devices/disconnect", headers=auth_headers)
    assert client.post("/remote/up", json={}, headers=auth_headers).status_code == 404
    # Reconnect by saved device id and the remote works again.
    res = client.post(
        "/devices/connect",
        json={"device_id": device_id},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert client.post("/remote/up", json={}, headers=auth_headers).status_code == 200


# ---------------------------------------------------------------------------
# Pairing-required flow
# ---------------------------------------------------------------------------

def test_pairing_flow_with_pin(client, auth_headers, pair_stub_adapters):
    """Connect, then complete PIN pairing; the adapter sees the PIN."""
    device_id = _connect(client, auth_headers).json()["device_id"]
    res = client.post(
        "/devices/pair",
        json={"device_id": device_id, "pin": "1234"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["connected"] is True
    assert pair_stub_adapters[-1].pair_calls == ["1234"]
    # The device stays paired/saved and active after pairing.
    assert _status(client, auth_headers)["connected"] is True
    assert client.post("/remote/up", json={}, headers=auth_headers).status_code == 200


def test_pairing_flow_without_pin_and_without_pair_support(
    client, auth_headers, pair_stub_adapters
):
    """Pairing with no PIN still completes for a pair-capable adapter."""
    device_id = _connect(client, auth_headers).json()["device_id"]
    res = client.post(
        "/devices/pair", json={"device_id": device_id}, headers=auth_headers
    )
    assert res.status_code == 200
    assert pair_stub_adapters[-1].pair_calls == [None]


def test_pairing_honest_422_when_adapter_has_no_pair(
    client, auth_headers, stub_adapters
):
    """Adapters without pair() (e.g. Samsung/LG, which pair on the TV
    during connect) must explain that — never fake a pairing success."""
    device_id = _connect(client, auth_headers).json()["device_id"]
    res = client.post(
        "/devices/pair",
        json={"device_id": device_id, "pin": "1234"},
        headers=auth_headers,
    )
    assert res.status_code == 422
    assert res.json()["success"] is False
    assert "not supported" in res.json()["error"]


# ---------------------------------------------------------------------------
# Unsupported-brand launch (honest error, never a guessed app id)
# ---------------------------------------------------------------------------

def test_launch_app_unsupported_brand_in_journey(
    client, auth_headers, stub_adapters
):
    """Sony has no documented app id for any streaming app (apps.py:
    None), so launching Netflix on a Sony TV is an honest 422 — and the
    TV stays connected for keys afterwards."""
    res = client.post(
        "/devices/connect",
        json={"ip": "127.0.0.1", "brand": "sony", "name": "Sony TV"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    for app_name in ("netflix", "prime", "youtube", "disney"):
        res = client.post(
            "/remote/launch-app",
            json={"app": app_name},
            headers=auth_headers,
        )
        assert res.status_code == 422, app_name
        assert "not supported/unknown for sony" in res.json()["error"]
    # Keys still work on the same TV after the refused launches.
    assert client.post("/remote/up", json={}, headers=auth_headers).status_code == 200
    # And an unknown app name is a 422 at the request-validation layer.
    res = client.post(
        "/remote/launch-app", json={"app": "hulu"}, headers=auth_headers
    )
    assert res.status_code == 422
    assert res.json()["success"] is False


def test_network_status_in_journey(client, auth_headers, stub_adapters):
    """Network status is reachable mid-journey and reports the LAN."""
    _connect(client, auth_headers)
    res = client.get("/network/status", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["validation"] in ("verified", "failed")
    assert isinstance(body["backend_ip"], str)
    assert isinstance(body["subnet"], str)
