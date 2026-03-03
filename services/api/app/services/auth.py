"""
JWT authentication service for whISP.

Provides:
  - create_access_token / create_refresh_token
  - decode_token
  - FastAPI dependencies: get_current_user, require_admin, require_franchisee
  - Redis-backed token blacklist (for logout)
  - get_db_conn() – raw asyncpg connection from the RADIUS pool
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import asyncpg
import redis.asyncio as aioredis
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import get_settings
from app.database import get_radius_pool

log = structlog.get_logger(__name__)
settings = get_settings()

_bearer_scheme = HTTPBearer(auto_error=True)

# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------

def create_access_token(data: dict[str, Any]) -> str:
    """
    Create a signed JWT access token.

    *data* must contain at minimum ``sub`` (user id as str) and ``type``
    (``admin`` | ``franchisee`` | ``subscriber``).
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_EXPIRE_MINUTES
    )
    payload.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    """Create a long-lived refresh token."""
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_EXPIRE_DAYS
    )
    payload.update(
        {"exp": expire, "iat": datetime.now(timezone.utc), "token_type": "refresh"}
    )
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Token decoding
# ---------------------------------------------------------------------------

def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT token.

    Raises ``HTTPException(401)`` on any failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def _get_redis(request: Request) -> aioredis.Redis | None:
    return getattr(request.app.state, "redis", None)


async def _is_token_blacklisted(redis: aioredis.Redis | None, jti: str) -> bool:
    if redis is None:
        return False
    return await redis.exists(f"blacklist:{jti}") > 0


async def blacklist_token(
    redis: aioredis.Redis | None, jti: str, ttl_seconds: int
) -> None:
    if redis is None:
        log.warning("redis_unavailable_cannot_blacklist_token", jti=jti)
        return
    await redis.setex(f"blacklist:{jti}", ttl_seconds, "1")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> dict[str, Any]:
    """
    Validate the Bearer token and return its payload.

    Checks the Redis blacklist so that logged-out tokens are rejected.
    """
    payload = decode_token(credentials.credentials)

    jti: str | None = payload.get("jti")
    if jti:
        redis = _get_redis(request)
        if await _is_token_blacklisted(redis, jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    return payload


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> dict[str, Any]:
    """Dependency that enforces the caller is an admin."""
    if user.get("type") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


AdminUser = Annotated[dict[str, Any], Depends(require_admin)]


async def require_franchisee(user: CurrentUser) -> dict[str, Any]:
    """Dependency that allows franchisee users or admins."""
    if user.get("type") not in ("franchisee", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Franchisee or admin privileges required",
        )
    return user


FranchiseeUser = Annotated[dict[str, Any], Depends(require_franchisee)]


async def require_subscriber(user: CurrentUser) -> dict[str, Any]:
    """Dependency that allows subscribers (or admin/franchisee)."""
    if user.get("type") not in ("subscriber", "franchisee", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Subscriber privileges required",
        )
    return user


# ---------------------------------------------------------------------------
# Raw asyncpg connection dependency
# ---------------------------------------------------------------------------

async def get_db_conn() -> asyncpg.Connection:  # type: ignore[return]
    """
    Yield a raw asyncpg connection from the RADIUS pool.

    Usage::

        @router.get("/")
        async def handler(conn: asyncpg.Connection = Depends(get_db_conn)):
            ...
    """
    pool = await get_radius_pool()
    async with pool.acquire() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Scope helpers used by routers
# ---------------------------------------------------------------------------

def assert_franchisee_scope(user: dict, franchisee_id: str) -> None:
    """
    Raise 403 if a franchisee user tries to access a different franchisee's
    resource.  Admins bypass this check.
    """
    if user.get("type") == "admin":
        return
    if user.get("franchisee_id") != franchisee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this franchisee's resource is not permitted",
        )


def assert_subscriber_scope(user: dict, subscriber_id: str) -> None:
    """Restrict subscriber-type tokens to their own resource."""
    if user.get("type") == "admin":
        return
    if user.get("type") == "franchisee":
        return  # franchisee can see all their subscribers
    if user.get("sub") != subscriber_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this subscriber's resource is not permitted",
        )
