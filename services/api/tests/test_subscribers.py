"""Tests for subscriber model and status transitions."""
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Franchisee, Plan, Subscriber
from app.services.crypto import hash_password


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest_asyncio.fixture()
async def franchisee(db_session: AsyncSession) -> Franchisee:
    fr = Franchisee(
        name="Sylhet Telecom",
        slug="sylhet-telecom",
        contact_email="ops@sylhettelecom.com",
        contact_phone="01711000002",
        status="active",
    )
    db_session.add(fr)
    await db_session.flush()
    return fr


@pytest_asyncio.fixture()
async def plan(db_session: AsyncSession) -> Plan:
    p = Plan(
        name="5 Mbps Home",
        slug="5mbps-home",
        download_kbps=5_120,
        upload_kbps=2_560,
        price=400,
        radius_group="5mbps",
    )
    db_session.add(p)
    await db_session.flush()
    return p


@pytest_asyncio.fixture()
async def subscriber(
    db_session: AsyncSession, franchisee: Franchisee, plan: Plan
) -> Subscriber:
    sub = Subscriber(
        franchisee_id=franchisee.id,
        plan_id=plan.id,
        name="Karim Ahmed",
        email="karim@example.com",
        phone="01812345678",
        username="karim01",
        password_hash=hash_password("pppoe-secret"),
        status="active",
        plan_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.flush()
    return sub


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscriber_default_status_is_pending(
    db_session: AsyncSession, franchisee: Franchisee
):
    sub = Subscriber(
        franchisee_id=franchisee.id,
        name="New User",
        email="new@example.com",
        username="newuser",
        password_hash=hash_password("pass"),
    )
    db_session.add(sub)
    await db_session.flush()
    assert sub.status == "pending"


@pytest.mark.asyncio
async def test_subscriber_quota_defaults_to_zero(subscriber: Subscriber):
    assert subscriber.quota_used_bytes == 0


@pytest.mark.asyncio
async def test_subscriber_is_not_deleted_by_default(subscriber: Subscriber):
    assert subscriber.is_deleted is False
    assert subscriber.deleted_at is None


@pytest.mark.asyncio
async def test_subscriber_has_uuid_id(subscriber: Subscriber):
    assert subscriber.id is not None
    assert isinstance(subscriber.id, uuid.UUID)


@pytest.mark.asyncio
async def test_subscriber_password_hash_not_plaintext(subscriber: Subscriber):
    assert subscriber.password_hash != "pppoe-secret"
    assert len(subscriber.password_hash) > 20


@pytest.mark.asyncio
async def test_soft_delete_subscriber(
    db_session: AsyncSession, subscriber: Subscriber
):
    subscriber.is_deleted = True
    subscriber.deleted_at = datetime.now(timezone.utc)
    subscriber.status = "terminated"
    await db_session.flush()

    result = await db_session.execute(
        select(Subscriber).where(Subscriber.id == subscriber.id)
    )
    fetched = result.scalar_one()
    assert fetched.is_deleted is True
    assert fetched.status == "terminated"


@pytest.mark.asyncio
async def test_subscriber_email_unique_constraint(
    db_session: AsyncSession, franchisee: Franchisee, subscriber: Subscriber
):
    dup = Subscriber(
        franchisee_id=franchisee.id,
        name="Another User",
        email="karim@example.com",  # same email
        username="karim02",
        password_hash=hash_password("pass"),
    )
    db_session.add(dup)
    with pytest.raises(Exception):  # IntegrityError
        await db_session.flush()
