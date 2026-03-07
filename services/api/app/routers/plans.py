"""
Plan management router for whISP.

Plans are either platform-wide (franchisee_id=None) or scoped to a franchisee.
Speeds are synced to FreeRADIUS radgroupreply on create/update.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    Plan,
    Subscriber,
)
from app.services.auth import (
    AdminUser,
    CurrentUser,
    FranchiseeUser as FranchiseeUserDep,
    assert_franchisee_scope,
    get_db_conn,
)
from app.services.radius import sync_plan_group

log = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PlanCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    download_kbps: int = Field(..., gt=0)
    upload_kbps: int = Field(..., gt=0)
    quota_gb: Optional[int] = Field(None, gt=0)
    validity_days: int = Field(30, gt=0)
    price: float = Field(..., ge=0)
    currency: str = "BDT"
    ip_pool: Optional[str] = None
    ott_entitlements: Optional[list[str]] = None
    is_active: bool = True
    is_public: bool = True
    franchisee_id: Optional[uuid.UUID] = None


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    download_kbps: Optional[int] = Field(None, gt=0)
    upload_kbps: Optional[int] = Field(None, gt=0)
    quota_gb: Optional[int] = Field(None, gt=0)
    validity_days: Optional[int] = Field(None, gt=0)
    price: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = None
    ip_pool: Optional[str] = None
    ott_entitlements: Optional[list[str]] = None
    is_active: Optional[bool] = None
    is_public: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify_plan(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _radius_group_from_name(name: str) -> str:
    """Generate a FreeRADIUS group name from the plan name."""
    g = name.lower().strip()
    g = re.sub(r"[^a-z0-9_]", "_", g)
    g = re.sub(r"_+", "_", g).strip("_")
    return g or "default_group"


def _log_audit(
    db: AsyncSession,
    user: dict,
    action: str,
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
        resource_type="plan",
        resource_id=resource_id,
        old_values=old_values,
        new_values=new_values,
        success=True,
    ))


def _plan_to_dict(p: Plan) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "slug": p.slug,
        "description": p.description,
        "download_kbps": p.download_kbps,
        "upload_kbps": p.upload_kbps,
        "quota_gb": p.quota_gb,
        "validity_days": p.validity_days,
        "price": float(p.price),
        "currency": p.currency,
        "radius_group": p.radius_group,
        "ip_pool": p.ip_pool,
        "ott_entitlements": p.ott_entitlements or [],
        "is_active": p.is_active,
        "is_public": p.is_public,
        "franchisee_id": str(p.franchisee_id) if p.franchisee_id else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /plans
# ---------------------------------------------------------------------------

@router.get("", summary="List plans")
async def list_plans(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    is_active: Optional[bool] = Query(None),
) -> dict[str, Any]:
    q = select(Plan)

    actor_type = user.get("type")
    if actor_type == "admin":
        # Admin sees all plans
        pass
    elif actor_type == "franchisee":
        fid = uuid.UUID(user["franchisee_id"])
        # Franchisee sees global plans + their own
        q = q.where(
            or_(Plan.franchisee_id == None, Plan.franchisee_id == fid)  # noqa: E711
        )
    else:
        # Subscribers see only public active plans
        fid = uuid.UUID(user.get("franchisee_id", str(uuid.uuid4())))
        q = q.where(
            or_(Plan.franchisee_id == None, Plan.franchisee_id == fid),  # noqa: E711
            Plan.is_active == True,  # noqa: E712
            Plan.is_public == True,  # noqa: E712
        )

    if is_active is not None:
        q = q.where(Plan.is_active == is_active)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.offset(offset).limit(limit).order_by(Plan.price.asc())
    rows = await db.execute(q)
    items = [_plan_to_dict(p) for p in rows.scalars()]

    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------------------
# GET /plans/{id}
# ---------------------------------------------------------------------------

@router.get("/{plan_id}", summary="Get plan detail")
async def get_plan(
    plan_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    p = result.scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    # Franchisee scope check for scoped plans
    if p.franchisee_id and user.get("type") not in ("admin",):
        if user.get("type") == "franchisee":
            assert_franchisee_scope(user, str(p.franchisee_id))
        elif user.get("type") == "subscriber":
            # Subscriber can see the plan for their franchisee
            sub_fid = user.get("franchisee_id")
            if sub_fid != str(p.franchisee_id):
                raise HTTPException(status_code=403, detail="Access denied")

    return _plan_to_dict(p)


# ---------------------------------------------------------------------------
# POST /plans
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, summary="Create plan")
async def create_plan(
    body: PlanCreate,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    # Franchisee can only create plans scoped to themselves
    if user.get("type") == "franchisee":
        fid = uuid.UUID(user["franchisee_id"])
        if body.franchisee_id and body.franchisee_id != fid:
            raise HTTPException(status_code=403, detail="Cannot create plan for another franchisee")
        # Force scope to their own franchisee_id
        franchisee_id = fid
    else:
        # Admin can create global or scoped
        franchisee_id = body.franchisee_id

    slug = _slugify_plan(body.name)
    radius_group = _radius_group_from_name(body.name)

    # Ensure slug uniqueness
    for attempt in range(10):
        exists = await db.execute(select(Plan).where(Plan.slug == slug))
        if not exists.scalar_one_or_none():
            break
        slug = f"{slug}-{attempt + 2}"

    # Ensure radius_group uniqueness across plans
    for attempt in range(10):
        exists = await db.execute(select(Plan).where(Plan.radius_group == radius_group))
        if not exists.scalar_one_or_none():
            break
        radius_group = f"{radius_group}_{attempt + 2}"

    plan = Plan(
        name=body.name,
        slug=slug,
        description=body.description,
        download_kbps=body.download_kbps,
        upload_kbps=body.upload_kbps,
        quota_gb=body.quota_gb,
        validity_days=body.validity_days,
        price=body.price,
        currency=body.currency,
        radius_group=radius_group,
        ip_pool=body.ip_pool,
        ott_entitlements=body.ott_entitlements or [],
        is_active=body.is_active,
        is_public=body.is_public,
        franchisee_id=franchisee_id,
    )
    db.add(plan)
    await db.flush()

    # Sync to FreeRADIUS radgroupreply
    try:
        await sync_plan_group(conn, plan)
    except Exception as exc:
        log.error("radius_plan_group_sync_failed", error=str(exc), plan_id=str(plan.id))

    _log_audit(db, user, "plan.create", plan.id, new_values={"name": body.name, "slug": slug})
    await db.commit()
    await db.refresh(plan)

    log.info("plan_created", plan_id=str(plan.id), slug=slug, radius_group=radius_group)
    return _plan_to_dict(plan)


# ---------------------------------------------------------------------------
# PATCH /plans/{id}
# ---------------------------------------------------------------------------

@router.patch("/{plan_id}", summary="Update plan")
async def update_plan(
    plan_id: uuid.UUID,
    body: PlanUpdate,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.franchisee_id and user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(plan.franchisee_id))

    # Deactivation guard: block if active subscribers
    if body.is_active is False and plan.is_active:
        active_count = await db.execute(
            select(func.count(Subscriber.id)).where(
                Subscriber.plan_id == plan_id,
                Subscriber.status == "active",
                Subscriber.is_deleted == False,  # noqa: E712
            )
        )
        count = active_count.scalar_one()
        if count > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot deactivate plan: {count} active subscriber(s) using it",
            )

    old_values = _plan_to_dict(plan)
    speeds_changed = False

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if field in ("download_kbps", "upload_kbps"):
            speeds_changed = True
        setattr(plan, field, value)

    await db.flush()

    # Re-sync RADIUS group if speeds changed
    if speeds_changed:
        try:
            await sync_plan_group(conn, plan)
        except Exception as exc:
            log.error("radius_plan_group_sync_failed_on_update", error=str(exc))

    _log_audit(db, user, "plan.update", plan.id, old_values=old_values, new_values=update_data)
    await db.commit()
    await db.refresh(plan)

    return _plan_to_dict(plan)


# ---------------------------------------------------------------------------
# DELETE /plans/{id}
# ---------------------------------------------------------------------------

@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Deactivate (soft-delete) plan")
async def delete_plan(
    plan_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.franchisee_id and user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(plan.franchisee_id))

    # Block if active subscribers on plan
    active_count = await db.execute(
        select(func.count(Subscriber.id)).where(
            Subscriber.plan_id == plan_id,
            Subscriber.status == "active",
            Subscriber.is_deleted == False,  # noqa: E712
        )
    )
    count = active_count.scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete plan: {count} active subscriber(s) still on this plan",
        )

    plan.is_active = False
    _log_audit(db, user, "plan.delete", plan.id, old_values={"is_active": True}, new_values={"is_active": False})
    await db.commit()
    log.info("plan_deactivated", plan_id=str(plan.id))
