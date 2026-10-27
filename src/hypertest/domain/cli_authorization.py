"""Explicit CLI pairing; secrets stay on the client and old grants keep their identity."""
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base
from hypertest.domain.interactive import utcnow


class CliAuthorizationRequest(Base):
    __tablename__ = "cli_authorization_requests"
    __table_args__ = (
        UniqueConstraint("client_instance_id", "create_key", name="uq_cli_pairing_create_key"),
        CheckConstraint("status IN ('PENDING','APPROVED','BOUND','DENIED','EXPIRED')", name="ck_cli_pairing_status"),
        CheckConstraint("credential_hash ~ '^[a-f0-9]{64}$' AND verifier_challenge ~ '^[a-f0-9]{64}$' AND create_digest ~ '^[a-f0-9]{64}$'", name="ck_cli_pairing_hashes"),
        CheckConstraint("expires_at > created_at", name="ck_cli_pairing_expiry"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    client_instance_id: Mapped[UUID] = mapped_column()
    client_name: Mapped[str] = mapped_column(String(80))
    server_url: Mapped[str] = mapped_column(String(512))
    create_key: Mapped[str] = mapped_column(String(128))
    create_digest: Mapped[str] = mapped_column(String(64))
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    verifier_challenge: Mapped[str] = mapped_column(String(64))
    requested_project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    short_code: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    approval: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CliAuthorizationGrant(Base):
    __tablename__ = "cli_authorization_grants"
    request_id: Mapped[UUID] = mapped_column(ForeignKey("cli_authorization_requests.id", ondelete="RESTRICT"), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), primary_key=True)
    grant_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"), unique=True)


class CliAuthorizationReceipt(Base):
    __tablename__ = "cli_authorization_receipts"
    __table_args__ = (
        UniqueConstraint("request_id", "operation", "idempotency_key", name="uq_cli_authorization_receipt"),
        CheckConstraint("operation IN ('CREATE','APPROVE','REDEEM','REVOKE')", name="ck_cli_authorization_operation"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    request_id: Mapped[UUID] = mapped_column(ForeignKey("cli_authorization_requests.id", ondelete="RESTRICT"))
    operation: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
