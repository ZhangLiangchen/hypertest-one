from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hypertest.common.repositories import validate_repository_origin
from hypertest.domain.enums import (
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    Priority,
    ProjectStatus,
    ProposalOperation,
    ProposalStatus,
    ProposalType,
    RequirementLifecycle,
    RequirementSourceType,
    RequirementType,
    RiskCategory,
    RiskLifecycle,
    RiskProbability,
    RiskSeverity,
    TestCaseLifecycle,
    TestCaseType,
    TestRunStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    key: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    repository_url: str | None = None
    default_branch: str = "main"

    @field_validator("repository_url")
    @classmethod
    def credential_free_repository(cls, value: str | None) -> str | None:
        return validate_repository_origin(value) if value is not None else None


class ProjectRead(ORMModel):
    id: UUID
    key: str
    name: str
    description: str | None
    repository_url: str | None
    default_branch: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    row_version: int


class SourceSnapshotCreate(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    repository_url: str
    commit_sha: str = Field(min_length=7, max_length=64)
    branch: str | None = None
    prd_sha256: str = Field(min_length=64, max_length=64)
    prd_artifact_uri: str | None = None
    configuration_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("repository_url")
    @classmethod
    def credential_free_repository(cls, value: str) -> str:
        return validate_repository_origin(value)


class SourceSnapshotRead(ORMModel):
    id: UUID
    project_id: UUID
    repository_url: str
    commit_sha: str
    branch: str | None
    prd_sha256: str
    prd_artifact_uri: str | None
    configuration_sha256: str
    environment_definition: dict[str, Any] | None = None
    source_fingerprint: str
    created_at: datetime


class PolicySnapshotCreate(BaseModel):
    project_id: UUID
    policy_name: str = "BUGate"
    policy_version: str
    content_sha256: str = Field(min_length=64, max_length=64)
    artifact_uri: str | None = None
    compiled_policy: dict[str, Any] = Field(default_factory=dict)


class PolicySnapshotRead(ORMModel):
    id: UUID
    project_id: UUID
    policy_name: str
    policy_version: str
    content_sha256: str
    artifact_uri: str | None
    compiled_policy: dict[str, Any]
    created_at: datetime


class TestRunCreate(BaseModel):
    project_id: UUID
    source_snapshot_id: UUID
    policy_snapshot_id: UUID
    trigger_type: str = "MANUAL"
    trigger_ref: str | None = None
    created_by: str = "user"


class TestRunRead(ORMModel):
    id: UUID
    key: str
    project_id: UUID
    source_snapshot_id: UUID
    policy_snapshot_id: UUID
    trigger_type: str
    trigger_ref: str | None
    status: TestRunStatus
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    row_version: int


class MissionCreate(BaseModel):
    mission_type: MissionType
    priority: Priority = Priority.P1
    objective: str = Field(min_length=1)
    protocol_version: str = "v1alpha1"
    spec: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=512)
    created_by: str = "planner"


class MissionRead(ORMModel):
    id: UUID
    key: str
    test_run_id: UUID
    mission_type: MissionType
    priority: Priority
    objective: str
    protocol_version: str
    spec: dict[str, Any]
    spec_sha256: str
    status: MissionStatus
    idempotency_key: str
    current_attempt_no: int
    created_by: str
    created_at: datetime
    ready_at: datetime | None
    dispatched_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    row_version: int


class MissionExecuteRequest(BaseModel):
    workspace: str = Field(min_length=1)
    provider: str = "codex"


class MissionAttemptRead(ORMModel):
    id: UUID
    mission_id: UUID
    durable_job_id: UUID | None = None
    attempt_no: int
    agent_session_id: UUID | None
    provider: str | None
    harness: str | None
    provider_run_ref: str | None
    status: MissionAttemptStatus
    started_at: datetime | None
    submitted_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    result_payload: dict[str, Any] | None


class MissionProposalRead(ORMModel):
    id: UUID
    mission_id: UUID
    attempt_id: UUID
    proposal_type: ProposalType
    operation: ProposalOperation
    idempotency_key: str
    object_payload: dict[str, Any]
    rationale: str | None
    confidence: float | None
    status: ProposalStatus
    validation_errors: list[dict[str, Any]] | None
    accepted_entity_type: str | None
    accepted_entity_id: UUID | None
    created_at: datetime
    reviewed_at: datetime | None


class RequirementRead(ORMModel):
    id: UUID
    key: str
    project_id: UUID
    source_snapshot_id: UUID
    logical_key: str | None
    title: str
    description: str
    requirement_type: RequirementType
    priority: Priority
    source_type: RequirementSourceType
    source_ref: str | None
    source_fingerprint: str
    confidence: float | None
    lifecycle_status: RequirementLifecycle
    created_by_type: str
    created_by_ref: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int


class RiskRead(ORMModel):
    id: UUID
    key: str
    project_id: UUID
    source_snapshot_id: UUID
    risk_fingerprint: str
    category: RiskCategory
    title: str
    description: str
    severity: RiskSeverity
    probability: RiskProbability
    rationale: str | None
    confidence: float | None
    lifecycle_status: RiskLifecycle
    disposition: str | None
    created_by_type: str
    created_by_ref: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int
    requirement_keys: list[str] = Field(default_factory=list)


class TestCaseRead(ORMModel):
    id: UUID
    key: str
    project_id: UUID
    source_snapshot_id: UUID
    title: str
    description: str
    test_type: TestCaseType
    priority: Priority
    preconditions: list[str]
    expected_result: str
    case_fingerprint: str
    lifecycle_status: TestCaseLifecycle
    confidence: float | None
    derived_from_id: UUID | None
    created_by_type: str
    created_by_ref: str | None
    created_at: datetime
    updated_at: datetime
    row_version: int
    risk_keys: list[str] = Field(default_factory=list)


class RiskCoverageRead(BaseModel):
    risk_id: UUID
    risk_key: str
    required_dimensions: list[TestCaseType]
    covered_dimensions: list[TestCaseType]
    missing_dimensions: list[TestCaseType]
    complete: bool


class TestRunCoverageRead(BaseModel):
    requirement_count: int
    risk_count: int
    test_case_count: int
    risk_identification_coverage: float | None
    risk_test_coverage: float | None
    risks: list[RiskCoverageRead]
    rule_version: str = "risk-design-baseline/v1"
    effective_policy_hash: str = ""


class MissionExecutionRead(BaseModel):
    mission: MissionRead
    attempt: MissionAttemptRead
    proposals: list[MissionProposalRead]
    requirements: list[RequirementRead]
    risks: list[RiskRead]
    test_cases: list[TestCaseRead] = Field(default_factory=list)
    implementations: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)


class PlannerRead(BaseModel):
    reason: str
    mission: MissionRead | None
