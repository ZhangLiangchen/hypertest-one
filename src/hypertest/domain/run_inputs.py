"""Run-scoped questions do not invent or reopen a MissionAttempt."""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.common.ids import uuid7
from hypertest.db.base import Base
from hypertest.domain.inputs import InputRequestStatus


class RunInputRequest(Base):
    __tablename__ = "run_input_requests"
    __table_args__ = (
        UniqueConstraint("binding_id", "question_id", name="uq_run_input_question"),
        UniqueConstraint("test_run_id", "key", name="uq_run_input_key"),
        CheckConstraint("row_version > 0", name="ck_run_input_version"),
        CheckConstraint("length(btrim(question)) > 0 AND length(question) <= 4096", name="ck_run_input_question_text"),
        CheckConstraint("answer IS NULL OR (length(btrim(answer)) > 0 AND length(answer) <= 12000)", name="ck_run_input_answer_text"),
        CheckConstraint("(answer IS NULL) = (answered_at IS NULL) AND (answer IS NULL) = (answer_idempotency_key IS NULL)", name="ck_run_input_answer_fields"),
        CheckConstraint("(status = 'PENDING' AND answer IS NULL AND consumed_at IS NULL AND cancelled_at IS NULL) OR (status = 'ANSWERED' AND answer IS NOT NULL AND consumed_at IS NULL AND cancelled_at IS NULL) OR (status = 'CONSUMED' AND answer IS NOT NULL AND consumed_at IS NOT NULL AND cancelled_at IS NULL) OR (status = 'CANCELLED' AND cancelled_at IS NOT NULL)", name="ck_run_input_lifecycle"),
        Index("uq_run_input_open_run", "test_run_id", unique=True, postgresql_where=text("status IN ('PENDING', 'ANSWERED')")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"), index=True)
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"), index=True)
    agent_session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id", ondelete="RESTRICT"))
    durable_job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id", ondelete="RESTRICT"), index=True)
    context_mission_id: Mapped[UUID | None] = mapped_column(ForeignKey("missions.id", ondelete="RESTRICT"))
    context_attempt_id: Mapped[UUID | None] = mapped_column(ForeignKey("mission_attempts.id", ondelete="RESTRICT"))
    question_id: Mapped[str] = mapped_column(String(128), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[InputRequestStatus] = mapped_column(Enum(InputRequestStatus, native_enum=False, create_constraint=True, name="ck_run_input_status", length=32), default=InputRequestStatus.PENDING)
    answer: Mapped[str | None] = mapped_column(Text)
    answer_idempotency_key: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)

    @property
    def scope(self) -> str:
        return "run"
