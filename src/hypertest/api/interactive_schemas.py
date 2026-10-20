"""Strict ADR-016 boundaries; host identities are daemon-injected, never MCP arguments."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.domain.interactive import INTERACTIVE_SCOPES

PROFILE = "hypertest.interactive-mcp/v1alpha1"
HOST_SCHEMA = "hypertest.host-attestation/v1alpha1"


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class RegisterIntegration(StrictInput):
    actor_ref: str = Field(min_length=1, max_length=128, pattern=r"\S")
    client_instance_id: UUID
    project_id: UUID
    scopes: list[str] = Field(min_length=1, max_length=5)
    expires_in_days: int = Field(default=30, ge=1, le=90)

    @field_validator("scopes")
    @classmethod
    def allowed_scopes(cls, value):
        if len(value) != len(set(value)) or not set(value) <= INTERACTIVE_SCOPES:
            raise ValueError("unsupported or duplicate integration scope")
        return sorted(value)


class Budget(StrictInput):
    max_steps: int = Field(default=12, ge=1, le=32)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    harness_budget_seconds: int = Field(default=3600, ge=1, le=7200)


class InteractiveBootstrap(RunBootstrap):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SubmitTask(StrictInput):
    project_id: UUID
    submission_key: str = Field(min_length=1, max_length=255, pattern=r"\S")
    execution_mode: Literal["CLOUD", "LOCAL"] = "CLOUD"
    execution_driver: Literal["PLATFORM_MANAGED", "INTERACTIVE_MCP"] = "PLATFORM_MANAGED"
    bootstrap: InteractiveBootstrap
    budget: Budget = Field(default_factory=Budget)

    @model_validator(mode="after")
    def placement(self):
        expected = "SERVER_HOST" if self.execution_mode == "CLOUD" else "LOCAL_CONNECTOR"
        if self.bootstrap.harness_mode != expected or (
            self.execution_mode == "CLOUD" and self.execution_driver != "PLATFORM_MANAGED"
        ):
            raise ValueError("execution mode, driver and Harness selection disagree")
        if self.bootstrap.idempotency_key is not None:
            raise ValueError("bootstrap idempotency is derived from the submission identity")
        return self


class HostProof(StrictInput):
    schema_version: Literal["hypertest.host-attestation/v1alpha1"] = HOST_SCHEMA
    adapter_id: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=64)
    harness: str = Field(default="codex", min_length=1, max_length=64)
    native_session_id: str = Field(min_length=1, max_length=512)
    node_id: UUID
    workspace_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    source_bundle_transfer_id: UUID
    attachment_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    lifecycle: Literal["ACTIVE"]

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("host observation requires a timezone")
        return value


class BindExecution(StrictInput):
    run_id: UUID
    attach_key: str = Field(min_length=1, max_length=255, pattern=r"\S")
    host_proof: HostProof


class ContinueExecution(StrictInput):
    continuation_key: str = Field(min_length=1, max_length=128, pattern=r"\S")
    host_proof: HostProof


class ExecuteTool(StrictInput):
    arguments: dict[str, Any]


class RecoverExecution(StrictInput):
    expected_epoch: int = Field(ge=1)
    expected_row_version: int = Field(ge=1)
    retry_key: str = Field(min_length=1, max_length=255, pattern=r"\S")
    host_proof: HostProof


class InteractiveRecoveryCommand(StrictInput):
    """Private API→Worker request; references only, never bearer credentials."""

    kind: Literal["INTERACTIVE_MCP_RECOVERY_V1"]
    execution_id: UUID
    integration_grant_id: UUID
    device_grant_id: UUID
    requested_by: str = Field(min_length=1, max_length=255)
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: RecoverExecution
