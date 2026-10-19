"""Immutable executor selection for controlled external Issue operations."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base


class GitLabIssueOperationExecutor(Base):
    __tablename__ = "gitlab_issue_operation_executors"
    __table_args__ = (
        CheckConstraint("executor_mode IN ('SERVER_HOST','LOCAL_CONNECTOR')", name="ck_issue_executor_mode"),
        CheckConstraint("(executor_mode='LOCAL_CONNECTOR') = (executor_node_id IS NOT NULL AND capability_id IS NOT NULL AND device_grant_id IS NOT NULL)", name="ck_issue_executor_node"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    operation_id: Mapped[UUID] = mapped_column(ForeignKey("gitlab_issue_operations.id", ondelete="RESTRICT"), unique=True)
    executor_mode: Mapped[str] = mapped_column(String(32))
    executor_node_id: Mapped[UUID | None] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    capability_id: Mapped[UUID | None] = mapped_column(ForeignKey("node_project_capabilities.id", ondelete="RESTRICT"))
    device_grant_id: Mapped[UUID | None] = mapped_column(ForeignKey("harness_device_grants.id", ondelete="RESTRICT"))
    integration_id: Mapped[str] = mapped_column(String(128))
    delegation_sha256: Mapped[str] = mapped_column(String(64))
    delegation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
