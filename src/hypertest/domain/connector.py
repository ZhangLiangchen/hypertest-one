"""ADR-015 operational node identities and durable cross-process dispatch mailbox."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class HarnessNode(Base):
    __tablename__ = "harness_nodes"
    __table_args__ = (
        CheckConstraint("node_kind IN ('SERVER_HOST','LOCAL_CONNECTOR')", name="ck_harness_node_kind"),
        CheckConstraint("registration_status IN ('PENDING','ACTIVE','REVOKED')", name="ck_harness_node_status"),
        CheckConstraint("presence IN ('UNKNOWN','ONLINE','OFFLINE')", name="ck_harness_node_presence"),
        CheckConstraint("connection_generation >= 0 AND row_version > 0", name="ck_harness_node_version"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    node_key: Mapped[str] = mapped_column(String(128), unique=True)
    owner_identity_id: Mapped[str] = mapped_column(String(128))
    node_kind: Mapped[str] = mapped_column(String(32), default="LOCAL_CONNECTOR")
    display_name: Mapped[str] = mapped_column(String(128))
    registration_status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    presence: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    connection_generation: Mapped[int] = mapped_column(BigInteger, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class HarnessDeviceGrant(Base):
    __tablename__ = "harness_device_grants"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','EXPIRED','REVOKED')", name="ck_device_grant_status"),
        CheckConstraint("expires_at > not_before AND row_version > 0", name="ck_device_grant_validity"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_version: Mapped[str] = mapped_column(String(64))
    operator_identity_id: Mapped[str] = mapped_column(String(128))
    policy_version: Mapped[str] = mapped_column(String(64), default="operator-v1")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


DeviceGrant = HarnessDeviceGrant


class NodeProjectCapability(Base):
    __tablename__ = "node_project_capabilities"
    __table_args__ = (
        CheckConstraint("capability IN ('harness','source_acquisition','issue_executor')", name="ck_node_capability"),
        CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_node_capability_status"),
        Index("uq_node_active_capability", "node_id", "project_id", "capability", unique=True,
              postgresql_where=text("status='ACTIVE'")),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    capability: Mapped[str] = mapped_column(String(32))
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    policy_version: Mapped[str] = mapped_column(String(64), default="operator-v1")
    operator_identity_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class RunHarnessPlacement(Base):
    __tablename__ = "run_harness_placements"
    __table_args__ = (
        CheckConstraint("mode IN ('SERVER_HOST','LOCAL_CONNECTOR')", name="ck_harness_placement_mode"),
        CheckConstraint("source_transfer_kind IN ('SERVER_WORKSPACE','SOURCE_BUNDLE')", name="ck_harness_placement_source"),
        CheckConstraint("(mode='LOCAL_CONNECTOR') = (source_bundle_transfer_id IS NOT NULL)", name="ck_harness_placement_bundle"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"), unique=True)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"), unique=True)
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    mode: Mapped[str] = mapped_column(String(32))
    source_transfer_kind: Mapped[str] = mapped_column(String(32))
    source_bundle_transfer_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_bundle_transfers.id",ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HarnessDispatchGrant(Base):
    __tablename__ = "harness_dispatch_grants"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','EXPIRED','REVOKED')", name="ck_dispatch_grant_status"),
        CheckConstraint("binding_epoch > 0 AND expires_at > not_before", name="ck_dispatch_grant_validity"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    placement_id: Mapped[UUID] = mapped_column(ForeignKey("run_harness_placements.id", ondelete="RESTRICT"))
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id", ondelete="RESTRICT"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    device_grant_id: Mapped[UUID] = mapped_column(ForeignKey("harness_device_grants.id", ondelete="RESTRICT"))
    capability_id: Mapped[UUID] = mapped_column(ForeignKey("node_project_capabilities.id", ondelete="RESTRICT"))
    audience: Mapped[str] = mapped_column(String(64), default="hypertest.harness-connector/v1alpha1")
    workspace_id: Mapped[str] = mapped_column(String(128))
    claim_identity: Mapped[str] = mapped_column(String(64))
    binding_epoch: Mapped[int] = mapped_column(BigInteger)
    call_id: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class ConnectorRequest(Base):
    __tablename__ = "connector_requests"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED','SENT','SUCCEEDED','FAILED','UNKNOWN')", name="ck_connector_request_status"),
        CheckConstraint("authority IN ('execution','management','integration')", name="ck_connector_authority"),
        Index("ix_connector_mailbox", "node_id", "status", "created_at"),
        Index("uq_issue_create_delivery",text("(payload->>'operation_id')"),unique=True,
              postgresql_where=text("operation='issue_create'")),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    dispatch_grant_id: Mapped[UUID | None] = mapped_column(ForeignKey("harness_dispatch_grants.id", ondelete="RESTRICT"))
    operation: Mapped[str] = mapped_column(String(32))
    authority: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    input_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    connection_generation: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
