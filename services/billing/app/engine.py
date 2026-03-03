"""
Billing engine: APScheduler-based background job runner for the ISP billing system.

Jobs:
  - check_expiry_warnings   every hour
  - process_auto_debit      every 15 minutes
  - enforce_expiry          every 5 minutes
  - reconcile_revenue       daily at 02:00 BDT
  - check_agreement_health  daily at 03:00 BDT
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytz
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bkash import BKashClient
from app.config import get_settings

log = structlog.get_logger(__name__)
BDT = pytz.timezone("Asia/Dhaka")

# ---------------------------------------------------------------------------
# Shared state (set during main())
# ---------------------------------------------------------------------------
_db_pool: asyncpg.Pool | None = None
_bkash: BKashClient | None = None
_kafka_producer = None  # aiokafka.AIOKafkaProducer


def _pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError("DB pool not initialised")
    return _db_pool


# ---------------------------------------------------------------------------
# Helper: publish to Kafka
# ---------------------------------------------------------------------------
async def _publish(topic: str, payload: dict) -> None:
    if _kafka_producer is None:
        log.warning("kafka_producer_not_ready", topic=topic)
        return
    try:
        value = json.dumps(payload).encode()
        await _kafka_producer.send_and_wait(topic, value=value)
    except Exception:
        log.exception("kafka_publish_error", topic=topic)


# ---------------------------------------------------------------------------
# Job 1 – check_expiry_warnings
# ---------------------------------------------------------------------------
async def check_expiry_warnings() -> None:
    """Send 24-hour and 2-hour expiry warnings to subscribers."""
    log.info("job_start", job="check_expiry_warnings")
    pool = _pool()
    now = datetime.now(timezone.utc)

    windows = [
        (now + timedelta(hours=23), now + timedelta(hours=25), "24h"),
        (now + timedelta(hours=2), now + timedelta(hours=4), "2h"),
    ]

    msg_24h = (
        "আপনার ইন্টারনেট প্যাকেজ ২৪ ঘণ্টার মধ্যে মেয়াদ শেষ হবে। "
        "পুনরায় চালু রাখতে এখনই পরিশোধ করুন।"
    )
    msg_2h = (
        "আপনার ইন্টারনেট প্যাকেজ ২ ঘণ্টার মধ্যে মেয়াদ শেষ হবে। "
        "পুনরায় চালু রাখতে এখনই পরিশোধ করুন।"
    )
    messages = {"24h": msg_24h, "2h": msg_2h}

    async with pool.acquire() as conn:
        for window_start, window_end, label in windows:
            # Find subscribers whose plan expires in this window and who have
            # not received a notification in the last 22 hours.
            rows = await conn.fetch(
                """
                SELECT s.id, s.phone, s.pppoe_username, s.plan_expires_at
                FROM subscribers s
                WHERE s.plan_expires_at BETWEEN $1 AND $2
                  AND s.status = 'active'
                  AND NOT EXISTS (
                      SELECT 1 FROM notifications n
                      WHERE n.subscriber_id = s.id
                        AND n.notification_type = 'expiry_warning'
                        AND n.created_at > now() - INTERVAL '22 hours'
                  )
                """,
                window_start,
                window_end,
            )

            for row in rows:
                try:
                    await conn.execute(
                        """
                        INSERT INTO notifications
                            (id, subscriber_id, channel, notification_type,
                             message, status, created_at)
                        VALUES ($1, $2, 'sms', 'expiry_warning', $3, 'pending', now())
                        """,
                        str(uuid.uuid4()),
                        row["id"],
                        messages[label],
                    )
                    log.info(
                        "expiry_warning_queued",
                        subscriber_id=row["id"],
                        label=label,
                        expires_at=str(row["plan_expires_at"]),
                    )
                except Exception:
                    log.exception("expiry_warning_insert_error", subscriber_id=row["id"])

    log.info("job_done", job="check_expiry_warnings")


# ---------------------------------------------------------------------------
# Job 2 – process_auto_debit
# ---------------------------------------------------------------------------
async def process_auto_debit() -> None:
    """Charge bKash agreements for subscribers near expiry."""
    log.info("job_start", job="process_auto_debit")
    pool = _pool()
    settings = get_settings()
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.pppoe_username, s.phone, s.bkash_agreement_id,
                   s.plan_expires_at, s.franchisee_id,
                   p.price, p.validity_days, p.name AS plan_name
            FROM subscribers s
            JOIN plans p ON p.id = s.plan_id
            WHERE s.bkash_agreement_id IS NOT NULL
              AND s.plan_expires_at BETWEEN $1 AND $2
              AND s.status = 'active'
            """,
            now - timedelta(hours=1),
            now + timedelta(hours=1),
        )

    for row in rows:
        subscriber_id = row["id"]
        agreement_id = row["bkash_agreement_id"]
        amount = float(row["price"])
        invoice_number = f"INV-{subscriber_id}-{int(now.timestamp())}"
        log.info(
            "auto_debit_attempt",
            subscriber_id=subscriber_id,
            agreement_id=agreement_id,
            amount=amount,
        )

        try:
            result = await _bkash.charge_agreement(
                agreement_id=agreement_id,
                amount=amount,
                invoice_number=invoice_number,
            )

            if result.get("statusCode") == "0000":
                trx_id = result.get("trxID", "")
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        new_expires = row["plan_expires_at"] + timedelta(
                            days=int(row["validity_days"])
                        )
                        await conn.execute(
                            """
                            UPDATE subscribers
                            SET plan_expires_at = $1,
                                data_used_bytes  = 0,
                                updated_at       = now()
                            WHERE id = $2
                            """,
                            new_expires,
                            subscriber_id,
                        )
                        await conn.execute(
                            """
                            INSERT INTO payment_transactions
                                (id, subscriber_id, franchisee_id, amount,
                                 gateway, gateway_trx_id, invoice_number,
                                 status, created_at)
                            VALUES ($1, $2, $3, $4, 'bkash', $5, $6, 'completed', now())
                            """,
                            str(uuid.uuid4()),
                            subscriber_id,
                            row["franchisee_id"],
                            amount,
                            trx_id,
                            invoice_number,
                        )
                        # Queue success SMS
                        success_msg = (
                            f"আপনার {row['plan_name']} প্যাকেজ সফলভাবে নবায়ন হয়েছে। "
                            f"পরিমাণ: ৳{amount:.2f}। TrxID: {trx_id}"
                        )
                        await conn.execute(
                            """
                            INSERT INTO notifications
                                (id, subscriber_id, channel, notification_type,
                                 message, status, created_at)
                            VALUES ($1, $2, 'sms', 'payment_success', $3, 'pending', now())
                            """,
                            str(uuid.uuid4()),
                            subscriber_id,
                            success_msg,
                        )

                # Publish reconnect command to Kafka
                await _publish(
                    "coa",
                    {
                        "action": "reconnect",
                        "username": row["pppoe_username"],
                        "subscriber_id": subscriber_id,
                        "reason": "auto_debit_success",
                    },
                )
                log.info(
                    "auto_debit_success",
                    subscriber_id=subscriber_id,
                    trx_id=trx_id,
                    new_expires=str(new_expires),
                )
            else:
                raise ValueError(
                    f"bKash returned non-zero status: {result.get('statusCode')} "
                    f"{result.get('statusMessage')}"
                )

        except Exception as exc:
            log.error("auto_debit_failed", subscriber_id=subscriber_id, error=str(exc))
            async with pool.acquire() as conn:
                failure_msg = (
                    "আপনার ইন্টারনেট বিল স্বয়ংক্রিয়ভাবে পরিশোধ করা সম্ভব হয়নি। "
                    "অনুগ্রহ করে ম্যানুয়ালি পরিশোধ করুন।"
                )
                await conn.execute(
                    """
                    INSERT INTO notifications
                        (id, subscriber_id, channel, notification_type,
                         message, status, created_at)
                    VALUES ($1, $2, 'sms', 'payment_failure', $3, 'pending', now())
                    """,
                    str(uuid.uuid4()),
                    subscriber_id,
                    failure_msg,
                )

    log.info("job_done", job="process_auto_debit")


