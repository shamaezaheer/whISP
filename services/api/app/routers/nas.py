"""
NAS (Network Access Server) device management router for whISP.

Manages registration, config sync to FreeRADIUS nas table,
CoA testing, and MikroTik config script generation.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    CoACommand,
    Franchisee,
    NASDevice,
)
from app.services.auth import (
    AdminUser,
    CurrentUser,
    FranchiseeUser as FranchiseeUserDep,
    assert_franchisee_scope,
    get_db_conn,
)
from app.services.coa import send_disconnect
from app.services.radius import delete_nas, upsert_nas

log = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NASCreate(BaseModel):
    franchisee_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    ip_address: str = Field(..., min_length=7, max_length=45)
    nas_type: str = "mikrotik"
    secret: Optional[str] = None  # If None, inherit franchisee's radius_secret
    coa_port: int = 3799
    description: Optional[str] = None


class NASUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    nas_type: Optional[str] = None
    secret: Optional[str] = None
    coa_port: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nas_to_dict(nas: NASDevice, include_secret: bool = True) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(nas.id),
        "franchisee_id": str(nas.franchisee_id),
        "name": nas.name,
        "ip_address": nas.ip_address,
        "nas_type": nas.nas_type,
        "coa_port": nas.coa_port,
        "description": nas.description,
        "is_active": nas.is_active,
        "last_seen_at": nas.last_seen_at.isoformat() if nas.last_seen_at else None,
        "last_coa_at": nas.last_coa_at.isoformat() if nas.last_coa_at else None,
        "created_at": nas.created_at.isoformat(),
        "updated_at": nas.updated_at.isoformat(),
    }
    if include_secret:
        d["secret"] = nas.secret
    return d


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
        resource_type="nas_device",
        resource_id=resource_id,
        old_values=old_values,
        new_values=new_values,
        success=True,
    ))


# ---------------------------------------------------------------------------
# GET /nas
# ---------------------------------------------------------------------------

@router.get("", summary="List NAS devices")
async def list_nas(
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    franchisee_id: Optional[uuid.UUID] = Query(None),
    is_active: Optional[bool] = Query(None),
) -> dict[str, Any]:
    q = select(NASDevice)

    if user.get("type") == "admin":
        if franchisee_id:
            q = q.where(NASDevice.franchisee_id == franchisee_id)
    else:
        fid = uuid.UUID(user["franchisee_id"])
        if franchisee_id:
            assert_franchisee_scope(user, str(franchisee_id))
        q = q.where(NASDevice.franchisee_id == fid)

    if is_active is not None:
        q = q.where(NASDevice.is_active == is_active)

    q = q.order_by(NASDevice.created_at.desc())
    rows = await db.execute(q)
    items = [_nas_to_dict(n) for n in rows.scalars()]
    return {"total": len(items), "items": items}


# ---------------------------------------------------------------------------
# GET /nas/{id}
# ---------------------------------------------------------------------------

@router.get("/{nas_id}", summary="Get NAS device detail")
async def get_nas(
    nas_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(NASDevice).where(NASDevice.id == nas_id))
    nas = result.scalar_one_or_none()
    if nas is None:
        raise HTTPException(status_code=404, detail="NAS device not found")

    assert_franchisee_scope(user, str(nas.franchisee_id))
    return _nas_to_dict(nas)


# ---------------------------------------------------------------------------
# POST /nas
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, summary="Register NAS device")
async def create_nas(
    body: NASCreate,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    assert_franchisee_scope(user, str(body.franchisee_id))

    # Validate franchisee exists
    f_result = await db.execute(select(Franchisee).where(Franchisee.id == body.franchisee_id))
    f = f_result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    # Determine secret: use provided or inherit franchisee's
    secret = body.secret or f.radius_secret
    if not secret:
        from app.services.crypto import generate_radius_secret
        secret = generate_radius_secret(20)

    nas = NASDevice(
        franchisee_id=body.franchisee_id,
        name=body.name,
        ip_address=body.ip_address,
        nas_type=body.nas_type,
        secret=secret,
        coa_port=body.coa_port,
        description=body.description,
        is_active=True,
    )
    db.add(nas)
    await db.flush()

    # Sync to FreeRADIUS nas table
    try:
        await upsert_nas(
            conn=conn,
            nasname=nas.ip_address,
            shortname=nas.name,
            secret=secret,
            nas_type=nas.nas_type,
            description=nas.description or "",
        )
    except Exception as exc:
        log.error("radius_nas_upsert_failed", error=str(exc), nas_id=str(nas.id))

    _log_audit(db, user, "nas.create", nas.id, new_values={"name": body.name, "ip": body.ip_address})
    await db.commit()
    await db.refresh(nas)

    log.info("nas_created", nas_id=str(nas.id), ip=body.ip_address)
    return _nas_to_dict(nas)


# ---------------------------------------------------------------------------
# PATCH /nas/{id}
# ---------------------------------------------------------------------------

@router.patch("/{nas_id}", summary="Update NAS device")
async def update_nas(
    nas_id: uuid.UUID,
    body: NASUpdate,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> dict[str, Any]:
    result = await db.execute(select(NASDevice).where(NASDevice.id == nas_id))
    nas = result.scalar_one_or_none()
    if nas is None:
        raise HTTPException(status_code=404, detail="NAS device not found")

    assert_franchisee_scope(user, str(nas.franchisee_id))

    old_ip = nas.ip_address
    old_values = _nas_to_dict(nas, include_secret=False)
    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(nas, field, value)

    await db.flush()

    # Re-sync to FreeRADIUS if relevant fields changed
    if any(f in update_data for f in ("ip_address", "secret", "nas_type", "name")):
        try:
            # If IP changed, remove old entry
            if "ip_address" in update_data and update_data["ip_address"] != old_ip:
                await delete_nas(conn, old_ip)
            await upsert_nas(
                conn=conn,
                nasname=nas.ip_address,
                shortname=nas.name,
                secret=nas.secret,
                nas_type=nas.nas_type,
                description=nas.description or "",
            )
        except Exception as exc:
            log.error("radius_nas_update_sync_failed", error=str(exc))

    _log_audit(db, user, "nas.update", nas.id, old_values=old_values, new_values=update_data)
    await db.commit()
    await db.refresh(nas)

    return _nas_to_dict(nas)


# ---------------------------------------------------------------------------
# DELETE /nas/{id}
# ---------------------------------------------------------------------------

@router.delete("/{nas_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Delete NAS device")
async def delete_nas_device(
    nas_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
    conn: asyncpg.Connection = Depends(get_db_conn),
) -> None:
    result = await db.execute(select(NASDevice).where(NASDevice.id == nas_id))
    nas = result.scalar_one_or_none()
    if nas is None:
        raise HTTPException(status_code=404, detail="NAS device not found")

    assert_franchisee_scope(user, str(nas.franchisee_id))

    ip_address = nas.ip_address
    _log_audit(db, user, "nas.delete", nas.id, old_values={"ip": ip_address, "name": nas.name})

    await db.delete(nas)
    await db.flush()

    # Remove from FreeRADIUS nas table
    try:
        await delete_nas(conn, ip_address)
    except Exception as exc:
        log.error("radius_nas_delete_failed", error=str(exc))

    await db.commit()
    log.info("nas_deleted", nas_id=str(nas_id), ip=ip_address)


# ---------------------------------------------------------------------------
# POST /nas/{id}/test-coa
# ---------------------------------------------------------------------------

@router.post("/{nas_id}/test-coa", summary="Send test CoA packet to NAS")
async def test_coa(
    nas_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(NASDevice).where(NASDevice.id == nas_id))
    nas = result.scalar_one_or_none()
    if nas is None:
        raise HTTPException(status_code=404, detail="NAS device not found")

    assert_franchisee_scope(user, str(nas.franchisee_id))

    start_time = time.monotonic()
    error_msg: Optional[str] = None
    success = False

    try:
        success = await send_disconnect(
            nas_ip=nas.ip_address,
            nas_secret=nas.secret,
            username="test-coa-check",
            port=nas.coa_port,
            timeout=5.0,
        )
        # A Disconnect-NAK for unknown user is actually expected and means CoA port is reachable
        # We treat any response (ACK or NAK) as a connectivity success
        if not success:
            # NAK means the NAS responded but rejected (user not found) – port is reachable
            success = True  # connectivity confirmed
    except Exception as exc:
        error_msg = str(exc)
        success = False

    latency_ms = round((time.monotonic() - start_time) * 1000, 2)

    # Update NAS last_coa_at
    nas.last_coa_at = datetime.now(timezone.utc)

    # Log CoA command
    coa_cmd = CoACommand(
        nas_device_id=nas.id,
        subscriber_id=None,
        command_type="disconnect",
        attributes={"username": "test-coa-check", "test": True},
        success=success,
        response={"latency_ms": latency_ms},
        error=error_msg,
    )
    db.add(coa_cmd)
    await db.commit()

    log.info("coa_test_completed", nas_id=str(nas_id), success=success, latency_ms=latency_ms)
    return {
        "nas_id": str(nas_id),
        "ip_address": nas.ip_address,
        "success": success,
        "latency_ms": latency_ms,
        "error": error_msg,
        "message": "CoA port is reachable" if success else "CoA test failed – check NAS connectivity",
    }


# ---------------------------------------------------------------------------
# GET /nas/{id}/config
# ---------------------------------------------------------------------------

@router.get("/{nas_id}/config", summary="Generate MikroTik RouterOS config script for this NAS")
async def get_nas_config(
    nas_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(select(NASDevice).where(NASDevice.id == nas_id))
    nas = result.scalar_one_or_none()
    if nas is None:
        raise HTTPException(status_code=404, detail="NAS device not found")

    assert_franchisee_scope(user, str(nas.franchisee_id))

    from app.config import get_settings
    settings = get_settings()
    radius_server_ip = getattr(settings, "RADIUS_SERVER_IP", "10.0.0.1")

    script = f"""# whISP - MikroTik RADIUS Configuration
# Generated for NAS: {nas.name} ({nas.ip_address})
# Franchisee ID: {nas.franchisee_id}
# Generated at: {datetime.now(timezone.utc).isoformat()}
# !! Store this script securely - it contains your RADIUS shared secret !!

/radius remove [find]
/radius add address={radius_server_ip} secret={nas.secret} \\
    service=ppp authentication-port=1812 accounting-port=1813 \\
    timeout=3000ms called-format=mac src-address=0.0.0.0

/ppp profile set default use-radius=yes accounting=yes \\
    session-timeout=0 idle-timeout=0

/ip firewall filter remove [find comment="CoA from RADIUS"]
/ip firewall filter add chain=input protocol=udp dst-port={nas.coa_port} \\
    action=accept comment="CoA from RADIUS" place-before=0

/interface pppoe-server server set accounting=yes

/radius incoming set accept=yes port={nas.coa_port}
"""

    return Response(content=script, media_type="text/plain; charset=utf-8")
