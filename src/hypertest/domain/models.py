from __future__ import annotations

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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hypertest.common.ids import uuid7
from hypertest.db.base import Base
from hypertest.domain.enums import (
    AgentSessionStatus,
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    Priority,
    ProjectStatus,
    ProposalOperation,
    ProposalStatus,
    ProposalType,
    RequirementLifecycle,
    RequirementSourceType,
    RequirementType,
    RiskCategory,
    RiskLifecycle,
    RiskProbability,
    RiskSeverity,
    TestCaseLifecycle,
    TestCaseType,
    TestRunStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def enum_column(enum_type: type, name: str, length: int = 64):
    return Enum(
        enum_type,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name,
        length=length,
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    repository_url: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(255), default="main", nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        enum_column(ProjectStatus, "ck_projects_status", 32),
        default=ProjectStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)

    source_snapshots: Mapped[list[SourceSnapshot]] = relationship(back_populates="project")
    policy_snapshots: Mapped[list[PolicySnapshot]] = relationship(back_populates="project")
    test_runs: Mapped[list[TestRun]] = relationship(back_populates="project")
    requirements: Mapped[list[Requirement]] = relationship(back_populates="project")
    risks: Mapped[list[Risk]] = relationship(back_populates="project")
    test_cases: Mapped[list[TestCase]] = relationship(back_populates="project")


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "source_fingerprint", name="uq_source_snapshot_fingerprint"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    repository_url: Mapped[str] = mapped_column(Text, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(255))
    prd_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prd_artifact_uri: Mapped[str | None] = mapped_column(Text)
    configuration_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="source_snapshots")
    test_runs: Mapped[list[TestRun]] = relationship(back_populates="source_snapshot")
    requirements: Mapped[list[Requirement]] = relationship(back_populates="source_snapshot")
    risks: Mapped[list[Risk]] = relationship(back_populates="source_snapshot")
    test_cases: Mapped[list[TestCase]] = relationship(back_populates="source_snapshot")


class PolicySnapshot(Base):
    __tablename__ = "policy_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "content_sha256", name="uq_policy_snapshot_content"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    policy_name: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    compiled_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="policy_snapshots")
    test_runs: Mapped[list[TestRun]] = relationship(back_populates="policy_snapshot")


class TestRun(Base):
    __tablename__ = "test_runs"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_test_run_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT")
    )
    policy_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_snapshots.id", ondelete="RESTRICT")
    )
    current_verdict_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "verdicts.id", ondelete="RESTRICT", name="fk_test_run_current_verdict", use_alter=True
        )
    )
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TestRunStatus] = mapped_column(
        enum_column(TestRunStatus, "ck_test_runs_status", 32),
        default=TestRunStatus.CREATED,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)

    project: Mapped[Project] = relationship(back_populates="test_runs")
    source_snapshot: Mapped[SourceSnapshot] = relationship(back_populates="test_runs")
    policy_snapshot: Mapped[PolicySnapshot] = relationship(back_populates="test_runs")
    missions: Mapped[list[Mission]] = relationship(back_populates="test_run")
    agent_sessions: Mapped[list[AgentSessionRecord]] = relationship(back_populates="test_run")


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_requirement_key"),
        UniqueConstraint(
            "source_snapshot_id",
            "source_fingerprint",
            name="uq_requirement_source_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT")
    )
    logical_key: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_type: Mapped[RequirementType] = mapped_column(
        enum_column(RequirementType, "ck_requirements_type", 32), nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority, "ck_requirements_priority", 16), nullable=False
    )
    source_type: Mapped[RequirementSourceType] = mapped_column(
        enum_column(RequirementSourceType, "ck_requirements_source_type", 32), nullable=False
    )
    source_ref: Mapped[str | None] = mapped_column(Text)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    lifecycle_status: Mapped[RequirementLifecycle] = mapped_column(
        enum_column(RequirementLifecycle, "ck_requirements_lifecycle", 32),
        default=RequirementLifecycle.ACTIVE,
        nullable=False,
    )
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    created_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)

    project: Mapped[Project] = relationship(back_populates="requirements")
    source_snapshot: Mapped[SourceSnapshot] = relationship(back_populates="requirements")
    risk_links: Mapped[list[RequirementRisk]] = relationship(back_populates="requirement")


