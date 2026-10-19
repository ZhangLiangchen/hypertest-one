from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hypertest.api.schemas import ORMModel
from hypertest.application.source_diagnostics import safe_source_diagnostic
from hypertest.domain.activity import ActivityKind, ActivitySource
from hypertest.domain.jobs import JobStatus, JobType


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: JobType
    idempotency_key: str = Field(min_length=1, max_length=512)
    mission_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class JobRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=512)


class JobRead(ORMModel):
    id: UUID
    key: str
    project_id: UUID
    test_run_id: UUID
    mission_id: UUID | None
    retry_of_job_id: UUID | None
    job_type: JobType
    status: JobStatus
    idempotency_key: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    attempts: int
    worker_id: str | None
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None

    @field_validator("result")
    @classmethod
    def project_source_diagnostic(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        # Re-project on read without rewriting immutable historical Job rows.
        if value is None or "source_preparation_diagnostic" not in value:
            return value
        projected = dict(value)
        diagnostic = safe_source_diagnostic(projected.pop("source_preparation_diagnostic"))
        if diagnostic is not None:
            projected["source_preparation_diagnostic"] = diagnostic
        return projected


class ActivityAttemptRead(BaseModel):
    mission_id: UUID
    mission_key: str
    mission_type: str
    attempt_id: UUID
    attempt_no: int
    agent_session_id: UUID


class ActivitySummaryRead(BaseModel):
    phase: Literal["QUEUED", "WAITING_INPUT", "CANCEL_REQUESTED", "AGENT_RUNNING", "RESULT_VALIDATION", "PLATFORM_WORK", "TERMINAL"]
    current_attempt: ActivityAttemptRead | None
    turn_started_at: datetime | None
    last_provider_signal_at: datetime | None
    provider_signal_age_seconds: float | None
    worker_heartbeat_at: datetime | None
    worker_heartbeat_age_seconds: float | None


class ActivityItemRead(BaseModel):
    id: UUID
    kind: ActivityKind
    source: ActivitySource
    recorded_at: datetime
    last_observed_at: datetime
    count: int
    mission_id: UUID
    attempt_id: UUID
    agent_session_id: UUID


class JobActivityRead(BaseModel):
    job_id: UUID
    server_time: datetime
    summary: ActivitySummaryRead
    items: list[ActivityItemRead]
    next_cursor: UUID | None
    retention_per_attempt: int
    window_seconds: int
    truncated: bool
