from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hypertest.common.ids import uuid7
from hypertest.db.base import Base
from hypertest.domain.enums import (
    MissionStatus,
    MissionType,
    Priority,
    ProjectStatus,
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
