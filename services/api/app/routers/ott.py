"""
OTT (Over-The-Top) entitlement management router for whISP.

Supports Chorki and Hoichoi partner APIs. Degrades gracefully when
API keys are not configured by returning mock SSO URLs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    OTTEntitlement,
    Subscriber,
)
from app.services.auth import (
    AdminUser,
    CurrentUser,
    FranchiseeUser as FranchiseeUserDep,
    assert_franchisee_scope,
    assert_subscriber_scope,
)

log = structlog.get_logger(__name__)
router = APIRouter()

_SUPPORTED_PARTNERS = ("chorki", "hoichoi")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OTTProvisionRequest(BaseModel):
    subscriber_id: uuid.UUID
    partner: str


# ---------------------------------------------------------------------------
# Partner API helpers
# ---------------------------------------------------------------------------

async def _chorki_generate_sso(subscriber: Subscriber, entitlement: OTTEntitlement) -> str:
    """Generate SSO URL for Chorki. Returns mock if API key not configured."""
    from app.config import get_settings
    settings = get_settings()

    if not settings.CHORKI_API_KEY:
        log.warning("chorki_api_key_not_configured", note="returning_mock_url")
        return (
            f"https://chorki.com/sso?token=MOCK_{subscriber.id}"
            f"&note=partner_not_configured"
        )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.CHORKI_BASE_URL}/v1/partner/sso",
                headers={
                    "Authorization": f"Bearer {settings.CHORKI_API_KEY}",
                    "X-Partner-ID": settings.CHORKI_PARTNER_ID,
                    "Content-Type": "application/json",
                },
                json={
                    "partner_user_id": str(subscriber.id),
                    "email": subscriber.email,
                    "name": subscriber.name,
                    "subscription_id": str(entitlement.id) if entitlement.id else "",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("sso_url") or data.get("url", "")
    except Exception as exc:
        log.error("chorki_sso_error", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Chorki API error: {exc}")


async def _hoichoi_generate_sso(subscriber: Subscriber, entitlement: OTTEntitlement) -> str:
    """Generate SSO URL for Hoichoi. Returns mock if API key not configured."""
    from app.config import get_settings
    settings = get_settings()

    if not settings.HOICHOI_API_KEY:
        log.warning("hoichoi_api_key_not_configured", note="returning_mock_url")
        return (
            f"https://hoichoi.tv/sso?token=MOCK_{subscriber.id}"
            f"&note=partner_not_configured"
        )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.HOICHOI_BASE_URL}/v1/partner/token",
                headers={
                    "X-API-Key": settings.HOICHOI_API_KEY,
                    "X-Partner-ID": settings.HOICHOI_PARTNER_ID,
                    "Content-Type": "application/json",
                },
                json={
                    "partner_user_id": str(subscriber.id),
                    "email": subscriber.email,
                    "name": subscriber.name,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("sso_url") or data.get("token_url", "")
    except Exception as exc:
        log.error("hoichoi_sso_error", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Hoichoi API error: {exc}")


async def _chorki_provision(subscriber: Subscriber) -> dict[str, Any]:
    """Call Chorki partner API to provision subscription. Degrades gracefully."""
    from app.config import get_settings
    settings = get_settings()

    if not settings.CHORKI_API_KEY:
        log.warning("chorki_provision_skipped_no_api_key")
        return {"status": "mock", "note": "partner_not_configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.CHORKI_BASE_URL}/v1/partner/provision",
                headers={
                    "Authorization": f"Bearer {settings.CHORKI_API_KEY}",
                    "X-Partner-ID": settings.CHORKI_PARTNER_ID,
                },
                json={
                    "partner_user_id": str(subscriber.id),
                    "email": subscriber.email,
                    "name": subscriber.name,
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        log.error("chorki_provision_error", error=str(exc))
        return {"error": str(exc)}


async def _hoichoi_provision(subscriber: Subscriber) -> dict[str, Any]:
    """Call Hoichoi partner API to provision subscription. Degrades gracefully."""
    from app.config import get_settings
    settings = get_settings()

    if not settings.HOICHOI_API_KEY:
        log.warning("hoichoi_provision_skipped_no_api_key")
        return {"status": "mock", "note": "partner_not_configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.HOICHOI_BASE_URL}/v1/partner/provision",
                headers={
                    "X-API-Key": settings.HOICHOI_API_KEY,
                    "X-Partner-ID": settings.HOICHOI_PARTNER_ID,
                },
                json={
                    "partner_user_id": str(subscriber.id),
                    "email": subscriber.email,
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        log.error("hoichoi_provision_error", error=str(exc))
        return {"error": str(exc)}


async def _chorki_revoke(entitlement: OTTEntitlement) -> dict[str, Any]:
    from app.config import get_settings
    settings = get_settings()

    if not settings.CHORKI_API_KEY:
        return {"status": "mock_revoked"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                f"{settings.CHORKI_BASE_URL}/v1/partner/provision/{entitlement.partner_subscription_id or entitlement.partner_user_id}",
                headers={
                    "Authorization": f"Bearer {settings.CHORKI_API_KEY}",
                    "X-Partner-ID": settings.CHORKI_PARTNER_ID,
                },
            )
            return {"status": "revoked", "code": resp.status_code}
    except Exception as exc:
        log.error("chorki_revoke_error", error=str(exc))
        return {"error": str(exc)}


async def _hoichoi_revoke(entitlement: OTTEntitlement) -> dict[str, Any]:
    from app.config import get_settings
    settings = get_settings()

    if not settings.HOICHOI_API_KEY:
        return {"status": "mock_revoked"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.HOICHOI_BASE_URL}/v1/partner/revoke",
                headers={"X-API-Key": settings.HOICHOI_API_KEY},
                json={"partner_user_id": entitlement.partner_user_id},
            )
            return {"status": "revoked", "code": resp.status_code}
    except Exception as exc:
        log.error("hoichoi_revoke_error", error=str(exc))
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# GET /ott/entitlements
# ---------------------------------------------------------------------------

@router.get("/entitlements", summary="List OTT entitlements")
async def list_entitlements(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    subscriber_id: Optional[uuid.UUID] = Query(None),
    partner: Optional[str] = Query(None),
) -> dict[str, Any]:
    q = select(OTTEntitlement)

    actor_type = user.get("type")
    if actor_type == "admin":
        if subscriber_id:
            q = q.where(OTTEntitlement.subscriber_id == subscriber_id)
    elif actor_type == "franchisee":
        fid = uuid.UUID(user["franchisee_id"])
        # Franchisee sees entitlements for their subscribers
        sub_ids_result = await db.execute(
            select(Subscriber.id).where(
                Subscriber.franchisee_id == fid,
                Subscriber.is_deleted == False,  # noqa: E712
            )
        )
        sub_ids = [r[0] for r in sub_ids_result.all()]
        q = q.where(OTTEntitlement.subscriber_id.in_(sub_ids))
        if subscriber_id:
            assert_franchisee_scope(user, str(fid))  # already checked above
            q = q.where(OTTEntitlement.subscriber_id == subscriber_id)
    else:
        # Subscriber sees only their own
        sid = uuid.UUID(user["sub"])
        q = q.where(OTTEntitlement.subscriber_id == sid)

    if partner:
        q = q.where(OTTEntitlement.partner == partner)

    q = q.order_by(OTTEntitlement.provisioned_at.desc())
    rows = await db.execute(q)

    def _ent_dict(e: OTTEntitlement) -> dict[str, Any]:
        return {
            "id": str(e.id),
            "subscriber_id": str(e.subscriber_id),
            "partner": e.partner,
            "partner_user_id": e.partner_user_id,
            "partner_subscription_id": e.partner_subscription_id,
            "status": e.status,
            "provisioned_at": e.provisioned_at.isoformat() if e.provisioned_at else None,
            "expires_at": e.expires_at.isoformat() if e.expires_at else None,
            "revoked_at": e.revoked_at.isoformat() if e.revoked_at else None,
        }

    items = [_ent_dict(e) for e in rows.scalars()]
    return {"total": len(items), "items": items}


# ---------------------------------------------------------------------------
# GET /ott/launch/{partner}
# ---------------------------------------------------------------------------

@router.get("/launch/{partner}", summary="Generate SSO URL for OTT partner")
async def launch_ott(
    partner: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if partner not in _SUPPORTED_PARTNERS:
        raise HTTPException(status_code=400, detail=f"Unsupported partner. Must be one of {_SUPPORTED_PARTNERS}")

    actor_type = user.get("type")
    if actor_type != "subscriber":
        raise HTTPException(status_code=403, detail="Only subscribers can launch OTT sessions")

    sid = uuid.UUID(user["sub"])
    sub_result = await db.execute(
        select(Subscriber).where(Subscriber.id == sid, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = sub_result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    # Get or create entitlement record
    ent_result = await db.execute(
        select(OTTEntitlement).where(
            OTTEntitlement.subscriber_id == sid,
            OTTEntitlement.partner == partner,
            OTTEntitlement.status == "active",
        ).order_by(OTTEntitlement.provisioned_at.desc()).limit(1)
    )
    entitlement = ent_result.scalar_one_or_none()

    created = False
    if entitlement is None:
        entitlement = OTTEntitlement(
            subscriber_id=sub.id,
            partner=partner,
            status="active",
            provisioned_at=datetime.now(timezone.utc),
        )
        db.add(entitlement)
        await db.flush()
        created = True

    # Generate SSO URL
    if partner == "chorki":
        sso_url = await _chorki_generate_sso(sub, entitlement)
    else:
        sso_url = await _hoichoi_generate_sso(sub, entitlement)

    if created:
        await db.commit()

    log.info("ott_sso_generated", subscriber_id=str(sub.id), partner=partner)
    return {
        "partner": partner,
        "sso_url": sso_url,
        "entitlement_id": str(entitlement.id) if entitlement.id else None,
    }


# ---------------------------------------------------------------------------
# POST /ott/provision
# ---------------------------------------------------------------------------

@router.post("/provision", status_code=status.HTTP_201_CREATED, summary="Manually provision OTT entitlement")
async def provision_ott(
    body: OTTProvisionRequest,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if body.partner not in _SUPPORTED_PARTNERS:
        raise HTTPException(status_code=400, detail=f"Unsupported partner. Must be one of {_SUPPORTED_PARTNERS}")

    sub_result = await db.execute(
        select(Subscriber).where(
            Subscriber.id == body.subscriber_id,
            Subscriber.is_deleted == False,  # noqa: E712
        )
    )
    sub = sub_result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    if user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(sub.franchisee_id))

    # Check if already active
    existing = await db.execute(
        select(OTTEntitlement).where(
            OTTEntitlement.subscriber_id == sub.id,
            OTTEntitlement.partner == body.partner,
            OTTEntitlement.status == "active",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Active {body.partner} entitlement already exists")

    # Call partner API
    if body.partner == "chorki":
        partner_resp = await _chorki_provision(sub)
    else:
        partner_resp = await _hoichoi_provision(sub)

    entitlement = OTTEntitlement(
        subscriber_id=sub.id,
        partner=body.partner,
        status="active",
        provisioned_at=datetime.now(timezone.utc),
        partner_user_id=partner_resp.get("user_id") or str(sub.id),
        partner_subscription_id=partner_resp.get("subscription_id"),
        partner_response=partner_resp,
    )
    db.add(entitlement)

    db.add(AuditLog(
        actor_type=user.get("type", "franchisee"),
        actor_email=user.get("email"),
        action="ott.provision",
        resource_type="ott_entitlement",
        resource_id=sub.id,
        new_values={"partner": body.partner, "subscriber_id": str(sub.id)},
        success=True,
    ))

    await db.commit()
    await db.refresh(entitlement)

    log.info("ott_provisioned", subscriber_id=str(sub.id), partner=body.partner)
    return {
        "id": str(entitlement.id),
        "subscriber_id": str(sub.id),
        "partner": body.partner,
        "status": entitlement.status,
        "provisioned_at": entitlement.provisioned_at.isoformat(),
        "partner_response": partner_resp,
    }


# ---------------------------------------------------------------------------
# POST /ott/revoke/{entitlement_id}
# ---------------------------------------------------------------------------

@router.post("/revoke/{entitlement_id}", summary="Revoke OTT entitlement")
async def revoke_ott(
    entitlement_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(OTTEntitlement).where(OTTEntitlement.id == entitlement_id))
    entitlement = result.scalar_one_or_none()
    if entitlement is None:
        raise HTTPException(status_code=404, detail="Entitlement not found")

    # Verify subscriber belongs to franchisee
    sub_result = await db.execute(
        select(Subscriber).where(Subscriber.id == entitlement.subscriber_id)
    )
    sub = sub_result.scalar_one_or_none()
    if sub and user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(sub.franchisee_id))

    if entitlement.status == "revoked":
        raise HTTPException(status_code=409, detail="Entitlement already revoked")

    # Call partner revoke API
    if entitlement.partner == "chorki":
        revoke_resp = await _chorki_revoke(entitlement)
    else:
        revoke_resp = await _hoichoi_revoke(entitlement)

    entitlement.status = "revoked"
    entitlement.revoked_at = datetime.now(timezone.utc)
    entitlement.partner_response = revoke_resp

    db.add(AuditLog(
        actor_type=user.get("type", "franchisee"),
        actor_email=user.get("email"),
        action="ott.revoke",
        resource_type="ott_entitlement",
        resource_id=entitlement_id,
        new_values={"status": "revoked", "partner": entitlement.partner},
        success=True,
    ))

    await db.commit()
    log.info("ott_revoked", entitlement_id=str(entitlement_id), partner=entitlement.partner)

    return {
        "id": str(entitlement.id),
        "status": entitlement.status,
        "revoked_at": entitlement.revoked_at.isoformat(),
        "partner_response": revoke_resp,
    }
