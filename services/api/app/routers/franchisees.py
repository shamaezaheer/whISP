"""
Franchisee management router for whISP.

Handles CRUD, approval workflow, credit, staff user management,
and MikroTik config generation.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    Franchisee,
    FranchiseeUser as FranchiseeUserModel,
    NASDevice,
)
from app.services.auth import (
    AdminUser,
    CurrentUser,
    FranchiseeUser as FranchiseeUserDep,
    assert_franchisee_scope,
    get_db_conn,
)
from app.services.crypto import generate_radius_secret, hash_password
from app.services.radius import upsert_nas

log = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FranchiseeCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    contact_email: EmailStr
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    district: Optional[str] = None
    division: Optional[str] = None
    bandwidth_pool_mbps: int = 100
    ip_pool_name: Optional[str] = None
    commission_rate: float = Field(0.0, ge=0, le=100)
    settings: Optional[dict] = None


class FranchiseeUpdate(BaseModel):
    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    district: Optional[str] = None
    division: Optional[str] = None
    bandwidth_pool_mbps: Optional[int] = None
    ip_pool_name: Optional[str] = None
    commission_rate: Optional[float] = None
    settings: Optional[dict] = None


class CreditRequest(BaseModel):
    amount: float = Field(..., gt=0)
    notes: Optional[str] = None


class FranchiseeUserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone: Optional[str] = None
    password: str = Field(..., min_length=8)
    role: str = "support"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


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
    db.add(AuditLog(
        actor_id=actor_id,
        actor_type=user.get("type", "system"),
        actor_email=user.get("email"),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_values=old_values,
        new_values=new_values,
        success=True,
    ))


def _franchisee_to_dict(f: Franchisee, include_sensitive: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(f.id),
        "name": f.name,
        "slug": f.slug,
        "contact_email": f.contact_email,
        "contact_phone": f.contact_phone,
        "address": f.address,
        "district": f.district,
        "division": f.division,
        "bandwidth_pool_mbps": f.bandwidth_pool_mbps,
        "ip_pool_name": f.ip_pool_name,
        "status": f.status,
        "approved_at": f.approved_at.isoformat() if f.approved_at else None,
        "settings": f.settings,
        "created_at": f.created_at.isoformat(),
        "updated_at": f.updated_at.isoformat(),
    }
    if include_sensitive:
        d["balance"] = float(f.balance)
        d["commission_rate"] = float(f.commission_rate)
        d["radius_secret"] = f.radius_secret
    return d


# ---------------------------------------------------------------------------
# GET /franchisees
# ---------------------------------------------------------------------------

@router.get("", summary="List franchisees (admin only)")
async def list_franchisees(
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
) -> dict[str, Any]:
    q = select(Franchisee)
    if status_filter:
        q = q.where(Franchisee.status == status_filter)
    q = q.offset(offset).limit(limit).order_by(Franchisee.created_at.desc())

    from sqlalchemy import func
    count_q = select(func.count(Franchisee.id))
    if status_filter:
        count_q = count_q.where(Franchisee.status == status_filter)
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    rows = await db.execute(q)
    items = [_franchisee_to_dict(f, include_sensitive=True) for f in rows.scalars()]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------------------
# GET /franchisees/{id}
# ---------------------------------------------------------------------------

@router.get("/{franchisee_id}", summary="Get franchisee detail")
async def get_franchisee(
    franchisee_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert_franchisee_scope(user, str(franchisee_id))

    result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    include_sensitive = user.get("type") in ("admin", "franchisee")
    return _franchisee_to_dict(f, include_sensitive=include_sensitive)


# ---------------------------------------------------------------------------
# POST /franchisees
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, summary="Create franchisee (admin only)")
async def create_franchisee(
    body: FranchiseeCreate,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    slug = _slugify(body.name)

    # Ensure slug uniqueness
    for attempt in range(10):
        existing = await db.execute(select(Franchisee).where(Franchisee.slug == slug))
        if not existing.scalar_one_or_none():
            break
        slug = f"{slug}-{attempt + 2}"

    radius_secret = generate_radius_secret(20)

    f = Franchisee(
        name=body.name,
        slug=slug,
        contact_email=body.contact_email.lower(),
        contact_phone=body.contact_phone,
        address=body.address,
        district=body.district,
        division=body.division,
        radius_secret=radius_secret,
        bandwidth_pool_mbps=body.bandwidth_pool_mbps,
        ip_pool_name=body.ip_pool_name,
        commission_rate=body.commission_rate,
        status="pending",
        balance=0,
        settings=body.settings or {},
    )
    db.add(f)
    await db.flush()
    _log_audit(db, user, "franchisee.create", "franchisee", f.id, new_values={"name": body.name, "slug": slug})
    await db.commit()
    await db.refresh(f)

    log.info("franchisee_created", franchisee_id=str(f.id), slug=slug)
    return _franchisee_to_dict(f, include_sensitive=True)


# ---------------------------------------------------------------------------
# PATCH /franchisees/{id}
# ---------------------------------------------------------------------------

@router.patch("/{franchisee_id}", summary="Update franchisee (admin only)")
async def update_franchisee(
    franchisee_id: uuid.UUID,
    body: FranchiseeUpdate,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    old_values: dict[str, Any] = {}
    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        old_values[field] = getattr(f, field)
        if field == "contact_email":
            value = value.lower()
        setattr(f, field, value)

    _log_audit(db, user, "franchisee.update", "franchisee", f.id, old_values=old_values, new_values=update_data)
    await db.commit()
    await db.refresh(f)

    return _franchisee_to_dict(f, include_sensitive=True)


# ---------------------------------------------------------------------------
# POST /franchisees/{id}/approve
# ---------------------------------------------------------------------------

@router.post("/{franchisee_id}/approve", summary="Approve franchisee (admin only)")
async def approve_franchisee(
    franchisee_id: uuid.UUID,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    f.status = "active"
    f.approved_at = datetime.now(timezone.utc)

    actor_id_str = user.get("sub")
    if actor_id_str and actor_id_str != "admin":
        try:
            f.approved_by = uuid.UUID(actor_id_str)
        except ValueError:
            pass

    _log_audit(db, user, "franchisee.approve", "franchisee", f.id, new_values={"status": "active"})
    await db.commit()
    await db.refresh(f)

    log.info("franchisee_approved", franchisee_id=str(f.id))
    return {"id": str(f.id), "status": f.status, "approved_at": f.approved_at.isoformat()}


# ---------------------------------------------------------------------------
# POST /franchisees/{id}/suspend
# ---------------------------------------------------------------------------

@router.post("/{franchisee_id}/suspend", summary="Suspend franchisee (admin only)")
async def suspend_franchisee(
    franchisee_id: uuid.UUID,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    old_status = f.status
    f.status = "suspended"
    _log_audit(db, user, "franchisee.suspend", "franchisee", f.id,
               old_values={"status": old_status}, new_values={"status": "suspended"})
    await db.commit()
    log.info("franchisee_suspended", franchisee_id=str(f.id))
    return {"id": str(f.id), "status": f.status}


# ---------------------------------------------------------------------------
# POST /franchisees/{id}/reactivate
# ---------------------------------------------------------------------------

@router.post("/{franchisee_id}/reactivate", summary="Reactivate franchisee (admin only)")
async def reactivate_franchisee(
    franchisee_id: uuid.UUID,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    old_status = f.status
    f.status = "active"
    _log_audit(db, user, "franchisee.reactivate", "franchisee", f.id,
               old_values={"status": old_status}, new_values={"status": "active"})
    await db.commit()
    log.info("franchisee_reactivated", franchisee_id=str(f.id))
    return {"id": str(f.id), "status": f.status}


# ---------------------------------------------------------------------------
# POST /franchisees/{id}/rotate-secret
# ---------------------------------------------------------------------------

@router.post("/{franchisee_id}/rotate-secret", summary="Rotate RADIUS secret")
async def rotate_radius_secret(
    franchisee_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    assert_franchisee_scope(user, str(franchisee_id))

    result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    new_secret = generate_radius_secret(20)
    old_secret = f.radius_secret
    f.radius_secret = new_secret
    await db.flush()

    # Re-sync all NAS devices for this franchisee
    nas_result = await db.execute(
        select(NASDevice).where(NASDevice.franchisee_id == franchisee_id)
    )
    nas_devices = nas_result.scalars().all()
    for nas in nas_devices:
        nas.secret = new_secret
        try:
            await upsert_nas(
                conn=conn,
                nasname=nas.ip_address,
                shortname=nas.name,
                secret=new_secret,
                nas_type=nas.nas_type,
                description=nas.description or "",
            )
        except Exception as exc:
            log.error("nas_secret_rotate_failed", nas_id=str(nas.id), error=str(exc))

    _log_audit(db, user, "franchisee.rotate_secret", "franchisee", f.id)
    await db.commit()

    log.info("radius_secret_rotated", franchisee_id=str(f.id))
    return {"id": str(f.id), "radius_secret": new_secret, "nas_updated": len(nas_devices)}


# ---------------------------------------------------------------------------
# POST /franchisees/{id}/credit
# ---------------------------------------------------------------------------

@router.post("/{franchisee_id}/credit", summary="Credit franchisee balance (admin only)")
async def credit_franchisee(
    franchisee_id: uuid.UUID,
    body: CreditRequest,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    old_balance = float(f.balance)
    f.balance = float(f.balance) + body.amount
    new_balance = float(f.balance)

    _log_audit(db, user, "franchisee.credit", "franchisee", f.id,
               old_values={"balance": old_balance},
               new_values={"balance": new_balance, "credited": body.amount, "notes": body.notes})
    await db.commit()
    await db.refresh(f)

    log.info("franchisee_credited", franchisee_id=str(f.id), amount=body.amount)
    return {"id": str(f.id), "balance": float(f.balance), "credited": body.amount}


# ---------------------------------------------------------------------------
# GET /franchisees/{id}/users
# ---------------------------------------------------------------------------

@router.get("/{franchisee_id}/users", summary="List franchisee staff users")
async def list_franchisee_users(
    franchisee_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert_franchisee_scope(user, str(franchisee_id))

    result = await db.execute(
        select(FranchiseeUserModel)
        .where(FranchiseeUserModel.franchisee_id == franchisee_id)
        .order_by(FranchiseeUserModel.created_at.desc())
    )
    users = result.scalars().all()

    items = [
        {
            "id": str(u.id),
            "franchisee_id": str(u.franchisee_id),
            "name": u.name,
            "email": u.email,
            "phone": u.phone,
            "role": u.role,
            "is_active": u.is_active,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]
    return {"franchisee_id": str(franchisee_id), "total": len(items), "items": items}


# ---------------------------------------------------------------------------
# POST /franchisees/{id}/users
# ---------------------------------------------------------------------------

@router.post("/{franchisee_id}/users", status_code=status.HTTP_201_CREATED, summary="Create franchisee staff user")
async def create_franchisee_user(
    franchisee_id: uuid.UUID,
    body: FranchiseeUserCreate,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert_franchisee_scope(user, str(franchisee_id))

    # Validate franchisee exists
    f_result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    if not f_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Franchisee not found")

    # Check email uniqueness
    existing = await db.execute(
        select(FranchiseeUserModel).where(FranchiseeUserModel.email == body.email.lower())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    valid_roles = ("owner", "manager", "support")
    if body.role not in valid_roles:
        raise HTTPException(status_code=422, detail=f"Role must be one of {valid_roles}")

    fu = FranchiseeUserModel(
        franchisee_id=franchisee_id,
        name=body.name,
        email=body.email.lower(),
        phone=body.phone,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(fu)
    _log_audit(db, user, "franchisee_user.create", "franchisee_user", franchisee_id,
               new_values={"email": body.email, "role": body.role})
    await db.commit()
    await db.refresh(fu)

    log.info("franchisee_user_created", user_id=str(fu.id), franchisee_id=str(franchisee_id))
    return {
        "id": str(fu.id),
        "franchisee_id": str(fu.franchisee_id),
        "name": fu.name,
        "email": fu.email,
        "role": fu.role,
        "is_active": fu.is_active,
    }


# ---------------------------------------------------------------------------
# DELETE /franchisees/{id}/users/{user_id}
# ---------------------------------------------------------------------------

@router.delete("/{franchisee_id}/users/{franchisee_user_id}",
               status_code=status.HTTP_204_NO_CONTENT,
               response_model=None,
               summary="Deactivate franchisee staff user")
async def deactivate_franchisee_user(
    franchisee_id: uuid.UUID,
    franchisee_user_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> None:
    assert_franchisee_scope(user, str(franchisee_id))

    result = await db.execute(
        select(FranchiseeUserModel).where(
            FranchiseeUserModel.id == franchisee_user_id,
            FranchiseeUserModel.franchisee_id == franchisee_id,
        )
    )
    fu = result.scalar_one_or_none()
    if fu is None:
        raise HTTPException(status_code=404, detail="User not found")

    fu.is_active = False
    _log_audit(db, user, "franchisee_user.deactivate", "franchisee_user", franchisee_user_id)
    await db.commit()
    log.info("franchisee_user_deactivated", user_id=str(fu.id))


# ---------------------------------------------------------------------------
# GET /franchisees/{id}/mikrotik-config
# ---------------------------------------------------------------------------

@router.get("/{franchisee_id}/mikrotik-config", summary="Generate MikroTik RouterOS RADIUS config script")
async def get_mikrotik_config(
    franchisee_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> Response:
    assert_franchisee_scope(user, str(franchisee_id))

    result = await db.execute(select(Franchisee).where(Franchisee.id == franchisee_id))
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    from app.config import get_settings
    settings = get_settings()

    # Derive RADIUS server IP from the DATABASE_URL or use a platform setting
    radius_server_ip = getattr(settings, "RADIUS_SERVER_IP", "10.0.0.1")

    script = f"""# whISP - MikroTik RADIUS Configuration
# Generated for Franchisee: {f.name} ({f.slug})
# Generated at: {datetime.now(timezone.utc).isoformat()}
# !! Store this script securely - it contains your RADIUS shared secret !!

/radius remove [find]
/radius add address={radius_server_ip} secret={f.radius_secret} \\
    service=ppp authentication-port=1812 accounting-port=1813 \\
    timeout=3000ms called-format=mac src-address=0.0.0.0

/ppp profile set default use-radius=yes accounting=yes \\
    session-timeout=0 idle-timeout=0

/ip firewall filter remove [find comment="CoA from RADIUS"]
/ip firewall filter add chain=input protocol=udp dst-port=3799 \\
    action=accept comment="CoA from RADIUS" place-before=0

/interface pppoe-server server set accounting=yes

/radius incoming set accept=yes port=3799

# Pool: {f.ip_pool_name or "default"}
# Bandwidth limit: {f.bandwidth_pool_mbps} Mbps aggregate
"""

    return Response(content=script, media_type="text/plain; charset=utf-8")
