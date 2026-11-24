"""Same-Wi-Fi validation (CONTRACTS.md §4).

The backend only talks to TVs whose IP is in the same subnet as one of the
backend host's local interfaces (``ipaddress`` module). Anything else is
rejected with a 403 and the exact message in :data:`SAME_WIFI_ERROR`.
Revalidate before EVERY command — the command service calls
:func:`assert_same_subnet` on each call.

Never use public IPs; never implement cloud control.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
import subprocess

logger = logging.getLogger(__name__)

#: Exact message required by CONTRACTS.md §4 (also used by the mobile app).
SAME_WIFI_ERROR = (
    "Your TV and smartphone must be connected to the same local Wi-Fi network."
)


class SameWifiError(ValueError):
    """Raised when a TV IP is not on the same local subnet (maps to 403)."""


# ---------------------------------------------------------------------------
# Local interfaces
# ---------------------------------------------------------------------------

def _interfaces_from_ip_cmd() -> list[dict]:
    """Parse ``ip -o -f inet addr show`` (Linux). Returns [{ip, netmask}]."""
    try:
        out = subprocess.run(
            ["ip", "-o", "-f", "inet", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    found: list[dict] = []
    for line in out.stdout.splitlines():
        m = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
        if not m:
            continue
        try:
            network = ipaddress.IPv4Network(f"{m.group(1)}/{m.group(2)}", strict=False)
        except ValueError:
            continue
        found.append({"ip": m.group(1), "netmask": str(network.netmask)})
    return found


def _interfaces_from_socket() -> list[dict]:
    """Fallback when the ``ip`` command is unavailable (stdlib only).

    The primary outbound IP is found with a UDP ``connect()`` (no packet is
    sent); hostname addresses are added too. Netmask is unknown here, so
    /24 is assumed — a conservative, documented approximation.
    """
    ips: set[str] = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ips.add(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass
    try:
        for addr in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(addr)
    except OSError:
        pass
    return [{"ip": ip, "netmask": "255.255.255.0"} for ip in sorted(ips)]


def get_local_interfaces() -> list[dict]:
    """Local IPv4 interfaces as ``[{ip, netmask}]`` (loopback included)."""
    interfaces = _interfaces_from_ip_cmd() or _interfaces_from_socket()
    seen: set[str] = set()
    unique: list[dict] = []
    for iface in interfaces:
        key = f"{iface['ip']}/{iface['netmask']}"
        if key not in seen:
            seen.add(key)
            unique.append(iface)
    return unique


def get_local_networks() -> list[ipaddress.IPv4Network]:
    """Local subnets, excluding loopback."""
    networks: list[ipaddress.IPv4Network] = []
    for iface in get_local_interfaces():
        try:
            ip = ipaddress.IPv4Address(iface["ip"])
        except ValueError:
            continue
        if ip.is_loopback:
            continue
        try:
            networks.append(
                ipaddress.IPv4Network(
                    f"{iface['ip']}/{iface['netmask']}", strict=False
                )
            )
        except ValueError:
            continue
    return networks


def get_primary_ip() -> str | None:
    """Best guess at this host's LAN IP (first non-loopback interface)."""
    for iface in get_local_interfaces():
        try:
            if not ipaddress.IPv4Address(iface["ip"]).is_loopback:
                return iface["ip"]
        except ValueError:
            continue
    return None


def _mock_tv_allowed() -> bool:
    """Loopback targets are only allowed for the mock adapter (testing)."""
    return os.environ.get("MOCK_TV", "").lower() == "true"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def is_same_subnet(ip_str: str) -> bool:
    """True iff ``ip_str`` is on the same subnet as a local interface.

    Membership in a local subnet wins over any ``is_private`` classification
    (e.g. CGNAT / benchmarking ranges a host may legitimately sit on).
    Public IPs are never accepted; loopback is only accepted for the mock
    adapter (``MOCK_TV=true``).
    """
    try:
        ip = ipaddress.IPv4Address(ip_str)
    except ValueError:
        return False
    if ip.is_loopback:
        return _mock_tv_allowed()
    if any(ip in network for network in get_local_networks()):
        return True
    if not ip.is_private:
        return False
    return False


def assert_same_subnet(ip_str: str) -> None:
    """Raise :class:`SameWifiError` (403) unless ``ip_str`` is same-subnet."""
    if not is_same_subnet(ip_str):
        raise SameWifiError(SAME_WIFI_ERROR)


def get_ssid() -> str | None:
    """Best-effort current Wi-Fi SSID (Linux ``iwgetid``); None if unknown."""
    try:
        out = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    ssid = (out.stdout or "").strip()
    return ssid or None


def network_status() -> dict:
    """Payload for ``GET /network/status`` (CONTRACTS.md §2).

    ``ssid`` / ``phone_ip`` are best-effort: the backend cannot reliably
    know the phone's SSID or IP, so they are ``None`` when undeterminable
    rather than guessed.
    """
    primary_ip = get_primary_ip()
    networks = get_local_networks()
    wifi_connected = primary_ip is not None and bool(networks)
    return {
        "wifi_connected": wifi_connected,
        # The backend cannot see the phone's SSID/IP; None = undeterminable.
        "ssid": get_ssid(),
        "phone_ip": None,
        "backend_ip": primary_ip or "unknown",
        "subnet": str(networks[0]) if networks else "unknown",
        "validation": "verified" if wifi_connected else "failed",
        # Failed validation uses the exact required error string
        # (CONTRACTS.md §4) so the app can display it verbatim.
        "message": (
            "Backend is on the local network."
            if wifi_connected
            else SAME_WIFI_ERROR
        ),
    }
