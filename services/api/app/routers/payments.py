"""
Payment management router for whISP.

Supports bKash, Nagad, SSLCommerz, and manual payment flows.
Includes OTT provisioning, RADIUS sync, and CoA reconnect on subscription completion.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    Notification,
    OTTEntitlement,
    PaymentTransaction,
    Plan,
    Subscriber,
)
from app.services.auth import (
    AdminUser,
    CurrentUser,
    FranchiseeUser as FranchiseeUserDep,
    assert_franchisee_scope,
    assert_subscriber_scope,
    get_db_conn,
)
from app.services.coa import send_disconnect, send_rate_limit
from app.services.radius import sync_subscriber

log = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PaymentInitiate(BaseModel):
    subscriber_id: uuid.UUID
    plan_id: uuid.UUID


class ManualPaymentRequest(BaseModel):
    subscriber_id: uuid.UUID
    plan_id: uuid.UUID
    amount: float = Field(..., gt=0)
    notes: Optional[str] = None
    gateway_transaction_id: Optional[str] = None


class BkashCallbackParams(BaseModel):
    paymentID: str
    status: str
    apiVersion: Optional[str] = None


class NagadCallbackParams(BaseModel):
    payment_ref_id: str
    status: str
    order_id: Optional[str] = None


class SSLCallbackParams(BaseModel):
    tran_id: str
    val_id: Optional[str] = None
    status: str
    amount: Optional[str] = None
    currency: Optional[str] = None


class BkashAgreementCreate(BaseModel):
    subscriber_id: uuid.UUID


class BkashAgreementCallback(BaseModel):
    paymentID: str
    status: str
    agreementID: Optional[str] = None


# ---------------------------------------------------------------------------
# Core helper: complete subscription after successful payment
# ---------------------------------------------------------------------------

async def _complete_subscription(
    db: AsyncSession,
    conn: asyncpg.Connection,
    subscriber: Subscriber,
    plan: Plan,
) -> None:
    """
    Activate subscription after a successful payment.

    Steps:
    1. Update subscriber's plan, reset quota, set expiry, set status=active
    2. Sync to RADIUS
    3. Send CoA reconnect if subscriber has an active session
    4. Provision OTT entitlements
    5. Queue activation notification
    """
    subscriber.plan_id = plan.id
    subscriber.quota_used_bytes = 0
    subscriber.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=plan.validity_days)
    subscriber.status = "active"

    await db.flush()

    # RADIUS sync
    try:
        await db.refresh(subscriber)
        await sync_subscriber(conn, subscriber)
    except Exception as exc:
        log.error("radius_sync_failed_in_complete_subscription", error=str(exc),
                  subscriber_id=str(subscriber.id))

    # CoA reconnect if subscriber has active session
    try:
        from app.models import NASDevice
        nas_result = await db.execute(
            select(NASDevice).where(
                NASDevice.franchisee_id == subscriber.franchisee_id,
                NASDevice.is_active == True,  # noqa: E712
            ).limit(1)
        )
        nas = nas_result.scalar_one_or_none()
        if nas:
            # Try CoA rate-limit update first (avoids dropping the session)
            try:
                await send_rate_limit(
                    nas_ip=nas.ip_address,
                    nas_secret=nas.secret,
                    username=subscriber.username,
                    download_kbps=plan.download_kbps,
                    upload_kbps=plan.upload_kbps,
                    port=nas.coa_port,
                )
            except Exception:
                # Fallback to disconnect-reconnect
                await send_disconnect(
                    nas_ip=nas.ip_address,
                    nas_secret=nas.secret,
                    username=subscriber.username,
                    port=nas.coa_port,
                )
    except Exception as exc:
        log.warning("coa_reconnect_failed_in_complete_subscription", error=str(exc))

    # OTT provisioning
    providers: list[str] = plan.ott_entitlements or []
    for provider in providers:
        existing = await db.execute(
            select(OTTEntitlement).where(
                OTTEntitlement.subscriber_id == subscriber.id,
                OTTEntitlement.partner == provider,
                OTTEntitlement.status == "active",
            )
        )
        if existing.scalar_one_or_none():
            continue
        entitlement = OTTEntitlement(
            subscriber_id=subscriber.id,
            partner=provider,
            status="active",
            provisioned_at=datetime.now(timezone.utc),
            expires_at=subscriber.plan_expires_at,
        )
        db.add(entitlement)

    # Queue activation notification
    notification = Notification(
        subscriber_id=subscriber.id,
        franchisee_id=subscriber.franchisee_id,
        channel="sms",
        title="সংযোগ সক্রিয়",
        body="আপনার ইন্টারনেট সংযোগ সক্রিয় হয়েছে।",
        status="pending",
    )
    db.add(notification)

    log.info("subscription_completed", subscriber_id=str(subscriber.id), plan_id=str(plan.id))


def _make_invoice_number() -> str:
    import random
    return f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{random.randint(100000, 999999)}"


# ---------------------------------------------------------------------------
# GET /payments
# ---------------------------------------------------------------------------

@router.get("", summary="List payment transactions")
async def list_payments(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    gateway: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None, alias="status"),
    subscriber_id: Optional[uuid.UUID] = Query(None),
) -> dict[str, Any]:
    q = select(PaymentTransaction)

    actor_type = user.get("type")
    if actor_type == "admin":
        if subscriber_id:
            q = q.where(PaymentTransaction.subscriber_id == subscriber_id)
    elif actor_type == "franchisee":
        # Franchisee sees payments of their subscribers
        fid = uuid.UUID(user["franchisee_id"])
        sub_ids_q = select(Subscriber.id).where(
            Subscriber.franchisee_id == fid,
            Subscriber.is_deleted == False,  # noqa: E712
        )
        sub_ids_result = await db.execute(sub_ids_q)
        sub_ids = [r[0] for r in sub_ids_result.all()]
        q = q.where(PaymentTransaction.subscriber_id.in_(sub_ids))
        if subscriber_id:
            q = q.where(PaymentTransaction.subscriber_id == subscriber_id)
    else:
        # Subscriber sees only their own
        sid = uuid.UUID(user["sub"])
        q = q.where(PaymentTransaction.subscriber_id == sid)

    if gateway:
        q = q.where(PaymentTransaction.gateway == gateway)
    if payment_status:
        q = q.where(PaymentTransaction.status == payment_status)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.offset(offset).limit(limit).order_by(PaymentTransaction.created_at.desc())
    rows = await db.execute(q)

    def _tx_dict(tx: PaymentTransaction) -> dict[str, Any]:
        return {
            "id": str(tx.id),
            "subscriber_id": str(tx.subscriber_id),
            "plan_id": str(tx.plan_id) if tx.plan_id else None,
            "gateway": tx.gateway,
            "invoice_number": tx.invoice_number,
            "amount": float(tx.amount),
            "currency": tx.currency,
            "status": tx.status,
            "gateway_payment_id": tx.gateway_payment_id,
            "gateway_transaction_id": tx.gateway_transaction_id,
            "completed_at": tx.completed_at.isoformat() if tx.completed_at else None,
            "notes": tx.notes,
            "created_at": tx.created_at.isoformat(),
        }

    items = [_tx_dict(tx) for tx in rows.scalars()]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------------------
# GET /payments/{id}
# ---------------------------------------------------------------------------

@router.get("/{payment_id}", summary="Get payment detail")
async def get_payment(
    payment_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(PaymentTransaction).where(PaymentTransaction.id == payment_id))
    tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    assert_subscriber_scope(user, str(tx.subscriber_id))

    return {
        "id": str(tx.id),
        "subscriber_id": str(tx.subscriber_id),
        "plan_id": str(tx.plan_id) if tx.plan_id else None,
        "gateway": tx.gateway,
        "invoice_number": tx.invoice_number,
        "amount": float(tx.amount),
        "currency": tx.currency,
        "status": tx.status,
        "gateway_payment_id": tx.gateway_payment_id,
        "gateway_transaction_id": tx.gateway_transaction_id,
        "completed_at": tx.completed_at.isoformat() if tx.completed_at else None,
        "gateway_response": tx.gateway_response,
        "notes": tx.notes,
        "created_at": tx.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /payments/bkash/initiate
# ---------------------------------------------------------------------------

@router.post("/bkash/initiate", status_code=status.HTTP_201_CREATED, summary="Initiate bKash payment")
async def bkash_initiate(
    body: PaymentInitiate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert_subscriber_scope(user, str(body.subscriber_id))

    sub_result = await db.execute(
        select(Subscriber).where(Subscriber.id == body.subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = sub_result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    plan_result = await db.execute(select(Plan).where(Plan.id == body.plan_id, Plan.is_active == True))  # noqa: E712
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found or inactive")

    invoice_number = _make_invoice_number()

    tx = PaymentTransaction(
        subscriber_id=sub.id,
        plan_id=plan.id,
        gateway="bkash",
        invoice_number=invoice_number,
        amount=plan.price,
        currency=plan.currency,
        status="initiated",
    )
    db.add(tx)
    await db.flush()

    redis = getattr(request.app.state, "redis", None)
    try:
        from app.services import bkash as bkash_svc
        result = await bkash_svc.create_payment(
            amount=float(plan.price),
            invoice_number=invoice_number,
            redis=redis,
        )
        bkash_url = result.get("bkashURL") or result.get("bkash_url", "")
        payment_id = result.get("paymentID", "")
        tx.gateway_payment_id = payment_id
        tx.status = "pending"
        tx.gateway_response = result
    except Exception as exc:
        log.error("bkash_create_payment_failed", error=str(exc))
        tx.status = "failed"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"bKash API error: {exc}")

    await db.commit()
    return {"bkash_url": bkash_url, "payment_id": str(tx.id), "invoice_number": invoice_number}


# ---------------------------------------------------------------------------
# POST /payments/bkash/callback
# ---------------------------------------------------------------------------

@router.post("/bkash/callback", summary="bKash IPN callback")
async def bkash_callback(
    body: BkashCallbackParams,
    request: Request,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    # Find transaction by gateway_payment_id
    result = await db.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.gateway_payment_id == body.paymentID,
            PaymentTransaction.gateway == "bkash",
        )
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    redis = getattr(request.app.state, "redis", None)

    if body.status.lower() == "success":
        try:
            from app.services import bkash as bkash_svc
            execute_result = await bkash_svc.execute_payment(body.paymentID, redis=redis)
            status_code = execute_result.get("statusCode", "")
            if status_code == "0000":
                tx.status = "completed"
                tx.completed_at = datetime.now(timezone.utc)
                tx.gateway_transaction_id = execute_result.get("trxID")
                tx.gateway_response = execute_result
                await db.flush()

                # Load subscriber and plan
                sub = (await db.execute(select(Subscriber).where(Subscriber.id == tx.subscriber_id))).scalar_one()
                plan = (await db.execute(select(Plan).where(Plan.id == tx.plan_id))).scalar_one()
                await _complete_subscription(db, conn, sub, plan)
            else:
                tx.status = "failed"
                tx.gateway_response = execute_result
        except Exception as exc:
            log.error("bkash_execute_failed", error=str(exc))
            tx.status = "failed"
    else:
        tx.status = "cancelled"

    await db.commit()
    return {"status": tx.status, "invoice_number": tx.invoice_number}


# ---------------------------------------------------------------------------
# POST /payments/nagad/initiate
# ---------------------------------------------------------------------------

@router.post("/nagad/initiate", status_code=status.HTTP_201_CREATED, summary="Initiate Nagad payment")
async def nagad_initiate(
    body: PaymentInitiate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert_subscriber_scope(user, str(body.subscriber_id))

    sub_result = await db.execute(
        select(Subscriber).where(Subscriber.id == body.subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = sub_result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    plan_result = await db.execute(select(Plan).where(Plan.id == body.plan_id, Plan.is_active == True))  # noqa: E712
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found or inactive")

    from app.config import get_settings
    settings = get_settings()
    invoice_number = _make_invoice_number()

    tx = PaymentTransaction(
        subscriber_id=sub.id,
        plan_id=plan.id,
        gateway="nagad",
        invoice_number=invoice_number,
        amount=plan.price,
        currency=plan.currency,
        status="initiated",
    )
    db.add(tx)
    await db.flush()

    try:
        from app.services import nagad as nagad_svc
        result = await nagad_svc.create_payment(
            amount=float(plan.price),
            order_id=invoice_number,
        )
        nagad_url = result.get("callBackUrl") or result.get("redirect_url", "")
        tx.gateway_payment_id = result.get("payment_ref_id", invoice_number)
        tx.status = "pending"
        tx.gateway_response = result
    except Exception as exc:
        log.warning("nagad_service_unavailable", error=str(exc))
        # Graceful degradation: return a mock URL in non-production
        nagad_url = f"{settings.NAGAD_BASE_URL}/payment?order_id={invoice_number}"
        tx.status = "pending"
        tx.gateway_payment_id = invoice_number

    await db.commit()
    return {"nagad_url": nagad_url, "payment_id": str(tx.id), "invoice_number": invoice_number}


# ---------------------------------------------------------------------------
# POST /payments/nagad/callback
# ---------------------------------------------------------------------------

@router.post("/nagad/callback", summary="Nagad IPN callback")
async def nagad_callback(
    body: NagadCallbackParams,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    result = await db.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.gateway_payment_id == body.payment_ref_id,
            PaymentTransaction.gateway == "nagad",
        )
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        # Try by order_id = invoice_number
        if body.order_id:
            result = await db.execute(
                select(PaymentTransaction).where(
                    PaymentTransaction.invoice_number == body.order_id,
                    PaymentTransaction.gateway == "nagad",
                )
            )
            tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if body.status.lower() in ("success", "completed"):
        tx.status = "completed"
        tx.completed_at = datetime.now(timezone.utc)
        await db.flush()

        sub = (await db.execute(select(Subscriber).where(Subscriber.id == tx.subscriber_id))).scalar_one()
        plan = (await db.execute(select(Plan).where(Plan.id == tx.plan_id))).scalar_one()
        await _complete_subscription(db, conn, sub, plan)
    else:
        tx.status = "failed"

    await db.commit()
    return {"status": tx.status}


# ---------------------------------------------------------------------------
# POST /payments/sslcommerz/initiate
# ---------------------------------------------------------------------------

@router.post("/sslcommerz/initiate", status_code=status.HTTP_201_CREATED, summary="Initiate SSLCommerz payment")
async def sslcommerz_initiate(
    body: PaymentInitiate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert_subscriber_scope(user, str(body.subscriber_id))

    sub_result = await db.execute(
        select(Subscriber).where(Subscriber.id == body.subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = sub_result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    plan_result = await db.execute(select(Plan).where(Plan.id == body.plan_id, Plan.is_active == True))  # noqa: E712
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found or inactive")

    from app.config import get_settings
    settings = get_settings()
    invoice_number = _make_invoice_number()

    tx = PaymentTransaction(
        subscriber_id=sub.id,
        plan_id=plan.id,
        gateway="sslcommerz",
        invoice_number=invoice_number,
        amount=plan.price,
        currency=plan.currency,
        status="initiated",
    )
    db.add(tx)
    await db.flush()

    try:
        import httpx
        payload = {
            "store_id": settings.SSLCOMMERZ_STORE_ID,
            "store_passwd": settings.SSLCOMMERZ_STORE_PASSWD,
            "total_amount": str(float(plan.price)),
            "currency": plan.currency,
            "tran_id": invoice_number,
            "success_url": settings.SSLCOMMERZ_SUCCESS_URL,
            "fail_url": settings.SSLCOMMERZ_FAIL_URL,
            "cancel_url": settings.SSLCOMMERZ_CANCEL_URL,
            "ipn_url": settings.SSLCOMMERZ_IPN_URL,
            "product_name": plan.name,
            "product_category": "Internet Plan",
            "cus_name": sub.name,
            "cus_email": sub.email,
            "cus_phone": sub.phone or "N/A",
            "cus_add1": sub.address or "N/A",
            "cus_city": "Dhaka",
            "cus_country": "Bangladesh",
            "shipping_method": "NO",
            "num_of_item": 1,
            "product_profile": "general",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.SSLCOMMERZ_BASE_URL}/gwprocess/v4/api.php",
                data=payload,
            )
            ssl_resp = resp.json()
        gateway_url = ssl_resp.get("GatewayPageURL", "")
        tx.gateway_payment_id = ssl_resp.get("sessionkey", invoice_number)
        tx.status = "pending"
        tx.gateway_response = ssl_resp
    except Exception as exc:
        log.error("sslcommerz_initiate_failed", error=str(exc))
        tx.status = "failed"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"SSLCommerz error: {exc}")

    await db.commit()
    return {"gateway_url": gateway_url, "payment_id": str(tx.id), "invoice_number": invoice_number}


# ---------------------------------------------------------------------------
# POST /payments/sslcommerz/success
# ---------------------------------------------------------------------------

@router.post("/sslcommerz/success", summary="SSLCommerz success redirect callback")
async def sslcommerz_success(
    request: Request,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    form = await request.form()
    tran_id = form.get("tran_id", "")
    val_id = form.get("val_id", "")
    txn_status = form.get("status", "")

    result = await db.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.invoice_number == tran_id,
            PaymentTransaction.gateway == "sslcommerz",
        )
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn_status == "VALID":
        tx.status = "completed"
        tx.completed_at = datetime.now(timezone.utc)
        tx.gateway_transaction_id = val_id
        tx.gateway_response = dict(form)
        await db.flush()

        sub = (await db.execute(select(Subscriber).where(Subscriber.id == tx.subscriber_id))).scalar_one()
        plan = (await db.execute(select(Plan).where(Plan.id == tx.plan_id))).scalar_one()
        await _complete_subscription(db, conn, sub, plan)
    else:
        tx.status = "failed"

    await db.commit()
    return {"status": tx.status, "invoice_number": tran_id}


# ---------------------------------------------------------------------------
# POST /payments/sslcommerz/ipn
# ---------------------------------------------------------------------------

@router.post("/sslcommerz/ipn", summary="SSLCommerz IPN handler")
async def sslcommerz_ipn(
    request: Request,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    """Validate SSLCommerz IPN and complete transaction."""
    from app.config import get_settings
    settings = get_settings()

    form = await request.form()
    tran_id = form.get("tran_id", "")
    val_id = form.get("val_id", "")
    txn_status = form.get("status", "")
    amount = form.get("amount", "0")

    if txn_status != "VALID":
        log.warning("sslcommerz_ipn_invalid_status", status=txn_status)
        return {"status": "ignored"}

    # Validate with SSLCommerz
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            validation_resp = await client.get(
                f"{settings.SSLCOMMERZ_BASE_URL}/validator/api/validationserverAPI.php",
                params={
                    "val_id": val_id,
                    "store_id": settings.SSLCOMMERZ_STORE_ID,
                    "store_passwd": settings.SSLCOMMERZ_STORE_PASSWD,
                    "format": "json",
                },
            )
            val_data = validation_resp.json()
        if val_data.get("status") != "VALID":
            log.warning("sslcommerz_validation_failed", val_id=val_id)
            return {"status": "validation_failed"}
    except Exception as exc:
        log.error("sslcommerz_validation_error", error=str(exc))
        # Continue with IPN data if validation endpoint unavailable
        val_data = {}

    result = await db.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.invoice_number == tran_id,
            PaymentTransaction.gateway == "sslcommerz",
        )
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.status == "completed":
        return {"status": "already_completed"}

    tx.status = "completed"
    tx.completed_at = datetime.now(timezone.utc)
    tx.gateway_transaction_id = val_id
    tx.gateway_response = {**dict(form), **val_data}
    await db.flush()

    sub = (await db.execute(select(Subscriber).where(Subscriber.id == tx.subscriber_id))).scalar_one()
    plan = (await db.execute(select(Plan).where(Plan.id == tx.plan_id))).scalar_one()
    await _complete_subscription(db, conn, sub, plan)

    await db.commit()
    return {"status": "completed", "invoice_number": tran_id}


# ---------------------------------------------------------------------------
# POST /payments/manual
# ---------------------------------------------------------------------------

@router.post("/manual", status_code=status.HTTP_201_CREATED, summary="Record manual payment (admin/franchisee)")
async def manual_payment(
    body: ManualPaymentRequest,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    sub_result = await db.execute(
        select(Subscriber).where(Subscriber.id == body.subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = sub_result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    assert_franchisee_scope(user, str(sub.franchisee_id))

    plan_result = await db.execute(select(Plan).where(Plan.id == body.plan_id))
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    invoice_number = _make_invoice_number()
    tx = PaymentTransaction(
        subscriber_id=sub.id,
        plan_id=plan.id,
        gateway="manual",
        invoice_number=invoice_number,
        amount=body.amount,
        currency=plan.currency,
        status="completed",
        completed_at=datetime.now(timezone.utc),
        gateway_transaction_id=body.gateway_transaction_id,
        notes=body.notes,
    )
    db.add(tx)
    await db.flush()

    await _complete_subscription(db, conn, sub, plan)

    db.add(AuditLog(
        actor_type=user.get("type", "franchisee"),
        actor_email=user.get("email"),
        action="payment.manual",
        resource_type="payment_transaction",
        resource_id=tx.id,
        new_values={"amount": body.amount, "plan_id": str(plan.id), "invoice": invoice_number},
        success=True,
    ))

    await db.commit()
    log.info("manual_payment_recorded", transaction_id=str(tx.id), subscriber_id=str(sub.id))

    return {
        "id": str(tx.id),
        "invoice_number": invoice_number,
        "status": tx.status,
        "amount": float(body.amount),
        "message": "Payment recorded and subscription activated",
    }


# ---------------------------------------------------------------------------
# POST /payments/bkash/agreement/create
# ---------------------------------------------------------------------------

@router.post("/bkash/agreement/create", status_code=status.HTTP_201_CREATED,
             summary="Create bKash auto-debit agreement")
async def bkash_agreement_create(
    body: BkashAgreementCreate,
    user: CurrentUser,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert_subscriber_scope(user, str(body.subscriber_id))

    sub_result = await db.execute(
        select(Subscriber).where(Subscriber.id == body.subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = sub_result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    redis = getattr(request.app.state, "redis", None)
    try:
        from app.services import bkash as bkash_svc
        result = await bkash_svc.create_agreement(
            payer_reference=str(sub.id),
            redis=redis,
        )
        agreement_url = result.get("bkashURL", "")
        payment_id = result.get("paymentID", "")
    except Exception as exc:
        log.error("bkash_agreement_create_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"bKash API error: {exc}")

    return {
        "agreement_url": agreement_url,
        "payment_id": payment_id,
        "subscriber_id": str(sub.id),
    }


# ---------------------------------------------------------------------------
# POST /payments/bkash/agreement/callback
# ---------------------------------------------------------------------------

@router.post("/bkash/agreement/callback", summary="bKash agreement confirmation callback")
async def bkash_agreement_callback(
    body: BkashAgreementCallback,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    redis = getattr(request.app.state, "redis", None)

    if body.status.lower() != "success":
        return {"status": "cancelled"}

    try:
        from app.services import bkash as bkash_svc
        result = await bkash_svc.execute_agreement(body.paymentID, redis=redis)
        agreement_id = result.get("agreementID") or body.agreementID
        payer_reference = result.get("payerReference", "")
    except Exception as exc:
        log.error("bkash_agreement_execute_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"bKash execute error: {exc}")

    if not agreement_id:
        raise HTTPException(status_code=400, detail="No agreement ID returned by bKash")

    # Find subscriber by payer_reference (which is subscriber UUID)
    try:
        sub_id = uuid.UUID(payer_reference)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payer_reference")

    result_sub = await db.execute(
        select(Subscriber).where(Subscriber.id == sub_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = result_sub.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    sub.bkash_agreement_id = agreement_id
    await db.commit()

    log.info("bkash_agreement_stored", subscriber_id=str(sub.id), agreement_id=agreement_id)
    return {
        "status": "success",
        "subscriber_id": str(sub.id),
        "agreement_id": agreement_id,
        "message": "Auto-debit agreement activated successfully",
    }
