from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hypertest.api.job_schemas import JobRead
from hypertest.api.schemas import ORMModel
from hypertest.domain.inputs import InputRequestStatus


class InputRequestRead(ORMModel):
    id: UUID
    key: str
    test_run_id: UUID
    scope: Literal["mission", "run"] = "mission"
    mission_id: UUID | None = None
    attempt_id: UUID | None = None
    binding_id: UUID | None = None
    context_mission_id: UUID | None = None
    context_attempt_id: UUID | None = None
    agent_session_id: UUID
    durable_job_id: UUID
    question_id: str
    question: str
    options: list[str]
    status: InputRequestStatus
    answer: str | None
    created_at: datetime
    answered_at: datetime | None
    consumed_at: datetime | None
    cancelled_at: datetime | None
    row_version: int


class InputAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=12000)
    expected_row_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=512)

    @field_validator("answer", "idempotency_key")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("text must not be blank or contain NUL")
        return value


class InputAnswerRead(BaseModel):
    input_request: InputRequestRead
    job: JobRead
