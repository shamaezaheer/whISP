"""
Cryptographic utilities for whISP.

Provides:
  - AES-256-GCM field encryption / decryption (using ENCRYPTION_KEY from settings)
  - bcrypt password hashing and verification
  - Secure RADIUS secret generation
"""
import base64
import hashlib
import os
import secrets
import string

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from passlib.context import CryptContext

from app.config import get_settings

# ---------------------------------------------------------------------------
# bcrypt context
# ---------------------------------------------------------------------------
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a bcrypt-hashed representation of *password*.

    bcrypt silently truncates at 72 bytes in older versions and raises
    ValueError in bcrypt >= 4.0.  Truncate here so callers never need
    to think about it.
    """
    return _pwd_context.hash(password[:72])


def verify_password(password: str, hashed: str) -> bool:
    """Return True if *password* matches *hashed*."""
    return _pwd_context.verify(password, hashed)


# ---------------------------------------------------------------------------
# AES-256-GCM field encryption
# ---------------------------------------------------------------------------

def _derive_key(raw_key: str) -> bytes:
    """
    Derive a 32-byte AES key from the configured ENCRYPTION_KEY string
    using SHA-256.
    """
    return hashlib.sha256(raw_key.encode()).digest()


def encrypt_field(value: str) -> str:
    """
    Encrypt *value* with AES-256-GCM.

    Returns a URL-safe base64-encoded string: ``<12-byte nonce><ciphertext+tag>``.
    """
    settings = get_settings()
    key = _derive_key(settings.ENCRYPTION_KEY)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
    ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_field(encrypted: str) -> str:
    """
    Decrypt a value produced by :func:`encrypt_field`.

    Raises ``ValueError`` if the ciphertext is invalid or tampered.
    """
    settings = get_settings()
    key = _derive_key(settings.ENCRYPTION_KEY)
    aesgcm = AESGCM(key)
    try:
        payload = base64.urlsafe_b64decode(encrypted.encode("ascii"))
        nonce = payload[:12]
        ciphertext = payload[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Decryption failed: {exc}") from exc


# ---------------------------------------------------------------------------
# RADIUS secret generator
# ---------------------------------------------------------------------------
_SECRET_ALPHABET = string.ascii_letters + string.digits


def generate_radius_secret(length: int = 16) -> str:
    """
    Generate a cryptographically-secure alphanumeric RADIUS shared secret.

    Default length is 16 characters.
    """
    return "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(length))
