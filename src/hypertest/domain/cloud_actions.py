"""Immutable identities and sends for externally side-effecting Cloud actions."""
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


class CloudActionIdentity(CloudRow, Base):
    __tablename__ = "cloud_action_identities"
    __table_args__ = (
        UniqueConstraint("task_id", "action_key"),
        UniqueConstraint("attempt_id", "operation_key"),
        UniqueConstraint("project_id", "client_ref"),
        UniqueConstraint("project_id", "unique_ref"),
        UniqueConstraint("project_id", "task_id", "attempt_id", "id"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["project_id", "config_id"], ["project_cloud_config_revisions.project_id", "project_cloud_config_revisions.id"], ondelete="RESTRICT"),
        CheckConstraint("generation > 0 AND hard_deadline > created_at"),
        CheckConstraint("plan_sha256 ~ '^[a-f0-9]{64}$'"),
    )
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    config_id: Mapped[UUID] = mapped_column()
    work_grant_id: Mapped[UUID] = mapped_column(ForeignKey("cloud_work_grants.id", ondelete="RESTRICT"))
    worker_id: Mapped[str] = mapped_column(String(255))
    generation: Mapped[int] = mapped_column(BigInteger)
    operation_key: Mapped[str] = mapped_column(String(96))
    action_key: Mapped[str] = mapped_column(String(64))
    client_ref: Mapped[str] = mapped_column(String(96))
    unique_ref: Mapped[str] = mapped_column(String(96))
    target: Mapped[str] = mapped_column(String(512))
    plan_sha256: Mapped[str] = mapped_column(String(64))
    hard_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CloudActionSend(CloudRow, Base):
    __tablename__ = "cloud_action_sends"
    __table_args__ = (
        UniqueConstraint("identity_id"),
        UniqueConstraint("project_id", "task_id", "attempt_id", "id"),
        ForeignKeyConstraint(["project_id", "task_id", "attempt_id", "identity_id"],
            ["cloud_action_identities.project_id", "cloud_action_identities.task_id", "cloud_action_identities.attempt_id", "cloud_action_identities.id"], ondelete="RESTRICT"),
        CheckConstraint("body_sha256 ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("state = 'SENT'"),
    )
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    identity_id: Mapped[UUID] = mapped_column()
    body_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="SENT")


class CloudActionObservation(CloudRow, Base):
    __tablename__ = "cloud_action_observations"
    __table_args__ = (
        UniqueConstraint("send_id", "observation_sha256"),
        ForeignKeyConstraint(["project_id", "task_id", "attempt_id", "send_id"],
            ["cloud_action_sends.project_id", "cloud_action_sends.task_id", "cloud_action_sends.attempt_id", "cloud_action_sends.id"], ondelete="RESTRICT"),
        CheckConstraint("state IN ('HTTP_OBSERVED','UNKNOWN','BUSINESS_TERMINAL')"),
        CheckConstraint("observation_sha256 ~ '^[a-f0-9]{64}$'"),
        Index("uq_cloud_action_http_observed", "send_id", unique=True, postgresql_where=text("state = 'HTTP_OBSERVED'")),
        Index("uq_cloud_action_terminal_observed", "send_id", unique=True, postgresql_where=text("state = 'BUSINESS_TERMINAL'")),
    )
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    send_id: Mapped[UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(32))
    observation_sha256: Mapped[str] = mapped_column(String(64))
    observation: Mapped[dict] = mapped_column(JSONB)
