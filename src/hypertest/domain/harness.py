"""Operational call, report and integration records, excluded from Gate hashes."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunHarnessState(Base):
    __tablename__ = "run_harness_states"
    __table_args__ = (CheckConstraint("max_steps BETWEEN 1 AND 32 AND timeout_seconds BETWEEN 1 AND 3600 AND harness_budget_seconds BETWEEN 1 AND 7200", name="ck_harness_budgets"),)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"), primary_key=True)
    first_job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    source_workspace: Mapped[str] = mapped_column(Text)
    max_steps: Mapped[int] = mapped_column(Integer)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    harness_budget_seconds: Mapped[int] = mapped_column(Integer, default=3600, server_default="3600")
    active_mission_id: Mapped[UUID | None] = mapped_column(ForeignKey("missions.id", ondelete="RESTRICT"))
    active_attempt_id: Mapped[UUID | None] = mapped_column(ForeignKey("mission_attempts.id", ondelete="RESTRICT"))
    last_call_id: Mapped[str | None] = mapped_column(String(128))
    last_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    last_call_epoch: Mapped[int | None] = mapped_column(Integer)
    pending_input: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunToolCall(Base):
    __tablename__ = "run_tool_calls"
    __table_args__ = (
        UniqueConstraint("binding_id", "idempotency_key", name="uq_run_tool_identity"),
        CheckConstraint("status IN ('STARTED','SUCCEEDED','FAILED','UNKNOWN')", name="ck_run_tool_status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"))
    durable_job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    binding_epoch: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    input_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="STARTED")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunReport(Base):
    __tablename__ = "run_reports"
    __table_args__ = (UniqueConstraint("binding_id", "idempotency_key", name="uq_run_report_identity"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"))
    durable_job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    artifact_uri: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RuntimeControlRequest(Base):
    __tablename__ = "runtime_control_requests"
    __table_args__ = (
        CheckConstraint("operation IN ('CAPABILITIES','ENVIRONMENTS','RESOLVE_ENVIRONMENT','CLEANUP_JOB','RECOVER_BINDING')", name="ck_control_operation"),
        CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','UNKNOWN')", name="ck_control_status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    operation: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GitLabIssueOperation(Base):
    __tablename__ = "gitlab_issue_operations"
    __table_args__ = (
        UniqueConstraint("binding_id", "finding_id", name="uq_gitlab_finding_issue"),
        CheckConstraint("status IN ('PENDING','UNKNOWN','SUCCEEDED','REJECTED')", name="ck_gitlab_operation_status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"))
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    finding_id: Mapped[UUID] = mapped_column(ForeignKey("findings.id", ondelete="RESTRICT"))
    durable_job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    input_sha256: Mapped[str] = mapped_column(String(64))
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB)
    authorization: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    issue_iid: Mapped[int | None] = mapped_column(Integer)
    issue_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
