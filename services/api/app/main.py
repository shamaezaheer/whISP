"""
whISP FastAPI application entry-point.

Wires together:
  - All domain routers
  - CORS, logging, and Prometheus middleware
  - Lifespan context manager (startup / shutdown)
  - Global exception handlers
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, make_asgi_app
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.database import close_radius_pool, init_db

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
from app.routers import (
    admin,
    auth,
    franchisees,
    nas,
    ott,
    payments,
    plans,
    subscribers,
    tickets,
    usage,
)

settings = get_settings()

# ---------------------------------------------------------------------------
# Logging setup — configure stdlib + structlog before anything else
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(message)s",
)
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    ),
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    log.info("startup_begin", platform=settings.PLATFORM_NAME)

    # Database connectivity check
    await init_db()

    # Redis connectivity check
    try:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis.ping()
        app.state.redis = redis
        log.info("redis_connected", url=settings.REDIS_URL)
    except Exception as exc:
        log.warning("redis_connection_failed", error=str(exc))
        app.state.redis = None

    log.info("startup_complete", platform=settings.PLATFORM_NAME)

    yield

    # --------------- shutdown ---------------
    log.info("shutdown_begin")
    if getattr(app.state, "redis", None):
        await app.state.redis.close()
    await close_radius_pool()
    log.info("shutdown_complete")


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title=f"{settings.PLATFORM_NAME} API",
    description="ISP Management Platform – REST API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request-logging & metrics middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def logging_and_metrics_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start_time = time.perf_counter()

    # Bind request context for structured logging
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else "unknown",
    )

    log.info("request_started")

    response = await call_next(request)

    duration = time.perf_counter() - start_time
    log.info(
        "request_finished",
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )

    # Prometheus
    endpoint = request.url.path
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status_code=str(response.status_code),
    ).inc()
    REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(duration)

    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint
# ---------------------------------------------------------------------------
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(subscribers.router, prefix="/subscribers", tags=["Subscribers"])
app.include_router(franchisees.router, prefix="/franchisees", tags=["Franchisees"])
app.include_router(plans.router, prefix="/plans", tags=["Plans"])
app.include_router(payments.router, prefix="/payments", tags=["Payments"])
app.include_router(usage.router, prefix="/usage", tags=["Usage & Analytics"])
app.include_router(ott.router, prefix="/ott", tags=["OTT Entitlements"])
app.include_router(nas.router, prefix="/nas", tags=["NAS Devices"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(tickets.router, prefix="/tickets", tags=["Support Tickets"])


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"], summary="Service health check")
async def health_check(request: Request) -> dict[str, Any]:
    redis_ok = False
    if getattr(request.app.state, "redis", None):
        try:
            await request.app.state.redis.ping()
            redis_ok = True
        except Exception:
            redis_ok = False

    return {
        "status": "ok",
        "platform": settings.PLATFORM_NAME,
        "environment": settings.ENVIRONMENT,
        "redis": "ok" if redis_ok else "unavailable",
    }


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    log.warning(
        "http_exception",
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    log.warning(
        "validation_error",
        errors=exc.errors(),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": exc.errors(),
            "status_code": 422,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "status_code": 500,
        },
    )
