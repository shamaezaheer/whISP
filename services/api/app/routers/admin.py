"""
Admin-only management router for whISP.

Platform-wide statistics, audit log access, franchisee management,
broadcast notifications, and NAS health monitoring.
All endpoints require AdminUser dependency.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    Franchisee,
    FranchiseeUser as FranchiseeUserModel,
    NASDevice,
    Notification,
    PaymentTransaction,
    Subscriber,
    SupportTicket,
)
from app.services.auth import (
    AdminUser,
    get_db_conn,
)

log = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BroadcastRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    channel: str = "sms"
    franchisee_id: Optional[uuid.UUID] = None  # None = all franchisees


# ---------------------------------------------------------------------------
# GET /admin/stats
# ---------------------------------------------------------------------------

@router.get("/stats", summary="Platform-wide statistics")
async def platform_stats(
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    # Franchisee counts
    total_franchisees = (await db.execute(
        select(func.count(Franchisee.id))
    )).scalar_one()

    active_franchisees = (await db.execute(
        select(func.count(Franchisee.id)).where(Franchisee.status == "active")
    )).scalar_one()

    # Subscriber counts
    total_subscribers = (await db.execute(
        select(func.count(Subscriber.id)).where(Subscriber.is_deleted == False)  # noqa: E712
    )).scalar_one()

    active_subscribers = (await db.execute(
        select(func.count(Subscriber.id)).where(
            Subscriber.is_deleted == False,  # noqa: E712
            Subscriber.status == "active",
        )
    )).scalar_one()

    # Revenue this calendar month
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    revenue_row = await db.execute(
        select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
            PaymentTransaction.status == "completed",
            PaymentTransaction.completed_at >= month_start,
        )
    )
    total_revenue_month = float(revenue_row.scalar_one() or 0)

    # Active RADIUS sessions
    try:
        session_row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM radacct WHERE acctstoptime IS NULL"
        )
        active_sessions = int(session_row["cnt"]) if session_row else 0
    except Exception as exc:
        log.warning("admin_stats_radacct_query_failed", error=str(exc))
        active_sessions = 0

    # Open tickets
    open_tickets = (await db.execute(
        select(func.count(SupportTicket.id)).where(
            SupportTicket.status.in_(("open", "in_progress"))
        )
    )).scalar_one()

    return {
        "total_franchisees": total_franchisees,
        "active_franchisees": active_franchisees,
        "total_subscribers": total_subscribers,
        "active_subscribers": active_subscribers,
        "total_revenue_month": total_revenue_month,
        "active_sessions": active_sessions,
        "open_tickets": open_tickets,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /admin/franchisees
# ---------------------------------------------------------------------------

@router.get("/franchisees", summary="Admin view of all franchisees with financial details")
async def admin_list_franchisees(
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    franchisee_status: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
) -> dict[str, Any]:
    q = select(Franchisee)

    if franchisee_status:
        q = q.where(Franchisee.status == franchisee_status)

    if search:
        from sqlalchemy import or_
        pattern = f"%{search}%"
        q = q.where(
            or_(
                Franchisee.name.ilike(pattern),
                Franchisee.contact_email.ilike(pattern),
                Franchisee.slug.ilike(pattern),
                Franchisee.district.ilike(pattern),
            )
        )

    count_q = select(func.count(Franchisee.id))
    if franchisee_status:
        count_q = count_q.where(Franchisee.status == franchisee_status)
    total = (await db.execute(count_q)).scalar_one()

    q = q.offset(offset).limit(limit).order_by(Franchisee.created_at.desc())
    rows = await db.execute(q)

    def _f_dict(f: Franchisee) -> dict[str, Any]:
        return {
            "id": str(f.id),
            "name": f.name,
            "slug": f.slug,
            "contact_email": f.contact_email,
            "contact_phone": f.contact_phone,
            "district": f.district,
            "division": f.division,
            "status": f.status,
            "balance": float(f.balance),
            "commission_rate": float(f.commission_rate),
            "bandwidth_pool_mbps": f.bandwidth_pool_mbps,
            "approved_at": f.approved_at.isoformat() if f.approved_at else None,
            "created_at": f.created_at.isoformat(),
        }

    items = [_f_dict(f) for f in rows.scalars()]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------------------
# GET /admin/audit-logs
# ---------------------------------------------------------------------------

@router.get("/audit-logs", summary="Paginated audit log")
async def list_audit_logs(
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    actor_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
) -> dict[str, Any]:
    q = select(AuditLog)

    if actor_type:
        q = q.where(AuditLog.actor_type == actor_type)
    if action:
        q = q.where(AuditLog.action == action)
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    if success is not None:
        q = q.where(AuditLog.success == success)
    if from_date:
        q = q.where(AuditLog.created_at >= from_date)
    if to_date:
        q = q.where(AuditLog.created_at <= to_date)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.offset(offset).limit(limit).order_by(AuditLog.created_at.desc())
    rows = await db.execute(q)

    def _log_dict(al: AuditLog) -> dict[str, Any]:
        return {
            "id": str(al.id),
            "actor_id": str(al.actor_id) if al.actor_id else None,
            "actor_type": al.actor_type,
            "actor_email": al.actor_email,
            "action": al.action,
            "resource_type": al.resource_type,
            "resource_id": str(al.resource_id) if al.resource_id else None,
            "ip_address": al.ip_address,
            "request_id": al.request_id,
            "old_values": al.old_values,
            "new_values": al.new_values,
            "success": al.success,
            "error_message": al.error_message,
            "created_at": al.created_at.isoformat(),
        }

    items = [_log_dict(al) for al in rows.scalars()]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------------------
# POST /admin/broadcast
# ---------------------------------------------------------------------------

@router.post("/broadcast", status_code=status.HTTP_202_ACCEPTED, summary="Broadcast notification to subscribers")
async def broadcast_notification(
    body: BroadcastRequest,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    valid_channels = ("sms", "email", "push", "in_app")
    if body.channel not in valid_channels:
        raise HTTPException(status_code=422, detail=f"channel must be one of {valid_channels}")

    # Build subscriber query
    q = select(Subscriber.id, Subscriber.franchisee_id).where(
        Subscriber.is_deleted == False,  # noqa: E712
        Subscriber.status.in_(("active", "suspended")),
    )
    if body.franchisee_id:
        q = q.where(Subscriber.franchisee_id == body.franchisee_id)

    rows = await db.execute(q)
    subscriber_rows = rows.all()

    if not subscriber_rows:
        return {"queued": 0, "message": "No eligible subscribers found"}

    # Bulk-create Notification records
    notifications = [
        Notification(
            subscriber_id=sub_id,
            franchisee_id=fid,
            channel=body.channel,
            title=body.title,
            body=body.body,
            status="pending",
        )
        for sub_id, fid in subscriber_rows
    ]

    for n in notifications:
        db.add(n)

    db.add(AuditLog(
        actor_type="admin",
        actor_email=user.get("email"),
        action="admin.broadcast",
        resource_type="notification",
        new_values={
            "title": body.title,
            "channel": body.channel,
            "franchisee_id": str(body.franchisee_id) if body.franchisee_id else "all",
            "recipient_count": len(notifications),
        },
        success=True,
    ))

    await db.commit()

    log.info(
        "admin_broadcast_queued",
        count=len(notifications),
        channel=body.channel,
        franchisee_id=str(body.franchisee_id) if body.franchisee_id else "all",
    )

    return {
        "queued": len(notifications),
        "channel": body.channel,
        "franchisee_id": str(body.franchisee_id) if body.franchisee_id else "all",
        "message": f"{len(notifications)} notifications queued for delivery",
    }


# ---------------------------------------------------------------------------
# GET /admin/nas-health
# ---------------------------------------------------------------------------

@router.get("/nas-health", summary="NAS device health overview")
async def nas_health(
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
    franchisee_id: Optional[uuid.UUID] = Query(None),
) -> dict[str, Any]:
    q = select(NASDevice, Franchisee).join(Franchisee, NASDevice.franchisee_id == Franchisee.id)

    if franchisee_id:
        q = q.where(NASDevice.franchisee_id == franchisee_id)

    q = q.order_by(NASDevice.last_seen_at.desc().nulls_last())
    rows = await db.execute(q)

    now = datetime.now(timezone.utc)
    devices = []
    for nas, f in rows.all():
        # Determine health status based on last_seen_at
        if nas.last_seen_at is None:
            health = "unknown"
        else:
            minutes_since_seen = (now - nas.last_seen_at.replace(tzinfo=timezone.utc)).total_seconds() / 60
            if minutes_since_seen < 5:
                health = "healthy"
            elif minutes_since_seen < 15:
                health = "warning"
            else:
                health = "offline"

        devices.append({
            "id": str(nas.id),
            "franchisee_id": str(nas.franchisee_id),
            "franchisee_name": f.name,
            "name": nas.name,
            "ip_address": nas.ip_address,
            "nas_type": nas.nas_type,
            "is_active": nas.is_active,
            "last_seen_at": nas.last_seen_at.isoformat() if nas.last_seen_at else None,
            "last_coa_at": nas.last_coa_at.isoformat() if nas.last_coa_at else None,
            "health": health,
        })

    summary = {
        "healthy": sum(1 for d in devices if d["health"] == "healthy"),
        "warning": sum(1 for d in devices if d["health"] == "warning"),
        "offline": sum(1 for d in devices if d["health"] == "offline"),
        "unknown": sum(1 for d in devices if d["health"] == "unknown"),
        "total": len(devices),
    }

    return {
        "summary": summary,
        "devices": devices,
        "generated_at": now.isoformat(),
    }
