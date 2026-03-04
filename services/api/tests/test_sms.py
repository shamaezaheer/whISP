"""Tests for Bangladesh SMS phone normalisation (SSL Wireless gateway)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.notification.app.sms import normalize_bd_phone, send_sms


# ------------------------------------------------------------------
# Phone normalisation
# ------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    # Standard Bangladeshi mobile formats
    ("01712345678",  "+8801712345678"),   # 01X 11-digit
    ("1712345678",   "+8801712345678"),   # 10-digit (no leading 0)
    ("8801712345678", "+8801712345678"),  # with country code, no +
    ("+8801712345678", "+8801712345678"), # already fully normalized
    # With spaces / dashes
    ("017-1234-5678", "+8801712345678"),
    ("017 1234 5678", "+8801712345678"),
    # All BD operator prefixes
    ("01811111111",  "+8801811111111"),   # Robi
    ("01911111111",  "+8801911111111"),   # Banglalink
    ("01611111111",  "+8801611111111"),   # Teletalk
    ("01511111111",  "+8801511111111"),   # Teletalk
    ("01312345678",  "+8801312345678"),   # GP
])
def test_normalize_bd_phone(raw, expected):
    assert normalize_bd_phone(raw) == expected


# ------------------------------------------------------------------
# send_sms – happy path
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_sms_success():
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.notification.app.sms.httpx.AsyncClient", return_value=mock_client), \
         patch("services.notification.app.sms.settings") as mock_settings:
        mock_settings.SMS_GATEWAY_URL = "http://sms.sslwireless.com/pushapi/dynamic/server.php"
        mock_settings.SMS_GATEWAY_API_KEY = "test-api-key"
        mock_settings.SMS_GATEWAY_SENDER_ID = "whISP"

        result = await send_sms("01712345678", "আপনার সংযোগ নবায়ন হয়েছে।")

    assert result is True
    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[1]["data"]["msisdn"] == "+8801712345678"
    assert call_kwargs[1]["data"]["sid"] == "whISP"


@pytest.mark.asyncio
async def test_send_sms_gateway_not_configured_returns_false():
    with patch("services.notification.app.sms.settings") as mock_settings:
        mock_settings.SMS_GATEWAY_URL = ""
        mock_settings.SMS_GATEWAY_API_KEY = ""
        mock_settings.SMS_GATEWAY_SENDER_ID = "whISP"

        result = await send_sms("01712345678", "Test")

    assert result is False


@pytest.mark.asyncio
async def test_send_sms_gateway_error_returns_false():
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("services.notification.app.sms.httpx.AsyncClient", return_value=mock_client), \
         patch("services.notification.app.sms.settings") as mock_settings:
        mock_settings.SMS_GATEWAY_URL = "http://sms.sslwireless.com/pushapi/dynamic/server.php"
        mock_settings.SMS_GATEWAY_API_KEY = "test-key"
        mock_settings.SMS_GATEWAY_SENDER_ID = "whISP"

        result = await send_sms("01712345678", "Test message")

    assert result is False