# ---------------------------------------------------------------------------
# Job 3 – enforce_expiry
# ---------------------------------------------------------------------------
async def enforce_expiry() -> None:
    """Suspend or terminate subscribers whose plans have expired."""
    log.info("job_start", job="enforce_expiry")
    pool = _pool()
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        # First pass: active subscribers expired < 24 h ago -> suspend
        to_suspend = await conn.fetch(
            """
            SELECT id, pppoe_username, phone
            FROM subscribers
            WHERE plan_expires_at < now()
              AND plan_expires_at >= now() - INTERVAL '24 hours'
              AND status = 'active'
            """
        )
        for row in to_suspend:
            try:
                async with conn.transaction():
                    await conn.execute(
                        """
                        UPDATE subscribers
                        SET status = 'suspended', updated_at = now()
                        WHERE id = $1
                        """,
                        row["id"],
                    )
                await _publish(
                    "coa",
                    {
                        "action": "disconnect",
                        "username": row["pppoe_username"],
                        "subscriber_id": row["id"],
                        "reason": "plan_expired",
                    },
                )
                log.info("subscriber_suspended", subscriber_id=row["id"])
            except Exception:
                log.exception("suspend_error", subscriber_id=row["id"])

        # Second pass: suspended subscribers expired > 24 h ago -> terminate
        to_terminate = await conn.fetch(
            """
            SELECT id, pppoe_username
            FROM subscribers
            WHERE plan_expires_at < now() - INTERVAL '24 hours'
              AND status = 'suspended'
            """
        )
        for row in to_terminate:
            try:
                await conn.execute(
                    """
                    UPDATE subscribers
                    SET status = 'terminated', updated_at = now()
                    WHERE id = $1
                    """,
                    row["id"],
                )
                log.info("subscriber_terminated", subscriber_id=row["id"])
            except Exception:
                log.exception("terminate_error", subscriber_id=row["id"])

    log.info("job_done", job="enforce_expiry")


