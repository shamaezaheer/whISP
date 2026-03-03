"""
Application configuration using Pydantic Settings.
All settings are loaded from environment variables or .env file.
"""
from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Core application
    # ------------------------------------------------------------------
    PLATFORM_NAME: str = "whISP"
    PLATFORM_DOMAIN: str = "localhost"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/whisp"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50

    # ------------------------------------------------------------------
    # Kafka
    # ------------------------------------------------------------------
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_BILLING_EVENTS: str = "billing-events"
    KAFKA_TOPIC_RADIUS_SYNC: str = "radius-sync"
    KAFKA_TOPIC_NOTIFICATIONS: str = "notifications"
    KAFKA_CONSUMER_GROUP: str = "whisp-api"

    # ------------------------------------------------------------------
    # JWT / Auth
    # ------------------------------------------------------------------
    JWT_SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_EXPIRE_DAYS: int = 30

    # ------------------------------------------------------------------
    # Encryption
    # ------------------------------------------------------------------
    ENCRYPTION_KEY: str = "change-me-32-bytes-encryption-key"

    # ------------------------------------------------------------------
    # bKash
    # ------------------------------------------------------------------
    BKASH_BASE_URL: str = "https://tokenized.sandbox.bka.sh/v1.2.0-beta"
    BKASH_APP_KEY: str = ""
    BKASH_APP_SECRET: str = ""
    BKASH_USERNAME: str = ""
    BKASH_PASSWORD: str = ""
    BKASH_CALLBACK_URL: str = "https://localhost/payments/bkash/callback"

    # ------------------------------------------------------------------
    # Nagad
    # ------------------------------------------------------------------
    NAGAD_BASE_URL: str = "https://sandbox.nagad.com.bd"
    NAGAD_MERCHANT_ID: str = ""
    NAGAD_MERCHANT_PHONE: str = ""
    NAGAD_PUBLIC_KEY: str = ""
    NAGAD_PRIVATE_KEY: str = ""
    NAGAD_CALLBACK_URL: str = "https://localhost/payments/nagad/callback"

    # ------------------------------------------------------------------
    # SSLCommerz
    # ------------------------------------------------------------------
    SSLCOMMERZ_BASE_URL: str = "https://sandbox.sslcommerz.com"
    SSLCOMMERZ_STORE_ID: str = ""
    SSLCOMMERZ_STORE_PASSWD: str = ""
    SSLCOMMERZ_SUCCESS_URL: str = "https://localhost/payments/sslcommerz/success"
    SSLCOMMERZ_FAIL_URL: str = "https://localhost/payments/sslcommerz/fail"
    SSLCOMMERZ_CANCEL_URL: str = "https://localhost/payments/sslcommerz/cancel"
    SSLCOMMERZ_IPN_URL: str = "https://localhost/payments/sslcommerz/ipn"

    # ------------------------------------------------------------------
    # SMS Gateway
    # ------------------------------------------------------------------
    SMS_GATEWAY_URL: str = ""
    SMS_GATEWAY_API_KEY: str = ""
    SMS_GATEWAY_SENDER_ID: str = "whISP"
    SMS_GATEWAY_PROVIDER: str = "twilio"  # twilio | infobip | custom

    # ------------------------------------------------------------------
    # Firebase Cloud Messaging
    # ------------------------------------------------------------------
    FCM_SERVER_KEY: str = ""
    FCM_BASE_URL: str = "https://fcm.googleapis.com/fcm/send"

    # ------------------------------------------------------------------
    # Chorki OTT
    # ------------------------------------------------------------------
    CHORKI_BASE_URL: str = "https://api.chorki.com"
    CHORKI_API_KEY: str = ""
    CHORKI_PARTNER_ID: str = ""
    CHORKI_PARTNER_SECRET: str = ""

    # ------------------------------------------------------------------
    # Hoichoi OTT
    # ------------------------------------------------------------------
    HOICHOI_BASE_URL: str = "https://api.hoichoi.tv"
    HOICHOI_API_KEY: str = ""
    HOICHOI_PARTNER_ID: str = ""
    HOICHOI_PARTNER_SECRET: str = ""

    # ------------------------------------------------------------------
    # FreeRADIUS / RADIUS
    # ------------------------------------------------------------------
    RADIUS_DB_URL: str = "postgresql+asyncpg://radius:radius@localhost:5432/radius"
    RADIUS_COA_DEFAULT_PORT: int = 3799
    RADIUS_COA_TIMEOUT: float = 5.0

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    CORS_ORIGINS: list[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True

    # ------------------------------------------------------------------
    # Computed helpers
    # ------------------------------------------------------------------
    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("ENCRYPTION_KEY must be at least 16 characters")
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def asyncpg_database_url(self) -> str:
        """Return raw asyncpg DSN (strip SQLAlchemy driver prefix)."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def asyncpg_radius_url(self) -> str:
        return self.RADIUS_DB_URL.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
