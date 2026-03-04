"""
RADIUS Accounting Consumer - processes accounting events from Kafka.
Writes to TimescaleDB usage_stats, updates subscriber quotas,
triggers CoA when quotas are exceeded.
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# Batch buffer
_batch: list[dict] = []
_last_flush = time.monotonic()

async def flush_batch(pool: asyncpg.Pool, batch: list[dict]) -> None:
    """Batch-write usage_stats to TimescaleDB."""
    if not batch:
        return

    try:
        async with pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO usage_stats (time, subscriber_id, franchisee_id, bytes_in, bytes_out, session_id)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT DO NOTHING""",
                [
                    (
                        row.get("timestamp") or datetime.now(timezone.utc),
                        row.get("subscriber_id"),
                        row.get("franchisee_id"),
                        row.get("bytes_in", 0),
                        row.get("bytes_out", 0),
                        row.get("session_id"),
                    )
                    for row in batch
                ]
            )
        log.debug("usage_stats_flushed", count=len(batch))
    except Exception as e:
        log.error("flush_batch_error", error=str(e))

async def process_accounting_event(
    pool: asyncpg.Pool,
    producer: AIOKafkaProducer,
    event: dict,
) -> None:
    """Process a single RADIUS accounting event."""
    acct_type = event.get("type", "")  # Start, Interim-Update, Stop
    username = event.get("username", "")
    bytes_in = int(event.get("bytes_in", 0))
    bytes_out = int(event.get("bytes_out", 0))
    session_id = event.get("session_id", "")

    if not username:
        return

    async with pool.acquire() as conn:
        # Look up subscriber
        sub = await conn.fetchrow(
            """SELECT s.id, s.franchisee_id, s.quota_used_bytes, s.status,
                      p.data_cap_gb, p.speed_throttle_kbps
               FROM subscribers s
               LEFT JOIN plans p ON p.id = s.plan_id
               WHERE s.username = $1 AND s.is_deleted = false""",
            username
        )

        if not sub:
            log.debug("accounting_unknown_username", username=username)
            return

        subscriber_id = sub["id"]
        franchisee_id = sub["franchisee_id"]
        total_bytes = bytes_in + bytes_out

        # Add to batch for TimescaleDB write
        _batch.append({
            "timestamp": datetime.now(timezone.utc),
            "subscriber_id": str(subscriber_id),
            "franchisee_id": str(franchisee_id),
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
            "session_id": session_id,
        })

        if acct_type in ("Interim-Update", "Stop") and total_bytes > 0:
            # Update subscriber's total data usage
            new_total = await conn.fetchval(
                """UPDATE subscribers
                   SET data_used_bytes = COALESCE(data_used_bytes, 0) + $1,
                       updated_at = NOW()
                   WHERE id = $2
                   RETURNING data_used_bytes""",
                total_bytes,
                subscriber_id
            )

            # Check quota
            data_cap_gb = sub["data_cap_gb"]
            if data_cap_gb and new_total is not None:
                cap_bytes = data_cap_gb * 1_073_741_824  # GB to bytes
                usage_pct = (new_total / cap_bytes) * 100

                # 80% warning notification
                prev_pct = ((new_total - total_bytes) / cap_bytes) * 100
                if prev_pct < 80 <= usage_pct:
                    log.info("quota_80pct", username=username, subscriber_id=str(subscriber_id))
                    await conn.execute(
                        """INSERT INTO notifications (subscriber_id, franchisee_id, channel, title, body, status)
                           VALUES ($1, $2, 'sms', 'ডেটা সতর্কতা',
                                   'আপনার ডেটা ব্যবহারের ৮০% সম্পন্ন হয়েছে। দ্রুত রিচার্জ করুন।',
                                   'pending')""",
                        subscriber_id, franchisee_id
                    )

                # 100% quota exceeded - throttle
                if usage_pct >= 100 and sub["status"] == "active":
                    log.info("quota_exceeded", username=username, subscriber_id=str(subscriber_id))
                    throttle_kbps = sub["speed_throttle_kbps"] or 512

                    # Insert notification
                    await conn.execute(
                        """INSERT INTO notifications (subscriber_id, franchisee_id, channel, title, body, status)
                           VALUES ($1, $2, 'sms', 'ডেটা শেষ',
                                   'আপনার ডেটা সীমা শেষ হয়েছে। গতি কমিয়ে দেওয়া হয়েছে।',
                                   'pending')""",
                        subscriber_id, franchisee_id
                    )

                    # Publish CoA rate-limit event to Kafka
                    coa_event = {
                        "action": "rate_limit",
                        "username": username,
                        "download_kbps": throttle_kbps,
                        "upload_kbps": throttle_kbps // 2,
                    }
                    await producer.send(
                        settings.KAFKA_COA_TOPIC,
                        json.dumps(coa_event).encode()
                    )

        if acct_type == "Stop":
            # Update radacct stop time
            await conn.execute(
                """UPDATE radacct
                   SET acctstoptime = NOW(),
                       acctinputoctets = acctinputoctets + $1,
                       acctoutputoctets = acctoutputoctets + $2
                   WHERE acctuniqueid = $3 AND acctstoptime IS NULL""",
                bytes_in, bytes_out,
                event.get("unique_id", "")
            )

async def main() -> None:
    global _batch, _last_flush

    log.info("radius_consumer_starting")
    pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
        min_size=3,
        max_size=20,
    )
    log.info("radius_consumer_db_connected")

    consumer = AIOKafkaConsumer(
        settings.KAFKA_RADIUS_ACCOUNTING_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="radius-consumer",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
    )

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode(),
    )

    await consumer.start()
    await producer.start()
    log.info("radius_consumer_kafka_connected")

    try:
        async for msg in consumer:
            event = msg.value
            try:
                await process_accounting_event(pool, producer, event)
            except Exception as e:
                log.error("accounting_event_error", error=str(e), event=str(event)[:200])

            # Flush batch every BATCH_SIZE messages or BATCH_TIMEOUT_SECONDS
            now = time.monotonic()
            if len(_batch) >= settings.BATCH_SIZE or (now - _last_flush) >= settings.BATCH_TIMEOUT_SECONDS:
                batch_to_flush = _batch.copy()
                _batch = []
                _last_flush = now
                await flush_batch(pool, batch_to_flush)
    finally:
        await consumer.stop()
        await producer.stop()
        await pool.close()
