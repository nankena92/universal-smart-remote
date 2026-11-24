"""Android TV / Google TV adapter — Android TV Remote protocol v2.

======================================================================
NEEDS ON-DEVICE VERIFICATION (CONTRACTS.md §7)
======================================================================
No real Android TV / Google TV set was available while writing this.
The protocol below follows the documented reverse-engineered
implementation used by Home Assistant (``tronikos/androidtvremote2``,
Apache-2.0) and the AOSP pairing protocol (``external/
google-tv-pairing-protocol``, ``polo.proto`` / ``remotemessage.proto``).
Every message layout, field number and key code was checked against
those sources while implementing, but the pairing handshake, the TLS
certificate handling and the remote session have NOT been exercised
against a real TV. Do not treat a successful unit test as proof that a
real TV will accept this client; verify on a device first.
======================================================================

Protocol (real, documented — no invented APIs):

- Remote session: mutual-TLS protobuf over TCP port 6466. Framing is
  ``[varint: message length][protobuf: RemoteMessage]`` (NOT a 4-byte
  length prefix). Both sides present self-signed RSA-2048 certificates.
- Pairing: mutual-TLS protobuf over TCP port 6467, Google's Polo
  protocol (``polo.proto``). Six steps:
  ``pairing_request`` -> ``pairing_request_ack`` -> ``options`` ->
  ``configuration`` -> ``configuration_ack`` -> TV shows a 6-character
  hex code -> ``secret`` -> ``secret_ack``.
  The secret is ``SHA256(client_modulus || client_exponent ||
  server_modulus || server_exponent || code[2:])`` where ``code`` is the
  6 hex characters shown on the TV; the first two characters are a
  checksum (``secret[0] == int(code[:2], 16)``), so a misread code is
  caught locally before anything is sent.
- Remote handshake: the TV speaks first, sending ``remote_configure``
  (field 1) with a feature bitmask (``code1``). The client replies with
  its own ``remote_configure`` requesting features 615 (``PING=1 |
  KEY=2 | IME=4 | POWER=32 | VOLUME=64 | APP_LINK=512``), then sends
  ``remote_set_active`` (field 2, ``active=1``). Only then are key
  presses accepted. The TV answers pings (``remote_ping_request``,
  field 8) and the client must reply with ``remote_ping_response``
  (field 9, echoing ``val1``) to keep the session alive; the TV also
  pushes state such as ``remote_set_volume_level`` (field 50).
- Keys: ``RemoteMessage.remote_key_inject`` (field 10) with
  ``key_code`` (field 1, Android ``KeyEvent`` code) and ``direction``
  (field 2, ``SHORT=3``). The TV sends no acknowledgement for a key
  press; success means the frame was written to the live session.
- App launch: via ADB when available (same ``monkey -p <package>``
  launch as the Fire TV adapter); otherwise ``supports("launch_app")``
  is False and :meth:`launch_app` returns an honest error. The remote
  protocol also has a ``remote_app_link_launch_request`` message
  (field 90) carrying a URL, but per CONTRACTS.md §5 launch is ADB
  only, so it is not used here.

Pairing flow in this adapter (the base interface has no ``pair``
method, so this is an extra method the backend's ``/devices/pair``
route can call):

- :meth:`connect` on an unpaired TV runs the pairing handshake up to
  ``configuration_ack`` — the point where the TV displays its code —
  keeps that pairing TLS session open, and returns
  ``success=False`` with ``details={"pairing_required": True}`` and an
  error telling the user to enter the code.
- :meth:`pair` takes the 6-character code, sends the secret, and on
  ``secret_ack`` with status 200 stores the client certificate/key
  (PEM) as JSON in ``device.pairing_token`` — the TV trusts that
  certificate on port 6466 from then on — and connects the remote
  session. (The backend must persist the device record for this to
  survive a restart.)
- :meth:`connect` on a paired TV goes straight to port 6466 with the
  stored certificate.

Dependencies: the ``cryptography`` package is required for certificate
generation and for reading the TV's certificate public key. It is NOT
yet in ``backend/requirements.txt`` (owned by the backend-core phase);
until it is added, :meth:`connect` fails with an honest error saying so.

Unverified details (see the banner above): whether the TV's options
reply arrives before ``configuration_ack`` on all models (handled both
ways here), the exact ``service_name``/``client_name`` the TV expects
(``"androidtvremote2"`` / the device name, per the reference library),
and whether ``getpeercert(binary_form=True)`` returns the peer cert
under ``CERT_NONE`` on this Python version.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import ssl
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import fire_tv as fire_tv_mod
from .base import CommandResult, DeviceInfo, RemoteKey, TvAdapter

REMOTE_PORT = 6466
PAIRING_PORT = 6467
CONNECT_TIMEOUT = 10.0
HANDSHAKE_TIMEOUT = 15.0
SEND_TIMEOUT = 10.0
MAX_FRAME_BYTES = 4 * 1024 * 1024

# RemoteMessage feature bits (RemoteConfigure.code1).
FEATURE_PING = 1
FEATURE_KEY = 2
FEATURE_IME = 4
FEATURE_POWER = 32
FEATURE_VOLUME = 64
FEATURE_APP_LINK = 512
REQUESTED_FEATURES = (
    FEATURE_PING | FEATURE_KEY | FEATURE_IME
    | FEATURE_POWER | FEATURE_VOLUME | FEATURE_APP_LINK
)  # 615

# RemoteMessage field numbers (remotemessage.proto).
F_CONFIGURE = 1
F_SET_ACTIVE = 2
F_ERROR = 3
F_PING_REQUEST = 8
F_PING_RESPONSE = 9
F_KEY_INJECT = 10
F_START = 40
F_SET_VOLUME_LEVEL = 50
F_APP_LINK_LAUNCH = 90

# Polo OuterMessage field numbers (polo.proto) and statuses.
F_PAIRING_REQUEST = 10
F_PAIRING_REQUEST_ACK = 11
F_OPTIONS = 20
F_CONFIGURATION = 30
F_CONFIGURATION_ACK = 31
F_SECRET = 40
F_SECRET_ACK = 41
STATUS_OK = 200
STATUS_ERROR = 400
STATUS_BAD_CONFIGURATION = 401
STATUS_BAD_SECRET = 402

# Polo Options.Encoding types / RoleType.
ENC_HEXADECIMAL = 3
ROLE_INPUT = 1

SERVICE_NAME = "androidtvremote2"  # established convention, see polo.proto
CLIENT_NAME = "Smart Remote"

# Android KeyEvent codes (android.view.KeyEvent; same enum as
# remotemessage.proto RemoteKeyCode).
KEY_MAP = {
    RemoteKey.UP: 19,  # KEYCODE_DPAD_UP
    RemoteKey.DOWN: 20,  # KEYCODE_DPAD_DOWN
    RemoteKey.LEFT: 21,  # KEYCODE_DPAD_LEFT
    RemoteKey.RIGHT: 22,  # KEYCODE_DPAD_RIGHT
    RemoteKey.OK: 23,  # KEYCODE_DPAD_CENTER
    RemoteKey.BACK: 4,  # KEYCODE_BACK
    RemoteKey.HOME: 3,  # KEYCODE_HOME
    RemoteKey.MENU: 82,  # KEYCODE_MENU
    RemoteKey.POWER: 26,  # KEYCODE_POWER
    RemoteKey.VOLUME_UP: 24,  # KEYCODE_VOLUME_UP
    RemoteKey.VOLUME_DOWN: 25,  # KEYCODE_VOLUME_DOWN
    RemoteKey.MUTE: 164,  # KEYCODE_VOLUME_MUTE
    RemoteKey.CHANNEL_UP: 166,  # KEYCODE_CHANNEL_UP
    RemoteKey.CHANNEL_DOWN: 167,  # KEYCODE_CHANNEL_DOWN
    RemoteKey.PLAY: 126,  # KEYCODE_MEDIA_PLAY
    RemoteKey.PAUSE: 127,  # KEYCODE_MEDIA_PAUSE
    RemoteKey.STOP: 86,  # KEYCODE_MEDIA_STOP
    RemoteKey.REWIND: 89,  # KEYCODE_MEDIA_REWIND
    RemoteKey.FAST_FORWARD: 90,  # KEYCODE_MEDIA_FAST_FORWARD
}

_CODE_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


# --------------------------------------------------------------------------
# Minimal protobuf encode/decode (no `protobuf` dependency; only the
# messages this adapter needs). Wire types: 0 = varint, 2 = length-delim.
# --------------------------------------------------------------------------

def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            return bytes(out)


def _tag(field_no: int, wire_type: int) -> bytes:
    return _varint((field_no << 3) | wire_type)


def _field_varint(field_no: int, value: int) -> bytes:
    return _tag(field_no, 0) + _varint(value)


def _field_bytes(field_no: int, payload: bytes) -> bytes:
    return _tag(field_no, 2) + _varint(len(payload)) + payload


def _field_string(field_no: int, value: str) -> bytes:
    return _field_bytes(field_no, value.encode("utf-8"))


def _frame(payload: bytes) -> bytes:
    """Varint length prefix + protobuf payload (the on-the-wire framing)."""
    return _varint(len(payload)) + payload


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(data) and shift < 70:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos
        shift += 7
    raise ValueError("Truncated or over-long varint in protobuf message.")


def _parse_fields(data: bytes) -> dict[int, list[tuple[int, object]]]:
    """Parse a protobuf message into {field_no: [(wire_type, value)]}.

    Varint values are ints; length-delimited values are bytes; 32/64-bit
    fixed values are ints. Unknown fields are kept, not dropped.
    """
    fields: dict[int, list[tuple[int, object]]] = {}
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        field_no, wire_type = tag >> 3, tag & 0x07
        if wire_type == 0:
            value, pos = _read_varint(data, pos)
        elif wire_type == 2:
            length, pos = _read_varint(data, pos)
            value = data[pos:pos + length]
            pos += length
            if len(value) != length:
                raise ValueError("Truncated length-delimited protobuf field.")
        elif wire_type == 1:
            value = int.from_bytes(data[pos:pos + 8], "little")
            pos += 8
        elif wire_type == 5:
            value = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire_type}.")
        fields.setdefault(field_no, []).append((wire_type, value))
    return fields


def _varint_field(fields: dict, field_no: int, default=None):
    for _wire, value in fields.get(field_no, []):
        if isinstance(value, int):
            return value
    return default


def _bytes_field(fields: dict, field_no: int):
    for _wire, value in fields.get(field_no, []):
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
    return None


def _outer_status(fields: dict) -> Optional[int]:
    return _varint_field(fields, 2)


# --------------------------------------------------------------------------
# Pairing secret (polo protocol).
# --------------------------------------------------------------------------

def _rsa_number_bytes(number: int) -> bytes:
    """Hex-encode an RSA number the way the reference implementation does:
    ``bytes.fromhex(format(n, "x"))`` with even-length padding, which
    silently drops leading zero bytes. Reproducing this exactly matters:
    the "correct" encoding would produce a different digest.
    """
    text = format(number, "x")
    if len(text) % 2:
        text = "0" + text
    return bytes.fromhex(text)


def compute_pairing_secret(client_n: int, client_e: int,
                           server_n: int, server_e: int,
                           code: str) -> bytes:
    """``SHA256(client_mod || client_exp || server_mod || server_exp ||
    code[2:])`` — ``code`` is the 6 hex characters shown on the TV."""
    payload = (
        _rsa_number_bytes(client_n)
        + _rsa_number_bytes(client_e)
        + _rsa_number_bytes(server_n)
        + _rsa_number_bytes(server_e)
        + bytes.fromhex(code[2:])
    )
    return hashlib.sha256(payload).digest()


def pairing_code_checksum_ok(secret: bytes, code: str) -> bool:
    """First two hex characters of the code are a checksum byte."""
    return len(secret) > 0 and secret[0] == int(code[:2], 16)


# --------------------------------------------------------------------------
# Message builders (each returns the unframed protobuf payload).
# --------------------------------------------------------------------------

def _outer_message(*parts: bytes, status: int = STATUS_OK) -> bytes:
    return (
        _field_varint(1, 1)  # protocol_version
        + _field_varint(2, status)
        + b"".join(parts)
    )


def _pairing_request_message(client_name: str) -> bytes:
    req = _field_string(1, SERVICE_NAME) + _field_string(2, client_name)
    return _outer_message(_field_bytes(F_PAIRING_REQUEST, req))


def _hex_encoding() -> bytes:
    """Options.Encoding {type: HEXADECIMAL, symbol_length: 6}."""
    return _field_varint(1, ENC_HEXADECIMAL) + _field_varint(2, 6)


def _options_message() -> bytes:
    # The client types the code (input role) and advertises hex/6 both
    # ways, as the reference library does.
    enc = _hex_encoding()
    options = (
        _field_bytes(1, enc)  # input_encodings
        + _field_bytes(2, enc)  # output_encodings
        + _field_varint(3, ROLE_INPUT)  # preferred_role
    )
    return _outer_message(_field_bytes(F_OPTIONS, options))


def _configuration_message(encoding: Optional[bytes] = None) -> bytes:
    config = (
        _field_bytes(1, encoding or _hex_encoding())
        + _field_varint(2, ROLE_INPUT)  # client_role
    )
    return _outer_message(_field_bytes(F_CONFIGURATION, config))


def _secret_message(secret: bytes) -> bytes:
    return _outer_message(
        _field_bytes(F_SECRET, _field_bytes(1, secret))
    )


def _remote_configure_message(features: int) -> bytes:
    device_info = (
        _field_string(1, "Smart Remote")  # model
        + _field_string(2, "Universal Smart Remote")  # vendor
        + _field_string(5, "com.universalsmartremote.app")  # package_name
        + _field_string(6, "1.0.0")  # app_version
    )
    configure = (
        _field_varint(1, features)  # code1: feature bitmask
        + _field_bytes(2, device_info)
    )
    return _field_bytes(F_CONFIGURE, configure)


def _remote_set_active_message() -> bytes:
    return _field_bytes(F_SET_ACTIVE, _field_varint(1, 1))


def _remote_ping_response_message(val1: int) -> bytes:
    return _field_bytes(F_PING_RESPONSE, _field_varint(1, val1))


def _remote_key_inject_message(key_code: int) -> bytes:
    inject = _field_varint(1, key_code) + _field_varint(2, 3)  # SHORT
    return _field_bytes(F_KEY_INJECT, inject)


# --------------------------------------------------------------------------
# Client identity (self-signed RSA certificate, mutual TLS).
# --------------------------------------------------------------------------

def _create_identity(client_name: str) -> tuple[str, str]:
    """Generate a self-signed RSA-2048 client certificate + key (PEM).

    The certificate needs ``basicConstraints CA:TRUE`` and a SAN, the
    same as the reference library's. A unique CN is used because the TV
    dedupes paired certificates by subject. Requires ``cryptography``.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:
        raise RuntimeError(
            "The 'cryptography' package is not installed; Android TV "
            "pairing needs it (`pip install cryptography`)."
        ) from exc
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(
            NameOID.COMMON_NAME,
            f"{client_name}-{secrets.token_hex(4)}",
        )
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("universal-smart-remote")]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    return cert_pem, key_pem


