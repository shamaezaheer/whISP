from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/whisp"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # bKash payment gateway
    BKASH_BASE_URL: str = "https://tokenized.sandbox.bka.sh/v1.2.0-beta"
    BKASH_USERNAME: str = ""
    BKASH_PASSWORD: str = ""
    BKASH_APP_KEY: str = ""
    BKASH_APP_SECRET: str = ""

    # Nagad payment gateway
    NAGAD_BASE_URL: str = "https://sandbox.nagad.com.bd/api"
    NAGAD_MERCHANT_ID: str = ""
    NAGAD_MERCHANT_KEY: str = ""

    # Platform
    PLATFORM_NAME: str = "whISP"

    # Encryption
    ENCRYPTION_KEY: str = ""


@lru_cache()
def get_settings() -> Settings:
    return Settings()
