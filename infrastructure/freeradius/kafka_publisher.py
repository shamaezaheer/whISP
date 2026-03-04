#!/usr/bin/env python3
"""
FreeRADIUS Python accounting module.
Publishes accounting events to Kafka.
Must be called from FreeRADIUS python module on accounting events.
"""
import json
import os
import time

try:
    import radiusd
except ImportError:
    # Mock for testing outside FreeRADIUS
    class radiusd:
        RLM_MODULE_OK = 0
        RLM_MODULE_FAIL = 1

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC = os.getenv("KAFKA_RADIUS_ACCOUNTING_TOPIC", "radius.accounting")

_producer = None

def _get_producer():
    global _producer
    if _producer is None:
        try:
            from kafka import KafkaProducer
            _producer = KafkaProducer(
                bootstrap_servers=KAFKA_SERVERS.split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks=0,  # Fire and forget - don't block RADIUS
                retries=0,
            )
        except Exception as e:
            radiusd.radlog(radiusd.L_ERR, f"Kafka producer init failed: {e}")
    return _producer

def accounting(p):
    """Called by FreeRADIUS on accounting packets."""
    try:
        attrs = dict(p)
        acct_status = attrs.get("Acct-Status-Type", [""])[0]

        type_map = {"Start": "Start", "Stop": "Stop", "Interim-Update": "Interim-Update"}
        event_type = type_map.get(acct_status, acct_status)

        event = {
            "type": event_type,
            "username": attrs.get("User-Name", [""])[0],
            "session_id": attrs.get("Acct-Session-Id", [""])[0],
            "unique_id": attrs.get("Acct-Unique-Session-Id", [""])[0],
            "nas_ip": attrs.get("NAS-IP-Address", [""])[0],
            "framed_ip": attrs.get("Framed-IP-Address", [""])[0],
            "bytes_in": int(attrs.get("Acct-Input-Octets", [0])[0]),
            "bytes_out": int(attrs.get("Acct-Output-Octets", [0])[0]),
            "session_time": int(attrs.get("Acct-Session-Time", [0])[0]),
            "timestamp": time.time(),
        }

        producer = _get_producer()
        if producer:
            producer.send(TOPIC, event)

    except Exception as e:
        try:
            radiusd.radlog(radiusd.L_ERR, f"Kafka accounting error: {e}")
        except Exception:
            pass

    return radiusd.RLM_MODULE_OK
