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
        CheckConstraint("(collaboration_enabled AND binding_state='BOUND' AND primary_generation>0) OR (NOT collaboration_enabled AND primary_generation=0 AND primary_participant_id IS NULL)", name="ck_task_collaboration_mode"),
        CheckConstraint("status IN ('DRAFT','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED')"),
        CheckConstraint(RESULT_CHECK),
        CheckConstraint("source = 'AGENT_REPORTED'"),
        CheckConstraint("binding_state IN ('UNBOUND','BOUND')", name="ck_session_binding_state"),
        CheckConstraint("(source IS NULL AND last_synced_at IS NULL) OR (source IS NOT NULL AND source='AGENT_REPORTED' AND last_synced_at IS NOT NULL)", name="ck_session_sync_source"),
        CheckConstraint("(binding_state='UNBOUND' AND binding_required AND creator_actor_ref IS NOT NULL AND provider IS NULL AND session_id IS NULL AND owner_actor_ref IS NULL AND source IS NULL AND last_synced_at IS NULL AND bound_at IS NULL) OR (binding_state='BOUND' AND provider IS NOT NULL AND session_id IS NOT NULL AND owner_actor_ref IS NOT NULL AND (NOT binding_required OR (bound_at IS NOT NULL AND intended_actor_ref IS NOT NULL AND owner_actor_ref=intended_actor_ref)))", name="ck_session_binding_identity"),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    provider: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[str | None] = mapped_column(String(512))
    owner_actor_ref: Mapped[str | None] = mapped_column(String(255))
    binding_state: Mapped[str] = mapped_column(String(16), default="BOUND", server_default="BOUND")
    binding_required: Mapped[bool] = mapped_column(default=False, server_default="false")
    creator_actor_ref: Mapped[str | None] = mapped_column(String(255))
    intended_actor_ref: Mapped[str | None] = mapped_column(String(255))
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(String(512))
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    plan_markdown: Mapped[str] = mapped_column(Text)
    reported_result: Mapped[str] = mapped_column(String(16))
    source: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(BigInteger)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_managed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collaboration_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    primary_participant_id: Mapped[UUID | None] = mapped_column()
    primary_generation: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class TaskManagementRevision(TaskRow, Base):
    """Human management snapshots, never represented as Agent sync receipts."""
    __tablename__ = "session_task_management_revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "task_version", name="uq_session_management_version"),
        CheckConstraint("task_version > 0"),
        CheckConstraint("action IN ('CREATE','AUTHORIZE','UPDATE','DELETE','RESTORE')", name="ck_session_management_action"),
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    task_version: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(16))
    actor_ref: Mapped[str] = mapped_column(String(255))
    task_snapshot: Mapped[dict] = mapped_column(JSONB)


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


class TaskOperationReceipt(TaskRow, Base):
    """CREATE/BIND intent receipts; neither operation is an Agent synchronization."""
    __tablename__ = "session_task_operation_receipts"
    __table_args__ = (
        UniqueConstraint("actor_ref", "project_id", "idempotency_key", name="uq_session_operation_key"),
        UniqueConstraint("task_id", "task_version", name="uq_session_operation_version"),
        CheckConstraint("operation IN ('CREATE','BIND')", name="ck_session_operation"),
        CheckConstraint("task_version > 0"),
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    actor_ref: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    input_digest: Mapped[str] = mapped_column(String(64))
    task_version: Mapped[int] = mapped_column(BigInteger)
    task_snapshot: Mapped[dict] = mapped_column(JSONB)
    response: Mapped[dict] = mapped_column(JSONB)


class TaskSessionSource(Base):
    """One global immutable source reservation across original and joined sessions."""
    __tablename__ = "session_task_sources"
    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))


class TaskSessionParticipant(TaskRow, Base):
    __tablename__ = "session_task_participants"
    __table_args__ = (
        UniqueConstraint("task_id", "provider", "session_id", name="uq_task_participant_source"),
        CheckConstraint("status IN ('AUTHORIZED','ACTIVE','REVOKED')"),
        CheckConstraint("role IN ('PRIMARY','CONTRIBUTOR')"),
        CheckConstraint("role <> 'PRIMARY' OR status='ACTIVE'"),
        CheckConstraint("task_version > 0"),
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    provider: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(512))
    actor_ref: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="CONTRIBUTOR")
    status: Mapped[str] = mapped_column(String(16))
    assignment: Mapped[str] = mapped_column(Text, default="")
    initial_binding: Mapped[bool] = mapped_column(default=False)
    task_version: Mapped[int] = mapped_column(BigInteger)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContributionRevision(TaskRow, Base):
    __tablename__ = "session_contribution_revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "participant_id", "kind", "stable_key", "revision", name="uq_contribution_revision"),
        CheckConstraint("revision > 0 AND task_version > 0"),
        CheckConstraint("kind IN ('PLAN','CASE','REPORT','REVIEW')"),
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    participant_id: Mapped[UUID] = mapped_column(ForeignKey("session_task_participants.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    stable_key: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(BigInteger)
    task_version: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[dict] = mapped_column(JSONB)
    actor_ref: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(512))


class TaskPublication(TaskRow, Base):
    __tablename__ = "session_task_publications"
    __table_args__ = (UniqueConstraint("task_id", "task_version", name="uq_task_publication_version"),
                      CheckConstraint("primary_generation > 0 AND task_version > 0"))
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    participant_id: Mapped[UUID] = mapped_column(ForeignKey("session_task_participants.id", ondelete="RESTRICT"))
    task_version: Mapped[int] = mapped_column(BigInteger)
    primary_generation: Mapped[int] = mapped_column(BigInteger)
    summary: Mapped[dict] = mapped_column(JSONB)


class CollaborationReceipt(TaskRow, Base):
    __tablename__ = "session_collaboration_receipts"
    __table_args__ = (
        UniqueConstraint("actor_ref", "project_id", "idempotency_key", name="uq_collaboration_key"),
        UniqueConstraint("task_id", "task_version", name="uq_collaboration_version"),
        CheckConstraint("operation IN ('ENABLE','AUTHORIZE','JOIN','REVOKE','CONTRIBUTE','PUBLISH','HANDOFF')"),
        CheckConstraint("task_version > 0"),
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("session_tasks.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    actor_ref: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    input_digest: Mapped[str] = mapped_column(String(64))
    task_version: Mapped[int] = mapped_column(BigInteger)
    provider: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[str | None] = mapped_column(String(512))
    participant_id: Mapped[UUID | None] = mapped_column(ForeignKey("session_task_participants.id", ondelete="RESTRICT"))
    request_payload: Mapped[dict] = mapped_column(JSONB)
    task_snapshot: Mapped[dict] = mapped_column(JSONB)
    collaboration_snapshot: Mapped[dict] = mapped_column(JSONB)
    response: Mapped[dict] = mapped_column(JSONB)
