"""Universal Smart TV Remote — FastAPI backend (Phase 4 + Phase 5 backend).

LAN-ONLY SERVER — READ THIS BEFORE RUNNING IT
==============================================
This server binds ``0.0.0.0:8000`` so the phone app can reach it over the
local Wi-Fi network. It must NEVER be port-forwarded, exposed to the
internet, or run on a public interface: there is no TLS and the only auth
is a shared ``X-API-Key`` header. It controls TVs on the local network
only (CONTRACTS.md §4: same-subnet validation before every command, no
public IPs, no cloud control).

Run (from ``backend/``):
    SMART_REMOTE_API_KEY=<key> uvicorn app:app --host 0.0.0.0 --port 8000
or simply ``python app.py``. If ``SMART_REMOTE_API_KEY`` is not set, an
ephemeral key is generated and printed/logged once at startup — enter it
in the phone app's Settings. Set ``MOCK_TV=true`` only for testing: it
enables the mock adapter (loopback only).

Note on layout: ``backend/app.py`` (this file) and ``backend/app/`` (the
package) share a name; Python resolves ``app`` to the package, whose
``__init__.py`` loads this file once via importlib and re-exports the
FastAPI instance. See ``backend/app/__init__.py``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.models import database as db
from app.routes import devices, network, remote
from app.security.auth import get_api_key

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    get_api_key()  # generates + prints the key if SMART_REMOTE_API_KEY unset
    logger.warning(
        "Smart Remote backend starting — LAN ONLY. Do NOT port-forward "
        "port 8000 or expose this server to the internet."
    )
    yield


app = FastAPI(
    title="Universal Smart Remote",
    version="1.0.0",
    description=(
        "LAN-only backend for the Universal Smart TV Remote app. "
        "Binds 0.0.0.0:8000 for the local Wi-Fi network only — never "
        "port-forward or expose to the internet. All endpoints except "
        "/health require the X-API-Key header."
    ),
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(_request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": str(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    _request: Request, exc: RequestValidationError
):
    messages = "; ".join(
        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
        for err in exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content={"success": False, "error": messages or "Invalid request."},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": f"Internal server error: {exc}"},
    )


@app.get("/health")
async def health():
    """Unauthenticated liveness probe (lets the app find the backend)."""
    return {"success": True, "status": "ok"}


app.include_router(devices.router)
app.include_router(remote.router)
app.include_router(network.router)


if __name__ == "__main__":
    # LAN-only: binds all local interfaces so the phone can reach it over
    # Wi-Fi. Never port-forward this port.
    uvicorn.run(app, host="0.0.0.0", port=8000)
