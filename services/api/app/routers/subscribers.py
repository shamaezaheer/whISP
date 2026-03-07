"""
Subscriber management router for whISP.

All subscriber operations are scoped to the caller's franchisee.
Admins can view/manage all subscribers.
"""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    CoACommand,
    FranchiseeUser as FranchiseeUserModel,
    NASDevice,
    OTTEntitlement,
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
from app.services.crypto import decrypt_field, encrypt_field, hash_password
from app.services.radius import remove_subscriber, sync_subscriber

log = structlog.get_logger(__name__)
router = APIRouter()

_USERNAME_ALPHABET = string.ascii_lowercase + string.digits


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SubscriberCreate(BaseModel):
    franchisee_id: uuid.UUID
    plan_id: Optional[uuid.UUID] = None
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone: Optional[str] = None
    nid: Optional[str] = None
    address: Optional[str] = None
    username: Optional[str] = None
    pppoe_password: Optional[str] = None  # cleartext, will be encrypted
    portal_password: Optional[str] = None
    custom_fields: Optional[dict] = None


class SubscriberUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    plan_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    custom_fields: Optional[dict] = None


class PasswordResetRequest(BaseModel):
    pppoe_password: Optional[str] = None
    portal_password: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_username(prefix: str = "user") -> str:
    suffix = "".join(secrets.choice(_USERNAME_ALPHABET) for _ in range(6))
    return f"{prefix}{suffix}"