class Risk(Base):
    __tablename__ = "risks"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_risk_key"),
        UniqueConstraint(
            "source_snapshot_id",
            "risk_fingerprint",
            name="uq_risk_source_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT")
    )
    risk_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[RiskCategory] = mapped_column(
        enum_column(RiskCategory, "ck_risks_category", 32), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[RiskSeverity] = mapped_column(
        enum_column(RiskSeverity, "ck_risks_severity", 16), nullable=False
    )
    probability: Mapped[RiskProbability] = mapped_column(
        enum_column(RiskProbability, "ck_risks_probability", 16), nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    lifecycle_status: Mapped[RiskLifecycle] = mapped_column(
        enum_column(RiskLifecycle, "ck_risks_lifecycle", 32),
        default=RiskLifecycle.OPEN,
        nullable=False,
    )
    disposition: Mapped[str | None] = mapped_column(Text)
    created_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)

    project: Mapped[Project] = relationship(back_populates="risks")
    source_snapshot: Mapped[SourceSnapshot] = relationship(back_populates="risks")
    requirement_links: Mapped[list[RequirementRisk]] = relationship(back_populates="risk")
    test_case_links: Mapped[list[RiskTestCase]] = relationship(back_populates="risk")


class RequirementRisk(Base):
    __tablename__ = "requirement_risks"

    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="RESTRICT"), primary_key=True
    )
    risk_id: Mapped[UUID] = mapped_column(
        ForeignKey("risks.id", ondelete="RESTRICT"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), default="ADDRESSES", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    requirement: Mapped[Requirement] = relationship(back_populates="risk_links")
    risk: Mapped[Risk] = relationship(back_populates="requirement_links")


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_test_case_key"),
        UniqueConstraint("source_snapshot_id", "case_fingerprint", name="uq_test_case_fingerprint"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="ck_test_case_confidence"
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
    case_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    test_type: Mapped[TestCaseType] = mapped_column(
        enum_column(TestCaseType, "ck_test_cases_type", 32), nullable=False, index=True
    )
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority, "ck_test_cases_priority", 16), nullable=False
    )
    preconditions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle_status: Mapped[TestCaseLifecycle] = mapped_column(
        enum_column(TestCaseLifecycle, "ck_test_cases_lifecycle", 32),
        default=TestCaseLifecycle.ACTIVE,
        nullable=False,
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    derived_from_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_cases.id", ondelete="RESTRICT")
    )
    created_by_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)

    project: Mapped[Project] = relationship(back_populates="test_cases")
    source_snapshot: Mapped[SourceSnapshot] = relationship(back_populates="test_cases")
    risk_links: Mapped[list[RiskTestCase]] = relationship(back_populates="test_case")


class RiskTestCase(Base):
    __tablename__ = "risk_test_cases"

    risk_id: Mapped[UUID] = mapped_column(
        ForeignKey("risks.id", ondelete="RESTRICT"), primary_key=True
    )
    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    risk: Mapped[Risk] = relationship(back_populates="test_case_links")
    test_case: Mapped[TestCase] = relationship(back_populates="risk_links")


