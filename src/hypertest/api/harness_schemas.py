"""Safe operational projections; native sessions, workspace paths and tokens stay private."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hypertest.api.schemas import ORMModel
from hypertest.domain.bindings import BindingStatus
from hypertest.domain.enums import VerdictDecision


class BindingRead(ORMModel):
    id: UUID
    test_run_id: UUID
    logical_worker_id: UUID
    primary_agent_session_id: UUID
    binding_epoch: int
    status: BindingStatus
    created_at: datetime
    updated_at: datetime
    row_version: int


class HarnessStateRead(ORMModel):
    max_steps: int
    timeout_seconds: int
    harness_budget_seconds: int
    active_mission_id: UUID | None
    active_attempt_id: UUID | None


class ReportRead(ORMModel):
    id: UUID
    test_run_id: UUID
    binding_id: UUID
    durable_job_id: UUID
    content_sha256: str
    created_at: datetime
    verdict_key: str | None = None
    verdict_decision: VerdictDecision | None = None


class IssueOperationRead(BaseModel):
    id: UUID
    finding_id: UUID
    status: str
    issue_iid: int | None
    issue_url: str | None
    created_at: datetime
    updated_at: datetime


class RunHarnessRead(BaseModel):
    binding: BindingRead | None
    state: HarnessStateRead | None
    reports: list[ReportRead]
    issues: list[IssueOperationRead]


class BindingRecover(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_epoch: int = Field(ge=1)
    expected_row_version: int = Field(ge=1)
