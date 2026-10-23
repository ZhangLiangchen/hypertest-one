"""Management records, intentionally separate from Run/Execution/Evidence."""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base


def utcnow():
    return datetime.now(UTC)


class TaskRow:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


RESULT_CHECK = "reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')"


class SessionTask(TaskRow, Base):
    __tablename__ = "session_tasks"
    __table_args__ = (
        UniqueConstraint("provider", "session_id", name="uq_session_task_identity"),
        CheckConstraint("version > 0"),
        CheckConstraint("status IN ('DRAFT','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED')"),
        CheckConstraint(RESULT_CHECK),
        CheckConstraint("source = 'AGENT_REPORTED'"),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    provider: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(512))
    owner_actor_ref: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    plan_markdown: Mapped[str] = mapped_column(Text)
    reported_result: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), default="AGENT_REPORTED")
    version: Mapped[int] = mapped_column(BigInteger)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseRevision(TaskRow, Base):
    __tablename__ = "session_case_revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "key", "revision", name="uq_session_case_revision"),
        CheckConstraint("revision > 0 AND task_version > 0"),
        CheckConstraint(RESULT_CHECK),
        CheckConstraint("source = 'AGENT_REPORTED'"),
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(BigInteger)
    task_version: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(512))
    steps: Mapped[list] = mapped_column(JSONB)
    expected: Mapped[str] = mapped_column(Text)
    actual: Mapped[str] = mapped_column(Text)
    reported_result: Mapped[str] = mapped_column(String(16))
    implementation_ref: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="AGENT_REPORTED")


class ReportRevision(TaskRow, Base):
    __tablename__ = "session_report_revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "key", "revision", name="uq_session_report_revision"),
        CheckConstraint("revision > 0 AND task_version > 0"),
        CheckConstraint(RESULT_CHECK),
        CheckConstraint("source = 'AGENT_REPORTED'"),
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(BigInteger)
    task_version: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(512))
    markdown: Mapped[str] = mapped_column(Text)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text)
    reported_result: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), default="AGENT_REPORTED")


class SyncReceipt(TaskRow, Base):
    __tablename__ = "session_sync_receipts"
    __table_args__ = (
        UniqueConstraint("actor_ref", "project_id", "idempotency_key", name="uq_session_sync_key"),
        UniqueConstraint("task_id", "task_version", name="uq_session_sync_version"),
        CheckConstraint("task_version > 0"),
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    actor_ref: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    input_digest: Mapped[str] = mapped_column(String(64))
    task_version: Mapped[int] = mapped_column(BigInteger)
    request_payload: Mapped[dict] = mapped_column(JSONB)
    task_snapshot: Mapped[dict] = mapped_column(JSONB)
    response: Mapped[dict] = mapped_column(JSONB)
