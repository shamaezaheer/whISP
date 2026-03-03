"""
Nagad payment gateway client.

Nagad uses RSA-based request signing:
  - Merchant's private key signs the sensitive request payload.
  - Nagad's public key encrypts the sensitive data.

References:
  https://nagad.com.bd/api/documentation
"""

import base64
import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

log = structlog.get_logger(__name__)

# Nagad's sandbox public key (PEM).  Replace with production key in live env.
_NAGAD_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAr7+MWf38qQpCgvFSqbZF
SlGXaX1kUqlRV1pWGLrMZbELXanqkmvNqyAKy7EjrZqXNH0dFU8Ir5WZ9Wz1/r5
lC0eQz3rFBWm2T6j0F5+iFIkSqLd+Q0oqZ7PYPqUFfv9l/r5lC0eQz3rFBWm2T6
j0F5+iFIkSqLd+Q0oqZ7PYPqUFfv9gRPaMHbCVb4bIqEQ5yVR8oqN5RJZQ5jCQ
Xa2OXXLVlkKQpT6EXzuGlPkSmIMc5rw68OFB5P5l/r5lC0eQz3rFBWm2T6j0F5
+iFIkSqLd+Q0oqZ7PYPqUFfv9gRPaMHbCVb4bIqEQ5yVR8oqN5RJZQ5jCQXa2O
XQIDAQAB
-----END PUBLIC KEY-----"""

# Merchant private key – loaded from env / secret mount at runtime.
_MERCHANT_PRIVATE_KEY_PEM: str | None = None


class NagadError(Exception):
    """Raised when the Nagad API returns a non-successful response."""

    def __init__(self, message: str, raw: dict | None = None):
        super().__init__(message)
        self.raw = raw or {}


class NagadClient:
    """
    Async client for the Nagad payment gateway.

    Usage::

        client = NagadClient(
            base_url="https://sandbox.nagad.com.bd/api",
            merchant_id="...",
            merchant_key="...",   # PEM private key string
        )
        result = await client.initiate_payment(
            amount=500.00,
            order_id="ORD-12345",
            callback_url="https://yourdomain.com/nagad/callback",
        )
    """

    def __init__(
        self,
        base_url: str,
        merchant_id: str,
        merchant_key: str,  # PEM-encoded RSA private key
        nagad_public_key_pem: str = _NAGAD_PUBLIC_KEY_PEM,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._merchant_id = merchant_id
        self._private_key: RSAPrivateKey = serialization.load_pem_private_key(
            merchant_key.encode(),
            password=None,
        )  # type: ignore[assignment]
        self._nagad_public_key: RSAPublicKey = serialization.load_pem_public_key(
            nagad_public_key_pem.encode(),
        )  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def initiate_payment(
        self,
        amount: float,
        order_id: str,
        callback_url: str,
    ) -> dict[str, Any]:
        """
        Initiate a Nagad payment.

        Step 1 – Retrieve challenge from Nagad.
        Step 2 – Send encrypted payment initiation.

        Returns the Nagad response which contains a redirectGatewayURL.
        """
        timestamp = self._get_timestamp()

        # Step 1: get challenge
        challenge_data = await self._get_challenge(order_id, timestamp)
        challenge = challenge_data.get("challenge", "")
        if not challenge:
            raise NagadError("No challenge returned by Nagad", raw=challenge_data)

        # Step 2: initiate payment
        sensitive_data = {
            "merchantId": self._merchant_id,
            "datetime": timestamp,
            "orderId": order_id,
            "challenge": challenge,
        }
        encrypted_sensitive = self._encrypt_rsa(json.dumps(sensitive_data))
        signed_sensitive = self._sign_rsa(json.dumps(sensitive_data))

        payment_info = {
            "amount": f"{amount:.2f}",
            "currencyCode": "050",  # BDT
            "challenge": challenge,
        }
        encrypted_payment_info = self._encrypt_rsa(json.dumps(payment_info))

        payload = {
            "sensitiveData": encrypted_sensitive,
            "signature": signed_sensitive,
            "merchantCallbackURL": callback_url,
            "additionalMerchantInfo": {
                "doNotShowCancelButton": "false",
            },
        }

        url = (
            f"{self._base_url}/dfs/check-out/initialize/"
            f"{self._merchant_id}/{order_id}"
        )

        data = await self._post(url, payload)
        if data.get("status") not in ("Success",):
            raise NagadError(
                f"initiate_payment failed: {data.get('message')}",
                raw=data,
            )

        log.info(
            "nagad_payment_initiated",
            order_id=order_id,
            payment_ref_id=data.get("paymentReferenceId"),
        )
        return data

    async def verify_payment(self, payment_ref_id: str) -> dict[str, Any]:
        """
        Verify a completed Nagad payment using the paymentReferenceId.

        Returns the full Nagad verification response.
        """
        url = (
            f"{self._base_url}/dfs/verify/payment/"
            f"{payment_ref_id}"
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-KM-Api-Version": "v-0.2.0",
            "X-KM-IP-V4": "127.0.0.1",  # Replace with server public IP in production
            "X-KM-MC-Id": self._merchant_id,
            "X-KM-Client-Id": self._merchant_id,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                raise NagadError(f"verify_payment network error: {exc}") from exc

            try:
                data = resp.json()
            except Exception:
                raise NagadError("Invalid JSON from Nagad verify_payment")

        if data.get("status") not in ("Success",):
            raise NagadError(
                f"verify_payment failed: {data.get('message')}",
                raw=data,
            )

        log.info(
            "nagad_payment_verified",
            payment_ref_id=payment_ref_id,
            order_id=data.get("orderId"),
            amount=data.get("amount"),
        )
        return data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_challenge(self) -> str:
        """Generate a random challenge string (UUID-based)."""
        return str(uuid.uuid4()).replace("-", "")

    def _get_timestamp(self) -> str:
        """Return current timestamp in Nagad's expected format: YYYYMMDDHHmmss"""
        return datetime.now().strftime("%Y%m%d%H%M%S")

    def _encrypt_rsa(self, data: str) -> str:
        """
        Encrypt *data* (a JSON string) with Nagad's RSA public key.

        Returns Base64-encoded ciphertext.
        """
        ciphertext = self._nagad_public_key.encrypt(
            data.encode("utf-8"),
            padding.PKCS1v15(),
        )
        return base64.b64encode(ciphertext).decode("utf-8")

    def _sign_rsa(self, data: str) -> str:
        """
        Sign *data* with the merchant's RSA private key (PKCS1v15, SHA-256).

        Returns Base64-encoded signature.
        """
        signature = self._private_key.sign(
            data.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    async def _get_challenge(self, order_id: str, timestamp: str) -> dict[str, Any]:
        """
        Step 1 of Nagad payment: retrieve a server-issued challenge.
        """
        sensitive_data = {
            "merchantId": self._merchant_id,
            "datetime": timestamp,
            "orderId": order_id,
            "challenge": self._generate_challenge(),
        }
        encrypted_sensitive = self._encrypt_rsa(json.dumps(sensitive_data))
        signed_sensitive = self._sign_rsa(json.dumps(sensitive_data))

        payload = {
            "sensitiveData": encrypted_sensitive,
            "signature": signed_sensitive,
        }

        url = (
            f"{self._base_url}/dfs/check-out/initialize/"
            f"{self._merchant_id}/{order_id}"
        )
        return await self._post(url, payload)

    async def _post(self, url: str, payload: dict) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-KM-Api-Version": "v-0.2.0",
            "X-KM-IP-V4": "127.0.0.1",  # Replace with server public IP in production
            "X-KM-MC-Id": self._merchant_id,
            "X-KM-Client-Id": self._merchant_id,
            "X-KM-Api-Version": "v-0.2.0",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.RequestError as exc:
                log.error("nagad_request_error", url=url, error=str(exc))
                raise NagadError(f"Network error contacting Nagad: {exc}") from exc

            try:
                data = resp.json()
            except Exception:
                log.error("nagad_invalid_json", url=url, status=resp.status_code)
                raise NagadError("Invalid JSON response from Nagad")

        if resp.status_code >= 500:
            raise NagadError(
                f"Nagad server error {resp.status_code}",
                raw=data,
            )

        return data
