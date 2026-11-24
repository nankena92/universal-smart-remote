"""API-key auth (CONTRACTS.md §2).

LAN-only service: the key is a shared secret between the phone app and this
backend on the same Wi-Fi network. It is NOT a substitute for keeping the
backend off the internet — never port-forward port 8000 (see app.py).
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

ENV_VAR = "SMART_REMOTE_API_KEY"

_generated_key: str | None = None


def get_api_key() -> str:
    """Return the configured API key, generating an ephemeral one if needed.

    The key is stable when ``SMART_REMOTE_API_KEY`` is set. Otherwise a
    random key is generated once per process and printed/logged (per
    CONTRACTS.md §2) so the user can enter it in the phone app's Settings.
    A restart generates a new key — set the env var for a stable key.
    """
    env_key = os.environ.get(ENV_VAR)
    if env_key:
        return env_key
    global _generated_key
    if _generated_key is None:
        _generated_key = secrets.token_urlsafe(32)
        logger.warning(
            "SMART_REMOTE_API_KEY is not set — generated an ephemeral API "
            "key for this run only. Set SMART_REMOTE_API_KEY to keep a "
            "stable key."
        )
        print(
            "[smart-remote] Generated API key (this run only; set "
            f"SMART_REMOTE_API_KEY to keep a stable key): {_generated_key}",
            flush=True,
        )
    return _generated_key


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency: reject requests without the correct X-API-Key."""
    expected = get_api_key()
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")
    return x_api_key