def _load_identity(token: str) -> Optional[tuple[str, str]]:
    """Parse a stored ``{"cert": ..., "key": ...}`` pairing token.

    Returns None when the token is missing, corrupt, or not a matching
    cert/key pair, so the caller generates a fresh identity and pairs.
    """
    if not token:
        return None
    try:
        data = json.loads(token)
        cert_pem, key_pem = str(data["cert"]), str(data["key"])
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
        serialization.load_pem_private_key(key_pem.encode("ascii"), None)
        return cert_pem, key_pem
    except Exception:
        return None


def _cert_rsa_numbers(cert_pem: str) -> tuple[int, int]:
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
    numbers = cert.public_key().public_numbers()
    return numbers.n, numbers.e


def _peer_rsa_numbers(peer_der: bytes) -> tuple[int, int]:
    from cryptography import x509
    cert = x509.load_der_x509_certificate(peer_der)
    public_key = cert.public_key()
    if not hasattr(public_key, "public_numbers"):
        raise ValueError("TV certificate is not an RSA certificate.")
    numbers = public_key.public_numbers()
    return numbers.n, numbers.e


class AndroidTvAdapter(TvAdapter):
    """Android TV / Google TV adapter over the Remote protocol v2.

    See the module docstring: NEEDS ON-DEVICE VERIFICATION.
    """

    brand = "androidtv"

    def __init__(self, device: DeviceInfo):
        super().__init__(device)
        self._reader = None
        self._writer = None
        self._reader_task: Optional[asyncio.Task] = None
        self._write_lock = asyncio.Lock()
        self._pairing_reader = None
        self._pairing_writer = None
        self._pairing_numbers: Optional[tuple[int, int, int, int]] = None
        self._identity_cert: Optional[str] = None
        self._identity_key: Optional[str] = None
        self._server_features: Optional[int] = None
        self._volume_level: Optional[int] = None
        self._volume_muted: Optional[bool] = None
        self._started = False
        self._last_error: Optional[str] = None

    # -- TLS plumbing -----------------------------------------------------

    async def _open_tls(self, host: str, port: int,
                        cert_pem: str, key_pem: str):
        """Open a mutual-TLS connection. Returns ``(reader, writer,
        peer_cert_der)``. Separated out so tests can substitute fake
        streams; production uses ``asyncio.open_connection`` with an
        ``SSLContext`` carrying our self-signed client certificate. The
        TV's certificate is self-signed, so it is not chain-verified —
        trust is established by the pairing secret, not the cert chain.
        """
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, "cert.pem")
            key_path = os.path.join(tmpdir, "key.pem")
            with open(cert_path, "w", encoding="ascii") as fh:
                fh.write(cert_pem)
            with open(key_path, "w", encoding="ascii") as fh:
                fh.write(key_pem)
            ctx.load_cert_chain(cert_path, key_path)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=ctx),
                timeout=CONNECT_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            raise ConnectionError(
                f"Timed out connecting to {host}:{port}."
            ) from exc
        ssl_obj = writer.get_extra_info("ssl_object")
        peer_der = (
            ssl_obj.getpeercert(binary_form=True)
            if ssl_obj is not None else None
        )
        if not peer_der:
            writer.close()
            raise ConnectionError(
                "The TV did not present a TLS certificate; cannot verify "
                "the pairing. (The TV must present its self-signed "
                "certificate during the mutual-TLS handshake.)"
            )
        return reader, writer, peer_der

    async def _read_exactly(self, reader, count: int,
                            timeout: Optional[float]):
        if timeout is None:
            return await reader.readexactly(count)
        return await asyncio.wait_for(
            reader.readexactly(count), timeout=timeout
        )

    async def _read_frame(self, reader,
                          timeout: Optional[float]) -> bytes:
        """Read one varint-framed protobuf message."""
        length = 0
        shift = 0
        for _ in range(10):  # a varint is at most 10 bytes
            chunk = await self._read_exactly(reader, 1, timeout)
            if not chunk:
                raise asyncio.IncompleteReadError(partial=b"", expected=1)
            byte = chunk[0]
            length |= (byte & 0x7F) << shift
            if byte < 0x80:
                break
            shift += 7
        else:
            raise ValueError("Message length varint is too long.")
        if length > MAX_FRAME_BYTES:
            raise ValueError(
                f"Message length {length} exceeds the {MAX_FRAME_BYTES} "
                "byte cap; refusing to allocate it."
            )
        return await self._read_exactly(reader, length, timeout)

    async def _send_frame(self, writer, payload: bytes) -> None:
        writer.write(_frame(payload))
        await writer.drain()

    async def _read_outer(self, reader, timeout: float) -> dict:
        """Read one Polo OuterMessage and parse it. Raises on EOF/timeout
        or on a non-200 protocol status."""
        payload = await self._read_frame(reader, timeout)
        fields = _parse_fields(payload)
        status = _outer_status(fields)
        if status is not None and status != STATUS_OK:
            detail = {
                STATUS_ERROR: "general protocol error",
                STATUS_BAD_CONFIGURATION: "bad configuration",
                STATUS_BAD_SECRET: "bad secret",
            }.get(status, f"status {status}")
            raise ConnectionError(
                f"TV reported a pairing protocol error: {detail}."
            )
        return fields

    # -- identity ---------------------------------------------------------

    def _load_or_create_identity(self) -> tuple[str, str, bool]:
        """Return ``(cert_pem, key_pem, was_stored)``."""
        stored = _load_identity(self.device.pairing_token)
        if stored is not None:
            return stored[0], stored[1], True
        cert_pem, key_pem = _create_identity(
            self.device.name or CLIENT_NAME
        )
        return cert_pem, key_pem, False

    # -- pairing ----------------------------------------------------------

    async def _close_pairing(self) -> None:
        self._pairing_numbers = None
        if self._pairing_writer is not None:
            try:
                self._pairing_writer.close()
                await asyncio.wait_for(
                    self._pairing_writer.wait_closed(), timeout=5
                )
            except Exception:
                pass
            self._pairing_writer = None
        self._pairing_reader = None

    async def _begin_pairing(self, cert_pem: str,
                             key_pem: str) -> CommandResult:
        """Run the Polo handshake on port 6467 up to configuration_ack.

        On success the TV is showing its 6-character code and the pairing
        TLS session is kept open for :meth:`pair`.
        """
        try:
            reader, writer, peer_der = await self._open_tls(
                self.device.ip, PAIRING_PORT, cert_pem, key_pem
            )
        except (ConnectionError, OSError, ssl.SSLError) as exc:
            return CommandResult(
                False,
                error=f"Could not reach Android TV at {self.device.ip}:"
                f"{PAIRING_PORT} for pairing ({exc}). Check the TV is on, "
                "on the same Wi-Fi, and the Android TV Remote Service is "
                "running.",
            )
        self._pairing_reader, self._pairing_writer = reader, writer
        try:
            server_n, server_e = _peer_rsa_numbers(peer_der)
            client_n, client_e = _cert_rsa_numbers(cert_pem)
        except Exception as exc:
            await self._close_pairing()
            return CommandResult(
                False,
                error=f"Could not read the TV's certificate for pairing "
                f"({exc}).",
            )
        self._pairing_numbers = (client_n, client_e, server_n, server_e)
        try:
            await self._send_frame(
                writer,
                _pairing_request_message(self.device.name or CLIENT_NAME),
            )
            ack = await self._read_outer(reader, HANDSHAKE_TIMEOUT)
            if F_PAIRING_REQUEST_ACK not in ack:
                raise ConnectionError(
                    "TV did not acknowledge the pairing request."
                )
            await self._send_frame(writer, _options_message())
            nxt = await self._read_outer(reader, HANDSHAKE_TIMEOUT)
            if F_OPTIONS in nxt:
                # The TV answered with its own options; pick its first
                # hexadecimal encoding (fall back to hex/6) and configure.
                encoding = _hex_encoding()
                options_bytes = _bytes_field(nxt, F_OPTIONS)
                if options_bytes:
                    for _wire, value in _parse_fields(
                            options_bytes).get(2, []):
                        if isinstance(value, (bytes, bytearray)):
                            enc_fields = _parse_fields(bytes(value))
                            if _varint_field(enc_fields, 1) == ENC_HEXADECIMAL:
                                encoding = bytes(value)
                                break
                await self._send_frame(
                    writer, _configuration_message(encoding)
                )
                nxt = await self._read_outer(reader, HANDSHAKE_TIMEOUT)
            if F_CONFIGURATION_ACK not in nxt:
                raise ConnectionError(
                    "TV did not acknowledge the pairing configuration."
                )
        except (ConnectionError, asyncio.TimeoutError,
                asyncio.IncompleteReadError, ValueError) as exc:
            await self._close_pairing()
            return CommandResult(
                False,
                error=f"Pairing handshake with Android TV at "
                f"{self.device.ip} failed: {exc}",
            )
        # The TV is now showing its 6-character pairing code.
        return CommandResult(
            False,
            message="A 6-character pairing code is now shown on the TV. "
            "Enter it to finish pairing.",
            error="Pairing required: enter the 6-character code shown on "
            "the TV to finish pairing this Android TV.",
            details={"pairing_required": True},
        )

    async def pair(self, code: str) -> CommandResult:
        """Finish pairing with the 6-character code shown on the TV.

        Sends the Polo secret, verifies ``secret_ack``, stores the client
        certificate in ``device.pairing_token`` and connects the remote
        session on port 6466.
        """
        code = (code or "").strip()
        if not _CODE_RE.match(code):
            return CommandResult(
                False,
                error="Pairing code must be exactly 6 hexadecimal "
                "characters, as shown on the TV.",
            )
        if (
            self._pairing_writer is None
            or self._pairing_reader is None
            or self._pairing_numbers is None
            or self._identity_cert is None
            or self._identity_key is None
        ):
            return CommandResult(
                False,
                error="No pairing session is in progress. Connect to the TV "
                "first so it shows a pairing code, then enter the code.",
            )
        client_n, client_e, server_n, server_e = self._pairing_numbers
        secret = compute_pairing_secret(
            client_n, client_e, server_n, server_e, code
        )
        if not pairing_code_checksum_ok(secret, code):
            return CommandResult(
                False,
                error="That code does not look right (its check digits do "
                "not match). Re-read the 6-character code shown on the TV "
                "and try again; nothing was sent to the TV.",
            )
        try:
            await self._send_frame(
                self._pairing_writer, _secret_message(secret)
            )
            ack = await self._read_outer(
                self._pairing_reader, HANDSHAKE_TIMEOUT
            )
            if F_SECRET_ACK not in ack:
                raise ConnectionError(
                    "TV did not acknowledge the pairing secret."
                )
        except (ConnectionError, asyncio.TimeoutError,
                asyncio.IncompleteReadError, ValueError) as exc:
            await self._close_pairing()
            return CommandResult(
                False,
                error=f"Pairing failed: {exc} The code may have expired; "
                "connect again to get a fresh code from the TV.",
            )
        # Pairing succeeded: persist the identity, then open the remote
        # session with it. (The caller must persist the device record.)
        self.device.pairing_token = json.dumps(
            {"cert": self._identity_cert, "key": self._identity_key}
        )
        self.device.paired = True
        await self._close_pairing()
        return await self.connect()

    # -- remote session ---------------------------------------------------

    async def _connect_remote(self, cert_pem: str,
                              key_pem: str) -> CommandResult:
        """Open the port 6466 remote session with a stored certificate."""
        try:
            reader, writer, _peer_der = await self._open_tls(
                self.device.ip, REMOTE_PORT, cert_pem, key_pem
            )
        except (ConnectionError, OSError, ssl.SSLError) as exc:
            return CommandResult(
                False,
                error=f"Could not open the remote session to Android TV at "
                f"{self.device.ip}:{REMOTE_PORT} ({exc}). If the TV was "
                "unpaired or reset, clear the stored pairing for this "
                "device and pair again.",
            )
        self._reader, self._writer = reader, writer
        try:
            first = await self._read_frame(reader, HANDSHAKE_TIMEOUT)
            fields = _parse_fields(first)
            if F_CONFIGURE not in fields:
                raise ConnectionError(
                    "TV did not send the expected remote_configure "
                    "handshake."
                )
            configure_bytes = _bytes_field(fields, F_CONFIGURE)
            configure = (
                _parse_fields(configure_bytes) if configure_bytes else {}
            )
            self._server_features = _varint_field(configure, 1)
            await self._send_frame(
                writer, _remote_configure_message(REQUESTED_FEATURES)
            )
            await self._send_frame(writer, _remote_set_active_message())
        except (ConnectionError, asyncio.TimeoutError,
                asyncio.IncompleteReadError, ValueError) as exc:
            await self.disconnect()
            return CommandResult(
                False,
                error=f"Android TV at {self.device.ip} accepted the TLS "
                f"connection but the remote handshake failed: {exc}",
            )
        self._reader_task = asyncio.create_task(self._reader_loop())
        self.connected = True
        self.device.paired = True
        return CommandResult(
            True,
            "Connected to Android TV.",
            details={
                "server_features": self._server_features,
                "requested_features": REQUESTED_FEATURES,
            },
        )

    async def _reader_loop(self) -> None:
        """Answer pings and track pushed state until the session drops."""
        try:
            while True:
                payload = await self._read_frame(self._reader, None)
                fields = _parse_fields(payload)
                if F_PING_REQUEST in fields:
                    ping_bytes = _bytes_field(fields, F_PING_REQUEST)
                    ping = (
                        _parse_fields(ping_bytes) if ping_bytes else {}
                    )
                    val1 = _varint_field(ping, 1, 0) or 0
                    async with self._write_lock:
                        await self._send_frame(
                            self._writer,
                            _remote_ping_response_message(val1),
                        )
                elif F_SET_VOLUME_LEVEL in fields:
                    vol_bytes = _bytes_field(fields, F_SET_VOLUME_LEVEL)
                    if vol_bytes:
                        volume = _parse_fields(vol_bytes)
                        level = _varint_field(volume, 7)
                        muted = _varint_field(volume, 8)
                        if level is not None:
                            self._volume_level = level
                        if muted is not None:
                            self._volume_muted = bool(muted)
                elif F_START in fields:
                    self._started = True
                elif F_ERROR in fields:
                    self._last_error = "TV reported a remote protocol error."
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass  # session dropped; connected flips False below
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # malformed frame: drop the session
            self._last_error = f"Remote session error: {exc}"
        finally:
            self.connected = False

    async def connect(self) -> CommandResult:
        if self.connected and self._writer is not None:
            return CommandResult(True, "Already connected to Android TV.")
        if not self.device.ip:
            return CommandResult(False, error="No IP address for Android TV.")
        try:
            cert_pem, key_pem, was_stored = self._load_or_create_identity()
        except RuntimeError as exc:
            return CommandResult(False, error=str(exc))
        self._identity_cert, self._identity_key = cert_pem, key_pem
        if was_stored:
            return await self._connect_remote(cert_pem, key_pem)
        return await self._begin_pairing(cert_pem, key_pem)

    async def disconnect(self) -> None:
        self.connected = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._writer is not None:
            try:
                self._writer.close()
                await asyncio.wait_for(
                    self._writer.wait_closed(), timeout=5
                )
            except Exception:
                pass
            self._writer = None
        self._reader = None
        await self._close_pairing()

    # -- commands ---------------------------------------------------------

    async def _ensure_connected(self) -> Optional[CommandResult]:
        """Return None when connected, else the failed connect() result."""
        if self.connected and self._writer is not None:
            return None
        result = await self.connect()
        return None if result.success else result

    async def send_key(self, key: RemoteKey) -> CommandResult:
        code = KEY_MAP.get(key)
        if code is None:
            return CommandResult(
                False, error=f"Android TV does not support key: {key.value}"
            )
        failed = await self._ensure_connected()
        if failed is not None:
            return failed
        try:
            async with self._write_lock:
                await asyncio.wait_for(
                    self._send_frame(
                        self._writer, _remote_key_inject_message(code)
                    ),
                    timeout=SEND_TIMEOUT,
                )
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            self.connected = False
            return CommandResult(
                False, error=f"Failed to send {key.value} to Android TV: {exc}"
            )
        return CommandResult(
            True,
            f"Sent {key.value} to Android TV. (The TV sends no "
            "acknowledgement for key presses; success means the key event "
            "was written to the live session.)",
            details={"key_code": code},
        )

    async def launch_app(self, app_id: str) -> CommandResult:
        # Here app_id is an Android package name (see apps.py). Launch is
        # via ADB only (CONTRACTS.md §5).
        if not app_id:
            return CommandResult(
                False,
                error="No Android TV package name given; refusing to guess one.",
            )
        if not fire_tv_mod.adb_available():
            return CommandResult(
                False,
                error="App launch on Android TV needs ADB (Android "
                "platform-tools) on the backend host, and it is not "
                "installed. Install adb on the machine running the backend "
                "and try again. No app was launched.",
            )
        ok, detail = await asyncio.to_thread(
            fire_tv_mod.adb_connect, self.device.ip
        )
        if not ok:
            return CommandResult(
                False,
                error=f"Could not reach Android TV at {self.device.ip} "
                f"over ADB ({detail}). On the TV, enable Developer Options "
                "-> USB debugging / ADB debugging and accept the "
                "authorization prompt, then try again.",
            )
        ok, detail = await asyncio.to_thread(
            fire_tv_mod.adb_launch_package, self.device.ip, app_id
        )
        if not ok:
            return CommandResult(
                False,
                error=f"Could not launch {app_id} on Android TV: {detail}",
            )
        return CommandResult(
            True,
            f"Launch requested for {app_id} on Android TV.",
            details={"app_id": app_id},
        )

    # -- capabilities / status --------------------------------------------

    def supports(self, feature: str) -> bool:
        if feature == "launch_app":
            # ADB only; False when adb is not installed on the host.
            return fire_tv_mod.adb_available()
        return feature in (
            "power",
            "volume",
            "mute",
            "channel",
            "media",
            "pairing",
        )

    async def get_status(self) -> dict:
        status = await super().get_status()
        status.update(
            {
                "paired": bool(self.device.pairing_token),
                "server_features": self._server_features,
                "requested_features": REQUESTED_FEATURES,
                "volume_level": self._volume_level,
                "volume_muted": self._volume_muted,
                "started": self._started,
                "last_error": self._last_error,
                # See the module docstring: verified against a real TV?
                "needs_on_device_verification": True,
            }
        )
        return status