class Mission(Base):
    __tablename__ = "missions"
    __table_args__ = (
        UniqueConstraint("test_run_id", "key", name="uq_mission_key"),
        UniqueConstraint("test_run_id", "idempotency_key", name="uq_mission_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    mission_type: Mapped[MissionType] = mapped_column(
        enum_column(MissionType, "ck_missions_type", 64), nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority, "ck_missions_priority", 16), default=Priority.P1, nullable=False
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(32), default="v1alpha1", nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[MissionStatus] = mapped_column(
        enum_column(MissionStatus, "ck_missions_status", 32),
        default=MissionStatus.CREATED,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    current_attempt_no: Mapped[int] = mapped_column(default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)

    test_run: Mapped[TestRun] = relationship(back_populates="missions")
    attempts: Mapped[list[MissionAttempt]] = relationship(back_populates="mission")
    proposals: Mapped[list[MissionProposal]] = relationship(back_populates="mission")


class AgentSessionRecord(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("provider", "provider_session_id", name="uq_agent_provider_session"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    harness: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_session_id: Mapped[str | None] = mapped_column(Text)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AgentSessionStatus] = mapped_column(
        enum_column(AgentSessionStatus, "ck_agent_sessions_status", 32),
        default=AgentSessionStatus.CREATED,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    test_run: Mapped[TestRun] = relationship(back_populates="agent_sessions")
    attempts: Mapped[list[MissionAttempt]] = relationship(back_populates="agent_session")


class MissionAttempt(Base):
    __tablename__ = "mission_attempts"
    __table_args__ = (
        UniqueConstraint("mission_id", "attempt_no", name="uq_mission_attempt_number"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(ForeignKey("missions.id", ondelete="RESTRICT"))
    durable_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("durable_jobs.id", ondelete="RESTRICT"), index=True
    )
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    agent_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="RESTRICT")
    )
    provider: Mapped[str | None] = mapped_column(String(64))
    harness: Mapped[str | None] = mapped_column(String(64))
    provider_run_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[MissionAttemptStatus] = mapped_column(
        enum_column(MissionAttemptStatus, "ck_mission_attempts_status", 32),
        default=MissionAttemptStatus.CREATED,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    mission: Mapped[Mission] = relationship(back_populates="attempts")
    agent_session: Mapped[AgentSessionRecord | None] = relationship(back_populates="attempts")
    proposals: Mapped[list[MissionProposal]] = relationship(back_populates="attempt")


class MissionProposal(Base):
    __tablename__ = "mission_proposals"
    __table_args__ = (
        UniqueConstraint("mission_id", "idempotency_key", name="uq_mission_proposal_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(ForeignKey("missions.id", ondelete="RESTRICT"))
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("mission_attempts.id", ondelete="RESTRICT"))
    proposal_type: Mapped[ProposalType] = mapped_column(
        enum_column(ProposalType, "ck_mission_proposals_type", 64), nullable=False
    )
    operation: Mapped[ProposalOperation] = mapped_column(
        enum_column(ProposalOperation, "ck_mission_proposals_operation", 32), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    object_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    status: Mapped[ProposalStatus] = mapped_column(
        enum_column(ProposalStatus, "ck_mission_proposals_status", 32),
        default=ProposalStatus.SUBMITTED,
        nullable=False,
    )
    validation_errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    accepted_entity_type: Mapped[str | None] = mapped_column(String(64))
    accepted_entity_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    mission: Mapped[Mission] = relationship(back_populates="proposals")
    attempt: Mapped[MissionAttempt] = relationship(back_populates="proposals")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    test_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_runs.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column()
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Register the remaining canonical chain on the shared declarative metadata.
from hypertest.domain.activity import MissionActivityEvent  # noqa: E402, F401
from hypertest.domain.delivery import (  # noqa: E402, F401
    Evidence,
    ExecutionEvidence,
    ExecutionTestCase,
    Finding,
    FindingEvidence,
    FindingRequirement,
    FindingRisk,
    FindingTestCase,
    ImplementationTestCase,
    TestExecution,
    TestImplementation,
    Verdict,
    VerdictEvidence,
    VerdictFinding,
)
from hypertest.domain.inputs import MissionInputRequest  # noqa: E402, F401
from hypertest.domain.jobs import DurableJob  # noqa: E402, F401
