"""Bounded operational observations, never testing facts or provider transcripts."""
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base


class ActivitySource(StrEnum):
    PROVIDER = "PROVIDER"
    CONTROL_PLANE = "CONTROL_PLANE"


class ActivityKind(StrEnum):
    SIGNAL_RECEIVED = "SIGNAL_RECEIVED"
    TURN_STARTED = "TURN_STARTED"
    TURN_COMPLETED = "TURN_COMPLETED"
    MODEL_ACTIVITY = "MODEL_ACTIVITY"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    FILE_ACTIVITY = "FILE_ACTIVITY"
    MISSION_STARTED = "MISSION_STARTED"
    RESUMED = "RESUMED"
    RESULT_SUBMITTED = "RESULT_SUBMITTED"
    MISSION_FINISHED = "MISSION_FINISHED"
    ERROR = "ERROR"


class MissionActivityEvent(Base):
    __tablename__ = "mission_activity_events"
    __table_args__ = (
        UniqueConstraint("attempt_id", "claim_no", "window_id", "source", "kind", name="uq_activity_window"),
        CheckConstraint("count > 0 AND claim_no > 0", name="ck_activity_positive_counts"),
        CheckConstraint("last_observed_at >= recorded_at", name="ck_activity_time_order"),
        CheckConstraint("source IN ('PROVIDER','CONTROL_PLANE')", name="ck_activity_source"),
        CheckConstraint("(source='PROVIDER' AND kind IN ('SIGNAL_RECEIVED','TURN_STARTED','TURN_COMPLETED','MODEL_ACTIVITY','TOOL_STARTED','TOOL_COMPLETED','FILE_ACTIVITY','ERROR')) OR (source='CONTROL_PLANE' AND kind IN ('MISSION_STARTED','RESUMED','RESULT_SUBMITTED','MISSION_FINISHED','ERROR'))", name="ck_activity_source_kind"),
        CheckConstraint("kind IN (" + ",".join("'" + k.value + "'" for k in ActivityKind) + ")", name="ck_activity_kind"),
        Index("ix_activity_job_cursor", "durable_job_id", "recorded_at", "id"),
        Index("ix_activity_attempt_recent", "attempt_id", "recorded_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    durable_job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"))
    mission_id: Mapped[UUID] = mapped_column(ForeignKey("missions.id", ondelete="RESTRICT"))
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("mission_attempts.id", ondelete="RESTRICT"))
    agent_session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(32))
    claim_no: Mapped[int] = mapped_column(Integer)
    window_id: Mapped[int] = mapped_column(BigInteger)
    count: Mapped[int] = mapped_column(Integer, default=1)
    recorded_at = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)
    last_observed_at = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)
    retention_truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
