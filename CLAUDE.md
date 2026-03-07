# whISP — Claude Code Context

## Project Overview

whISP is a multi-tenant ISP management platform for Bangladeshi ISPs. It handles subscriber lifecycle, PPPoE authentication via FreeRADIUS, billing, quota enforcement, and OTT entitlements.

## Current Implementation Status

> **Update this section every session.**

- [ ] Step 1: Project scaffold & Docker Compose
- [ ] Step 2: Database schema (TimescaleDB + PostgreSQL)
- [ ] Step 3: API service (FastAPI)
- [ ] Step 4: Environment configuration (`.env`)
- [ ] Step 5: _update as you progress_

**Last worked on:** _fill in before starting a session_

---

## Architecture

```
Nginx → FastAPI (api:8000)
             ↓ asyncpg
        PostgreSQL + TimescaleDB
             ↓ aiokafka
        Kafka → radius-consumer → quota enforcement → coa-engine → FreeRADIUS CoA
             ↓
        billing → bKash / Nagad / SSLCommerz
             ↓
        notification → SMS (SSL Wireless)
```

**Services:**

| Service | Port | Description |
|---------|------|-------------|
| `api` | 8000 | FastAPI REST — auth, subscribers, billing, OTT |
| `billing` | — | APScheduler jobs — expiry, auto-debit, reconciliation |
| `coa-engine` | — | RADIUS CoA — disconnect/rate-limit commands to NAS |
| `notification` | — | SMS + in-app notifications |
| `radius-consumer` | — | Kafka consumer for RADIUS accounting events |
| `postgres` | 5432 | TimescaleDB (timescale/timescaledb:latest-pg15) |
| `redis` | 6379 | Cache + session state |
| `kafka` | 29092 (host) / 9092 (internal) | Message bus |

---

## Stack & Key Versions

All services use **Python 3.12-slim**.

### API (`services/api/requirements.txt`)
```
fastapi==0.109.0
uvicorn[standard]==0.27.0
asyncpg==0.29.0
sqlalchemy[asyncio]==2.0.25
alembic==1.13.1
redis==5.0.1
aiokafka==0.10.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt<4.0          # MUST stay <4.0 — passlib 1.7.4 incompatible with bcrypt 4.x
python-multipart==0.0.6
httpx==0.26.0
pydantic==2.5.3
pydantic-settings==2.1.0
python-dateutil==2.8.2
pytz==2024.1
structlog==24.1.0
prometheus-client==0.19.0
```

### Billing (`services/billing/requirements.txt`)
```
asyncpg==0.29.0, aiokafka==0.10.0, redis==5.0.1, httpx==0.26.0
apscheduler==3.10.4, pydantic-settings==2.1.0, python-dateutil==2.8.2
pytz==2024.1, structlog==24.1.0
passlib[bcrypt]==1.7.4, cryptography==41.0.7
```

### Other services
`asyncpg`, `aiokafka`, `pydantic-settings`, `structlog` — no auth deps.

---

## Database

- **Engine:** PostgreSQL 15 + TimescaleDB extension
- **Connection string:** `postgresql+asyncpg://isp_user:isp_password@postgres:5432/isp_platform`
  - Always use `postgresql+asyncpg://` — plain `postgresql://` will fail with asyncpg
- **Alembic migrations:** `services/api/alembic/versions/`
- **Raw SQL migrations:** `database/migrations/001_initial_schema.sql` (applied via Docker entrypoint)
- **RADIUS tables:** `radcheck`, `radreply`, `radgroupcheck`, `radgroupreply`, `radusergroup`, `radacct`
- `radacct` is a **TimescaleDB hypertable** partitioned monthly

### Required PostgreSQL Extensions
```sql
pgcrypto, timescaledb, pg_stat_statements, citext
```

---

## Common Commands

### Build & Run
```bash
docker compose build <service>          # rebuild one service
docker compose build --no-cache <service>  # force clean rebuild (e.g. after requirements.txt change)
docker compose up -d                    # start all services
docker compose logs <service> --tail=50 # check logs
docker compose ps                       # check health status
```

### After changing requirements.txt
```bash
docker compose build --no-cache <service>
docker compose up -d <service>
```

### Database
```bash
# Run migrations (Alembic)
docker compose run --rm api alembic upgrade head

# Seed dev data
docker compose run --rm api python scripts/seed_dev.py
docker compose run --rm api python scripts/seed_dev.py --reset    # truncate + reseed
docker compose run --rm api python scripts/seed_dev.py --minimal  # 10 subscribers only

# Connect directly
psql postgresql://isp_user:isp_password@localhost:5432/isp_platform
```

### Tests
```bash
docker compose run --rm api pytest
docker compose run --rm api pytest tests/test_auth.py -v
```

---

## Environment Variables (`.env`)

Copy from `.env.example`. Key variables:

```bash
# Database — use asyncpg prefix
DATABASE_URL=postgresql+asyncpg://isp_user:isp_password@postgres:5432/isp_platform
RADIUS_DB_URL=postgresql+asyncpg://isp_user:isp_password@postgres:5432/isp_platform

# Security — generate once, never change after data is encrypted
JWT_SECRET_KEY=$(openssl rand -hex 32)           # 64-char hex
ENCRYPTION_KEY=$(openssl rand -base64 32 | head -c 32)  # encrypts NID + PPPoE passwords

# Kafka (internal Docker network)
KAFKA_BOOTSTRAP_SERVERS=kafka:9092

# Redis
REDIS_URL=redis://redis:6379/0
```

---

## Known Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| `bcrypt` error on login | `bcrypt>=4.0` breaks `passlib 1.7.4` | Pin `bcrypt<4.0` in requirements.txt, then `docker compose build --no-cache api` |
| `asyncpg` connection error | Wrong DB URL scheme | Use `postgresql+asyncpg://` not `postgresql://` |
| Container has old packages | `pip install` only runs at build time | Always rebuild image after changing `requirements.txt` |

---

## Infrastructure

- **FreeRADIUS:** `infrastructure/freeradius/` — SQL module + Kafka accounting publisher
- **Nginx:** `infrastructure/nginx/nginx.conf` — reverse proxy, serves frontend static files
- **Kubernetes:** `infrastructure/kubernetes/deployment.yaml` — HPA configured for api (2-10 replicas) and radius-consumer (3-12 replicas)

## Seed Data Credentials

- **Franchisee staff password:** `Password@123`
- **Admin:** set via `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars

## API Endpoints

Base: `http://localhost:8000`

| Prefix | Description |
|--------|-------------|
| `/auth` | Login, token refresh |
| `/subscribers` | Subscriber CRUD, quota |
| `/franchisees` | Franchisee management |
| `/plans` | Internet plans |
| `/payments` | bKash, Nagad, SSLCommerz |
| `/usage` | Analytics, TimescaleDB queries |
| `/ott` | OTT entitlements (Chorki, Hoichoi) |
| `/nas` | NAS device management |
| `/admin` | Admin operations |
| `/tickets` | Support tickets |
| `/health` | Health check |
| `/metrics` | Prometheus metrics |
