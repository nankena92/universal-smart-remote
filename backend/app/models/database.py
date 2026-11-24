"""SQLite storage for saved/paired devices and the active session.

Standard-library ``sqlite3`` only. The DB file lives at
``backend/smart_remote.db`` by default (gitignored via ``backend/*.db``) and
can be overridden with the ``SMART_REMOTE_DB`` env var (used by tests).
One connected device at a time: the ``session`` table holds a single row.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    brand TEXT NOT NULL DEFAULT 'unknown',
    model TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    port INTEGER NOT NULL DEFAULT 0,
    mac TEXT NOT NULL DEFAULT '',
    paired INTEGER NOT NULL DEFAULT 0,
    pairing_token TEXT NOT NULL DEFAULT '',
    last_connected TEXT
);
CREATE TABLE IF NOT EXISTS session (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    device_id TEXT
);
"""


def get_db_path() -> Path:
    override = os.environ.get("SMART_REMOTE_DB")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "smart_remote.db"


def _connect() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def init_db() -> None:
    with _connect():
        pass


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["paired"] = bool(d.get("paired", 0))
    d["port"] = int(d.get("port") or 0)
    return d


def upsert_device(device: dict) -> dict:
    """Insert or replace a device record; returns the stored dict."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO devices
                (id, name, brand, model, ip, port, mac, paired,
                 pairing_token, last_connected)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, brand=excluded.brand,
                model=excluded.model, ip=excluded.ip, port=excluded.port,
                mac=excluded.mac, paired=excluded.paired,
                pairing_token=excluded.pairing_token,
                last_connected=excluded.last_connected
            """,
            (
                device["id"],
                device.get("name", ""),
                device.get("brand", "unknown"),
                device.get("model", ""),
                device.get("ip", ""),
                int(device.get("port") or 0),
                device.get("mac", ""),
                1 if device.get("paired") else 0,
                device.get("pairing_token", ""),
                device.get("last_connected"),
            ),
        )
        conn.commit()
    return get_device(device["id"])  # type: ignore[return-value]


def list_devices() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY name").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_device(device_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_device_by_ip(ip: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE ip = ? ORDER BY last_connected DESC "
            "LIMIT 1",
            (ip,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def set_paired(device_id: str, paired: bool, pairing_token: str | None = None) -> None:
    with _connect() as conn:
        if pairing_token is None:
            conn.execute(
                "UPDATE devices SET paired = ? WHERE id = ?",
                (1 if paired else 0, device_id),
            )
        else:
            conn.execute(
                "UPDATE devices SET paired = ?, pairing_token = ? WHERE id = ?",
                (1 if paired else 0, pairing_token, device_id),
            )
        conn.commit()


def touch_last_connected(device_id: str, timestamp: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE devices SET last_connected = ? WHERE id = ?",
            (timestamp, device_id),
        )
        conn.commit()


def set_active(device_id: str | None) -> None:
    with _connect() as conn:
        if device_id is None:
            conn.execute("DELETE FROM session WHERE id = 1")
        else:
            conn.execute(
                "INSERT INTO session (id, device_id) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET device_id = excluded.device_id",
                (device_id,),
            )
        conn.commit()


def get_active() -> dict | None:
    """The currently connected device record, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT d.* FROM session s JOIN devices d ON d.id = s.device_id "
            "WHERE s.id = 1"
        ).fetchone()
    return _row_to_dict(row) if row else None


def clear_all() -> None:
    """Delete all devices and the session (test helper)."""
    with _connect() as conn:
        conn.execute("DELETE FROM devices")
        conn.execute("DELETE FROM session")
        conn.commit()
