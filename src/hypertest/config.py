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
    # ADR-027 cutover: old receipts and versions remain readable. This switch is
    # for historical fixture replay/rollback, never a new client install option.
    local_session_writes_enabled: bool = False
    # ADR-019: independent opt-in Cloud worker; no Local authorization coupling.
    cloud_enabled: bool = False
    cloud_worker_enabled: bool = False
    # Docker execution and side-effecting actions require separate explicit opt-ins.
    cloud_docker_enabled: bool = False
    cloud_container_intents_enabled: bool = False
    cloud_controlled_actions_enabled: bool = False
    # Optional dedicated-service admission; empty preserves the existing CLI path.
    cloud_service_release_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    cloud_runtime_root: str = "/var/lib/hypertest-cloud/runtime"
    cloud_credential_key_file: str = "/run/secrets/hypertest-cloud-key"
    cloud_credential_key_id: str = "primary"
    cloud_model_key_file: str = "/run/secrets/hypertest-cloud-model-key"
    cloud_model_base_url: str = "https://api.deepseek.com/anthropic"
    cloud_model: str = "deepseek-flash"
    cloud_model_max_tokens: int = Field(default=8192, ge=1, le=49152)
    cloud_model_max_requests: int = Field(default=100, ge=1, le=10000)
    # Conservative reserved cost per request, configured for the selected model;
    # a non-positive or unknown rate disables execution instead of ignoring budget.
    cloud_model_request_cost_microunits: int = Field(default=0, ge=0)
    # Child model identities are cloud-only host capabilities; never Local logins.
    cloud_codex_enabled: bool = False
    cloud_codex_payload: str = "/opt/hypertest-cloud/delegates"
    cloud_codex_payload_sha256: str = ""
    cloud_codex_oauth_file: str = "/run/credentials/hypertest-cloud.service/codex-oauth"
    cloud_codex_model: str = "gpt-5.6-sol"
    cloud_codex_max_requests: int = Field(default=20, ge=1, le=10000)
    cloud_codex_request_credits: int = Field(default=1, ge=1)
    # Independent fixed SSH diagnostics. Never fall back to user SSH/PATH/auth.
    cloud_ssh_enabled: bool = False
    # Independent bounded public HTTPS reads, opt-in only after target authorization.
    cloud_https_enabled: bool = False
    cloud_ssh_authority_key_file: str = "/run/credentials/hypertest-cloud.service/ssh-authority"
    cloud_ssh_executable: str = "/usr/bin/ssh"
    cloud_ssh_executable_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    cloud_attempt_timeout_seconds: int = Field(default=1800, ge=1, le=7200)
    cloud_worker_lease_seconds: int = Field(default=90, ge=15, le=300)
    cloud_worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    # ADR-022: optional Gateway. Only the API role mounts the upstream secret.
    memory_enabled: bool = False
    memory_powercontext_origin: str = "https://powercontext.invalid:8443"
    memory_powercontext_token_file: str = "/run/hypertest-memory/powercontext-token"
    memory_powercontext_ca_file: str | None = None
    memory_timeout_seconds: float = Field(default=4.0, ge=0.1, le=5.0)
    memory_max_response_bytes: int = Field(default=1048576, ge=16384, le=2097152)
    # A separately granted integration token, never the PowerContext admin key.
    cloud_memory_enabled: bool = False
    cloud_memory_api_url: str = "https://hypertest.invalid/api/v1"
    cloud_memory_api_socket: str | None = None
    cloud_memory_token_file: str = "/run/credentials/hypertest-cloud.service/memory-integration"
    cloud_memory_token_directory: str | None = None
    cloud_memory_ca_file: str | None = None
    cloud_memory_allow_insecure_loopback: bool = False
    cloud_memory_timeout_seconds: float = Field(default=5.0, ge=0.1, le=5.0)
    # ADR-017 is independently enabled for explicitly approved Project keys.
    native_intake_enabled: bool = False
    native_project_keys: list[str] = Field(default_factory=list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
