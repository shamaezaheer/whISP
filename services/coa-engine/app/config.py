from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    DATABASE_URL: str = "postgresql://isp_user:isp_password@localhost:5432/isp_platform"
    REDIS_URL: str = "redis://localhost:6379/0"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_COA_TOPIC: str = "radius.coa"
    COA_POLL_INTERVAL: int = 5  # seconds
    COA_MAX_RETRIES: int = 3

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
