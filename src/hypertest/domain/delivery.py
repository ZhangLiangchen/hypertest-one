"""Canonical implementation, trusted execution, evidence, findings, and decisions.

Only service transactions commit these entities. Agent results remain proposals;
provider session state never participates in the canonical quality chain.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base
from hypertest.domain.enums import (
    CaseResult,
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionPurpose,
    ExecutionStatus,
    FindingClassification,
    FindingEvidenceRelation,
    FindingResolution,
    FindingSeverity,
    FindingStatus,
    ImplementationValidationStatus,
    TrustLevel,
    VerdictDecision,
    VerdictScope,
    VerdictStatus,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _enum(enum_type: type, name: str, length: int = 32):
    return Enum(
        enum_type,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name,
        length=length,
    )


class TestImplementation(Base):
    __tablename__ = "test_implementations"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_test_implementation_key"),
        UniqueConstraint(
            "source_snapshot_id",
            "implementation_fingerprint",
            name="uq_test_implementation_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"), index=True
    )
    repository_url: Mapped[str] = mapped_column(Text, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    framework: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False)
    implementation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    validation_status: Mapped[ImplementationValidationStatus] = mapped_column(
        _enum(ImplementationValidationStatus, "ck_test_implementations_validation"),
        default=ImplementationValidationStatus.PENDING,
        nullable=False,
        index=True,
    )
    created_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class ImplementationTestCase(Base):
    __tablename__ = "implementation_test_cases"

    implementation_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_implementations.id", ondelete="RESTRICT"), primary_key=True
    )
    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class TestExecution(Base):
    __tablename__ = "test_executions"
    __table_args__ = (
        UniqueConstraint("test_run_id", "key", name="uq_test_execution_key"),
        UniqueConstraint("test_run_id", "idempotency_key", name="uq_test_execution_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    test_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="RESTRICT"), index=True
    )
    mission_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("missions.id", ondelete="RESTRICT"), index=True
    )
    durable_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("durable_jobs.id", ondelete="RESTRICT"), index=True
    )
    execution_request_id: Mapped[UUID | None] = mapped_column()
    retry_of_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_executions.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    purpose: Mapped[ExecutionPurpose] = mapped_column(
        _enum(ExecutionPurpose, "ck_test_executions_purpose"),
        default=ExecutionPurpose.OFFICIAL,
        nullable=False,
    )
    runner_backend: Mapped[str] = mapped_column(String(64), nullable=False)
    environment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    environment_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(
        _enum(ExecutionStatus, "ck_test_executions_status"),
        default=ExecutionStatus.QUEUED,
        nullable=False,
        index=True,
    )
    outcome: Mapped[ExecutionOutcome | None] = mapped_column(
        _enum(ExecutionOutcome, "ck_test_executions_outcome"), index=True
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    runner_instance: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class ExecutionTestCase(Base):
    __tablename__ = "execution_test_cases"
    __table_args__ = (
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_execution_case_duration"
        ),
    )

    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_executions.id", ondelete="RESTRICT"), primary_key=True
    )
    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    implementation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_implementations.id", ondelete="RESTRICT"), index=True
    )
    result: Mapped[CaseResult] = mapped_column(
        _enum(CaseResult, "ck_execution_test_cases_result"),
        default=CaseResult.NOT_RUN,
        nullable=False,
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    failure_summary: Mapped[str | None] = mapped_column(Text)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("test_run_id", "key", name="uq_evidence_key"),
        UniqueConstraint("test_run_id", "sha256", "evidence_type", name="uq_evidence_content"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_evidence_size"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    test_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="RESTRICT"), index=True
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_executions.id", ondelete="RESTRICT"), index=True
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        _enum(EvidenceType, "ck_evidence_type", 64), nullable=False, index=True
    )
    trust_level: Mapped[TrustLevel] = mapped_column(
        _enum(TrustLevel, "ck_evidence_trust"), nullable=False
    )
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    inline_summary: Mapped[str | None] = mapped_column(Text)
    collector: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[EvidenceStatus] = mapped_column(
        _enum(EvidenceStatus, "ck_evidence_status"),
        default=EvidenceStatus.COLLECTED,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class ExecutionEvidence(Base):
    __tablename__ = "execution_evidence"

    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_executions.id", ondelete="RESTRICT"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_finding_key"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="ck_finding_confidence"
        ),
        Index(
            "uq_finding_active_fingerprint",
            "project_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("status IN ('NEW', 'TRIAGED', 'CONFIRMED', 'REOPENED')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    test_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="RESTRICT"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[FindingClassification] = mapped_column(
        _enum(FindingClassification, "ck_findings_classification"), nullable=False, index=True
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        _enum(FindingSeverity, "ck_findings_severity", 16), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    status: Mapped[FindingStatus] = mapped_column(
        _enum(FindingStatus, "ck_findings_status"),
        default=FindingStatus.NEW,
        nullable=False,
        index=True,
    )
    resolution: Mapped[FindingResolution | None] = mapped_column(
        _enum(FindingResolution, "ck_findings_resolution")
    )
    external_issue_ref: Mapped[str | None] = mapped_column(Text)
    reported_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reported_by_ref: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"

    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="RESTRICT"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    relation_type: Mapped[FindingEvidenceRelation] = mapped_column(
        _enum(FindingEvidenceRelation, "ck_finding_evidence_relation"),
        default=FindingEvidenceRelation.SUPPORTS,
        nullable=False,
    )


class FindingRequirement(Base):
    __tablename__ = "finding_requirements"

    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="RESTRICT"), primary_key=True
    )
    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class FindingRisk(Base):
    __tablename__ = "finding_risks"

    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="RESTRICT"), primary_key=True
    )
    risk_id: Mapped[UUID] = mapped_column(
        ForeignKey("risks.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class FindingTestCase(Base):
    __tablename__ = "finding_test_cases"

    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="RESTRICT"), primary_key=True
    )
    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class Verdict(Base):
    __tablename__ = "verdicts"
    __table_args__ = (
        UniqueConstraint("test_run_id", "key", name="uq_verdict_key"),
        UniqueConstraint("test_run_id", "sequence_no", name="uq_verdict_sequence"),
        CheckConstraint("sequence_no > 0", name="ck_verdict_sequence"),
        CheckConstraint(
            "status != 'FINAL' OR (state_snapshot_hash IS NOT NULL AND evidence_manifest_sha256 IS NOT NULL AND finalized_at IS NOT NULL)",
            name="ck_verdict_finalized",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    test_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="RESTRICT"), index=True
    )
    scope: Mapped[VerdictScope] = mapped_column(
        _enum(VerdictScope, "ck_verdicts_scope"), default=VerdictScope.TEST_RUN, nullable=False
    )
    scope_ref: Mapped[str | None] = mapped_column(Text)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[VerdictDecision] = mapped_column(
        _enum(VerdictDecision, "ck_verdicts_decision"), nullable=False
    )
    status: Mapped[VerdictStatus] = mapped_column(
        _enum(VerdictStatus, "ck_verdicts_status"),
        default=VerdictStatus.DRAFT,
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_snapshots.id", ondelete="RESTRICT"), index=True
    )
    state_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    evidence_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    issued_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_by_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VerdictEvidence(Base):
    __tablename__ = "verdict_evidence"

    verdict_id: Mapped[UUID] = mapped_column(
        ForeignKey("verdicts.id", ondelete="RESTRICT"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class VerdictFinding(Base):
    __tablename__ = "verdict_findings"

    verdict_id: Mapped[UUID] = mapped_column(
        ForeignKey("verdicts.id", ondelete="RESTRICT"), primary_key=True
    )
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
