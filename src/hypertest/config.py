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
    artifact_root: str = "/workspace/.hypertest-artifacts"
    runner_image: str = "hypertest-runner:py312"
    runner_controlled_image: str = "hypertest-runner:py312-controlled"
    runner_api_image: str = "hypertest-runner:py312-api-v1"
    runner_allow_local: bool = False
    workspace_root: str = "/workspace"
    codex_binary: str = "codex"
    codex_model: str | None = None
    codex_ignore_user_config: bool = False
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = 30
    worker_heartbeat_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
