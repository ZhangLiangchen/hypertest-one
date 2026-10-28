"""ADR-016 operational registration, receipts and current-Agent execution identity.

These records never participate in Snapshot fingerprints or Gate hashes. Tokens
are random capabilities: only their hashes are persisted here.
"""
from datetime import UTC, datetime
from typing import Any
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, synonym

from hypertest.common.ids import uuid7
from hypertest.db.base import Base

INTERACTIVE_SCOPES = frozenset({"task:submit", "task:sync", "run:read", "evidence:read", "report:read", "run:execute", "cloud:configure", "credential:manage", "cloud:dispatch", "cloud:control", "cloud:read", "memory:read", "memory:propose", "memory:publish", "archive:read", "archive:write"})


def utcnow() -> datetime:
    return datetime.now(UTC)


class InteractiveActorIdentity(Base):
    __tablename__ = "interactive_actor_identities"
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_interactive_actor_status"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    actor_ref: Mapped[str] = mapped_column(String(128), unique=True)
    registered_by: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class InteractiveClientRegistration(Base):
    __tablename__ = "interactive_client_registrations"
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_interactive_client_status"),)
    actor_identity_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_actor_identities.id", ondelete="RESTRICT"), primary_key=True)
    client_instance_id: Mapped[UUID] = mapped_column(primary_key=True)
    registered_by: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class InteractiveIntegrationGrant(Base):
    __tablename__ = "interactive_integration_grants"
    __table_args__ = (
        ForeignKeyConstraint(["actor_identity_id", "client_instance_id"],
            ["interactive_client_registrations.actor_identity_id", "interactive_client_registrations.client_instance_id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('ACTIVE','EXPIRED','REVOKED')", name="ck_interactive_integration_status"),
        CheckConstraint("token_hash ~ '^[a-f0-9]{64}$' AND row_version > 0 AND ((expires_at IS NOT NULL AND expires_at > not_before) OR (expires_at IS NULL AND policy_version IN ('cli-archive-v1','cli-archive-global-v1') AND scopes <@ '[\"archive:read\",\"archive:write\"]'::jsonb))", name="ck_interactive_integration_validity"),
        CheckConstraint("jsonb_typeof(scopes)='array' AND jsonb_array_length(scopes)>0 AND scopes <@ '[\"task:submit\",\"task:sync\",\"run:read\",\"evidence:read\",\"report:read\",\"run:execute\",\"cloud:configure\",\"credential:manage\",\"cloud:dispatch\",\"cloud:control\",\"cloud:read\",\"memory:read\",\"memory:propose\",\"memory:publish\",\"archive:read\",\"archive:write\"]'::jsonb", name="ck_interactive_integration_scopes"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    actor_identity_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_actor_identities.id", ondelete="RESTRICT"))
    client_instance_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    policy_version: Mapped[str] = mapped_column(String(64), default="interactive-v1")
    registered_by: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class RunExecutionSelection(Base):
    """New requests freeze mode/driver without rewriting legacy local selections."""
    __tablename__ = "run_execution_selections"
    __table_args__ = (
        CheckConstraint("(execution_mode='CLOUD' AND harness_mode='SERVER_HOST' AND execution_driver='PLATFORM_MANAGED' AND source_bundle_transfer_id IS NULL) OR (execution_mode='LOCAL' AND harness_mode='LOCAL_CONNECTOR' AND execution_driver IN ('PLATFORM_MANAGED','INTERACTIVE_MCP') AND node_id IS NOT NULL AND source_bundle_transfer_id IS NOT NULL)", name="ck_execution_selection_combination"),
    )
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"), primary_key=True)
    execution_mode: Mapped[str] = mapped_column(String(16))
    execution_driver: Mapped[str] = mapped_column(String(32))
    harness_mode: Mapped[str] = mapped_column(String(32))
    harness_host_id: Mapped[str | None] = mapped_column(String(255))
    node_id: Mapped[UUID | None] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    source_bundle_transfer_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_bundle_transfers.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InteractiveSubmissionReceipt(Base):
    __tablename__ = "interactive_submission_receipts"
    __table_args__ = (
        UniqueConstraint("actor_identity_id", "client_instance_id", "project_id", "submission_key", name="uq_interactive_submission_key"),
        CheckConstraint("input_digest ~ '^[a-f0-9]{64}$' AND length(btrim(submission_key)) BETWEEN 1 AND 255", name="ck_interactive_submission_input"),
        CheckConstraint("(status='ACCEPTED' AND test_run_id IS NOT NULL AND initial_durable_job_id IS NOT NULL AND error_code IS NULL) OR (status='REJECTED' AND test_run_id IS NULL AND initial_durable_job_id IS NULL AND error_code IS NOT NULL)", name="ck_interactive_submission_result"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    grant_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"))
    actor_identity_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_actor_identities.id", ondelete="RESTRICT"))
    client_instance_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    submission_key: Mapped[str] = mapped_column(String(255))
    normalization_version: Mapped[str] = mapped_column(String(64), default="interactive-submission/v1")
    input_digest: Mapped[str] = mapped_column(String(64))
    input_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16))
    test_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"), unique=True)
    initial_durable_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run_id = synonym("test_run_id")
    initial_job_id = synonym("initial_durable_job_id")


class InteractiveExecutionBinding(Base):
    __tablename__ = "interactive_execution_bindings"
    __table_args__ = (
        UniqueConstraint("actor_identity_id", "client_instance_id", "test_run_id", "attach_key", name="uq_interactive_attach_key"),
        CheckConstraint("input_digest ~ '^[a-f0-9]{64}$' AND host_proof_sha256 ~ '^[a-f0-9]{64}$' AND attached_epoch>0 AND length(btrim(attach_key)) BETWEEN 1 AND 255", name="ck_interactive_attachment_input"),
        CheckConstraint("length(btrim(native_session_id))>0 AND length(btrim(host_attachment_id))>0", name="ck_interactive_attachment_native"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"), unique=True)
    agent_session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id", ondelete="RESTRICT"), unique=True)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"), unique=True)
    grant_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"))
    actor_identity_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_actor_identities.id", ondelete="RESTRICT"))
    client_instance_id: Mapped[UUID] = mapped_column()
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    provider: Mapped[str] = mapped_column(String(64))
    native_session_id: Mapped[str] = mapped_column(Text)
    workspace_id: Mapped[str] = mapped_column(Text)
    attach_key: Mapped[str] = mapped_column(String(255))
    normalization_version: Mapped[str] = mapped_column(String(64), default="interactive-attachment/v1")
    input_digest: Mapped[str] = mapped_column(String(64))
    attached_epoch: Mapped[int] = mapped_column(BigInteger)
    host_attachment_id: Mapped[str] = mapped_column(String(255))
    host_proof_sha256: Mapped[str] = mapped_column(String(64))
    host_proof: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    primary_agent_session_id = synonym("agent_session_id")
    run_id = synonym("test_run_id")


class InteractiveExecutionGrant(Base):
    __tablename__ = "interactive_execution_grants"
    __table_args__ = (
        UniqueConstraint("interactive_binding_id", "call_id", name="uq_interactive_execution_call"),
        CheckConstraint("status IN ('ACTIVE','EXPIRED','REVOKED')", name="ck_interactive_execution_grant_status"),
        CheckConstraint("binding_epoch>0 AND expires_at>not_before AND token_hash ~ '^[a-f0-9]{64}$'", name="ck_interactive_execution_grant_validity"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    interactive_binding_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_execution_bindings.id", ondelete="RESTRICT"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    integration_grant_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"))
    device_grant_id: Mapped[UUID | None] = mapped_column(ForeignKey("harness_device_grants.id", ondelete="RESTRICT"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    binding_epoch: Mapped[int] = mapped_column(BigInteger)
    claim_identity: Mapped[str] = mapped_column(String(64))
    call_id: Mapped[str] = mapped_column(String(128))
    host_attachment_id: Mapped[str] = mapped_column(String(255))
    host_proof_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class InteractiveToolRequest(Base):
    """Durable transport inbox consumed only under the original Worker claim."""
    __tablename__ = "interactive_tool_requests"
    __table_args__ = (
        UniqueConstraint("interactive_binding_id", "idempotency_key", name="uq_interactive_tool_key"),
        UniqueConstraint("interactive_binding_id", "tool_call_id", name="uq_interactive_tool_call"),
        Index("ix_interactive_tool_job_queue", "job_id", "status", "created_at"),
        CheckConstraint("tool_name IN ('get_state','request_mission','complete_mission','request_execution','ask_user','evaluate_gate','submit_report','request_gitlab_issue','get_issue')", name="ck_interactive_tool_name"),
        CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','REJECTED','UNKNOWN')", name="ck_interactive_tool_status"),
        CheckConstraint("binding_epoch>0 AND input_digest ~ '^[a-f0-9]{64}$' AND claim_identity ~ '^[a-f0-9]{64}$' AND length(btrim(idempotency_key)) BETWEEN 1 AND 255 AND length(btrim(tool_call_id)) BETWEEN 1 AND 255", name="ck_interactive_tool_identity"),
        CheckConstraint("jsonb_typeof(arguments)='object' AND octet_length(arguments::text)<=4000000 AND (result IS NULL OR (jsonb_typeof(result)='object' AND octet_length(result::text)<=4000000))", name="ck_interactive_tool_json"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    interactive_binding_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_execution_bindings.id", ondelete="RESTRICT"))
    execution_grant_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_execution_grants.id", ondelete="RESTRICT"))
    integration_grant_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"))
    actor_identity_id: Mapped[UUID] = mapped_column(ForeignKey("interactive_actor_identities.id", ondelete="RESTRICT"))
    client_instance_id: Mapped[UUID] = mapped_column()
    job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    binding_epoch: Mapped[int] = mapped_column(BigInteger)
    claim_identity: Mapped[str] = mapped_column(String(64))
    tool_call_id: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    tool_name: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def interactive_claim_identity(interactive_binding_id: UUID, lease_token: UUID) -> str:
    """One-way projection: a caller never receives the server's lease secret."""
    import hashlib

    return hashlib.sha256(
        f"hypertest.interactive-mcp/v1alpha1:{interactive_binding_id}:{lease_token}".encode()
    ).hexdigest()
