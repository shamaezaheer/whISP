"""
Support ticket management router for whISP.

Subscribers create tickets, franchisee staff triage and resolve them.
Messages are stored as a JSONB array appended with each reply.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    Subscriber,
    SupportTicket,
)
from app.services.auth import (
    CurrentUser,
    FranchiseeUser as FranchiseeUserDep,
    assert_franchisee_scope,
    assert_subscriber_scope,
)

log = structlog.get_logger(__name__)
router = APIRouter()

_VALID_CATEGORIES = ("billing", "connectivity", "speed", "installation", "other")
_VALID_PRIORITIES = ("low", "medium", "high", "critical")
_VALID_STATUSES = ("open", "in_progress", "pending_customer", "resolved", "closed")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TicketCreate(BaseModel):
    franchisee_id: uuid.UUID
    subscriber_id: Optional[uuid.UUID] = None  # franchisee can create on behalf of subscriber
    subject: str = Field(..., min_length=5, max_length=500)
    description: str = Field(..., min_length=10)
    category: str = "other"
    priority: str = "medium"


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[uuid.UUID] = None
    message: Optional[str] = None  # add a message along with the update
    sender_type: Optional[str] = "franchisee"


class TicketReply(BaseModel):
    message: str = Field(..., min_length=1)
    sender_type: str = "subscriber"  # subscriber | franchisee | system


class TicketResolve(BaseModel):
    resolution_notes: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(
    content: str,
    sender_type: str,
    sender_id: Optional[str] = None,
    sender_email: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "content": content,
        "sender_type": sender_type,
        "sender_id": sender_id,
        "sender_email": sender_email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _ticket_to_dict(t: SupportTicket, include_messages: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(t.id),
        "subscriber_id": str(t.subscriber_id),
        "franchisee_id": str(t.franchisee_id),
        "assigned_to": str(t.assigned_to) if t.assigned_to else None,
        "subject": t.subject,
        "description": t.description,
        "category": t.category,
        "priority": t.priority,
        "status": t.status,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "resolution_notes": t.resolution_notes,
        "message_count": len(t.messages or []),
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }
    if include_messages:
        d["messages"] = t.messages or []
    return d


def _log_audit(
    db: AsyncSession,
    user: dict,
    action: str,
    resource_id: uuid.UUID,
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
        resource_type="support_ticket",
        resource_id=resource_id,
        new_values=new_values,
        success=True,
    ))


# ---------------------------------------------------------------------------
# GET /tickets
# ---------------------------------------------------------------------------

@router.get("", summary="List support tickets")
async def list_tickets(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ticket_status: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = Query(None),
    franchisee_id: Optional[uuid.UUID] = Query(None),
) -> dict[str, Any]:
    q = select(SupportTicket)

    actor_type = user.get("type")
    if actor_type == "admin":
        if franchisee_id:
            q = q.where(SupportTicket.franchisee_id == franchisee_id)
    elif actor_type == "franchisee":
        fid = uuid.UUID(user["franchisee_id"])
        q = q.where(SupportTicket.franchisee_id == fid)
    else:
        # Subscriber sees only their own tickets
        sid = uuid.UUID(user["sub"])
        q = q.where(SupportTicket.subscriber_id == sid)

    if ticket_status:
        q = q.where(SupportTicket.status == ticket_status)
    if priority:
        q = q.where(SupportTicket.priority == priority)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.offset(offset).limit(limit).order_by(SupportTicket.created_at.desc())
    rows = await db.execute(q)
    items = [_ticket_to_dict(t) for t in rows.scalars()]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------------------
# GET /tickets/{id}
# ---------------------------------------------------------------------------

@router.get("/{ticket_id}", summary="Get ticket detail with message thread")
async def get_ticket(
    ticket_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    actor_type = user.get("type")
    if actor_type == "subscriber":
        assert_subscriber_scope(user, str(ticket.subscriber_id))
    elif actor_type == "franchisee":
        assert_franchisee_scope(user, str(ticket.franchisee_id))

    return _ticket_to_dict(ticket, include_messages=True)


# ---------------------------------------------------------------------------
# POST /tickets
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, summary="Create support ticket")
async def create_ticket(
    body: TicketCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    actor_type = user.get("type")

    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category must be one of {_VALID_CATEGORIES}")
    if body.priority not in _VALID_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {_VALID_PRIORITIES}")

    # Determine subscriber_id
    subscriber_id: uuid.UUID
    if actor_type == "subscriber":
        subscriber_id = uuid.UUID(user["sub"])
        assert_franchisee_scope(user, str(body.franchisee_id))
    elif actor_type == "franchisee":
        assert_franchisee_scope(user, str(body.franchisee_id))
        if body.subscriber_id is None:
            raise HTTPException(status_code=422, detail="subscriber_id required when franchisee creates ticket")
        subscriber_id = body.subscriber_id
        # Verify subscriber belongs to this franchisee
        sub_result = await db.execute(
            select(Subscriber).where(
                Subscriber.id == subscriber_id,
                Subscriber.franchisee_id == body.franchisee_id,
                Subscriber.is_deleted == False,  # noqa: E712
            )
        )
        if not sub_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Subscriber not found in this franchisee")
    else:
        # admin
        if body.subscriber_id is None:
            raise HTTPException(status_code=422, detail="subscriber_id required")
        subscriber_id = body.subscriber_id

    initial_message = _make_message(
        content=body.description,
        sender_type=actor_type or "subscriber",
        sender_id=user.get("sub"),
        sender_email=user.get("email"),
    )

    ticket = SupportTicket(
        subscriber_id=subscriber_id,
        franchisee_id=body.franchisee_id,
        subject=body.subject,
        description=body.description,
        category=body.category,
        priority=body.priority,
        status="open",
        messages=[initial_message],
    )
    db.add(ticket)
    await db.flush()

    _log_audit(db, user, "ticket.create", ticket.id, new_values={"subject": body.subject, "category": body.category})
    await db.commit()
    await db.refresh(ticket)

    log.info("ticket_created", ticket_id=str(ticket.id), category=body.category)
    return _ticket_to_dict(ticket, include_messages=True)


# ---------------------------------------------------------------------------
# PATCH /tickets/{id}
# ---------------------------------------------------------------------------

@router.patch("/{ticket_id}", summary="Update ticket status, priority, assignment")
async def update_ticket(
    ticket_id: uuid.UUID,
    body: TicketUpdate,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(ticket.franchisee_id))

    if body.status is not None:
        if body.status not in _VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {_VALID_STATUSES}")
        ticket.status = body.status

    if body.priority is not None:
        if body.priority not in _VALID_PRIORITIES:
            raise HTTPException(status_code=422, detail=f"priority must be one of {_VALID_PRIORITIES}")
        ticket.priority = body.priority

    if body.assigned_to is not None:
        ticket.assigned_to = body.assigned_to

    # Optionally add a message along with the update
    if body.message:
        messages = list(ticket.messages or [])
        messages.append(_make_message(
            content=body.message,
            sender_type=body.sender_type or "franchisee",
            sender_id=user.get("sub"),
            sender_email=user.get("email"),
        ))
        ticket.messages = messages

    _log_audit(db, user, "ticket.update", ticket.id, new_values=body.model_dump(exclude_none=True))
    await db.commit()
    await db.refresh(ticket)

    return _ticket_to_dict(ticket, include_messages=True)


# ---------------------------------------------------------------------------
# POST /tickets/{id}/reply
# ---------------------------------------------------------------------------

@router.post("/{ticket_id}/reply", summary="Add reply message to ticket")
async def reply_ticket(
    ticket_id: uuid.UUID,
    body: TicketReply,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    actor_type = user.get("type")
    if actor_type == "subscriber":
        assert_subscriber_scope(user, str(ticket.subscriber_id))
    elif actor_type == "franchisee":
        assert_franchisee_scope(user, str(ticket.franchisee_id))

    messages = list(ticket.messages or [])
    messages.append(_make_message(
        content=body.message,
        sender_type=body.sender_type,
        sender_id=user.get("sub"),
        sender_email=user.get("email"),
    ))
    ticket.messages = messages

    # Reopen resolved ticket on subscriber reply
    if actor_type == "subscriber" and ticket.status == "resolved":
        ticket.status = "open"
        log.info("ticket_reopened_on_subscriber_reply", ticket_id=str(ticket_id))

    await db.commit()
    await db.refresh(ticket)

    return {
        "ticket_id": str(ticket.id),
        "status": ticket.status,
        "message_count": len(ticket.messages or []),
        "last_message": messages[-1],
    }


# ---------------------------------------------------------------------------
# POST /tickets/{id}/resolve
# ---------------------------------------------------------------------------

@router.post("/{ticket_id}/resolve", summary="Resolve ticket (franchisee/admin)")
async def resolve_ticket(
    ticket_id: uuid.UUID,
    body: TicketResolve,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(ticket.franchisee_id))

    ticket.status = "resolved"
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.resolution_notes = body.resolution_notes

    # Add resolution message
    messages = list(ticket.messages or [])
    messages.append(_make_message(
        content=f"[RESOLVED] {body.resolution_notes}",
        sender_type=user.get("type", "franchisee"),
        sender_id=user.get("sub"),
        sender_email=user.get("email"),
    ))
    ticket.messages = messages

    _log_audit(db, user, "ticket.resolve", ticket.id, new_values={"status": "resolved"})
    await db.commit()
    await db.refresh(ticket)

    log.info("ticket_resolved", ticket_id=str(ticket_id))
    return _ticket_to_dict(ticket, include_messages=True)


# ---------------------------------------------------------------------------
# POST /tickets/{id}/close
# ---------------------------------------------------------------------------

@router.post("/{ticket_id}/close", summary="Close ticket")
async def close_ticket(
    ticket_id: uuid.UUID,
    user: FranchiseeUserDep,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if user.get("type") == "franchisee":
        assert_franchisee_scope(user, str(ticket.franchisee_id))

    ticket.status = "closed"

    messages = list(ticket.messages or [])
    messages.append(_make_message(
        content="Ticket closed.",
        sender_type=user.get("type", "franchisee"),
        sender_id=user.get("sub"),
        sender_email=user.get("email"),
    ))
    ticket.messages = messages

    _log_audit(db, user, "ticket.close", ticket.id, new_values={"status": "closed"})
    await db.commit()
    await db.refresh(ticket)

    log.info("ticket_closed", ticket_id=str(ticket_id))
    return {"id": str(ticket.id), "status": ticket.status}
