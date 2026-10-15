from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hypertest.domain.enums import MissionStatus, MissionType, Priority, ProjectStatus, TestRunStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    key: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    repository_url: str | None = None
    default_branch: str = "main"


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
    repository_url: str
    commit_sha: str = Field(min_length=7, max_length=64)
    branch: str | None = None
    prd_sha256: str = Field(min_length=64, max_length=64)
    prd_artifact_uri: str | None = None
    configuration_sha256: str = Field(min_length=64, max_length=64)


class SourceSnapshotRead(ORMModel):
    id: UUID
    project_id: UUID
    repository_url: str
    commit_sha: str
    branch: str | None
    prd_sha256: str
    prd_artifact_uri: str | None
    configuration_sha256: str
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
