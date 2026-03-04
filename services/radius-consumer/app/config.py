from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    DATABASE_URL: str = "postgresql://isp_user:isp_password@localhost:5432/isp_platform"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_RADIUS_ACCOUNTING_TOPIC: str = "radius.accounting"
    KAFKA_NOTIFICATIONS_TOPIC: str = "notifications"
    KAFKA_COA_TOPIC: str = "radius.coa"
    BATCH_SIZE: int = 100
    BATCH_TIMEOUT_SECONDS: float = 1.0

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
