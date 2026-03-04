"""
RADIUS CoA/Disconnect packet implementation (RFC 5176).
Supports MikroTik vendor-specific attributes (vendor ID 14988).
"""
import asyncio
import hashlib
import os
import socket
import struct
import time
from typing import Optional
import structlog

log = structlog.get_logger(__name__)

# RADIUS packet codes
DISCONNECT_REQUEST = 40
DISCONNECT_ACK = 41
DISCONNECT_NAK = 42
COA_REQUEST = 43
COA_ACK = 44
COA_NAK = 45

# Standard RADIUS attributes
ATTR_USER_NAME = 1
ATTR_NAS_IP_ADDRESS = 4
ATTR_FRAMED_IP_ADDRESS = 8
ATTR_SESSION_TIMEOUT = 27
ATTR_CALLED_STATION_ID = 30
ATTR_CALLING_STATION_ID = 31
ATTR_ACCT_SESSION_ID = 44
ATTR_EVENT_TIMESTAMP = 55
ATTR_VENDOR_SPECIFIC = 26

# MikroTik VSA
MIKROTIK_VENDOR_ID = 14988
MIKROTIK_RATE_LIMIT = 8  # Mikrotik-Rate-Limit attribute type

def _encode_string(value: str) -> bytes:
    return value.encode("utf-8")

def _encode_ipv4(ip: str) -> bytes:
    return socket.inet_aton(ip)

def _encode_integer(value: int) -> bytes:
    return struct.pack("!I", value)

def _encode_tlv(attr_type: int, value: bytes) -> bytes:
    length = 2 + len(value)
    return struct.pack("!BB", attr_type, length) + value

def _encode_vendor_specific(vendor_id: int, vendor_type: int, value: bytes) -> bytes:
    vsa_inner = struct.pack("!BB", vendor_type, 2 + len(value)) + value
    vsa_payload = struct.pack("!I", vendor_id) + vsa_inner
    return _encode_tlv(ATTR_VENDOR_SPECIFIC, vsa_payload)

def _calc_authenticator(code: int, identifier: int, length: int, secret: str, attrs: bytes) -> bytes:
    request_auth = b"\x00" * 16
    header = struct.pack("!BBH", code, identifier, length) + request_auth + attrs
    return hashlib.md5(header + secret.encode()).digest()

def _encode_packet(code: int, identifier: int, secret: str, attributes: bytes) -> bytes:
    length = 20 + len(attributes)
    authenticator = _calc_authenticator(code, identifier, length, secret, attributes)
    return struct.pack("!BBH", code, identifier, length) + authenticator + attributes

async def _send_udp_packet(host: str, port: int, packet: bytes, timeout: float = 2.0) -> Optional[bytes]:
    """Send UDP packet and wait for response. Returns response bytes or None on timeout."""
    loop = asyncio.get_event_loop()

    def _send_recv():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (host, port))
            response, _ = sock.recvfrom(4096)
            return response
        except socket.timeout:
            return None
        finally:
            sock.close()

    return await loop.run_in_executor(None, _send_recv)

async def send_disconnect(
    nas_ip: str,
    nas_secret: str,
    username: str,
    session_id: Optional[str] = None,
    framed_ip: Optional[str] = None,
    coa_port: int = 3799,
    max_retries: int = 3,
) -> dict:
    """Send Disconnect-Request to NAS. Returns {success, code, latency_ms}."""
    attrs = b""
    attrs += _encode_tlv(ATTR_USER_NAME, _encode_string(username))
    if session_id:
        attrs += _encode_tlv(ATTR_ACCT_SESSION_ID, _encode_string(session_id))
    if framed_ip:
        try:
            attrs += _encode_tlv(ATTR_FRAMED_IP_ADDRESS, _encode_ipv4(framed_ip))
        except Exception:
            pass
    attrs += _encode_tlv(ATTR_EVENT_TIMESTAMP, _encode_integer(int(time.time())))

    identifier = os.urandom(1)[0]
    packet = _encode_packet(DISCONNECT_REQUEST, identifier, nas_secret, attrs)

    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            response = await _send_udp_packet(nas_ip, coa_port, packet)
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            if response is None:
                log.warning("coa_disconnect_timeout", nas_ip=nas_ip, attempt=attempt + 1)
                continue
            resp_code = response[0]
            success = resp_code == DISCONNECT_ACK
            log.info("coa_disconnect_sent", nas_ip=nas_ip, username=username, success=success, code=resp_code, latency_ms=latency_ms)
            return {"success": success, "code": resp_code, "latency_ms": latency_ms, "attempts": attempt + 1}
        except Exception as e:
            log.error("coa_disconnect_error", nas_ip=nas_ip, error=str(e), attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

    return {"success": False, "code": None, "latency_ms": None, "attempts": max_retries}

async def send_rate_limit(
    nas_ip: str,
    nas_secret: str,
    username: str,
    download_kbps: int,
    upload_kbps: int,
    session_id: Optional[str] = None,
    coa_port: int = 3799,
    max_retries: int = 3,
) -> dict:
    """Send CoA-Request to change rate limit on active session."""
    rate_limit = f"{download_kbps}k/{upload_kbps}k"

    attrs = b""
    attrs += _encode_tlv(ATTR_USER_NAME, _encode_string(username))
    if session_id:
        attrs += _encode_tlv(ATTR_ACCT_SESSION_ID, _encode_string(session_id))
    attrs += _encode_vendor_specific(
        MIKROTIK_VENDOR_ID, MIKROTIK_RATE_LIMIT, _encode_string(rate_limit)
    )
    attrs += _encode_tlv(ATTR_EVENT_TIMESTAMP, _encode_integer(int(time.time())))

    identifier = os.urandom(1)[0]
    packet = _encode_packet(COA_REQUEST, identifier, nas_secret, attrs)

    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            response = await _send_udp_packet(nas_ip, coa_port, packet)
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            if response is None:
                log.warning("coa_rate_limit_timeout", nas_ip=nas_ip, attempt=attempt + 1)
                continue
            resp_code = response[0]
            success = resp_code == COA_ACK
            log.info("coa_rate_limit_sent", nas_ip=nas_ip, username=username, rate_limit=rate_limit, success=success, latency_ms=latency_ms)
            return {"success": success, "code": resp_code, "latency_ms": latency_ms, "rate_limit": rate_limit}
        except Exception as e:
            log.error("coa_rate_limit_error", nas_ip=nas_ip, error=str(e), attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

    return {"success": False, "code": None, "latency_ms": None, "rate_limit": rate_limit}