def _generate_pppoe_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _get_nas_for_franchisee(
    db: AsyncSession, franchisee_id: uuid.UUID
) -> Optional[NASDevice]:
    result = await db.execute(
        select(NASDevice).where(
            NASDevice.franchisee_id == franchisee_id,
            NASDevice.is_active == True,  # noqa: E712
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def _send_coa_disconnect_for_subscriber(
    db: AsyncSession,
    conn: asyncpg.Connection,
    subscriber: Subscriber,
    user: dict,
) -> None:
    """Disconnect subscriber via CoA and log the command."""
    nas = await _get_nas_for_franchisee(db, subscriber.franchisee_id)
    if nas is None:
        log.warning("no_active_nas_for_coa_disconnect", subscriber_id=str(subscriber.id))
        return

    try:
        success = await send_disconnect(
            nas_ip=nas.ip_address,
            nas_secret=nas.secret,
            username=subscriber.username,
            port=nas.coa_port,
        )
    except Exception as exc:
        log.error("coa_disconnect_error", error=str(exc), subscriber_id=str(subscriber.id))
        success = False
        error_msg = str(exc)
    else:
        error_msg = None if success else "CoA NAK or timeout"

    coa_cmd = CoACommand(
        nas_device_id=nas.id,
        subscriber_id=subscriber.id,
        command_type="disconnect",
        attributes={"username": subscriber.username},
        success=success,
        response={"result": "ack" if success else "nak"},
        error=error_msg,
    )
    db.add(coa_cmd)


async def _provision_ott_for_plan(
    db: AsyncSession,
    subscriber: Subscriber,
    plan: Plan,
) -> None:
    """Create OTTEntitlement records for each provider in the plan."""
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
        )
        db.add(entitlement)
    if providers:
        log.info("ott_entitlements_provisioned", subscriber_id=str(subscriber.id), providers=providers)


def _log_audit(
    db: AsyncSession,
    user: dict,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
) -> None:
    actor_id_str = user.get("sub")
    actor_id = None
    if actor_id_str and actor_id_str != "admin":
        try:
            actor_id = uuid.UUID(actor_id_str)
        except ValueError:
            pass

    audit = AuditLog(
        actor_id=actor_id,
        actor_type=user.get("type", "system"),
        actor_email=user.get("email"),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_values=old_values,
        new_values=new_values,
        success=True,
    )
    db.add(audit)


# ---------------------------------------------------------------------------
# GET /subscribers
# ---------------------------------------------------------------------------

@router.get("", summary="List subscribers")
async def list_subscribers(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None, description="Search by name, username, or phone"),
    franchisee_id: Optional[uuid.UUID] = Query(None),
) -> dict[str, Any]:
    q = select(Subscriber, Plan).outerjoin(Plan, Subscriber.plan_id == Plan.id).where(
        Subscriber.is_deleted == False  # noqa: E712
    )

    if user.get("type") == "admin":
        if franchisee_id:
            q = q.where(Subscriber.franchisee_id == franchisee_id)
    elif user.get("type") == "franchisee":
        fid = uuid.UUID(user["franchisee_id"])
        q = q.where(Subscriber.franchisee_id == fid)
    else:
        # subscriber: can only see themselves
        sid = uuid.UUID(user["sub"])
        q = q.where(Subscriber.id == sid)

    if status_filter:
        q = q.where(Subscriber.status == status_filter)

    if search:
        pattern = f"%{search}%"
        from sqlalchemy import or_
        q = q.where(
            or_(
                Subscriber.name.ilike(pattern),
                Subscriber.username.ilike(pattern),
                Subscriber.phone.ilike(pattern),
                Subscriber.email.ilike(pattern),
            )
        )

    count_q = select(func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.offset(offset).limit(limit).order_by(Subscriber.created_at.desc())
    rows = await db.execute(q)
    results = rows.all()

    items = []
    for sub, plan in results:
        items.append({
            "id": str(sub.id),
            "franchisee_id": str(sub.franchisee_id),
            "name": sub.name,
            "email": sub.email,
            "phone": sub.phone,
            "username": sub.username,
            "status": sub.status,
            "plan_id": str(sub.plan_id) if sub.plan_id else None,
            "plan_name": plan.name if plan else None,
            "plan_expires_at": sub.plan_expires_at.isoformat() if sub.plan_expires_at else None,
            "quota_used_bytes": sub.quota_used_bytes,
            "created_at": sub.created_at.isoformat(),
        })

    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------------------
# GET /subscribers/{id}
# ---------------------------------------------------------------------------

@router.get("/{subscriber_id}", summary="Get subscriber detail")
async def get_subscriber(
    subscriber_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    assert_subscriber_scope(user, str(subscriber_id))

    result = await db.execute(
        select(Subscriber, Plan)
        .outerjoin(Plan, Subscriber.plan_id == Plan.id)
        .where(Subscriber.id == subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    sub, plan = row

    if user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(sub.franchisee_id))

    # Fetch active RADIUS session
    session = await conn.fetchrow(
        """
        SELECT radacctid, acctsessionid, nasipaddress, framedipaddress,
               acctstarttime, acctsessiontime, acctinputoctets, acctoutputoctets,
               callingstationid
        FROM radacct
        WHERE username = $1 AND acctstoptime IS NULL
        ORDER BY acctstarttime DESC
        LIMIT 1
        """,
        sub.username,
    )

    return {
        "id": str(sub.id),
        "franchisee_id": str(sub.franchisee_id),
        "name": sub.name,
        "email": sub.email,
        "phone": sub.phone,
        "nid": sub.nid,
        "address": sub.address,
        "username": sub.username,
        "status": sub.status,
        "plan_id": str(sub.plan_id) if sub.plan_id else None,
        "plan": {
            "id": str(plan.id),
            "name": plan.name,
            "download_kbps": plan.download_kbps,
            "upload_kbps": plan.upload_kbps,
            "quota_gb": plan.quota_gb,
            "validity_days": plan.validity_days,
            "price": float(plan.price),
        } if plan else None,
        "plan_expires_at": sub.plan_expires_at.isoformat() if sub.plan_expires_at else None,
        "quota_used_bytes": sub.quota_used_bytes,
        "bkash_agreement_id": sub.bkash_agreement_id,
        "custom_fields": sub.custom_fields,
        "created_at": sub.created_at.isoformat(),
        "updated_at": sub.updated_at.isoformat(),
        "active_session": dict(session) if session else None,
    }


# ---------------------------------------------------------------------------
# POST /subscribers
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, summary="Create subscriber")
async def create_subscriber(
    body: SubscriberCreate,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    assert_franchisee_scope(user, str(body.franchisee_id))

    # Deduplicate email
    existing = await db.execute(
        select(Subscriber).where(
            Subscriber.email == body.email.lower(),
            Subscriber.is_deleted == False,  # noqa: E712
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Auto-generate username if not provided
    username = (body.username or "").strip().lower()
    if not username:
        base = body.name.split()[0].lower()[:6]
        username = _generate_username(base)
    # Ensure uniqueness
    for _ in range(5):
        exists = await db.execute(
            select(Subscriber).where(Subscriber.username == username)
        )
        if not exists.scalar_one_or_none():
            break
        username = _generate_username()

    # Resolve plan
    plan: Optional[Plan] = None
    if body.plan_id:
        plan_result = await db.execute(select(Plan).where(Plan.id == body.plan_id))
        plan = plan_result.scalar_one_or_none()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

    # Passwords
    pppoe_cleartext = body.pppoe_password or _generate_pppoe_password()
    portal_pwd = body.portal_password or pppoe_cleartext

    sub = Subscriber(
        franchisee_id=body.franchisee_id,
        plan_id=body.plan_id,
        name=body.name,
        email=body.email.lower(),
        phone=body.phone,
        nid=body.nid,
        address=body.address,
        username=username,
        password_hash=hash_password(pppoe_cleartext),
        pppoe_password_enc=encrypt_field(pppoe_cleartext),
        portal_password_hash=hash_password(portal_pwd),
        status="pending",
        quota_used_bytes=0,
        custom_fields=body.custom_fields or {},
    )

    if plan:
        sub.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=plan.validity_days)
        sub.status = "active"

    db.add(sub)
    await db.flush()

    # Sync to RADIUS
    if plan:
        try:
            await sync_subscriber(conn, sub)
        except Exception as exc:
            log.error("radius_sync_failed_on_create", error=str(exc), subscriber_id=str(sub.id))

    # Provision OTT entitlements if plan has them
    if plan and plan.ott_entitlements:
        await _provision_ott_for_plan(db, sub, plan)

    _log_audit(db, user, "subscriber.create", "subscriber", sub.id, new_values={"username": username, "email": body.email})

    await db.commit()
    await db.refresh(sub)

    log.info("subscriber_created", subscriber_id=str(sub.id), username=username)

    return {
        "id": str(sub.id),
        "username": sub.username,
        "status": sub.status,
        "pppoe_password": pppoe_cleartext,  # returned only on creation
        "portal_password": portal_pwd,
        "message": "Subscriber created successfully",
    }


# ---------------------------------------------------------------------------
# PATCH /subscribers/{id}
# ---------------------------------------------------------------------------

@router.patch("/{subscriber_id}", summary="Update subscriber")
async def update_subscriber(
    subscriber_id: uuid.UUID,
    body: SubscriberUpdate,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    result = await db.execute(
        select(Subscriber).where(Subscriber.id == subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    assert_franchisee_scope(user, str(sub.franchisee_id))

    old_status = sub.status
    old_plan_id = sub.plan_id
    old_values = {"status": old_status, "plan_id": str(old_plan_id) if old_plan_id else None}

    if body.name is not None:
        sub.name = body.name
    if body.email is not None:
        sub.email = body.email.lower()
    if body.phone is not None:
        sub.phone = body.phone
    if body.address is not None:
        sub.address = body.address
    if body.custom_fields is not None:
        sub.custom_fields = body.custom_fields

    plan_changed = body.plan_id is not None and body.plan_id != old_plan_id
    status_changed = body.status is not None and body.status != old_status

    new_plan: Optional[Plan] = None
    if plan_changed:
        plan_result = await db.execute(select(Plan).where(Plan.id == body.plan_id))
        new_plan = plan_result.scalar_one_or_none()
        if not new_plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        sub.plan_id = body.plan_id
        sub.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=new_plan.validity_days)
        sub.quota_used_bytes = 0

    if status_changed:
        sub.status = body.status

    await db.flush()

    # RADIUS actions
    if plan_changed and new_plan:
        try:
            # Re-load plan relationship
            await db.refresh(sub)
            await sync_subscriber(conn, sub)
        except Exception as exc:
            log.error("radius_sync_failed_on_plan_change", error=str(exc))

    if status_changed and body.status == "suspended":
        await _send_coa_disconnect_for_subscriber(db, conn, sub, user)
    elif status_changed and body.status == "active":
        try:
            await db.refresh(sub)
            await sync_subscriber(conn, sub)
        except Exception as exc:
            log.error("radius_sync_failed_on_reactivation", error=str(exc))

    new_values = {"status": sub.status, "plan_id": str(sub.plan_id) if sub.plan_id else None}
    _log_audit(db, user, "subscriber.update", "subscriber", sub.id, old_values=old_values, new_values=new_values)

    await db.commit()
    await db.refresh(sub)

    return {"id": str(sub.id), "status": sub.status, "plan_id": str(sub.plan_id) if sub.plan_id else None}


# ---------------------------------------------------------------------------
# POST /subscribers/{id}/suspend
# ---------------------------------------------------------------------------

@router.post("/{subscriber_id}/suspend", summary="Suspend subscriber")
async def suspend_subscriber(
    subscriber_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    result = await db.execute(
        select(Subscriber).where(Subscriber.id == subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    assert_franchisee_scope(user, str(sub.franchisee_id))

    old_status = sub.status
    sub.status = "suspended"
    await db.flush()

    await _send_coa_disconnect_for_subscriber(db, conn, sub, user)
    _log_audit(db, user, "subscriber.suspend", "subscriber", sub.id,
               old_values={"status": old_status}, new_values={"status": "suspended"})

    await db.commit()
    log.info("subscriber_suspended", subscriber_id=str(sub.id))
    return {"id": str(sub.id), "status": sub.status, "message": "Subscriber suspended"}


# ---------------------------------------------------------------------------
# POST /subscribers/{id}/reactivate
# ---------------------------------------------------------------------------

@router.post("/{subscriber_id}/reactivate", summary="Reactivate subscriber")
async def reactivate_subscriber(
    subscriber_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    result = await db.execute(
        select(Subscriber).where(Subscriber.id == subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    assert_franchisee_scope(user, str(sub.franchisee_id))

    old_status = sub.status
    sub.status = "active"
    await db.flush()

    try:
        await db.refresh(sub)
        await sync_subscriber(conn, sub)
    except Exception as exc:
        log.error("radius_sync_failed_on_reactivate", error=str(exc))

    _log_audit(db, user, "subscriber.reactivate", "subscriber", sub.id,
               old_values={"status": old_status}, new_values={"status": "active"})

    await db.commit()
    log.info("subscriber_reactivated", subscriber_id=str(sub.id))
    return {"id": str(sub.id), "status": sub.status, "message": "Subscriber reactivated"}


# ---------------------------------------------------------------------------
# POST /subscribers/{id}/reset-password
# ---------------------------------------------------------------------------

@router.post("/{subscriber_id}/reset-password", summary="Reset PPPoE and portal passwords")
async def reset_password(
    subscriber_id: uuid.UUID,
    body: PasswordResetRequest,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    result = await db.execute(
        select(Subscriber).where(Subscriber.id == subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    assert_franchisee_scope(user, str(sub.franchisee_id))

    pppoe_cleartext = body.pppoe_password or _generate_pppoe_password()
    portal_cleartext = body.portal_password or pppoe_cleartext

    sub.password_hash = hash_password(pppoe_cleartext)
    sub.pppoe_password_enc = encrypt_field(pppoe_cleartext)
    sub.portal_password_hash = hash_password(portal_cleartext)
    await db.flush()

    try:
        await db.refresh(sub)
        await sync_subscriber(conn, sub)
    except Exception as exc:
        log.error("radius_sync_failed_on_password_reset", error=str(exc))

    _log_audit(db, user, "subscriber.reset_password", "subscriber", sub.id)

    await db.commit()
    log.info("subscriber_password_reset", subscriber_id=str(sub.id))

    return {
        "id": str(sub.id),
        "pppoe_password": pppoe_cleartext,
        "portal_password": portal_cleartext,
        "message": "Passwords reset successfully",
    }


# ---------------------------------------------------------------------------
# DELETE /subscribers/{id}
# ---------------------------------------------------------------------------

@router.delete("/{subscriber_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Soft-delete subscriber")
async def delete_subscriber(
    subscriber_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> None:
    result = await db.execute(
        select(Subscriber).where(Subscriber.id == subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    assert_franchisee_scope(user, str(sub.franchisee_id))

    sub.is_deleted = True
    sub.deleted_at = datetime.now(timezone.utc)
    sub.status = "terminated"
    await db.flush()

    try:
        await remove_subscriber(conn, sub.username)
    except Exception as exc:
        log.error("radius_remove_failed_on_delete", error=str(exc))

    _log_audit(db, user, "subscriber.delete", "subscriber", sub.id)

    await db.commit()
    log.info("subscriber_soft_deleted", subscriber_id=str(sub.id))


# ---------------------------------------------------------------------------
# GET /subscribers/{id}/sessions
# ---------------------------------------------------------------------------

@router.get("/{subscriber_id}/sessions", summary="Get active RADIUS sessions for subscriber")
async def get_subscriber_sessions(
    subscriber_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    assert_subscriber_scope(user, str(subscriber_id))

    result = await db.execute(
        select(Subscriber).where(Subscriber.id == subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    if user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(sub.franchisee_id))

    rows = await conn.fetch(
        """
        SELECT radacctid, acctsessionid, nasipaddress, framedipaddress,
               acctstarttime, acctsessiontime, acctinputoctets, acctoutputoctets,
               callingstationid, acctterminatecause
        FROM radacct
        WHERE username = $1 AND acctstoptime IS NULL
        ORDER BY acctstarttime DESC
        """,
        sub.username,
    )

    sessions = [dict(row) for row in rows]
    # Serialize datetime objects
    for s in sessions:
        for k, v in s.items():
            if isinstance(v, datetime):
                s[k] = v.isoformat()

    return {"subscriber_id": str(subscriber_id), "username": sub.username, "sessions": sessions}
