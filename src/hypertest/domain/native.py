"""Additive ADR-017 state. No legacy Execution/Evidence/Verdict rows are reused."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base


def now():
    return datetime.now(UTC)


class NativeRow:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NativeTestRun(NativeRow, Base):
    __tablename__ = "native_test_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key"),
        CheckConstraint("generation > 0"),
        CheckConstraint("profile = 'native-framework-intake/v1alpha1'"),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    profile: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    proposal_digest: Mapped[str] = mapped_column(String(64))
    proposal: Mapped[dict] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(String(64))
    actor_ref: Mapped[str] = mapped_column(String(255))
    generation: Mapped[int] = mapped_column(BigInteger, default=1)


class NativeContributor(NativeRow, Base):
    __tablename__ = "native_contributors"
    __table_args__ = (UniqueConstraint("run_id", "generation"), CheckConstraint("generation > 0"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("native_test_runs.id", ondelete="RESTRICT"))
    actor_ref: Mapped[str] = mapped_column(String(255))
    session_ref: Mapped[str] = mapped_column(String(512))
    generation: Mapped[int] = mapped_column(BigInteger)
    writer_token_hash: Mapped[str] = mapped_column(String(64))


class NativeCase(NativeRow, Base):
    __tablename__ = "native_cases"
    __table_args__ = (UniqueConstraint("run_id", "case_key"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("native_test_runs.id", ondelete="RESTRICT"))
    case_key: Mapped[str] = mapped_column(String(128))
    accepted_payload: Mapped[dict] = mapped_column(JSONB)


class NativeExecutionRecord(NativeRow, Base):
    __tablename__ = "native_execution_records"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("native_test_runs.id", ondelete="RESTRICT"))
    contributor_id: Mapped[UUID] = mapped_column(ForeignKey("native_contributors.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    retry_of_execution_id: Mapped[UUID | None] = mapped_column(ForeignKey("native_execution_records.id", ondelete="RESTRICT"))
    observation: Mapped[dict] = mapped_column(JSONB)


class NativeExecutionCase(Base):
    __tablename__ = "native_execution_cases"
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("native_execution_records.id", ondelete="RESTRICT"), primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("native_cases.id", ondelete="RESTRICT"), primary_key=True)
    observed_result: Mapped[str] = mapped_column(String(16))
    __table_args__ = (CheckConstraint("observed_result IN ('PASS','FAIL','ERROR','SKIPPED','UNKNOWN')"),)


class NativeMaterial(NativeRow, Base):
    __tablename__ = "native_materials"
    __table_args__ = (UniqueConstraint("execution_id", "name"), CheckConstraint("size_bytes BETWEEN 0 AND 2097152"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("native_test_runs.id", ondelete="RESTRICT"))
    execution_id: Mapped[UUID | None] = mapped_column(ForeignKey("native_execution_records.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    format: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    artifact_uri: Mapped[str] = mapped_column(String(80))


class NativeVerification(NativeRow, Base):
    __tablename__ = "native_verifications"
    __table_args__ = (CheckConstraint("provenance = 'UNVERIFIED'"),)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("native_execution_records.id", ondelete="RESTRICT"))
    verifier_version: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[str] = mapped_column(String(32), default="UNVERIFIED")
    checks: Mapped[dict] = mapped_column(JSONB)


class NativeConclusion(NativeRow, Base):
    __tablename__ = "native_conclusions"
    __table_args__ = (CheckConstraint("decision IN ('UNKNOWN','BLOCKED')"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("native_test_runs.id", ondelete="RESTRICT"))
    contributor_id: Mapped[UUID] = mapped_column(ForeignKey("native_contributors.id", ondelete="RESTRICT"))
    policy_version: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    state_digest: Mapped[str] = mapped_column(String(64))
    reasons: Mapped[list] = mapped_column(JSONB)


class NativeConclusionExecution(Base):
    __tablename__ = "native_conclusion_executions"
    conclusion_id: Mapped[UUID] = mapped_column(ForeignKey("native_conclusions.id", ondelete="RESTRICT"), primary_key=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("native_execution_records.id", ondelete="RESTRICT"), primary_key=True)


class NativeHandoffRecord(NativeRow, Base):
    __tablename__ = "native_handoffs"
    __table_args__ = (UniqueConstraint("run_id", "to_generation"), CheckConstraint("to_generation = from_generation + 1"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("native_test_runs.id", ondelete="RESTRICT"))
    from_contributor_id: Mapped[UUID] = mapped_column(ForeignKey("native_contributors.id", ondelete="RESTRICT"))
    to_contributor_id: Mapped[UUID] = mapped_column(ForeignKey("native_contributors.id", ondelete="RESTRICT"))
    from_generation: Mapped[int] = mapped_column(BigInteger)
    to_generation: Mapped[int] = mapped_column(BigInteger)
    actor_ref: Mapped[str] = mapped_column(String(255))
    state_digest: Mapped[str] = mapped_column(String(64))
    state_artifact_uri: Mapped[str] = mapped_column(String(80))
    remaining_work: Mapped[list] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(4000))


class NativeOperation(NativeRow, Base):
    __tablename__ = "native_operations"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"), CheckConstraint("status IN ('SUCCEEDED','UNKNOWN','RESOLVED')"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("native_test_runs.id", ondelete="RESTRICT"))
    contributor_id: Mapped[UUID] = mapped_column(ForeignKey("native_contributors.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    input_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="SUCCEEDED")
    result: Mapped[dict] = mapped_column(JSONB)
    reconciled_material_id: Mapped[UUID | None] = mapped_column(ForeignKey("native_materials.id", ondelete="RESTRICT"))
