"""Operational source acquisition records; no change to SourceSnapshot hashes."""
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


class SourceAcquisitionRequest(Base):
    __tablename__ = "source_acquisition_requests"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    origin: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str] = mapped_column(String(64))
    ref: Mapped[str | None] = mapped_column(String(255))
    policy_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceBundleTransfer(Base):
    __tablename__ = "source_bundle_transfers"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_source_transfer_idempotency"),
        CheckConstraint("status IN ('UPLOADING','VERIFYING','ACCEPTED','REJECTED','EXPIRED')", name="ck_source_transfer_status"),
        CheckConstraint("bundle_size IS NULL OR bundle_size BETWEEN 1 AND 50331648", name="ck_source_transfer_size"),
        CheckConstraint("(status='ACCEPTED') = (server_workspace IS NOT NULL AND accepted_at IS NOT NULL)", name="ck_source_transfer_acceptance"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    request_id: Mapped[UUID] = mapped_column(ForeignKey("source_acquisition_requests.id", ondelete="RESTRICT"))
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    source_capability_id: Mapped[UUID] = mapped_column(ForeignKey("node_project_capabilities.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    origin: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str] = mapped_column(String(64))
    ref: Mapped[str | None] = mapped_column(String(255))
    policy_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="UPLOADING")
    root_tree: Mapped[str | None] = mapped_column(String(64))
    object_format: Mapped[str | None] = mapped_column(String(8))
    bundle_sha256: Mapped[str | None] = mapped_column(String(64))
    bundle_size: Mapped[int | None] = mapped_column(BigInteger)
    manifest: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    acquisition_receipt: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    bundle_path: Mapped[str | None] = mapped_column(Text)
    server_workspace: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceUploadGrant(Base):
    __tablename__ = "source_upload_grants"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','CONSUMED','REVOKED','EXPIRED')", name="ck_source_upload_status"),
        CheckConstraint("bundle_size BETWEEN 1 AND 50331648 AND expires_at>created_at", name="ck_source_upload_bounds"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    transfer_id: Mapped[UUID] = mapped_column(ForeignKey("source_bundle_transfers.id", ondelete="RESTRICT"), unique=True)
    device_grant_id: Mapped[UUID] = mapped_column(ForeignKey("harness_device_grants.id", ondelete="RESTRICT"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    bundle_size: Mapped[int] = mapped_column(BigInteger)
    receipt: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceTransferSnapshot(Base):
    __tablename__ = "source_transfer_snapshots"
    transfer_id: Mapped[UUID] = mapped_column(ForeignKey("source_bundle_transfers.id", ondelete="RESTRICT"), primary_key=True)
    source_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("source_snapshots.id", ondelete="RESTRICT"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
