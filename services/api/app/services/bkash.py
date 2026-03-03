"""
bKash Tokenized Checkout API client.

Implements:
  - Token management with Redis caching
  - Create / execute payment
  - Agreement (auto-debit) creation and execution
  - Charge via agreement (recurring billing)
  - Payment query
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

_REDIS_TOKEN_KEY = "bkash:access_token"
_TOKEN_TTL_BUFFER = 60  # expire Redis key 60s before actual expiry


# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------

def _get_base_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "username": settings.BKASH_USERNAME,
        "password": settings.BKASH_PASSWORD,
    }


async def _post(url: str, payload: dict, headers: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

async def get_token(redis=None) -> str:
    """
    Return a valid bKash access token.

    Caches the token in Redis (if available) so we don't re-authenticate
    on every API call.
    """
    if redis is not None:
        cached = await redis.get(_REDIS_TOKEN_KEY)
        if cached:
            log.debug("bkash_token_from_cache")
            return cached

    url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/token/grant"
    payload = {
        "app_key": settings.BKASH_APP_KEY,
        "app_secret": settings.BKASH_APP_SECRET,
    }
    headers = _get_base_headers()

    data = await _post(url, payload, headers)
    token: str = data["id_token"]
    expires_in: int = int(data.get("expires_in", 3600))

    if redis is not None:
        await redis.setex(_REDIS_TOKEN_KEY, expires_in - _TOKEN_TTL_BUFFER, token)
        log.debug("bkash_token_cached", ttl=expires_in - _TOKEN_TTL_BUFFER)

    return token


def _get_auth_headers(token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": token,
        "X-APP-Key": settings.BKASH_APP_KEY,
    }


# ---------------------------------------------------------------------------
# Payment lifecycle
# ---------------------------------------------------------------------------

async def create_payment(
    amount: str | float,
    invoice_number: str,
    callback_url: Optional[str] = None,
    redis=None,
) -> dict[str, Any]:
    """
    Initiate a bKash Tokenized Checkout payment.

    Returns the full API response including ``bkashURL`` for redirect.
    """
    token = await get_token(redis)
    url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/create"
    payload = {
        "mode": "0011",  # Checkout URL mode
        "payerReference": invoice_number,
        "callbackURL": callback_url or settings.BKASH_CALLBACK_URL,
        "amount": str(amount),
        "currency": "BDT",
        "intent": "sale",
        "merchantInvoiceNumber": invoice_number,
    }
    data = await _post(url, payload, _get_auth_headers(token))
    log.info("bkash_payment_created", invoice=invoice_number, amount=amount)
    return data


async def execute_payment(payment_id: str, redis=None) -> dict[str, Any]:
    """Execute (capture) a bKash payment after user approval."""
    token = await get_token(redis)
    url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/execute"
    payload = {"paymentID": payment_id}
    data = await _post(url, payload, _get_auth_headers(token))
    log.info(
        "bkash_payment_executed",
        payment_id=payment_id,
        status=data.get("statusCode"),
    )
    return data


async def query_payment(payment_id: str, redis=None) -> dict[str, Any]:
    """Query the status of a payment."""
    token = await get_token(redis)
    url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/payment/status"
    payload = {"paymentID": payment_id}
    data = await _post(url, payload, _get_auth_headers(token))
    return data


# ---------------------------------------------------------------------------
# Agreement (auto-debit)
# ---------------------------------------------------------------------------

async def create_agreement(
    callback_url: Optional[str] = None,
    payer_reference: str = "",
    redis=None,
) -> dict[str, Any]:
    """Create a bKash tokenized agreement for auto-debit."""
    token = await get_token(redis)
    url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/agreement/create"
    payload = {
        "mode": "0000",
        "payerReference": payer_reference,
        "callbackURL": callback_url or settings.BKASH_CALLBACK_URL,
        "merchantInvoiceNumber": f"AGR-{payer_reference}",
    }
    data = await _post(url, payload, _get_auth_headers(token))
    log.info("bkash_agreement_created", payer_reference=payer_reference)
    return data


async def execute_agreement(payment_id: str, redis=None) -> dict[str, Any]:
    """Execute (confirm) a bKash agreement after user approval."""
    token = await get_token(redis)
    url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/agreement/execute"
    payload = {"paymentID": payment_id}
    data = await _post(url, payload, _get_auth_headers(token))
    log.info(
        "bkash_agreement_executed",
        payment_id=payment_id,
        status=data.get("statusCode"),
    )
    return data


# ---------------------------------------------------------------------------
# Agreement charge (recurring payment)
# ---------------------------------------------------------------------------

async def charge_agreement(
    agreement_id: str,
    amount: str | float,
    invoice_number: str,
    redis=None,
) -> dict[str, Any]:
    """
    Charge a customer using an existing auto-debit agreement.

    Uses ``mode 0000`` with the agreement token.
    """
    token = await get_token(redis)
    url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/payment/create"
    payload = {
        "mode": "0000",
        "payerReference": agreement_id,
        "callbackURL": settings.BKASH_CALLBACK_URL,
        "amount": str(amount),
        "currency": "BDT",
        "intent": "sale",
        "merchantInvoiceNumber": invoice_number,
        "agreementID": agreement_id,
    }
    data = await _post(url, payload, _get_auth_headers(token))
    log.info(
        "bkash_agreement_charged",
        agreement_id=agreement_id,
        invoice=invoice_number,
        amount=amount,
    )
    return data
