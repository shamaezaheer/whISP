"""
CoA Worker - processes pending CoA commands from DB and Kafka.
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import structlog
from aiokafka import AIOKafkaConsumer

from app.config import get_settings
from app.coa import send_disconnect, send_rate_limit

log = structlog.get_logger(__name__)
settings = get_settings()

# Metrics
success_count = 0
failure_count = 0

async def process_command(pool: asyncpg.Pool, command: dict) -> bool:
    """Process a single CoA command. Returns True on success."""
    global success_count, failure_count

    command_id = command["id"]
    command_type = command["command_type"]
    username = command.get("username") or command.get("attributes", {}).get("username", "")

    async with pool.acquire() as conn:
        # Fetch NAS device details
        nas = await conn.fetchrow(
            "SELECT ip_address, secret, coa_port FROM nas_devices WHERE id = $1 AND is_active = true",
            command["nas_device_id"]
        )
        if not nas:
            log.warning("coa_nas_not_found", command_id=command_id)
            await conn.execute(
                "UPDATE coa_commands SET success=false, error='NAS not found', updated_at=NOW() WHERE id=$1",
                command_id
            )
            return False

        t0 = time.monotonic()
        try:
            if command_type in ("disconnect",):
                result = await send_disconnect(
                    nas_ip=nas["ip_address"],
                    nas_secret=nas["secret"],
                    username=username,
                    session_id=command.get("attributes", {}).get("session_id"),
                    coa_port=nas["coa_port"] or 3799,
                )
            elif command_type in ("rate_limit", "coa"):
                attrs = command.get("attributes", {})
                result = await send_rate_limit(
                    nas_ip=nas["ip_address"],
                    nas_secret=nas["secret"],
                    username=username,
                    download_kbps=attrs.get("download_kbps", 512),
                    upload_kbps=attrs.get("upload_kbps", 256),
                    session_id=attrs.get("session_id"),
                    coa_port=nas["coa_port"] or 3799,
                )
            else:
                result = {"success": False, "error": f"Unknown command type: {command_type}"}

            success = result.get("success", False)
            if success:
                success_count += 1
            else:
                failure_count += 1

            await conn.execute(
                """UPDATE coa_commands
                   SET success=$1, response=$2, updated_at=NOW()
                   WHERE id=$3""",
                success,
                json.dumps(result),
                command_id
            )
            return success
        except Exception as e:
            failure_count += 1
            log.error("coa_process_error", command_id=command_id, error=str(e))
            await conn.execute(
                "UPDATE coa_commands SET success=false, error=$1, updated_at=NOW() WHERE id=$2",
                str(e), command_id
            )
            return False

async def poll_pending_commands(pool: asyncpg.Pool) -> None:
    """Poll DB for pending CoA commands and process them."""
    while True:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, nas_device_id, subscriber_id, command_type, attributes
                       FROM coa_commands
                       WHERE success IS NULL OR success = false
                       ORDER BY created_at ASC
                       LIMIT 50"""
                )

            if rows:
                log.info("coa_polling_batch", count=len(rows))
                tasks = [process_command(pool, dict(row)) for row in rows]
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            log.error("coa_poll_error", error=str(e))

        await asyncio.sleep(settings.COA_POLL_INTERVAL)

async def consume_kafka_commands(pool: asyncpg.Pool) -> None:
    """Consume real-time CoA commands from Kafka. Retries with backoff if Kafka is unavailable."""
    backoff = 5
    while True:
        consumer = AIOKafkaConsumer(
            settings.KAFKA_COA_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="coa-engine",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
        )
        try:
            await consumer.start()
        except Exception as exc:
            log.warning("coa_kafka_connect_failed", error=str(exc), retry_in=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        backoff = 5  # reset on successful connect
        log.info("coa_kafka_consumer_started", topic=settings.KAFKA_COA_TOPIC)

        try:
            async for msg in consumer:
                command = msg.value
                try:
                    # Fetch NAS for this subscriber from DB
                    async with pool.acquire() as conn:
                        nas = await conn.fetchrow(
                            """SELECT nd.id as nas_device_id, nd.ip_address, nd.secret, nd.coa_port
                               FROM nas_devices nd
                               JOIN subscribers s ON s.franchisee_id = nd.franchisee_id
                               WHERE s.username = $1 AND nd.is_active = true
                               LIMIT 1""",
                            command.get("username", "")
                        )

                    if not nas:
                        log.warning("coa_kafka_no_nas", username=command.get("username"))
                        continue

                    action = command.get("action", "disconnect")
                    if action == "disconnect":
                        await send_disconnect(
                            nas_ip=nas["ip_address"],
                            nas_secret=nas["secret"],
                            username=command["username"],
                            coa_port=nas["coa_port"] or 3799,
                        )
                    elif action == "rate_limit":
                        await send_rate_limit(
                            nas_ip=nas["ip_address"],
                            nas_secret=nas["secret"],
                            username=command["username"],
                            download_kbps=command.get("download_kbps", 512),
                            upload_kbps=command.get("upload_kbps", 256),
                            coa_port=nas["coa_port"] or 3799,
                        )
                except Exception as e:
                    log.error("coa_kafka_process_error", error=str(e), command=command)
        except Exception as exc:
            log.warning("coa_kafka_consumer_error", error=str(exc), retry_in=backoff)
        finally:
            await consumer.stop()

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)

async def metrics_reporter() -> None:
    """Log metrics every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        log.info("coa_metrics", success_count=success_count, failure_count=failure_count)

async def main() -> None:
    log.info("coa_engine_starting")
    pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
        min_size=2,
        max_size=10,
    )
    log.info("coa_db_connected")

    await asyncio.gather(
        poll_pending_commands(pool),
        consume_kafka_commands(pool),
        metrics_reporter(),
    )