# ---------------------------------------------------------------------------
# Job 4 – reconcile_revenue
# ---------------------------------------------------------------------------
async def reconcile_revenue() -> None:
    """Aggregate yesterday's payments per franchisee and write audit log."""
    log.info("job_start", job="reconcile_revenue")
    pool = _pool()
    bdt_now = datetime.now(BDT)
    yesterday = (bdt_now - timedelta(days=1)).date()
    day_start = BDT.localize(
        datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0)
    ).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT franchisee_id,
                   COUNT(*)        AS transaction_count,
                   SUM(amount)     AS total_amount,
                   COUNT(DISTINCT subscriber_id) AS unique_subscribers
            FROM payment_transactions
            WHERE status    = 'completed'
              AND created_at >= $1
              AND created_at <  $2
            GROUP BY franchisee_id
            """,
            day_start,
            day_end,
        )

        for row in rows:
            payload = {
                "date": str(yesterday),
                "franchisee_id": str(row["franchisee_id"]),
                "transaction_count": int(row["transaction_count"]),
                "total_amount": float(row["total_amount"]),
                "unique_subscribers": int(row["unique_subscribers"]),
            }
            try:
                await conn.execute(
                    """
                    INSERT INTO audit_logs
                        (id, event_type, entity_type, entity_id, payload, created_at)
                    VALUES ($1, 'revenue_reconciliation', 'franchisee', $2, $3, now())
                    """,
                    str(uuid.uuid4()),
                    str(row["franchisee_id"]),
                    json.dumps(payload),
                )
                log.info(
                    "revenue_reconciled",
                    franchisee_id=str(row["franchisee_id"]),
                    total_amount=float(row["total_amount"]),
                )
            except Exception:
                log.exception(
                    "reconcile_insert_error",
                    franchisee_id=str(row["franchisee_id"]),
                )

    log.info("job_done", job="reconcile_revenue")


# ---------------------------------------------------------------------------
# Job 5 – check_agreement_health
# ---------------------------------------------------------------------------
async def check_agreement_health() -> None:
    """Verify bKash agreements are still active; clear cancelled ones."""
    log.info("job_start", job="check_agreement_health")
    pool = _pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.bkash_agreement_id, s.franchisee_id,
                   s.phone, s.pppoe_username
            FROM subscribers s
            WHERE s.bkash_agreement_id IS NOT NULL
              AND s.status IN ('active', 'suspended')
            """
        )

    for row in rows:
        agreement_id = row["bkash_agreement_id"]
        try:
            result = await _bkash.query_agreement(agreement_id)
            agreement_status = result.get("agreementStatus", "")

            if agreement_status.upper() in ("CANCELLED", "EXPIRED", "INVALID"):
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.execute(
                            """
                            UPDATE subscribers
                            SET bkash_agreement_id = NULL, updated_at = now()
                            WHERE id = $1
                            """,
                            row["id"],
                        )
                        # Notify franchisee
                        notify_msg = (
                            f"গ্রাহক {row['pppoe_username']} এর bKash চুক্তি "
                            f"({agreement_id}) বাতিল হয়েছে। "
                            "অটো পেমেন্ট বন্ধ হয়ে গেছে।"
                        )
                        await conn.execute(
                            """
                            INSERT INTO notifications
                                (id, franchisee_id, channel, notification_type,
                                 message, status, created_at)
                            VALUES ($1, $2, 'sms', 'agreement_cancelled',
                                    $3, 'pending', now())
                            """,
                            str(uuid.uuid4()),
                            row["franchisee_id"],
                            notify_msg,
                        )
                log.warning(
                    "agreement_cleared",
                    subscriber_id=row["id"],
                    agreement_id=agreement_id,
                    agreement_status=agreement_status,
                )
        except Exception:
            log.exception(
                "agreement_health_check_error",
                subscriber_id=row["id"],
                agreement_id=agreement_id,
            )

    log.info("job_done", job="check_agreement_health")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    global _db_pool, _bkash, _kafka_producer

    import redis.asyncio as aioredis
    from aiokafka import AIOKafkaProducer

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )

    settings = get_settings()
    log.info("billing_engine_starting", platform=settings.PLATFORM_NAME)

    # DB pool
    _db_pool = await asyncpg.create_pool(
        settings.DATABASE_URL,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    log.info("db_pool_ready")

    # Redis (used by bKash client for token cache)
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    # bKash client
    _bkash = BKashClient(
        base_url=settings.BKASH_BASE_URL,
        username=settings.BKASH_USERNAME,
        password=settings.BKASH_PASSWORD,
        app_key=settings.BKASH_APP_KEY,
        app_secret=settings.BKASH_APP_SECRET,
        redis=redis_client,
    )

    # Kafka producer
    _kafka_producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    )
    await _kafka_producer.start()
    log.info("kafka_producer_ready")

    # Scheduler
    scheduler = AsyncIOScheduler(timezone=BDT)

    scheduler.add_job(
        check_expiry_warnings,
        "interval",
        hours=1,
        id="check_expiry_warnings",
        next_run_time=datetime.now(BDT),
    )
    scheduler.add_job(
        process_auto_debit,
        "interval",
        minutes=15,
        id="process_auto_debit",
        next_run_time=datetime.now(BDT),
    )
    scheduler.add_job(
        enforce_expiry,
        "interval",
        minutes=5,
        id="enforce_expiry",
        next_run_time=datetime.now(BDT),
    )
    scheduler.add_job(
        reconcile_revenue,
        "cron",
        hour=2,
        minute=0,
        id="reconcile_revenue",
    )
    scheduler.add_job(
        check_agreement_health,
        "cron",
        hour=3,
        minute=0,
        id="check_agreement_health",
    )

    scheduler.start()
    log.info("scheduler_started")

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("billing_engine_stopping")
    finally:
        scheduler.shutdown(wait=False)
        await _kafka_producer.stop()
        await _db_pool.close()
        await redis_client.aclose()
        log.info("billing_engine_stopped")
