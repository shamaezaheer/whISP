"""
FreeRADIUS synchronisation service.

All functions accept a raw asyncpg connection so they can be composed inside
larger transactions or called from background workers.

RADIUS tables used:
  radcheck    – per-user check attributes (Cleartext-Password, Auth-Type)
  radreply    – per-user reply attributes (Mikrotik-Rate-Limit, Framed-Pool, …)
  radusergroup – user → group mapping
  radgroupreply – per-group reply attributes (shared speed settings)
  radacct      – accounting / session records (TimescaleDB hypertable)
  nas          – Network Access Servers (FreeRADIUS reads this table)
"""
from __future__ import annotations

from typing import Any, Optional

import asyncpg
import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_rate_limit(download_kbps: int, upload_kbps: int) -> str:
    """
    Format a MikroTik rate-limit string.

    Returns ``"<download>k/<upload>k"`` e.g. ``"2048k/1024k"``.
    """
    return f"{download_kbps}k/{upload_kbps}k"


# ---------------------------------------------------------------------------
# Subscriber sync
# ---------------------------------------------------------------------------

async def sync_subscriber(conn: asyncpg.Connection, subscriber: Any) -> None:
    """
    Upsert radcheck and radreply rows for *subscriber*.

    *subscriber* is expected to expose:
      - username: str
      - pppoe_password_enc (or the cleartext password via decrypt_field)
      - plan.download_kbps / plan.upload_kbps
      - plan.quota_gb
      - plan.ip_pool
      - plan.radius_group
      - plan.validity_days

    Call this after create / password reset / plan change / reactivation.
    """
    from app.services.crypto import decrypt_field

    username: str = subscriber.username

    # Resolve cleartext PPPoE password
    try:
        cleartext = decrypt_field(subscriber.pppoe_password_enc) if subscriber.pppoe_password_enc else ""
    except Exception:
        cleartext = ""

    # ---- radcheck ----
    await _upsert_radcheck(conn, username, "Cleartext-Password", ":=", cleartext)
    await _upsert_radcheck(conn, username, "Auth-Type", ":=", "Local")

    # ---- radreply ----
    if subscriber.plan:
        rate = format_rate_limit(
            subscriber.plan.download_kbps,
            subscriber.plan.upload_kbps,
        )
        await _upsert_radreply(conn, username, "Mikrotik-Rate-Limit", ":=", rate)

        if subscriber.plan.ip_pool:
            await _upsert_radreply(conn, username, "Framed-Pool", ":=", subscriber.plan.ip_pool)

        if subscriber.plan.quota_gb:
            # Session-Timeout is a blunt cap; real quota enforcement uses a RADIUS policy
            max_seconds = subscriber.plan.validity_days * 86400
            await _upsert_radreply(conn, username, "Session-Timeout", ":=", str(max_seconds))

        # ---- radusergroup ----
        await _upsert_radusergroup(conn, username, subscriber.plan.radius_group)

    log.info("radius_subscriber_synced", username=username)


async def _upsert_radcheck(
    conn: asyncpg.Connection,
    username: str,
    attribute: str,
    op: str,
    value: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO radcheck (username, attribute, op, value)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (username, attribute)
        DO UPDATE SET op = EXCLUDED.op, value = EXCLUDED.value
        """,
        username,
        attribute,
        op,
        value,
    )


async def _upsert_radreply(
    conn: asyncpg.Connection,
    username: str,
    attribute: str,
    op: str,
    value: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO radreply (username, attribute, op, value)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (username, attribute)
        DO UPDATE SET op = EXCLUDED.op, value = EXCLUDED.value
        """,
        username,
        attribute,
        op,
        value,
    )


