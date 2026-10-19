from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hypertest.api.schemas import ORMModel
from hypertest.common.repositories import validate_repository_origin
from hypertest.domain.enums import (
    ExecutionPurpose,
    FindingResolution,
    FindingStatus,
)
from hypertest.domain.environments import EnvironmentRequest


class RunBootstrap(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    repository_url: str = Field(min_length=1, max_length=2048)
    commit_sha: str = Field(pattern=r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
    branch: str | None = None
    prd_text: str = Field(min_length=1, max_length=2_000_000)
    configuration_text: str = Field(default="{}", max_length=100_000)
    policy: dict[str, Any] = Field(default_factory=dict)
    environment: EnvironmentRequest | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    harness_mode: Literal["SERVER_HOST", "LOCAL_CONNECTOR"] = "SERVER_HOST"
    harness_node_id: UUID | None = None
    source_bundle_transfer_id: UUID | None = None

    @model_validator(mode="after")
    def harness_selection(self):
        if self.harness_mode == "LOCAL_CONNECTOR":
            if not self.harness_node_id or not self.source_bundle_transfer_id:
                raise ValueError("local Harness requires an authorized node and accepted source transfer")
        elif self.harness_node_id or self.source_bundle_transfer_id:
            raise ValueError("server Harness cannot receive local node or source transfer options")
        return self

    @field_validator("repository_url")
    @classmethod
    def credential_free_repository(cls, value: str) -> str:
        return validate_repository_origin(value)


class SourceResolveRequest(BaseModel):
    repository_url: str = Field(min_length=1, max_length=2048)
    revision: str = Field(min_length=1, max_length=255)


class SourceResolveRead(BaseModel):
    repository_url: str
    commit_sha: str
    revision: str


class ExecutionCreate(BaseModel):
    workspace: str = Field(min_length=1)
    backend: Literal["docker", "local"] = "docker"
    purpose: ExecutionPurpose = ExecutionPurpose.OFFICIAL
    idempotency_key: str = Field(min_length=1, max_length=512)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


class GateRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    finalize: bool = True
    reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def controlled_reason(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            if "\x00" in value:
                raise ValueError("Gate request reason cannot contain NUL")
            return value.strip()
        return value


class RunAdvance(BaseModel):
    execution_profile: Literal["run-persistent-harness/v1"] | None = None
    workspace: str | None = Field(default=None, min_length=1)
    prepare_workspace: bool = False
    backend: Literal["docker", "local"] = "docker"
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_steps: int = Field(default=12, ge=1, le=32)

    @model_validator(mode="after")
    def source_mode(self):
        if self.prepare_workspace == bool(self.workspace and self.workspace.strip()):
            raise ValueError("choose either automatic pinned checkout or an existing workspace")
        return self


class FindingTransition(BaseModel):
    status: FindingStatus
    resolution: FindingResolution | None = None
    reason: str = Field(min_length=1)
    expected_row_version: int | None = Field(default=None, ge=1)


class ImplementationRead(ORMModel):
    id: UUID
    key: str
    project_id: UUID
    source_snapshot_id: UUID
    repository_url: str
    commit_sha: str
    file_path: str
    symbol: str
    framework: str
    language: str
    implementation_fingerprint: str
    validation_status: str
    artifact_uri: str | None = None
    source_sha256: str | None = None
    created_by_type: str
    created_by_ref: str | None
    created_at: datetime
    updated_at: datetime
    test_case_keys: list[str] = Field(default_factory=list)


class ExecutionRead(ORMModel):
    id: UUID
    key: str
    test_run_id: UUID
    mission_id: UUID | None
    durable_job_id: UUID | None = None
    retry_of_execution_id: UUID | None
    idempotency_key: str
    purpose: str
    runner_backend: str
    environment_id: str
    environment_fingerprint: str
    source_commit: str
    execution_spec_sha256: str
    spec: dict[str, Any]
    status: str
    outcome: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    error_code: str | None
    error_message: str | None
    runner_instance: str | None
    created_at: datetime


class ExecutionCaseRead(ORMModel):
    test_case_id: UUID
    test_case_key: str = ""
    implementation_id: UUID | None
    result: str
    duration_ms: int | None
    failure_summary: str | None


class ExecutionDetail(BaseModel):
    execution: ExecutionRead
    test_cases: list[ExecutionCaseRead]
    evidence_keys: list[str] = Field(default_factory=list)


class EvidenceRead(ORMModel):
    id: UUID
    key: str
    test_run_id: UUID
    execution_id: UUID | None
    evidence_type: str
    trust_level: str
    artifact_uri: str | None
    content_type: str | None
    sha256: str
    size_bytes: int | None
    inline_summary: str | None
    collector: str
    source: str
    status: str
    created_at: datetime
    verified_at: datetime | None
    rejection_reason: str | None


class FindingRead(ORMModel):
    id: UUID
    key: str
    project_id: UUID
    test_run_id: UUID
    fingerprint: str
    classification: str
    severity: str
    title: str
    description: str
    root_cause: str | None
    confidence: float | None
    status: str
    resolution: str | None
    external_issue_ref: str | None
    reported_by_type: str
    reported_by_ref: str | None
    confirmed_by: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    row_version: int
    evidence_keys: list[str] = Field(default_factory=list)
    test_case_keys: list[str] = Field(default_factory=list)


class FindingHistoryState(BaseModel):
    status: FindingStatus | None
    resolution: FindingResolution | None
    row_version: int | None


class FindingHistoryEvent(BaseModel):
    id: UUID
    created_at: datetime
    actor_type: str
    action: str
    before: FindingHistoryState | None
    after: FindingHistoryState | None
    reason: str | None
    reason_truncated: bool


class FindingHistoryRead(BaseModel):
    events: list[FindingHistoryEvent]
    truncated: bool


class VerdictRead(ORMModel):
    id: UUID
    key: str
    test_run_id: UUID
    scope: str
    scope_ref: str | None
    sequence_no: int
    decision: str
    status: str
    reason: str
    policy_snapshot_id: UUID
    state_snapshot_hash: str | None
    evidence_manifest_sha256: str | None
    issued_by_type: str
    issued_by_ref: str | None
    created_at: datetime
    finalized_at: datetime | None
    revoked_at: datetime | None
    evidence_keys: list[str] = Field(default_factory=list)
    finding_keys: list[str] = Field(default_factory=list)
