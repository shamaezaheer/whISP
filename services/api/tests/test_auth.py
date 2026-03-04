"""Tests for JWT auth service."""
import time

import pytest
from fastapi import HTTPException

from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.services.crypto import hash_password, verify_password


# ------------------------------------------------------------------
# Token creation and decoding
# ------------------------------------------------------------------

def test_create_access_token_contains_sub():
    token = create_access_token({"sub": "user-123", "type": "admin"})
    assert isinstance(token, str)
    assert len(token) > 20


def test_decode_access_token_roundtrip():
    payload = {"sub": "user-abc", "type": "franchisee", "franchisee_id": "fran-001"}
    token = create_access_token(payload)
    decoded = decode_token(token)
    assert decoded["sub"] == "user-abc"
    assert decoded["type"] == "franchisee"
    assert decoded["franchisee_id"] == "fran-001"


def test_decode_invalid_token_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        decode_token("this.is.not.a.valid.jwt")
    assert exc_info.value.status_code == 401


def test_decode_tampered_token_raises_401():
    token = create_access_token({"sub": "user-123", "type": "admin"})
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(HTTPException) as exc_info:
        decode_token(tampered)
    assert exc_info.value.status_code == 401


def test_refresh_token_has_token_type_claim():
    token = create_refresh_token({"sub": "user-123", "type": "subscriber"})
    decoded = decode_token(token)
    assert decoded.get("token_type") == "refresh"


# ------------------------------------------------------------------
# Password hashing
# ------------------------------------------------------------------

def test_hash_password_is_not_plaintext():
    pw = "MySecretP@ssw0rd"
    hashed = hash_password(pw)
    assert hashed != pw
    assert len(hashed) > 20


def test_verify_password_correct():
    pw = "WhISP#2025!"
    hashed = hash_password(pw)
    assert verify_password(pw, hashed) is True


def test_verify_password_wrong():
    pw = "WhISP#2025!"
    hashed = hash_password(pw)
    assert verify_password("wrongpassword", hashed) is False


def test_hash_is_deterministically_different():
    """bcrypt salts must make each hash unique."""
    pw = "samepassword"
    h1 = hash_password(pw)
    h2 = hash_password(pw)
    assert h1 != h2
