"""Tests for the plans router."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Franchisee, Plan


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest_asyncio.fixture()
async def franchisee(db_session: AsyncSession) -> Franchisee:
    fr = Franchisee(
        name="Dhaka Net",
        slug="dhaka-net",
        contact_email="admin@dhakanet.com",
        contact_phone="01711000001",
        status="active",
    )
    db_session.add(fr)
    await db_session.flush()
    return fr


@pytest_asyncio.fixture()
async def active_plan(db_session: AsyncSession, franchisee: Franchisee) -> Plan:
    plan = Plan(
        name="10 Mbps Unlimited",
        slug="10mbps-unlimited",
        download_kbps=10_240,
        upload_kbps=5_120,
        validity_days=30,
        price=500,
        currency="BDT",
        radius_group="10mbps",
        is_active=True,
        is_public=True,
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


# ------------------------------------------------------------------
# Model-level tests (no HTTP layer)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_default_currency_is_bdt(db_session: AsyncSession):
    plan = Plan(
        name="Basic 5 Mbps",
        slug="basic-5mbps",
        download_kbps=5_120,
        upload_kbps=2_560,
        price=300,
        radius_group="5mbps",
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.currency == "BDT"


@pytest.mark.asyncio
async def test_plan_with_quota(db_session: AsyncSession):
    plan = Plan(
        name="20GB Pack",
        slug="20gb-pack",
        download_kbps=20_480,
        upload_kbps=10_240,
        quota_gb=20,
        validity_days=15,
        price=200,
        radius_group="quota-20gb",
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.quota_gb == 20
    assert plan.validity_days == 15


@pytest.mark.asyncio
async def test_plan_unlimited_has_null_quota(active_plan: Plan):
    assert active_plan.quota_gb is None


@pytest.mark.asyncio
async def test_plan_ott_entitlements(db_session: AsyncSession):
    plan = Plan(
        name="Premium OTT Bundle",
        slug="premium-ott",
        download_kbps=30_720,
        upload_kbps=15_360,
        price=900,
        radius_group="30mbps",
        ott_entitlements=["chorki", "hoichoi"],
    )
    db_session.add(plan)
    await db_session.flush()
    assert "chorki" in plan.ott_entitlements
    assert "hoichoi" in plan.ott_entitlements


@pytest.mark.asyncio
async def test_plan_franchisee_scoped(db_session: AsyncSession, franchisee: Franchisee):
    plan = Plan(
        name="Franchisee Special",
        slug="fran-special",
        download_kbps=8_192,
        upload_kbps=4_096,
        price=450,
        radius_group="8mbps",
        franchisee_id=franchisee.id,
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.franchisee_id == franchisee.id
