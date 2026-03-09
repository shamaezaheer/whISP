"""
Usage and analytics router for whISP.

All data queries run against TimescaleDB / FreeRADIUS via raw asyncpg.
Franchisee-scoped: franchisee sees only their subscribers' data.
Subscriber-scoped: subscriber sees only their own data.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Plan, Subscriber
from app.services.auth import (
    CurrentUser,
    FranchiseeUser as FranchiseeUserDep,
    assert_franchisee_scope,
    assert_subscriber_scope,
    get_db_conn,
)

log = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_range(range_str: str) -> timedelta:
    mapping = {
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "72h": timedelta(hours=72),
        "7d": timedelta(days=7),
    }
    return mapping.get(range_str, timedelta(hours=24))


async def _get_franchisee_usernames(
    conn: asyncpg.Connection,
    db: AsyncSession,
    franchisee_id: uuid.UUID,
) -> list[str]:
    """Return list of PPPoE usernames for all non-deleted subscribers of a franchisee."""
    rows = await db.execute(
        select(Subscriber.username).where(
            Subscriber.franchisee_id == franchisee_id,
            Subscriber.is_deleted == False,  # noqa: E712
        )
    )
    return [r[0] for r in rows.all()]


# ---------------------------------------------------------------------------
# GET /usage/franchisee/overview
# ---------------------------------------------------------------------------

@router.get("/franchisee/overview", summary="Franchisee usage overview")
async def franchisee_overview(
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
    franchisee_id: Optional[uuid.UUID] = Query(None),
) -> dict[str, Any]:
    if user.get("type") == "admin":
        if franchisee_id is None:
            raise HTTPException(status_code=400, detail="franchisee_id required for admin")
        fid = franchisee_id
    else:
        fid = uuid.UUID(user["franchisee_id"])
        if franchisee_id:
            assert_franchisee_scope(user, str(franchisee_id))

    _empty_overview = {
        "franchisee_id": str(fid),
        "active_sessions": 0,
        "subscribers_online": 0,
        "total_download_today_bytes": 0,
        "total_upload_today_bytes": 0,
        "total_download_month_bytes": 0,
        "bandwidth_mbps_current": 0.0,
    }

    usernames = await _get_franchisee_usernames(conn, db, fid)
    if not usernames:
        return _empty_overview

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        active_sessions_row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS cnt
            FROM radacct
            WHERE username = ANY($1::text[])
              AND acctstoptime IS NULL
            """,
            usernames,
        )
        active_sessions = active_sessions_row["cnt"] if active_sessions_row else 0

        today_row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(acctinputoctets), 0)  AS dl_bytes,
                COALESCE(SUM(acctoutputoctets), 0) AS ul_bytes
            FROM radacct
            WHERE username = ANY($1::text[])
              AND acctstarttime >= $2
            """,
            usernames,
            today_start,
        )

        month_row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(acctinputoctets), 0) AS dl_bytes
            FROM radacct
            WHERE username = ANY($1::text[])
              AND acctstarttime >= $2
            """,
            usernames,
            month_start,
        )

        bw_row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(acctinputoctets + acctoutputoctets), 0) AS total_bytes,
                COALESCE(SUM(acctsessiontime), 1) AS total_seconds
            FROM radacct
            WHERE username = ANY($1::text[])
              AND acctstoptime IS NULL
              AND acctstarttime >= NOW() - INTERVAL '5 minutes'
            """,
            usernames,
        )

        total_bytes = int(bw_row["total_bytes"]) if bw_row else 0
        total_secs = max(int(bw_row["total_seconds"]), 1) if bw_row else 1
        bandwidth_mbps = round(total_bytes / total_secs * 8 / 1_000_000, 2)

        return {
            "franchisee_id": str(fid),
            "active_sessions": active_sessions,
            "subscribers_online": active_sessions,
            "total_download_today_bytes": int(today_row["dl_bytes"]) if today_row else 0,
            "total_upload_today_bytes": int(today_row["ul_bytes"]) if today_row else 0,
            "total_download_month_bytes": int(month_row["dl_bytes"]) if month_row else 0,
            "bandwidth_mbps_current": bandwidth_mbps,
        }
    except Exception:
        log.warning("radacct_query_failed_returning_zeros", franchisee_id=str(fid))
        return _empty_overview


# ---------------------------------------------------------------------------
# GET /usage/franchisee/chart
# ---------------------------------------------------------------------------

@router.get("/franchisee/chart", summary="Franchisee bandwidth time-series chart data")
async def franchisee_chart(
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
    range: str = Query("24h", regex="^(6h|24h|72h|7d)$"),
    franchisee_id: Optional[uuid.UUID] = Query(None),
) -> dict[str, Any]:
    if user.get("type") == "admin":
        if franchisee_id is None:
            raise HTTPException(status_code=400, detail="franchisee_id required for admin")
        fid = franchisee_id
    else:
        fid = uuid.UUID(user["franchisee_id"])
        if franchisee_id:
            assert_franchisee_scope(user, str(franchisee_id))

    usernames = await _get_franchisee_usernames(conn, db, fid)
    delta = _parse_range(range)
    since = datetime.now(timezone.utc) - delta

    if not usernames:
        return {"franchisee_id": str(fid), "range": range, "data": []}

    try:
        rows = await conn.fetch(
            """
            SELECT
                date_trunc('hour', acctstarttime)              AS bucket,
                COALESCE(SUM(acctinputoctets), 0)              AS bytes_in,
                COALESCE(SUM(acctoutputoctets), 0)             AS bytes_out
            FROM radacct
            WHERE username = ANY($1::text[])
              AND acctstarttime >= $2
            GROUP BY bucket
            ORDER BY bucket ASC
            """,
            usernames,
            since,
        )
        data = [
            {
                "time": row["bucket"].isoformat(),
                "bytes_in": int(row["bytes_in"]),
                "bytes_out": int(row["bytes_out"]),
            }
            for row in rows
        ]
    except Exception:
        log.warning("radacct_chart_query_failed", franchisee_id=str(fid))
        data = []

    return {"franchisee_id": str(fid), "range": range, "data": data}


# ---------------------------------------------------------------------------
# GET /usage/franchisee/top-consumers
# ---------------------------------------------------------------------------

@router.get("/franchisee/top-consumers", summary="Top 10 subscribers by data usage this month")
async def franchisee_top_consumers(
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
    franchisee_id: Optional[uuid.UUID] = Query(None),
) -> dict[str, Any]:
    if user.get("type") == "admin":
        if franchisee_id is None:
            raise HTTPException(status_code=400, detail="franchisee_id required for admin")
        fid = franchisee_id
    else:
        fid = uuid.UUID(user["franchisee_id"])
        if franchisee_id:
            assert_franchisee_scope(user, str(franchisee_id))

    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Get subscribers with their plan names
    sub_rows = await db.execute(
        select(Subscriber, Plan)
        .outerjoin(Plan, Subscriber.plan_id == Plan.id)
        .where(
            Subscriber.franchisee_id == fid,
            Subscriber.is_deleted == False,  # noqa: E712
        )
    )
    sub_data = {
        sub.username: {
            "subscriber_id": str(sub.id),
            "name": sub.name,
            "username": sub.username,
            "plan_name": plan.name if plan else None,
            "quota_used_bytes": sub.quota_used_bytes,
        }
        for sub, plan in sub_rows.all()
    }

    if not sub_data:
        return {"franchisee_id": str(fid), "top_consumers": []}

    usernames = list(sub_data.keys())

    try:
        rows = await conn.fetch(
            """
            SELECT
                username,
                COALESCE(SUM(acctinputoctets + acctoutputoctets), 0) AS bytes_used
            FROM radacct
            WHERE username = ANY($1::text[])
              AND acctstarttime >= $2
            GROUP BY username
            ORDER BY bytes_used DESC
            LIMIT 10
            """,
            usernames,
            month_start,
        )
        top = [
            {**sub_data.get(row["username"], {}), "bytes_used_this_month": int(row["bytes_used"])}
            for row in rows
        ]
    except Exception:
        log.warning("radacct_top_consumers_query_failed", franchisee_id=str(fid))
        top = []

    return {"franchisee_id": str(fid), "top_consumers": top}


# ---------------------------------------------------------------------------
# GET /usage/franchisee/sessions
# ---------------------------------------------------------------------------

@router.get("/franchisee/sessions", summary="List active PPPoE sessions for franchisee")
async def franchisee_sessions(
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
    franchisee_id: Optional[uuid.UUID] = Query(None),
) -> dict[str, Any]:
    if user.get("type") == "admin":
        if franchisee_id is None:
            raise HTTPException(status_code=400, detail="franchisee_id required for admin")
        fid = franchisee_id
    else:
        fid = uuid.UUID(user["franchisee_id"])
        if franchisee_id:
            assert_franchisee_scope(user, str(franchisee_id))

    usernames = await _get_franchisee_usernames(conn, db, fid)
    if not usernames:
        return {"franchisee_id": str(fid), "session_count": 0, "sessions": []}

    try:
        rows = await conn.fetch(
            """
            SELECT
                username,
                nasipaddress,
                framedipaddress,
                acctstarttime,
                acctsessiontime,
                acctinputoctets,
                acctoutputoctets,
                acctterminatecause,
                callingstationid
            FROM radacct
            WHERE username = ANY($1::text[])
              AND acctstoptime IS NULL
            ORDER BY acctstarttime DESC
            """,
            usernames,
        )
        sessions = []
        for row in rows:
            s = dict(row)
            if isinstance(s.get("acctstarttime"), datetime):
                s["acctstarttime"] = s["acctstarttime"].isoformat()
            sessions.append(s)
    except Exception:
        log.warning("radacct_sessions_query_failed", franchisee_id=str(fid))
        sessions = []

    return {"franchisee_id": str(fid), "session_count": len(sessions), "sessions": sessions}


# ---------------------------------------------------------------------------
# GET /usage/subscriber/{id}
# ---------------------------------------------------------------------------

@router.get("/subscriber/{subscriber_id}", summary="Subscriber's own usage statistics")
async def subscriber_usage(
    subscriber_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    assert_subscriber_scope(user, str(subscriber_id))

    sub_result = await db.execute(
        select(Subscriber, Plan)
        .outerjoin(Plan, Subscriber.plan_id == Plan.id)
        .where(Subscriber.id == subscriber_id, Subscriber.is_deleted == False)  # noqa: E712
    )
    row = sub_result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    sub, plan = row

    if user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(sub.franchisee_id))

    # Quota info
    data_cap_bytes: Optional[int] = None
    if plan and plan.quota_gb:
        data_cap_bytes = plan.quota_gb * 1_073_741_824  # GB to bytes
    quota_used = sub.quota_used_bytes or 0
    percentage = 0.0
    if data_cap_bytes and data_cap_bytes > 0:
        percentage = min(round(quota_used / data_cap_bytes * 100, 2), 100.0)

    # Days remaining
    days_remaining: Optional[int] = None
    if sub.plan_expires_at:
        delta = sub.plan_expires_at - datetime.now(timezone.utc)
        days_remaining = max(0, delta.days)

    # Current session
    session_row = await conn.fetchrow(
        """
        SELECT radacctid, acctsessionid, nasipaddress, framedipaddress,
               acctstarttime, acctsessiontime, acctinputoctets, acctoutputoctets
        FROM radacct
        WHERE username = $1 AND acctstoptime IS NULL
        ORDER BY acctstarttime DESC
        LIMIT 1
        """,
        sub.username,
    )
    current_session = None
    if session_row:
        current_session = dict(session_row)
        if isinstance(current_session.get("acctstarttime"), datetime):
            current_session["acctstarttime"] = current_session["acctstarttime"].isoformat()

    # Last 7 days hourly usage
    since_7d = datetime.now(timezone.utc) - timedelta(days=7)
    history_rows = await conn.fetch(
        """
        SELECT
            date_trunc('hour', acctstarttime)  AS bucket,
            COALESCE(SUM(acctinputoctets), 0)  AS bytes_in,
            COALESCE(SUM(acctoutputoctets), 0) AS bytes_out
        FROM radacct
        WHERE username = $1
          AND acctstarttime >= $2
        GROUP BY bucket
        ORDER BY bucket ASC
        """,
        sub.username,
        since_7d,
    )

    history = [
        {
            "time": row["bucket"].isoformat(),
            "bytes_in": int(row["bytes_in"]),
            "bytes_out": int(row["bytes_out"]),
        }
        for row in history_rows
    ]

    return {
        "subscriber_id": str(sub.id),
        "username": sub.username,
        "status": sub.status,
        "quota_used_bytes": quota_used,
        "data_cap_bytes": data_cap_bytes,
        "usage_percentage": percentage,
        "days_remaining": days_remaining,
        "plan_expires_at": sub.plan_expires_at.isoformat() if sub.plan_expires_at else None,
        "plan": {
            "id": str(plan.id),
            "name": plan.name,
            "download_kbps": plan.download_kbps,
            "upload_kbps": plan.upload_kbps,
            "quota_gb": plan.quota_gb,
        } if plan else None,
        "current_session": current_session,
        "history_7d": history,
    }
