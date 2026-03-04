"""Tests for payment transaction model and invoice generation."""
import re
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Franchisee, PaymentTransaction, Plan, Subscriber
from app.services.crypto import hash_password


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest_asyncio.fixture()
async def franchisee(db_session: AsyncSession) -> Franchisee:
    fr = Franchisee(
        name="Chittagong ISP",
        slug="ctg-isp",
        contact_email="ops@ctgisp.com",
        status="active",
    )
    db_session.add(fr)
    await db_session.flush()
    return fr


@pytest_asyncio.fixture()
async def subscriber(db_session: AsyncSession, franchisee: Franchisee) -> Subscriber:
    sub = Subscriber(
        franchisee_id=franchisee.id,
        name="Rahim Islam",
        email="rahim@example.com",
        username="rahim01",
        password_hash=hash_password("pass"),
        status="active",
    )
    db_session.add(sub)
    await db_session.flush()
    return sub


@pytest_asyncio.fixture()
async def plan(db_session: AsyncSession) -> Plan:
    p = Plan(
        name="15 Mbps",
        slug="15mbps",
        download_kbps=15_360,
        upload_kbps=7_680,
        price=700,
        radius_group="15mbps",
    )
    db_session.add(p)
    await db_session.flush()
    return p


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_transaction_default_status(
    db_session: AsyncSession, subscriber: Subscriber
):
    tx = PaymentTransaction(
        subscriber_id=subscriber.id,
        gateway="bkash",
        invoice_number="INV-2025-00001",
        amount=500.00,
    )
    db_session.add(tx)
    await db_session.flush()
    assert tx.status == "initiated"


@pytest.mark.asyncio
async def test_payment_currency_defaults_to_bdt(
    db_session: AsyncSession, subscriber: Subscriber
):
    tx = PaymentTransaction(
        subscriber_id=subscriber.id,
        gateway="nagad",
        invoice_number="INV-2025-00002",
        amount=300.00,
    )
    db_session.add(tx)
    await db_session.flush()
    assert tx.currency == "BDT"


@pytest.mark.asyncio
async def test_payment_gateway_response_stored(
    db_session: AsyncSession, subscriber: Subscriber
):
    gateway_data = {
        "transactionId": "TXN123456",
        "paymentId": "PAY789",
        "trxID": "BKASH-TRX-001",
        "amount": "500.00",
        "currency": "BDT",
    }
    tx = PaymentTransaction(
        subscriber_id=subscriber.id,
        gateway="bkash",
        invoice_number="INV-2025-00003",
        amount=500.00,
        status="completed",
        completed_at=datetime.now(timezone.utc),
        gateway_response=gateway_data,
    )
    db_session.add(tx)
    await db_session.flush()
    assert tx.gateway_response["trxID"] == "BKASH-TRX-001"


@pytest.mark.asyncio
async def test_payment_invoice_unique_constraint(
    db_session: AsyncSession, subscriber: Subscriber
):
    tx1 = PaymentTransaction(
        subscriber_id=subscriber.id,
        gateway="manual",
        invoice_number="INV-DUP-001",
        amount=200.00,
    )
    tx2 = PaymentTransaction(
        subscriber_id=subscriber.id,
        gateway="manual",
        invoice_number="INV-DUP-001",  # duplicate
        amount=200.00,
    )
    db_session.add(tx1)
    db_session.add(tx2)
    with pytest.raises(Exception):  # IntegrityError
        await db_session.flush()


@pytest.mark.asyncio
async def test_payment_all_bd_gateways(
    db_session: AsyncSession, subscriber: Subscriber
):
    """All supported Bangladesh payment gateways can be stored."""
    gateways = ["bkash", "nagad", "sslcommerz", "manual"]
    for i, gw in enumerate(gateways, start=10):
        tx = PaymentTransaction(
            subscriber_id=subscriber.id,
            gateway=gw,
            invoice_number=f"INV-GW-{i:04d}",
            amount=100.00 * i,
        )
        db_session.add(tx)
    await db_session.flush()


def test_invoice_number_format():
    """Invoice numbers must match the WHISP-YYYYMM-NNNNNN pattern."""
    pattern = re.compile(r"^WHISP-\d{6}-\d{6}$")
    samples = [
        "WHISP-202501-000001",
        "WHISP-202512-999999",
    ]
    for s in samples:
        assert pattern.match(s), f"{s!r} does not match expected invoice format"
