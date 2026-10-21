from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    runner_api_v2_image: str = "hypertest-runner:py312-api-v2"
    runner_allow_local: bool = False
    workspace_root: str = "/workspace"
    codex_binary: str = "codex"
    codex_model: str | None = None
    codex_ignore_user_config: bool = False
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = 30
    worker_heartbeat_seconds: float = 5.0
    # Legacy histories retain their original per-Mission protocol. Container
    # deployments explicitly select the versioned persistent profile for new work.
    execution_mode: Literal["direct", "queued"] = "direct"
    harness_mode: Literal["legacy", "bridge"] = "legacy"
    bridge_socket: str = "/run/hypertest-bridge/control.sock"
    bridge_execution_key_file: str = "/run/secrets/bridge_execution"
    bridge_management_key_file: str = "/run/secrets/bridge_management"
    bridge_host_id: str = "hypertest-host-1"
    runtime_control_timeout_seconds: float = 20.0
    harness_max_seconds: int = Field(default=3600, ge=1, le=7200)
    gitlab_policy_file: str | None = None
    connector_operator_key: str = ""
    connector_operator_identity: str = "local-operator"
    connector_request_timeout_seconds: float = 20.0
    connector_allow_insecure_loopback: bool = False
    interactive_grant_ttl_seconds: int = Field(default=120, ge=10, le=120)
    interactive_bind_grace_seconds: int = Field(default=120, ge=10, le=300)
    # ADR-017 is independently enabled for explicitly approved Project keys.
    native_intake_enabled: bool = False
    native_project_keys: list[str] = Field(default_factory=list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