async def _upsert_radusergroup(
    conn: asyncpg.Connection,
    username: str,
    groupname: str,
    priority: int = 1,
) -> None:
    await conn.execute(
        """
        INSERT INTO radusergroup (username, groupname, priority)
        VALUES ($1, $2, $3)
        ON CONFLICT (username)
        DO UPDATE SET groupname = EXCLUDED.groupname, priority = EXCLUDED.priority
        """,
        username,
        groupname,
        priority,
    )


# ---------------------------------------------------------------------------
# Remove subscriber
# ---------------------------------------------------------------------------

async def remove_subscriber(conn: asyncpg.Connection, username: str) -> None:
    """
    Remove all RADIUS entries for *username*.

    Used on soft-delete or termination.
    """
    await conn.execute("DELETE FROM radcheck WHERE username = $1", username)
    await conn.execute("DELETE FROM radreply WHERE username = $1", username)
    await conn.execute("DELETE FROM radusergroup WHERE username = $1", username)
    log.info("radius_subscriber_removed", username=username)


# ---------------------------------------------------------------------------
# Plan group sync
# ---------------------------------------------------------------------------

async def sync_plan_group(conn: asyncpg.Connection, plan: Any) -> None:
    """
    Upsert radgroupreply for *plan.radius_group*.

    Sets Mikrotik-Rate-Limit at the group level (applies to all members
    that don't have a per-user override).
    """
    groupname: str = plan.radius_group
    rate = format_rate_limit(plan.download_kbps, plan.upload_kbps)

    await conn.execute(
        """
        INSERT INTO radgroupreply (groupname, attribute, op, value)
        VALUES ($1, 'Mikrotik-Rate-Limit', ':=', $2)
        ON CONFLICT (groupname, attribute)
        DO UPDATE SET op = EXCLUDED.op, value = EXCLUDED.value
        """,
        groupname,
        rate,
    )

    if plan.ip_pool:
        await conn.execute(
            """
            INSERT INTO radgroupreply (groupname, attribute, op, value)
            VALUES ($1, 'Framed-Pool', ':=', $2)
            ON CONFLICT (groupname, attribute)
            DO UPDATE SET op = EXCLUDED.op, value = EXCLUDED.value
            """,
            groupname,
            plan.ip_pool,
        )

    log.info("radius_plan_group_synced", groupname=groupname, rate=rate)


# ---------------------------------------------------------------------------
# Active session query
# ---------------------------------------------------------------------------

async def get_active_session(
    conn: asyncpg.Connection,
    username: str,
) -> Optional[dict]:
    """
    Return the most recent open accounting record for *username*, or None.

    An open record has ``acctstoptime IS NULL``.
    """
    row = await conn.fetchrow(
        """
        SELECT
            radacctid,
            acctsessionid,
            nasipaddress,
            framedipaddress,
            acctstarttime,
            acctsessiontime,
            acctinputoctets,
            acctoutputoctets,
            callingstationid
        FROM radacct
        WHERE username = $1
          AND acctstoptime IS NULL
        ORDER BY acctstarttime DESC
        LIMIT 1
        """,
        username,
    )
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# NAS table management
# ---------------------------------------------------------------------------

async def upsert_nas(
    conn: asyncpg.Connection,
    nasname: str,
    shortname: str,
    secret: str,
    nas_type: str = "other",
    description: str = "",
) -> None:
    """Add or update a NAS entry in the FreeRADIUS nas table."""
    await conn.execute(
        """
        INSERT INTO nas (nasname, shortname, type, secret, description)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (nasname)
        DO UPDATE SET shortname = EXCLUDED.shortname,
                      type      = EXCLUDED.type,
                      secret    = EXCLUDED.secret,
                      description = EXCLUDED.description
        """,
        nasname,
        shortname,
        nas_type,
        secret,
        description,
    )
    log.info("radius_nas_upserted", nasname=nasname)


async def delete_nas(conn: asyncpg.Connection, nasname: str) -> None:
    await conn.execute("DELETE FROM nas WHERE nasname = $1", nasname)
    log.info("radius_nas_deleted", nasname=nasname)
