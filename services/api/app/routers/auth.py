"""
Authentication router for whISP.

Endpoints:
  POST /auth/login                  – issue JWT for admin / franchisee / subscriber
  POST /auth/refresh                – exchange refresh token for new access token
  POST /auth/logout                 – blacklist current token in Redis
  POST /auth/register/subscriber    – self-registration
  GET  /auth/me                     – return current user info
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import FranchiseeUser, Subscriber
from app.services.auth import (
    CurrentUser,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from app.services.crypto import hash_password, verify_password

log = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    actor_type: Literal["admin", "franchisee", "subscriber"] = "subscriber"


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: dict[str, Any]


class RefreshRequest(BaseModel):
    refresh_token: str


class SubscriberRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone: str | None = None
    password: str = Field(..., min_length=8)
    username: str = Field(..., min_length=3, max_length=100)
    franchisee_id: uuid.UUID


# ---------------------------------------------------------------------------
# Hardcoded admin check (production: replace with DB admin table)
# ---------------------------------------------------------------------------

_ADMIN_EMAIL = "admin@whisp.local"
_ADMIN_PASSWORD_HASH: str | None = None  # Loaded lazily from env / DB


def _get_admin_password_hash() -> str:
    """
    In production this should be fetched from a secure admins table.
    For bootstrap we derive it from an env var ADMIN_PASSWORD.
    """
    from app.config import get_settings

    settings = get_settings()
    raw = getattr(settings, "ADMIN_PASSWORD", "changeme")
    return hash_password(raw)


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse, summary="Login and obtain JWT")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from app.config import get_settings

    settings = get_settings()

    if body.actor_type == "admin":
        # Simple single-admin model – expand to admin table as needed
        admin_email = getattr(settings, "ADMIN_EMAIL", _ADMIN_EMAIL)
        if body.email.lower() != admin_email.lower():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        stored_hash = _get_admin_password_hash()
        if not verify_password(body.password, stored_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        token_data: dict[str, Any] = {
            "sub": "admin",
            "type": "admin",
            "email": admin_email,
            "jti": str(uuid.uuid4()),
        }
        user_info = {"id": "admin", "email": admin_email, "type": "admin"}

    elif body.actor_type == "franchisee":
        result = await db.execute(
            select(FranchiseeUser).where(
                FranchiseeUser.email == body.email.lower(),
                FranchiseeUser.is_active == True,  # noqa: E712
            )
        )
        fu = result.scalar_one_or_none()
        if fu is None or not verify_password(body.password, fu.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        fu.last_login_at = datetime.now(timezone.utc)
        token_data = {
            "sub": str(fu.id),
            "type": "franchisee",
            "franchisee_id": str(fu.franchisee_id),
            "role": fu.role,
            "email": fu.email,
            "jti": str(uuid.uuid4()),
        }
        user_info = {
            "id": str(fu.id),
            "email": fu.email,
            "name": fu.name,
            "role": fu.role,
            "franchisee_id": str(fu.franchisee_id),
            "type": "franchisee",
        }

    else:  # subscriber
        result = await db.execute(
            select(Subscriber).where(
                Subscriber.email == body.email.lower(),
                Subscriber.is_deleted == False,  # noqa: E712
            )
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        # Subscribers can use either their portal password or their PPPoE password
        portal_ok = sub.portal_password_hash and verify_password(body.password, sub.portal_password_hash)
        if not portal_ok:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if sub.status == "terminated":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account terminated")
        token_data = {
            "sub": str(sub.id),
            "type": "subscriber",
            "franchisee_id": str(sub.franchisee_id),
            "email": sub.email,
            "jti": str(uuid.uuid4()),
        }
        user_info = {
            "id": str(sub.id),
            "email": sub.email,
            "name": sub.name,
            "status": sub.status,
            "franchisee_id": str(sub.franchisee_id),
            "type": "subscriber",
        }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    log.info("user_logged_in", actor_type=body.actor_type, email=body.email)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
        user=user_info,
    )


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=LoginResponse, summary="Refresh access token")
async def refresh_token(body: RefreshRequest, request: Request):
    from app.config import get_settings

    settings = get_settings()

    payload = decode_token(body.refresh_token)
    if payload.get("token_type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a refresh token",
        )

    # Issue new tokens
    new_data = {k: v for k, v in payload.items() if k not in ("exp", "iat")}
    new_data["jti"] = str(uuid.uuid4())

    access_token = create_access_token(new_data)
    new_refresh = create_refresh_token(new_data)

    return LoginResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
        user={"sub": payload.get("sub"), "type": payload.get("type")},
    )


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Logout / revoke token")
async def logout(request: Request, user: CurrentUser):
    from app.config import get_settings

    settings = get_settings()

    jti = user.get("jti")
    if jti:
        redis = getattr(request.app.state, "redis", None)
        ttl = settings.JWT_EXPIRE_MINUTES * 60
        await blacklist_token(redis, jti, ttl)
    log.info("user_logged_out", sub=user.get("sub"))


# ---------------------------------------------------------------------------
# POST /auth/register/subscriber
# ---------------------------------------------------------------------------

@router.post(
    "/register/subscriber",
    status_code=status.HTTP_201_CREATED,
    summary="Self-registration for subscribers",
)
async def register_subscriber(
    body: SubscriberRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    # Check unique email
    existing_email = await db.execute(
        select(Subscriber).where(Subscriber.email == body.email.lower())
    )
    if existing_email.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Check unique username
    existing_username = await db.execute(
        select(Subscriber).where(Subscriber.username == body.username.lower())
    )
    if existing_username.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    from app.services.crypto import encrypt_field

    subscriber = Subscriber(
        franchisee_id=body.franchisee_id,
        name=body.name,
        email=body.email.lower(),
        phone=body.phone,
        username=body.username.lower(),
        password_hash=hash_password(body.password),
        portal_password_hash=hash_password(body.password),
        pppoe_password_enc=encrypt_field(body.password),
        status="pending",
    )
    db.add(subscriber)
    await db.flush()

    log.info("subscriber_self_registered", subscriber_id=str(subscriber.id), email=body.email)

    return {
        "id": str(subscriber.id),
        "email": subscriber.email,
        "username": subscriber.username,
        "status": subscriber.status,
        "message": "Registration successful. Please wait for activation.",
    }


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get("/me", summary="Return current authenticated user info")
async def get_me(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    actor_type = user.get("type")
    sub = user.get("sub")

    if actor_type == "admin":
        return {"id": "admin", "type": "admin", "email": user.get("email")}

    if actor_type == "franchisee":
        result = await db.execute(
            select(FranchiseeUser).where(FranchiseeUser.id == uuid.UUID(sub))
        )
        fu = result.scalar_one_or_none()
        if not fu:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "id": str(fu.id),
            "type": "franchisee",
            "email": fu.email,
            "name": fu.name,
            "role": fu.role,
            "franchisee_id": str(fu.franchisee_id),
        }

    # subscriber
    result = await db.execute(
        select(Subscriber).where(
            Subscriber.id == uuid.UUID(sub),
            Subscriber.is_deleted == False,  # noqa: E712
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return {
        "id": str(s.id),
        "type": "subscriber",
        "email": s.email,
        "name": s.name,
        "username": s.username,
        "status": s.status,
        "franchisee_id": str(s.franchisee_id),
        "plan_expires_at": s.plan_expires_at.isoformat() if s.plan_expires_at else None,
    }
