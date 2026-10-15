from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HYPERTEST_",
        extra="ignore",
    )

    env: str = "dev"
    database_url: str = (
        "postgresql+asyncpg://hypertest:hypertest@localhost:5432/hypertest"
    )
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
