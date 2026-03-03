"""
bKash tokenized payment gateway client.

Supports:
  - Token management (cached in Redis for 50 minutes)
  - Regular payment creation/execution
  - Agreement (auto-debit) creation/execution
  - Agreement charge (recurring debit)
  - Agreement query
"""

import json
import time
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

_TOKEN_REDIS_KEY = "bkash:token"
_TOKEN_TTL_SECONDS = 50 * 60  # 50 minutes


class BKashError(Exception):
    """Raised when bKash API returns a non-successful response."""

    def __init__(self, message: str, status_code: str | None = None, raw: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw or {}


class BKashClient:
    """Async client for the bKash tokenized payment API."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        app_key: str,
        app_secret: str,
        redis,  # redis.asyncio.Redis
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._app_key = app_key
        self._app_secret = app_secret
        self._redis = redis

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _default_headers(self, token: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "username": self._username,
            "password": self._password,
            "Authorization": token,
            "x-app-key": self._app_key,
        }

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        with_token: bool = True,
        retry_on_401: bool = True,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if with_token:
            token = await self.get_token()
            headers["Authorization"] = token
            headers["x-app-key"] = self._app_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.request(
                    method,
                    url,
                    json=payload,
                    headers=headers,
                )
            except httpx.RequestError as exc:
                log.error("bkash_request_error", url=url, error=str(exc))
                raise BKashError(f"Network error: {exc}") from exc

            if resp.status_code == 401 and retry_on_401 and with_token:
                # Token may have expired; clear cache and retry once
                await self._redis.delete(_TOKEN_REDIS_KEY)
                token = await self.get_token()
                headers["Authorization"] = token
                resp = await client.request(
                    method,
                    url,
                    json=payload,
                    headers=headers,
                )

            try:
                data: dict = resp.json()
            except Exception:
                log.error("bkash_invalid_json", url=url, status=resp.status_code)
                raise BKashError("Invalid JSON response from bKash")

            if resp.status_code >= 500:
                log.error("bkash_server_error", url=url, status=resp.status_code)
                raise BKashError(
                    f"bKash server error {resp.status_code}",
                    raw=data,
                )

            return data

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def get_token(self) -> str:
        """
        Return a valid bKash grant token, using Redis as a 50-minute cache.
        """
        cached = await self._redis.get(_TOKEN_REDIS_KEY)
        if cached:
            return cached

        url = f"{self._base_url}/tokenized/checkout/token/grant"
        payload = {
            "app_key": self._app_key,
            "app_secret": self._app_secret,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "username": self._username,
            "password": self._password,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.RequestError as exc:
                raise BKashError(f"Token grant network error: {exc}") from exc

            try:
                data = resp.json()
            except Exception:
                raise BKashError("Invalid JSON from bKash token grant")

        if data.get("statusCode") != "0000":
            raise BKashError(
                f"Token grant failed: {data.get('statusMessage')}",
                status_code=data.get("statusCode"),
                raw=data,
            )

        token: str = data["id_token"]
        await self._redis.setex(_TOKEN_REDIS_KEY, _TOKEN_TTL_SECONDS, token)
        log.info("bkash_token_refreshed")
        return token

    # ------------------------------------------------------------------
    # Regular payments
    # ------------------------------------------------------------------

    async def create_payment(
        self,
        amount: float,
        invoice_number: str,
        callback_url: str,
    ) -> dict[str, Any]:
        """
        Create a tokenized payment (customer-initiated, one-time).

        Returns the full bKash response dict (includes paymentID, bkashURL, etc.)
        """
        payload = {
            "mode": "0011",
            "payerReference": invoice_number,
            "callbackURL": callback_url,
            "amount": f"{amount:.2f}",
            "currency": "BDT",
            "intent": "sale",
            "merchantInvoiceNumber": invoice_number,
        }
        data = await self._request(
            "POST",
            "/tokenized/checkout/create",
            payload=payload,
        )
        if data.get("statusCode") != "0000":
            raise BKashError(
                f"create_payment failed: {data.get('statusMessage')}",
                status_code=data.get("statusCode"),
                raw=data,
            )
        log.info(
            "bkash_payment_created",
            payment_id=data.get("paymentID"),
            invoice=invoice_number,
        )
        return data

    async def execute_payment(self, payment_id: str) -> dict[str, Any]:
        """
        Execute a previously created payment after the user completes the bKash flow.
        """
        payload = {"paymentID": payment_id}
        data = await self._request(
            "POST",
            "/tokenized/checkout/execute",
            payload=payload,
        )
        if data.get("statusCode") != "0000":
            raise BKashError(
                f"execute_payment failed: {data.get('statusMessage')}",
                status_code=data.get("statusCode"),
                raw=data,
            )
        log.info(
            "bkash_payment_executed",
            payment_id=payment_id,
            trx_id=data.get("trxID"),
        )
        return data

    # ------------------------------------------------------------------
    # Agreement (auto-debit / recurring)
    # ------------------------------------------------------------------

    async def create_agreement(self, callback_url: str) -> dict[str, Any]:
        """
        Initiate a bKash agreement request (mode 0000).

        The customer is redirected to bkashURL to approve the agreement.
        """
        payload = {
            "mode": "0000",
            "callbackURL": callback_url,
            "merchantShortCode": self._app_key[:6],  # first 6 chars used as short code
            "currency": "BDT",
            "intent": "agreement",
        }
        data = await self._request(
            "POST",
            "/tokenized/checkout/create",
            payload=payload,
        )
        if data.get("statusCode") != "0000":
            raise BKashError(
                f"create_agreement failed: {data.get('statusMessage')}",
                status_code=data.get("statusCode"),
                raw=data,
            )
        log.info("bkash_agreement_created", payment_id=data.get("paymentID"))
        return data

    async def execute_agreement(self, payment_id: str) -> dict[str, Any]:
        """
        Complete an agreement after the customer approves it.

        Returns agreementID used for future charge_agreement calls.
        """
        payload = {"paymentID": payment_id}
        data = await self._request(
            "POST",
            "/tokenized/checkout/execute",
            payload=payload,
        )
        if data.get("statusCode") != "0000":
            raise BKashError(
                f"execute_agreement failed: {data.get('statusMessage')}",
                status_code=data.get("statusCode"),
                raw=data,
            )
        log.info(
            "bkash_agreement_executed",
            payment_id=payment_id,
            agreement_id=data.get("agreementID"),
        )
        return data

    async def charge_agreement(
        self,
        agreement_id: str,
        amount: float,
        invoice_number: str,
    ) -> dict[str, Any]:
        """
        Debit a pre-authorized bKash agreement (auto-debit / recurring charge).

        This is a merchant-initiated call; no customer action required.
        """
        payload = {
            "mode": "0001",
            "agreementID": agreement_id,
            "amount": f"{amount:.2f}",
            "currency": "BDT",
            "intent": "sale",
            "merchantInvoiceNumber": invoice_number,
        }
        data = await self._request(
            "POST",
            "/tokenized/checkout/create",
            payload=payload,
        )
        if data.get("statusCode") not in ("0000",):
            # For auto-debit, some gateways return the charge result directly
            # in the create response when mode=0001.  Handle both patterns.
            raise BKashError(
                f"charge_agreement failed: {data.get('statusMessage')}",
                status_code=data.get("statusCode"),
                raw=data,
            )

        # If paymentID is returned we need an extra execute call
        if "paymentID" in data and data.get("statusCode") == "0000":
            execute_data = await self.execute_payment(data["paymentID"])
            log.info(
                "bkash_agreement_charged",
                agreement_id=agreement_id,
                invoice=invoice_number,
                trx_id=execute_data.get("trxID"),
            )
            return execute_data

        log.info(
            "bkash_agreement_charged",
            agreement_id=agreement_id,
            invoice=invoice_number,
            trx_id=data.get("trxID"),
        )
        return data

    async def query_agreement(self, agreement_id: str) -> dict[str, Any]:
        """
        Query the current status of a bKash agreement.

        Returns the full response including agreementStatus field.
        """
        payload = {"agreementID": agreement_id}
        data = await self._request(
            "POST",
            "/tokenized/checkout/agreement/status",
            payload=payload,
        )
        if data.get("statusCode") not in ("0000",):
            raise BKashError(
                f"query_agreement failed: {data.get('statusMessage')}",
                status_code=data.get("statusCode"),
                raw=data,
            )
        log.debug(
            "bkash_agreement_queried",
            agreement_id=agreement_id,
            status=data.get("agreementStatus"),
        )
        return data
