"""
Async SQLAlchemy database setup for whISP.

Provides:
  - async_engine   – SQLAlchemy AsyncEngine backed by asyncpg
  - AsyncSessionLocal – sessionmaker for AsyncSession
  - get_db()       – FastAPI dependency that yields an AsyncSession
  - init_db()      – startup health-check / connection test
"""
import asyncpg
import structlog
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.config import get_settings

log = structlog.get_logger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    echo=settings.DEBUG,
    future=True,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# ---------------------------------------------------------------------------
# Declarative base (imported by models)
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
async def get_db() -> AsyncSession:  # type: ignore[return]
    """
    Yield an AsyncSession and ensure it is closed after the request.
    Usage::

        @router.get("/")
        async def handler(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Startup helper
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """
    Verify that the database is reachable and log the server version.
    Called during application lifespan startup.
    """
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            log.info("database_connected", version=version)
    except Exception as exc:
        log.error("database_connection_failed", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# Raw asyncpg pool (for RADIUS / TimescaleDB direct queries)
# ---------------------------------------------------------------------------
_radius_pool: asyncpg.Pool | None = None


async def get_radius_pool() -> asyncpg.Pool:
    """
    Return a shared asyncpg connection pool for the RADIUS database.
    Creates the pool on first call.
    """
    global _radius_pool
    if _radius_pool is None:
        _radius_pool = await asyncpg.create_pool(
            dsn=settings.asyncpg_radius_url,
            min_size=5,
            max_size=20,
            command_timeout=30,
        )
        log.info("radius_pool_created")
    return _radius_pool


async def close_radius_pool() -> None:
    global _radius_pool
    if _radius_pool is not None:
        await _radius_pool.close()
        _radius_pool = None
        log.info("radius_pool_closed")
