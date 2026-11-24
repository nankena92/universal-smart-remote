"""LAN discovery of TVs: SSDP M-SEARCH (stdlib socket) + mDNS (zeroconf).

SSDP is always available. mDNS runs only when the ``zeroconf`` package is
installed; if it is missing (or browsing fails), discovery degrades
gracefully to SSDP-only and logs the fact — never a hard failure.

Brand is best-effort from discovery headers / description documents;
``"unknown"`` when it cannot be determined (CONTRACTS.md §2).
"""

from __future__ import annotations

import logging
import socket
import time
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from app.models import database as db

logger = logging.getLogger(__name__)

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_MX = 3

_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ns=01"\r\n'
    "MX: 3\r\n"
    "ST: ssdp:all\r\n"
    "USER-AGENT: SmartRemote/1.0\r\n"
    "\r\n"
).encode("utf-8")

# mDNS service types worth browsing for TVs / cast targets.
_MDNS_TYPES = [
    "_googlecast._tcp.local.",
    "_airplay._tcp.local.",
    "_http._tcp.local.",
]

# (substring in server/manufacturer/model text, brand)
_BRAND_HINTS = [
    ("samsung", "samsung"),
    ("tizen", "samsung"),
    ("lg", "lg"),
    ("webos", "lg"),
    ("roku", "roku"),
    ("sony", "sony"),
    ("bravia", "sony"),
    ("tcl", "tcl"),
    ("fire tv", "firetv"),
    ("firetv", "firetv"),
    ("aft", "firetv"),  # Amazon Fire TV model prefix (AFT*)
    ("android tv", "androidtv"),
    ("googletv", "googletv"),
    ("google tv", "googletv"),
    ("androidtv", "androidtv"),
    ("philips", "unknown"),
]


def guess_brand(*texts: str) -> str:
    """Best-effort brand from discovery text; ``"unknown"`` if no match."""
    haystack = " ".join(t or "" for t in texts).lower()
    for needle, brand in _BRAND_HINTS:
        if needle in haystack:
            return brand
    return "unknown"


def _parse_ssdp_response(data: bytes) -> dict | None:
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        return None
    headers: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    location = headers.get("location", "")
    if not location:
        return None
    try:
        parsed = urlparse(location)
        ip = parsed.hostname or ""
        port = parsed.port or 0
    except ValueError:
        return None
    if not ip:
        return None
    return {
        "ip": ip,
        "port": port,
        "location": location,
        "server": headers.get("server", ""),
        "usn": headers.get("usn", ""),
        "st": headers.get("st", ""),
    }


def _fetch_description(location: str, timeout: float = 2.0) -> dict:
    """Fetch a UPnP device-description XML; best-effort, {} on any failure."""
    try:
        with urllib.request.urlopen(location, timeout=timeout) as resp:
            raw = resp.read(40960)
    except Exception as exc:  # noqa: BLE001 - any fetch failure is fine
        logger.debug("Could not fetch device description %s: %s", location, exc)
        return {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    info: dict[str, str] = {}
    for tag in ("friendlyName", "manufacturer", "modelName", "modelNumber"):
        el = root.find(f".//{{*}}{tag}")
        if el is not None and el.text:
            info[tag] = el.text.strip()
    return info


def _ssdp_discover(timeout: float = 3.0) -> list[dict]:
    """One SSDP M-SEARCH sweep. Returns raw per-response dicts."""
    responses: list[dict] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        sock.sendto(_MSEARCH, SSDP_ADDR)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                logger.debug("SSDP recv error: %s", exc)
                break
            parsed = _parse_ssdp_response(data)
            if parsed:
                responses.append(parsed)
    except OSError as exc:
        logger.warning("SSDP discovery failed: %s", exc)
    finally:
        sock.close()
    return responses


def _mdns_discover(timeout: float = 2.0) -> list[dict]:
    """Browse mDNS service types via zeroconf; [] if unavailable/failing."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        logger.info("zeroconf is not installed — mDNS discovery skipped (SSDP-only).")
        return []
    found: dict[str, dict] = {}

    class _Collector:
        def add_service(self, zc, service_type, name):  # noqa: ANN001, ANN202
            try:
                info = zc.get_service_info(service_type, name, timeout=2000)
            except Exception as exc:  # noqa: BLE001
                logger.debug("mDNS service info failed for %s: %s", name, exc)
                return
            if not info or not info.addresses:
                return
            ip = socket.inet_ntoa(info.addresses[0])
            props = {
                k.decode("utf-8", "ignore"): v.decode("utf-8", "ignore")
                for k, v in (info.properties or {}).items()
            }
            found[ip] = {
                "ip": ip,
                "port": info.port or 0,
                "server": props.get("md", props.get("model", "")),
                "name_hint": name,
                "properties": props,
            }

        def remove_service(self, zc, service_type, name):  # noqa: ANN001, ANN202
            pass

        def update_service(self, zc, service_type, name):  # noqa: ANN001, ANN202
            pass

    try:
        zc = Zeroconf()
        try:
            ServiceBrowser(zc, _MDNS_TYPES, handlers=[_Collector()])
            time.sleep(timeout)
        finally:
            zc.close()
    except Exception as exc:  # noqa: BLE001 - mDNS must never break discovery
        logger.warning("mDNS discovery failed (continuing SSDP-only): %s", exc)
        return []
    return list(found.values())


def discover_devices(timeout: float = 4.0) -> list[dict]:
    """Run SSDP (+ mDNS where available) and return discovered TVs.

    Each item: ``{id, name, brand, model, ip, port, mac, paired}`` per
    CONTRACTS.md §2 (plus ``source``). Deduped by IP; SSDP wins on conflicts.
    """
    by_ip: dict[str, dict] = {}

    for resp in _ssdp_discover(timeout=max(1.0, timeout - 1.0)):
        desc = _fetch_description(resp["location"])
        name = desc.get("friendlyName", "") or resp["usn"] or resp["ip"]
        brand = guess_brand(
            desc.get("manufacturer", ""),
            desc.get("modelName", ""),
            resp["server"],
            resp["st"],
        )
        by_ip[resp["ip"]] = {
            "id": f"discovered-{resp['ip']}",
            "name": name,
            "brand": brand,
            "model": desc.get("modelName", desc.get("modelNumber", "")),
            "ip": resp["ip"],
            "port": resp["port"],
            "mac": "",
            "source": "ssdp",
        }

    for entry in _mdns_discover(timeout=2.0):
        if entry["ip"] in by_ip:
            continue
        props = entry.get("properties", {})
        brand = guess_brand(
            entry.get("server", ""),
            props.get("fn", ""),
            props.get("md", ""),
            entry.get("name_hint", ""),
        )
        by_ip[entry["ip"]] = {
            "id": f"discovered-{entry['ip']}",
            "name": props.get("fn", entry.get("name_hint", entry["ip"])),
            "brand": brand,
            "model": props.get("md", entry.get("server", "")),
            "ip": entry["ip"],
            "port": entry["port"],
            "mac": "",
            "source": "bonjour",
        }

    devices = list(by_ip.values())
    for device in devices:
        saved = db.get_device_by_ip(device["ip"])
        device["paired"] = bool(saved and saved.get("paired"))
        if saved and saved.get("id"):
            device["id"] = saved["id"]
    return devices
