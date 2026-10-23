"""Immutable controlled-HTTPS intents and observations, separate from SSH."""
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.db.base import Base
from hypertest.domain.cloud_tasks import CloudRow


class CloudHttpOperation(CloudRow, Base):
    __tablename__ = "cloud_http_operations"
    __table_args__ = (
        UniqueConstraint("attempt_id", "operation_key"),
        UniqueConstraint("project_id", "task_id", "attempt_id", "id", "request_digest"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["project_id", "config_id"], ["project_cloud_config_revisions.project_id", "project_cloud_config_revisions.id"], ondelete="RESTRICT"),
        CheckConstraint("generation > 0 AND hard_deadline > sent_at"),
        CheckConstraint("request_digest ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("state = 'SENT'"),
    )
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    config_id: Mapped[UUID] = mapped_column()
    work_grant_id: Mapped[UUID] = mapped_column(ForeignKey("cloud_work_grants.id", ondelete="RESTRICT"))
    worker_id: Mapped[str] = mapped_column(String(255))
    generation: Mapped[int] = mapped_column(BigInteger)
    operation_key: Mapped[str] = mapped_column(String(96))
    resource_key: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(512))
    request_digest: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16), default="SENT")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hard_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CloudHttpObservation(CloudRow, Base):
    __tablename__ = "cloud_http_observations"
    __table_args__ = (
        UniqueConstraint("operation_id", "observation_digest"),
        ForeignKeyConstraint(["project_id", "task_id", "attempt_id", "operation_id", "request_digest"],
            ["cloud_http_operations.project_id", "cloud_http_operations.task_id", "cloud_http_operations.attempt_id", "cloud_http_operations.id", "cloud_http_operations.request_digest"], ondelete="RESTRICT"),
        CheckConstraint("generation > 0"),
        CheckConstraint("state IN ('OBSERVED','UNKNOWN')"),
        CheckConstraint("observation_digest ~ '^[a-f0-9]{64}$'"),
        Index("uq_cloud_http_observed", "operation_id", unique=True, postgresql_where=text("state = 'OBSERVED'")),
    )
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    operation_id: Mapped[UUID] = mapped_column()
    request_digest: Mapped[str] = mapped_column(String(64))
    worker_id: Mapped[str] = mapped_column(String(255))
    generation: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16))
    observation_digest: Mapped[str] = mapped_column(String(64))
    observation: Mapped[dict] = mapped_column(JSONB)
