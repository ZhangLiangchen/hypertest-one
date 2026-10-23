"""ADR-022 project experience. These are not testing facts or task sync state."""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base

MEMORY_SCOPES = frozenset({"memory:read", "memory:propose", "memory:publish"})


def utcnow():
    return datetime.now(UTC)


class MemoryRow:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryProjectMapping(MemoryRow, Base):
    __tablename__ = "memory_project_mappings"
    __table_args__ = (UniqueConstraint("project_id"), UniqueConstraint("namespace"),
                     UniqueConstraint("scope_id"), CheckConstraint("version > 0"),
                     CheckConstraint("status IN ('PENDING','READY','UNKNOWN')"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    namespace: Mapped[str] = mapped_column(String(128))
    scope_id: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))


class MemoryEntry(MemoryRow, Base):
    __tablename__ = "memory_entries"
    __table_args__ = (UniqueConstraint("project_id", "id"), CheckConstraint("version > 0"),
                     CheckConstraint("status IN ('CANDIDATE','PENDING','PUBLISHED','RETRACTED')"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    owner_actor_ref: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    # Frozen, server-verified provenance. Public projections redact inaccessible refs.
    source: Mapped[dict] = mapped_column(JSONB)
    pending_operation_id: Mapped[UUID | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryRevision(MemoryRow, Base):
    __tablename__ = "memory_revisions"
    __table_args__ = (UniqueConstraint("entry_id", "version"), CheckConstraint("version > 0"),
                     CheckConstraint("status IN ('CANDIDATE','PUBLISHED','RETRACTED')"))
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("memory_entries.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    applicability: Mapped[str] = mapped_column(Text, default="")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_note: Mapped[str] = mapped_column(Text, default="")
    confirmed_by: Mapped[str | None] = mapped_column(String(255))
    content_digest: Mapped[str] = mapped_column(String(64))
    upstream_ref: Mapped[dict | None] = mapped_column(JSONB)


class MemoryOperation(MemoryRow, Base):
    """Independent durable intent/outbox. SENT and UNKNOWN are never redispatched."""
    __tablename__ = "memory_operations"
    __table_args__ = (UniqueConstraint("project_id", "operation_key"),
        ForeignKeyConstraint(["project_id", "entry_id"], ["memory_entries.project_id", "memory_entries.id"], ondelete="RESTRICT"),
        CheckConstraint("expected_version >= 0 AND target_version = expected_version + 1"),
        CheckConstraint("state IN ('SENT','UNKNOWN','ACCEPTED')"),
        CheckConstraint("operation IN ('CONFIGURE','CREATE_CANDIDATE','PUBLISH','REVISE','RETRACT')"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    operation_key: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(32))
    actor_ref: Mapped[str] = mapped_column(String(255))
    grant_id: Mapped[UUID | None] = mapped_column(ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"))
    expected_version: Mapped[int] = mapped_column(BigInteger)
    input_digest: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSONB)
    entry_id: Mapped[UUID | None] = mapped_column()
    target_version: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16))
    marker: Mapped[str] = mapped_column(String(128))
    upstream_ref: Mapped[dict | None] = mapped_column(JSONB)
    response: Mapped[dict] = mapped_column(JSONB)
