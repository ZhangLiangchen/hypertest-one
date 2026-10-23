"""ADR-019 Cloud aggregates; deliberately independent of sessions and legacy jobs."""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base

CLOUD_SCOPES = frozenset({"cloud:configure", "credential:manage", "cloud:dispatch", "cloud:control", "cloud:read"})
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
RESULT_CHECK = "reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')"
ATTEMPT_STATUS = "status IN ('QUEUED','PREPARING','RUNNING','WAITING_INPUT','RECOVERY_REQUIRED','COMPLETED','FAILED','CANCELLED')"


def utcnow():
    return datetime.now(UTC)


class CloudRow:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectCredential(CloudRow, Base):
    __tablename__ = "project_credentials"
    __table_args__ = (UniqueConstraint("project_id", "id"), CheckConstraint("version > 0"),
                      CheckConstraint("status IN ('ACTIVE','REVOKED')"),)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(255))
    allowed_targets: Mapped[list] = mapped_column(JSONB)
    allowed_actions: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_by: Mapped[str] = mapped_column(String(255))


class CredentialVersion(CloudRow, Base):
    __tablename__ = "project_credential_versions"
    __table_args__ = (UniqueConstraint("credential_id", "version"),
        UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(["project_id", "credential_id"], ["project_credentials.project_id", "project_credentials.id"], ondelete="RESTRICT"),
        CheckConstraint("version > 0"),)
    project_id: Mapped[UUID] = mapped_column()
    credential_id: Mapped[UUID] = mapped_column()
    version: Mapped[int] = mapped_column(BigInteger)
    encrypted_secret: Mapped[dict] = mapped_column(JSONB)
    key_id: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255))


class ProjectCloudConfigRevision(CloudRow, Base):
    __tablename__ = "project_cloud_config_revisions"
    __table_args__ = (UniqueConstraint("project_id", "revision"), UniqueConstraint("project_id", "id"), CheckConstraint("revision > 0"),)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(BigInteger)
    configuration: Mapped[dict] = mapped_column(JSONB)
    digest: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(255))


