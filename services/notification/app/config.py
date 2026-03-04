from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    DATABASE_URL: str = "postgresql://isp_user:isp_password@localhost:5432/isp_platform"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_NOTIFICATIONS_TOPIC: str = "notifications"
    SMS_GATEWAY_URL: str = ""
    SMS_GATEWAY_API_KEY: str = ""
    SMS_GATEWAY_SENDER_ID: str = "whISP"
    FCM_SERVER_KEY: str = ""
    SMS_RATE_LIMIT_PER_SECOND: int = 10

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
