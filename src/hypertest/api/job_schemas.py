from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hypertest.api.schemas import ORMModel
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
