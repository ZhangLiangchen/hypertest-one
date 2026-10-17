"""Durable operational requests; canonical testing state remains in domain entities."""
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base


class JobType(StrEnum):
    ADVANCE_RUN = "ADVANCE_RUN"
    EXECUTE_MISSION = "EXECUTE_MISSION"
    EXECUTE_TESTS = "EXECUTE_TESTS"
    EVALUATE_GATE = "EVALUATE_GATE"
    PREPARE_WORKSPACE = "PREPARE_WORKSPACE"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


ACTIVE_JOB_STATUSES = (
    JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.WAITING_INPUT, JobStatus.CANCEL_REQUESTED,
)


def _now() -> datetime:
    return datetime.now(UTC)


class DurableJob(Base):
    __tablename__ = "durable_jobs"
    __table_args__ = (
        UniqueConstraint("test_run_id", "key", name="uq_durable_job_key"),
        UniqueConstraint("test_run_id", "idempotency_key", name="uq_durable_job_idempotency"),
        CheckConstraint("attempts >= 0", name="ck_durable_job_attempts"),
        CheckConstraint("(job_type = 'EXECUTE_MISSION') = (mission_id IS NOT NULL)", name="ck_durable_job_mission"),
        Index("uq_durable_job_active_run", "test_run_id", unique=True,
              postgresql_where=text("status IN ('QUEUED', 'RUNNING', 'WAITING_INPUT', 'CANCEL_REQUESTED')")),
        Index("ix_durable_job_claim", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"), index=True)
    mission_id: Mapped[UUID | None] = mapped_column(ForeignKey("missions.id", ondelete="RESTRICT"), index=True)
    retry_of_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    job_type: Mapped[JobType] = mapped_column(Enum(JobType, native_enum=False, create_constraint=True, name="ck_durable_job_type", length=32))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False, create_constraint=True, name="ck_durable_job_status", length=32), default=JobStatus.QUEUED)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_token: Mapped[UUID | None] = mapped_column()
    worker_id: Mapped[str | None] = mapped_column(String(255))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)
    active_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
