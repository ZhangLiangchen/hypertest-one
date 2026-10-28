"""ADR-027 archival records; independent of native session and Cloud execution."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.db.base import Base
from hypertest.domain.session_tasks import TaskRow

STATUS = "status IN ('DRAFT','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED')"
RESULT = "reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')"
TARGET = "(target_kind='TASK' AND subtask_id IS NULL) OR (target_kind='SUBTASK' AND subtask_id IS NOT NULL)"


class LocalArchiveTask(TaskRow, Base):
    __tablename__ = "local_archive_tasks"
    __table_args__ = (UniqueConstraint("project_id", "id"), CheckConstraint("version>0 AND archive_version>0"), CheckConstraint(STATUS), CheckConstraint(RESULT))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    creator_actor_ref: Mapped[str] = mapped_column(String(255))
    owner_uploader_actor_ref: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    objective: Mapped[str] = mapped_column(Text)
    sut_repository_url: Mapped[str | None] = mapped_column(Text)
    test_framework_repository_url: Mapped[str | None] = mapped_column(Text)
    sut_branch: Mapped[str | None] = mapped_column(String(255))
    framework_branch: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(BigInteger)
    archive_version: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    reported_result: Mapped[str] = mapped_column(String(16), default="NOT_RUN")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LocalArchiveSubtask(TaskRow, Base):
    __tablename__ = "local_archive_subtasks"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "task_id"], ["local_archive_tasks.project_id", "local_archive_tasks.id"], ondelete="RESTRICT"),
        UniqueConstraint("project_id", "task_id", "id"),
        CheckConstraint("archive_version>0"), CheckConstraint(STATUS), CheckConstraint(RESULT),
    )
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    authorized_uploader_actor_ref: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    objective: Mapped[str] = mapped_column(Text)
    archive_version: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    reported_result: Mapped[str] = mapped_column(String(16), default="NOT_RUN")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ArchiveTarget:
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    target_kind: Mapped[str] = mapped_column(String(16))
    subtask_id: Mapped[UUID | None] = mapped_column()


def target_constraints():
    return (
        ForeignKeyConstraint(["project_id", "task_id"], ["local_archive_tasks.project_id", "local_archive_tasks.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["project_id", "task_id", "subtask_id"], ["local_archive_subtasks.project_id", "local_archive_subtasks.task_id", "local_archive_subtasks.id"], ondelete="RESTRICT"),
        CheckConstraint(TARGET),
    )


class LocalArchiveSnapshot(TaskRow, ArchiveTarget, Base):
    __tablename__ = "local_archive_snapshots"
    __table_args__ = (
        *target_constraints(), UniqueConstraint("project_id", "task_id", "id"),
        CheckConstraint("archive_version>0"),
        Index("uq_archive_root_snapshot", "task_id", "archive_version", unique=True, postgresql_where=text("subtask_id IS NULL")),
        Index("uq_archive_child_snapshot", "subtask_id", "archive_version", unique=True, postgresql_where=text("subtask_id IS NOT NULL")),
    )
    archive_version: Mapped[int] = mapped_column(BigInteger)
    document: Mapped[dict] = mapped_column(JSONB)


class LocalArchiveSubmission(TaskRow, ArchiveTarget, Base):
    __tablename__ = "local_archive_submissions"
    __table_args__ = (
        *target_constraints(), UniqueConstraint("project_id", "task_id", "id"),
        UniqueConstraint("project_id", "uploader_actor_ref", "operation", "idempotency_key", name="uq_archive_submission_key"),
        ForeignKeyConstraint(["project_id", "task_id", "snapshot_id"], ["local_archive_snapshots.project_id", "local_archive_snapshots.task_id", "local_archive_snapshots.id"], ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        CheckConstraint("expected_archive_version>0 AND accepted_version>0"),
        CheckConstraint("operation='ARCHIVE'"), CheckConstraint("outcome IN ('ACCEPTED','UNCHANGED')"),
        CheckConstraint("(outcome='ACCEPTED' AND accepted_version=expected_archive_version+1) OR (outcome='UNCHANGED' AND accepted_version=expected_archive_version)"),
    )
    profile: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(32), default="ARCHIVE")
    uploader_actor_ref: Mapped[str] = mapped_column(String(255))
    client_instance_id: Mapped[UUID] = mapped_column()
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_payload: Mapped[dict] = mapped_column(JSONB)
    request_digest: Mapped[str] = mapped_column(String(64))
    expected_archive_version: Mapped[int] = mapped_column(BigInteger)
    outcome: Mapped[str] = mapped_column(String(16))
    accepted_version: Mapped[int] = mapped_column(BigInteger)
    snapshot_id: Mapped[UUID] = mapped_column()
    response: Mapped[dict] = mapped_column(JSONB)


class LocalArchiveAssetRevision(TaskRow, ArchiveTarget, Base):
    __tablename__ = "local_archive_asset_revisions"
    __table_args__ = (
        *target_constraints(),
        ForeignKeyConstraint(["project_id", "task_id", "submission_id"], ["local_archive_submissions.project_id", "local_archive_submissions.task_id", "local_archive_submissions.id"], ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        CheckConstraint("kind IN ('PLAN','CASE','REPORT')"), CheckConstraint("revision>0 AND archive_version>0"),
        Index("uq_archive_root_asset", "task_id", "kind", "stable_key", "revision", unique=True, postgresql_where=text("subtask_id IS NULL")),
        Index("uq_archive_child_asset", "subtask_id", "kind", "stable_key", "revision", unique=True, postgresql_where=text("subtask_id IS NOT NULL")),
    )
    submission_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(16))
    stable_key: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(BigInteger)
    archive_version: Mapped[int] = mapped_column(BigInteger)
    uploader_actor_ref: Mapped[str] = mapped_column(String(255))
    content: Mapped[dict] = mapped_column(JSONB)


class LocalArchivePublication(TaskRow, Base):
    __tablename__ = "local_archive_publications"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "task_id"], ["local_archive_tasks.project_id", "local_archive_tasks.id"], ondelete="RESTRICT"),
        UniqueConstraint("task_id", "task_version"), CheckConstraint("task_version>0 AND root_archive_version>0"),
        CheckConstraint(STATUS), CheckConstraint(RESULT),
    )
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    task_version: Mapped[int] = mapped_column(BigInteger)
    root_archive_version: Mapped[int] = mapped_column(BigInteger)
    subtask_versions: Mapped[list] = mapped_column(JSONB)
    asset_revision_ids: Mapped[list] = mapped_column(JSONB)
    omitted_subtask_ids: Mapped[list] = mapped_column(JSONB)
    incomplete_subtask_ids: Mapped[list] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    reported_result: Mapped[str] = mapped_column(String(16))
    actor_ref: Mapped[str] = mapped_column(String(255))


class LocalArchiveOperation(TaskRow, Base):
    __tablename__ = "local_archive_operations"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "task_id"], ["local_archive_tasks.project_id", "local_archive_tasks.id"], ondelete="RESTRICT"),
        UniqueConstraint("project_id", "actor_ref", "idempotency_key", name="uq_archive_management_key"),
        UniqueConstraint("task_id", "task_version"), CheckConstraint("task_version>0"),
        CheckConstraint("operation IN ('CREATE','UPDATE','SUBTASK_CREATE','AUTHORIZE','PUBLISH')"),
    )
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    actor_ref: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    request_payload: Mapped[dict] = mapped_column(JSONB)
    task_version: Mapped[int] = mapped_column(BigInteger)
    response: Mapped[dict] = mapped_column(JSONB)
