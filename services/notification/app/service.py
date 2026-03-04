"""
Notification service - drains notifications table and consumes Kafka topic.
"""
import asyncio
import json
import time
from datetime import datetime, timezone

import asyncpg
import structlog
from aiokafka import AIOKafkaConsumer

from app.config import get_settings
from app.sms import send_sms, send_push

log = structlog.get_logger(__name__)
settings = get_settings()

MAX_ATTEMPTS = 5
DRAIN_INTERVAL = 3  # seconds
RATE_LIMIT = settings.SMS_RATE_LIMIT_PER_SECOND  # per second

async def drain_notifications(pool: asyncpg.Pool) -> None:
    """Continuously drain pending notifications from DB."""
    tokens_per_second = RATE_LIMIT
    last_refill = time.monotonic()
    tokens = float(tokens_per_second)

    while True:
        try:
            # Token bucket refill
            now = time.monotonic()
            elapsed = now - last_refill
            tokens = min(tokens_per_second, tokens + elapsed * tokens_per_second)
            last_refill = now

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT n.id, n.subscriber_id, n.franchisee_id, n.channel,
                              n.title, n.body, n.attempts,
                              s.phone, s.fcm_token
                       FROM notifications n
                       LEFT JOIN subscribers s ON s.id = n.subscriber_id
                       WHERE n.status = 'pending' AND n.attempts < $1
                       ORDER BY n.created_at ASC
                       LIMIT 50""",
                    MAX_ATTEMPTS
                )

            for row in rows:
                if tokens < 1:
                    await asyncio.sleep(1.0 / tokens_per_second)
                    tokens = 1
                tokens -= 1

                success = False
                channel = row["channel"]

                try:
                    if channel == "sms" and row["phone"]:
                        success = await send_sms(row["phone"], row["body"])
                    elif channel == "push" and row["fcm_token"]:
                        success = await send_push(
                            row["fcm_token"], row["title"], row["body"]
                        )
                    elif channel == "email":
                        log.info("notification_email_skipped", id=str(row["id"]))
                        success = True  # Skip email for now
                except Exception as e:
                    log.error("notification_send_error", id=str(row["id"]), error=str(e))

                async with pool.acquire() as conn:
                    new_attempts = row["attempts"] + 1
                    new_status = "sent" if success else ("failed" if new_attempts >= MAX_ATTEMPTS else "pending")
                    await conn.execute(
                        """UPDATE notifications
                           SET status=$1, attempts=$2, sent_at=$3
                           WHERE id=$4""",
                        new_status,
                        new_attempts,
                        datetime.now(timezone.utc) if success else None,
                        row["id"]
                    )

            if not rows:
                await asyncio.sleep(DRAIN_INTERVAL)

        except Exception as e:
            log.error("drain_loop_error", error=str(e))
            await asyncio.sleep(DRAIN_INTERVAL)

async def consume_kafka_notifications(pool: asyncpg.Pool) -> None:
    """Consume real-time notification events from Kafka."""
    consumer = AIOKafkaConsumer(
        settings.KAFKA_NOTIFICATIONS_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="notification-service",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
    )
    await consumer.start()
    log.info("notification_kafka_consumer_started")

    try:
        async for msg in consumer:
            event = msg.value
            try:
                # Insert into notifications table for the drain loop to pick up
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO notifications (subscriber_id, channel, title, body, status)
                           VALUES ($1, $2, $3, $4, 'pending')
                           ON CONFLICT DO NOTHING""",
                        event.get("subscriber_id"),
                        event.get("channel", "sms"),
                        event.get("title", "whISP"),
                        event.get("body", ""),
                    )
            except Exception as e:
                log.error("kafka_notification_error", error=str(e), event=event)
    finally:
        await consumer.stop()

async def main() -> None:
    log.info("notification_service_starting")
    pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
        min_size=3,
        max_size=15,
    )
    log.info("notification_db_connected")

    await asyncio.gather(
        drain_notifications(pool),
        consume_kafka_notifications(pool),
    )
