"""Application configuration (environment variables)."""
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg2://calib:calib@db:5432/calibration"
    )
    # Seconds to wait for PostgreSQL to become ready during startup.
    db_connect_timeout: int = 60
    db_pool_size: int = 10
    max_overflow: int = 20

    class Config:
        env_prefix = "APP_"
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
