"""
RADIUS CoA (Change of Authorization) engine.

Implements RFC 3576 CoA and Disconnect-Message packets over UDP.
Supports MikroTik VSAs (Vendor-ID 14988).

Packet format:
  Code (1 byte) | Identifier (1 byte) | Length (2 bytes) | Authenticator (16 bytes) | Attributes

Authenticator for CoA/DM requests:
  MD5( Code + ID + Length + 16*0x00 + Attributes + Secret )
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import socket
import struct
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# RADIUS packet codes
# ---------------------------------------------------------------------------
ACCESS_REQUEST = 1
ACCESS_ACCEPT = 2
ACCESS_REJECT = 3
ACCOUNTING_REQUEST = 4
ACCOUNTING_RESPONSE = 5
COA_REQUEST = 43
COA_ACK = 44
COA_NAK = 45
DISCONNECT_REQUEST = 40
DISCONNECT_ACK = 41
DISCONNECT_NAK = 42

# ---------------------------------------------------------------------------
# Standard RADIUS attribute types
# ---------------------------------------------------------------------------
ATTR_USER_NAME = 1
ATTR_FRAMED_IP_ADDRESS = 8
ATTR_ACCT_SESSION_ID = 44
ATTR_NAS_IP_ADDRESS = 4
ATTR_NAS_PORT = 5
ATTR_VENDOR_SPECIFIC = 26

# MikroTik VSA (Vendor 14988)
VENDOR_MIKROTIK = 14988
MT_RATE_LIMIT = 8  # Mikrotik-Rate-Limit


# ---------------------------------------------------------------------------
# Attribute encoding helpers
# ---------------------------------------------------------------------------

def _encode_attr(attr_type: int, value: bytes) -> bytes:
    """Encode a single TLV RADIUS attribute."""
    length = 2 + len(value)
    return struct.pack("!BB", attr_type, length) + value


def _encode_string_attr(attr_type: int, value: str) -> bytes:
    return _encode_attr(attr_type, value.encode("utf-8"))


def _encode_ip_attr(attr_type: int, ip: str) -> bytes:
    return _encode_attr(attr_type, socket.inet_aton(ip))


def _encode_mikrotik_vsa(attr_id: int, value: str) -> bytes:
    """Encode a MikroTik VSA inside a Vendor-Specific attribute."""
    inner_value = value.encode("utf-8")
    # VSA inner TLV: Vendor-Type (1 byte) + Vendor-Length (1 byte) + Value
    inner = struct.pack("!BB", attr_id, 2 + len(inner_value)) + inner_value
    # VSA outer: Vendor-ID (4 bytes big-endian) + inner
    vendor_id_bytes = struct.pack("!I", VENDOR_MIKROTIK)
    return _encode_attr(ATTR_VENDOR_SPECIFIC, vendor_id_bytes + inner)


# ---------------------------------------------------------------------------
# Packet construction
# ---------------------------------------------------------------------------

def encode_radius_packet(
    code: int,
    identifier: int,
    secret: str,
    attributes: bytes,
) -> bytes:
    """
    Build a RADIUS CoA/DM packet with a proper MD5 authenticator.

    Authenticator = MD5(Code + ID + Length + 16*0x00 + Attributes + Secret)
    """
    length = 20 + len(attributes)  # 20 = header size
    # First build with zero authenticator
    header = struct.pack("!BBH16s", code, identifier, length, b"\x00" * 16)
    # Compute authenticator
    authenticator = hashlib.md5(
        header + attributes + secret.encode("utf-8")
    ).digest()
    # Rebuild with real authenticator
    return struct.pack("!BBH", code, identifier, length) + authenticator + attributes


def decode_radius_response(data: bytes) -> dict:
    """
    Decode a RADIUS response packet.

    Returns ``{"code": int, "identifier": int, "attributes": bytes}``.
    """
    if len(data) < 20:
        raise ValueError(f"RADIUS response too short: {len(data)} bytes")
    code, identifier, length = struct.unpack("!BBH", data[:4])
    authenticator = data[4:20]
    attributes_raw = data[20:length]
    return {
        "code": code,
        "identifier": identifier,
        "length": length,
        "authenticator": authenticator,
        "attributes_raw": attributes_raw,
    }


# ---------------------------------------------------------------------------
# UDP send / receive
# ---------------------------------------------------------------------------

async def send_coa(
    nas_ip: str,
    nas_secret: str,
    attributes: bytes,
    code: int = COA_REQUEST,
    port: int = 3799,
    timeout: float = 5.0,
) -> bool:
    """
    Send a RADIUS CoA (or DM) packet to *nas_ip*:*port* and wait for ACK.

    Returns True on ACK, False on NAK or timeout.
    """
    identifier = secrets.randbelow(256)
    packet = encode_radius_packet(code, identifier, nas_secret, attributes)
    loop = asyncio.get_running_loop()

    log.debug("coa_send_attempt", nas_ip=nas_ip, port=port, code=code, packet_len=len(packet))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setblocking(False)
        # Do NOT call sock.settimeout() — it overrides setblocking(False) and
        # puts the socket back into blocking mode, breaking asyncio I/O.
        # Timeout is handled by asyncio.wait_for() below.

        try:
            await loop.sock_sendto(sock, packet, (nas_ip, port))
            log.debug("coa_packet_sent", nas_ip=nas_ip, port=port)
        except OSError as exc:
            log.error("coa_sendto_error", nas_ip=nas_ip, port=port, errno=exc.errno, error=str(exc))
            raise RuntimeError(f"Cannot send CoA UDP to {nas_ip}:{port} — {exc}") from exc

        try:
            response_data = await asyncio.wait_for(
                loop.sock_recv(sock, 4096), timeout=timeout
            )
        except asyncio.TimeoutError:
            log.warning("coa_timeout", nas_ip=nas_ip, code=code, port=port, timeout=timeout)
            return False
        except OSError as exc:
            log.error("coa_recv_error", nas_ip=nas_ip, port=port, errno=exc.errno, error=str(exc))
            raise RuntimeError(f"CoA recv error from {nas_ip}:{port} — {exc}") from exc

        response = decode_radius_response(response_data)
        ack_code = COA_ACK if code == COA_REQUEST else DISCONNECT_ACK
        success = response["code"] == ack_code
        log.info(
            "coa_response",
            nas_ip=nas_ip,
            sent_code=code,
            recv_code=response["code"],
            success=success,
        )
        return success

    finally:
        sock.close()


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

async def send_disconnect(
    nas_ip: str,
    nas_secret: str,
    username: str,
    session_id: Optional[str] = None,
    port: int = 3799,
    timeout: float = 5.0,
) -> bool:
    """
    Send a RADIUS Disconnect-Request to terminate a user's session.

    If *session_id* is provided it is included as Acct-Session-Id for
    more precise matching (required on MikroTik when multiple sessions
    exist for the same user).
    """
    attrs = _encode_string_attr(ATTR_USER_NAME, username)
    if session_id:
        attrs += _encode_string_attr(ATTR_ACCT_SESSION_ID, session_id)

    log.info("coa_disconnect_send", nas_ip=nas_ip, username=username)
    return await send_coa(
        nas_ip, nas_secret, attrs, code=DISCONNECT_REQUEST, port=port, timeout=timeout
    )


async def send_rate_limit(
    nas_ip: str,
    nas_secret: str,
    username: str,
    download_kbps: int,
    upload_kbps: int,
    port: int = 3799,
    timeout: float = 5.0,
) -> bool:
    """
    Send a CoA packet to update the rate-limit for an active session.

    Uses Mikrotik-Rate-Limit VSA.
    """
    from app.services.radius import format_rate_limit

    rate = format_rate_limit(download_kbps, upload_kbps)
    attrs = _encode_string_attr(ATTR_USER_NAME, username)
    attrs += _encode_mikrotik_vsa(MT_RATE_LIMIT, rate)

    log.info("coa_rate_limit_send", nas_ip=nas_ip, username=username, rate=rate)
    return await send_coa(
        nas_ip, nas_secret, attrs, code=COA_REQUEST, port=port, timeout=timeout
    )


async def send_coa_reconnect(
    nas_ip: str,
    nas_secret: str,
    username: str,
    session_id: Optional[str] = None,
    port: int = 3799,
    timeout: float = 5.0,
) -> bool:
    """
    Disconnect the user so they immediately reconnect and pick up new RADIUS
    attributes (e.g. after a plan change or payment).
    """
    return await send_disconnect(
        nas_ip, nas_secret, username, session_id=session_id, port=port, timeout=timeout
    )