class CloudConfigCredential(Base):
    __tablename__ = "cloud_config_credentials"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "config_id"], ["project_cloud_config_revisions.project_id", "project_cloud_config_revisions.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["project_id", "credential_version_id"], ["project_credential_versions.project_id", "project_credential_versions.id"], ondelete="RESTRICT"),)
    config_id: Mapped[UUID] = mapped_column(primary_key=True)
    credential_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[UUID] = mapped_column()


class CloudTask(CloudRow, Base):
    __tablename__ = "cloud_tasks"
    __table_args__ = (UniqueConstraint("project_id", "id"), CheckConstraint("version > 0"),
        CheckConstraint("status IN ('DRAFT','QUEUED','PREPARING','RUNNING','WAITING_INPUT','RECOVERY_REQUIRED','COMPLETED','FAILED','CANCELLED')"),
        CheckConstraint(RESULT_CHECK),
        ForeignKeyConstraint(["project_id", "config_id"], ["project_cloud_config_revisions.project_id", "project_cloud_config_revisions.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["id", "latest_attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT", use_alter=True, name="fk_cloud_latest_attempt"),)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    owner_actor_ref: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    config_id: Mapped[UUID] = mapped_column()
    inputs: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    reported_result: Mapped[str] = mapped_column(String(16), default="NOT_RUN")
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    frozen_manifest: Mapped[dict | None] = mapped_column(JSONB)
    input_digest: Mapped[str | None] = mapped_column(String(64))
    latest_attempt_id: Mapped[UUID | None] = mapped_column()
    related_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("cloud_tasks.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CloudInputResolution(CloudRow, Base):
    __tablename__ = "cloud_input_resolutions"
    __table_args__ = (UniqueConstraint("task_id", "operation_key"), UniqueConstraint("task_id", "id"), UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('PENDING','RESOLVING','ACCEPTED','FAILED','RECOVERY_REQUIRED')"),)
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    operation_key: Mapped[str] = mapped_column(String(128))
    source_draft_version: Mapped[int] = mapped_column(BigInteger)
    accepted_task_version: Mapped[int | None] = mapped_column(BigInteger)
    source_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    result: Mapped[dict | None] = mapped_column(JSONB)
    digest: Mapped[str | None] = mapped_column(String(64))
    worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[str] = mapped_column(String(255))
    grant_id: Mapped[UUID | None] = mapped_column(ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"))


class CloudAttempt(CloudRow, Base):
    __tablename__ = "cloud_attempts"
    __table_args__ = (UniqueConstraint("task_id", "attempt_no"), UniqueConstraint("task_id", "id"), UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        CheckConstraint("attempt_no > 0 AND lease_generation >= 0 AND usage_seconds >= 0 AND cost_microunits >= 0"),
        CheckConstraint(ATTEMPT_STATUS), CheckConstraint(RESULT_CHECK),
        Index("uq_cloud_unfinished_attempt", "task_id", unique=True, postgresql_where=text("status NOT IN ('COMPLETED','FAILED','CANCELLED')")),)
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_no: Mapped[int] = mapped_column(BigInteger)
    input_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    reported_result: Mapped[str] = mapped_column(String(16), default="NOT_RUN")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_generation: Mapped[int] = mapped_column(BigInteger, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workspace_id: Mapped[str | None] = mapped_column(String(512))
    runtime_namespace: Mapped[str | None] = mapped_column(String(512))
    dsh_home: Mapped[str | None] = mapped_column(String(512))
    checkpoint: Mapped[dict] = mapped_column(JSONB, default=dict)
    runtime_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    usage_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_microunits: Mapped[int] = mapped_column(BigInteger, default=0)
    authorization_grant_id: Mapped[UUID | None] = mapped_column(ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"))


class CloudWorkGrant(CloudRow, Base):
    """Short-lived, target-bound worker capability, never an Agent credential."""
    __tablename__ = "cloud_work_grants"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "attempt_id"], ["cloud_attempts.project_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["project_id", "resolution_id"], ["cloud_input_resolutions.project_id", "cloud_input_resolutions.id"], ondelete="RESTRICT"),
        CheckConstraint("(attempt_id IS NOT NULL)::int + (resolution_id IS NOT NULL)::int = 1"),
        CheckConstraint("expires_at > created_at"),)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    attempt_id: Mapped[UUID | None] = mapped_column()
    resolution_id: Mapped[UUID | None] = mapped_column()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    worker_id: Mapped[str] = mapped_column(String(255))
    lease_generation: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CloudRemoteOperation(CloudRow, Base):
    """SENT-before-I/O intent; immutable identity, bounded mutable control state."""
    __tablename__ = "cloud_remote_operations"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_id", "operation_key"),
        UniqueConstraint("task_id", "attempt_id", "id", "request_digest"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["project_id", "config_id"], ["project_cloud_config_revisions.project_id", "project_cloud_config_revisions.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["project_id", "credential_version_id"], ["project_credential_versions.project_id", "project_credential_versions.id"], ondelete="RESTRICT"),
        CheckConstraint("generation > 0 AND last_sequence >= 0 AND hard_deadline > sent_at"),
        CheckConstraint("request_digest ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("state IN ('SENT','RUNNING','STOP_REQUESTED','COMPLETED','FAILED','CANCELLED','UNKNOWN')"),)
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    config_id: Mapped[UUID] = mapped_column()
    credential_version_id: Mapped[UUID] = mapped_column()
    work_grant_id: Mapped[UUID] = mapped_column(ForeignKey("cloud_work_grants.id", ondelete="RESTRICT"))
    worker_id: Mapped[str] = mapped_column(String(255))
    generation: Mapped[int] = mapped_column(BigInteger)
    operation_key: Mapped[str] = mapped_column(String(96))
    action_key: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(512))
    request_digest: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(32), default="SENT")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hard_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sequence: Mapped[int] = mapped_column(BigInteger, default=0)


class CloudRemoteObservation(CloudRow, Base):
    """Immutable, bounded host projection; no raw stdout, secret or ticket."""
    __tablename__ = "cloud_remote_observations"
    __table_args__ = (
        UniqueConstraint("operation_id", "sequence"),
        UniqueConstraint("operation_id", "observation_digest"),
        UniqueConstraint("task_id", "attempt_id", "operation_id", "request_digest", "id"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "attempt_id", "operation_id", "request_digest"],
            ["cloud_remote_operations.task_id", "cloud_remote_operations.attempt_id", "cloud_remote_operations.id", "cloud_remote_operations.request_digest"], ondelete="RESTRICT"),
        CheckConstraint("sequence > 0 AND generation > 0"),
        CheckConstraint("observation_digest ~ '^[a-f0-9]{64}$'"),
        CheckConstraint("authority_mode IN ('CURRENT','CLEANUP')"),)
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    operation_id: Mapped[UUID] = mapped_column()
    request_digest: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(BigInteger)
    observation_digest: Mapped[str] = mapped_column(String(64))
    observation: Mapped[dict] = mapped_column(JSONB)
    worker_id: Mapped[str] = mapped_column(String(255))
    generation: Mapped[int] = mapped_column(BigInteger)
    authority_mode: Mapped[str] = mapped_column(String(16))


class CloudRemoteOperationResult(CloudRow, Base):
    """Immutable stopped result linked to one exact intent and observation."""
    __tablename__ = "cloud_remote_operation_results"
    __table_args__ = (
        UniqueConstraint("operation_id"), UniqueConstraint("observation_id"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "attempt_id", "operation_id", "request_digest", "observation_id"],
            ["cloud_remote_observations.task_id", "cloud_remote_observations.attempt_id", "cloud_remote_observations.operation_id",
             "cloud_remote_observations.request_digest", "cloud_remote_observations.id"], ondelete="RESTRICT"),
        CheckConstraint("terminal_state IN ('COMPLETED','FAILED','CANCELLED')"),)
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    operation_id: Mapped[UUID] = mapped_column()
    request_digest: Mapped[str] = mapped_column(String(64))
    observation_id: Mapped[UUID] = mapped_column()
    terminal_state: Mapped[str] = mapped_column(String(32))
    request: Mapped[dict] = mapped_column(JSONB)
    observation: Mapped[dict] = mapped_column(JSONB)


class CloudArtifact(CloudRow, Base):
    __tablename__ = "cloud_artifacts"
    __table_args__ = (UniqueConstraint("task_id", "id"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        CheckConstraint("byte_count >= 0 AND sha256 ~ '^[a-f0-9]{64}$'"),)
    project_id: Mapped[UUID] = mapped_column()
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128))
    byte_count: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CloudAssetRevision(CloudRow, Base):
    __tablename__ = "cloud_asset_revisions"
    __table_args__ = (UniqueConstraint("task_id", "kind", "key", "revision"), UniqueConstraint("task_id", "id"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "artifact_id"], ["cloud_artifacts.task_id", "cloud_artifacts.id"], ondelete="RESTRICT"),
        CheckConstraint("kind IN ('ANALYSIS','DESIGN','CASE','IMPLEMENTATION','REPORT')"),
        CheckConstraint("revision > 0 AND task_version > 0"), CheckConstraint(RESULT_CHECK),)
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(BigInteger)
    task_version: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(512))
    markdown: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    artifact_id: Mapped[UUID | None] = mapped_column()
    reported_result: Mapped[str] = mapped_column(String(16), default="NOT_RUN")
    source: Mapped[dict] = mapped_column(JSONB, default=dict)
    content_digest: Mapped[str] = mapped_column(String(64))


class CloudAssetReference(Base):
    __tablename__ = "cloud_asset_references"
    __table_args__ = (
        ForeignKeyConstraint(["task_id", "asset_id"], ["cloud_asset_revisions.task_id", "cloud_asset_revisions.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "referenced_asset_id"], ["cloud_asset_revisions.task_id", "cloud_asset_revisions.id"], ondelete="RESTRICT"),)
    asset_id: Mapped[UUID] = mapped_column(primary_key=True)
    referenced_asset_id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column()


class CloudRunRecord(CloudRow, Base):
    __tablename__ = "cloud_run_records"
    __table_args__ = (UniqueConstraint("attempt_id", "run_key"), UniqueConstraint("task_id", "id"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"), CheckConstraint(RESULT_CHECK),)
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    task_version: Mapped[int] = mapped_column(BigInteger)
    run_key: Mapped[str] = mapped_column(String(128))
    execution: Mapped[dict] = mapped_column(JSONB)
    reported_result: Mapped[str] = mapped_column(String(16))


class CloudRunArtifact(Base):
    __tablename__ = "cloud_run_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(["task_id", "run_id"], ["cloud_run_records.task_id", "cloud_run_records.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "artifact_id"], ["cloud_artifacts.task_id", "cloud_artifacts.id"], ondelete="RESTRICT"),)
    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[UUID] = mapped_column()


class CloudRunCase(CloudRow, Base):
    __tablename__ = "cloud_run_cases"
    __table_args__ = (UniqueConstraint("run_id", "case_revision_id"),
        ForeignKeyConstraint(["task_id", "run_id"], ["cloud_run_records.task_id", "cloud_run_records.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "case_revision_id"], ["cloud_asset_revisions.task_id", "cloud_asset_revisions.id"], ondelete="RESTRICT"), CheckConstraint(RESULT_CHECK),)
    task_id: Mapped[UUID] = mapped_column()
    run_id: Mapped[UUID] = mapped_column()
    case_revision_id: Mapped[UUID] = mapped_column()
    actual: Mapped[str] = mapped_column(Text)
    reported_result: Mapped[str] = mapped_column(String(16))


class CloudDelegation(CloudRow, Base):
    __tablename__ = "cloud_delegations"
    __table_args__ = (UniqueConstraint("attempt_id", "delegation_key"), UniqueConstraint("task_id", "id"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('RUNNING','COMPLETED','FAILED','CANCELLED','UNKNOWN')"),)
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    task_version: Mapped[int] = mapped_column(BigInteger)
    delegation_key: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(64))
    responsibility: Mapped[str] = mapped_column(Text)
    native_ref: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16))
    terminal_observation: Mapped[dict | None] = mapped_column(JSONB)


class CloudDelegationAsset(Base):
    __tablename__ = "cloud_delegation_assets"
    __table_args__ = (
        ForeignKeyConstraint(["task_id", "delegation_id"], ["cloud_delegations.task_id", "cloud_delegations.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "asset_id"], ["cloud_asset_revisions.task_id", "cloud_asset_revisions.id"], ondelete="RESTRICT"),)
    task_id: Mapped[UUID] = mapped_column()
    delegation_id: Mapped[UUID] = mapped_column(primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(primary_key=True)


class CloudInputRequest(CloudRow, Base):
    __tablename__ = "cloud_input_requests"
    __table_args__ = (UniqueConstraint("attempt_id", "question_key"), UniqueConstraint("task_id", "id"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),)
    task_id: Mapped[UUID] = mapped_column()
    attempt_id: Mapped[UUID] = mapped_column()
    task_version: Mapped[int] = mapped_column(BigInteger)
    question_key: Mapped[str] = mapped_column(String(128))
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSONB)
    checkpoint: Mapped[dict] = mapped_column(JSONB)
    required_action: Mapped[str] = mapped_column(String(255))


class CloudInputAnswer(CloudRow, Base):
    __tablename__ = "cloud_input_answers"
    __table_args__ = (ForeignKeyConstraint(["task_id", "question_id"], ["cloud_input_requests.task_id", "cloud_input_requests.id"], ondelete="RESTRICT"),)
    task_id: Mapped[UUID] = mapped_column()
    question_id: Mapped[UUID] = mapped_column()
    task_version: Mapped[int] = mapped_column(BigInteger)
    answer: Mapped[str] = mapped_column(Text)
    answered_by: Mapped[str] = mapped_column(String(255))


class CloudOperationReceipt(CloudRow, Base):
    __tablename__ = "cloud_operation_receipts"
    __table_args__ = (UniqueConstraint("project_id", "operation_key"),
        UniqueConstraint("task_id", "accepted_version", name="uq_cloud_receipt_task_version"),
        ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    task_id: Mapped[UUID | None] = mapped_column()
    attempt_id: Mapped[UUID | None] = mapped_column()
    operation_key: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(64))
    actor_ref: Mapped[str] = mapped_column(String(255))
    input_digest: Mapped[str] = mapped_column(String(64))
    expected_version: Mapped[int] = mapped_column(BigInteger)
    accepted_version: Mapped[int] = mapped_column(BigInteger)
    response: Mapped[dict] = mapped_column(JSONB)
    task_snapshot: Mapped[dict | None] = mapped_column(JSONB)
