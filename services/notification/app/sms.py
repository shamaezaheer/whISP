"""SMS (SSL Wireless) and FCM push notification clients."""
import httpx
import structlog
from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

def normalize_bd_phone(phone: str) -> str:
    """Normalize BD phone to +8801XXXXXXXXX format."""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+880"):
        return phone
    if phone.startswith("880"):
        return "+" + phone
    if phone.startswith("01") and len(phone) == 11:
        return "+880" + phone[1:]
    if phone.startswith("1") and len(phone) == 10:
        return "+8801" + phone[1:]
    return phone

async def send_sms(phone: str, message: str) -> bool:
    """Send SMS via SSL Wireless API. Returns True on success."""
    if not settings.SMS_GATEWAY_URL or not settings.SMS_GATEWAY_API_KEY:
        log.warning("sms_gateway_not_configured")
        return False

    normalized = normalize_bd_phone(phone)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.SMS_GATEWAY_URL,
                data={
                    "api_token": settings.SMS_GATEWAY_API_KEY,
                    "sid": settings.SMS_GATEWAY_SENDER_ID,
                    "msisdn": normalized,
                    "sms": message,
                    "csmsid": f"whisp_{hash(message) % 100000}",
                },
            )
            success = resp.status_code == 200
            if success:
                log.info("sms_sent", phone=normalized)
            else:
                log.warning("sms_failed", phone=normalized, status=resp.status_code, body=resp.text[:200])
            return success
    except Exception as e:
        log.error("sms_error", phone=normalized, error=str(e))
        return False

async def send_push(fcm_token: str, title: str, body: str, data: dict = None) -> bool:
    """Send FCM push notification. Returns True on success."""
    if not settings.FCM_SERVER_KEY:
        log.warning("fcm_not_configured")
        return False
    if not fcm_token:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://fcm.googleapis.com/fcm/send",
                headers={
                    "Authorization": f"key={settings.FCM_SERVER_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "to": fcm_token,
                    "notification": {"title": title, "body": body},
                    "data": data or {},
                },
            )
            success = resp.status_code == 200
            if success:
                log.info("push_sent", token=fcm_token[:20])
            else:
                log.warning("push_failed", status=resp.status_code, body=resp.text[:200])
            return success
    except Exception as e:
        log.error("push_error", error=str(e))
        return False
