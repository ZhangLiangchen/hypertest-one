"""Persistent Run ownership; these records never contribute to Gate hashes."""
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base


class BindingStatus(StrEnum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    WAITING_INPUT = "WAITING_INPUT"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_BINDING_STATUSES = (BindingStatus.CLOSED, BindingStatus.FAILED, BindingStatus.CANCELLED)


class RunExecutionBinding(Base):
    __tablename__ = "run_execution_bindings"
    __table_args__ = (
        UniqueConstraint("test_run_id", name="uq_run_binding_run"),
        UniqueConstraint("logical_worker_id", name="uq_run_binding_worker"),
        UniqueConstraint("primary_agent_session_id", name="uq_run_binding_session"),
        CheckConstraint("binding_epoch > 0", name="ck_run_binding_epoch"),
        CheckConstraint("row_version > 0", name="ck_run_binding_version"),
        CheckConstraint("length(btrim(harness_host_id)) > 0", name="ck_run_binding_host"),
        CheckConstraint("length(btrim(workspace_id)) > 0", name="ck_run_binding_workspace"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    logical_worker_id: Mapped[UUID] = mapped_column(nullable=False)
    primary_agent_session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id", ondelete="RESTRICT"))
    harness_host_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    binding_epoch: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    status: Mapped[BindingStatus] = mapped_column(Enum(BindingStatus, native_enum=False, create_constraint=True, name="ck_run_binding_status", length=32), default=BindingStatus.RESERVED, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
