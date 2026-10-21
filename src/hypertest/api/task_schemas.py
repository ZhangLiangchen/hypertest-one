"""ADR-018 management intake. No field authorizes test execution."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROFILE = "codex-session-task-sync/v1alpha1"
TaskStatus = Literal["DRAFT", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"]
ReportedResult = Literal["NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"]
KEY = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TaskCase(TaskInput):
    key: str = Field(pattern=KEY)
    title: str = Field(min_length=1, max_length=512, pattern=r"\S")
    steps: list[str] = Field(default_factory=list, max_length=100)
    expected: str = Field(default="", max_length=16000)
    actual: str = Field(default="", max_length=16000)
    reported_result: ReportedResult = "NOT_RUN"
    implementation_ref: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def bounded_steps(self):
        if any(len(step) > 16000 for step in self.steps):
            raise ValueError("case step exceeds 16000 characters")
        return self


class TaskReport(TaskInput):
    key: str = Field(pattern=KEY)
    title: str = Field(min_length=1, max_length=512, pattern=r"\S")
    markdown: str = Field(min_length=1, max_length=262144)
    artifact_uri: str | None = Field(default=None, max_length=2048)
    source_ref: str | None = Field(default=None, max_length=2048)
    reported_result: ReportedResult = "UNKNOWN"


class SessionTaskSync(TaskInput):
    project_id: UUID
    idempotency_key: str = Field(pattern=KEY)
    expected_version: int = Field(ge=0)
    provider: str = Field(default="codex", pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    session_id: str = Field(min_length=1, max_length=512, pattern=r"\S")
    title: str = Field(min_length=1, max_length=512, pattern=r"\S")
    objective: str = Field(default="", max_length=16000)
    status: TaskStatus = "IN_PROGRESS"
    plan_markdown: str = Field(default="", max_length=262144)
    reported_result: ReportedResult = "NOT_RUN"
    cases: list[TaskCase] = Field(default_factory=list, max_length=200)
    reports: list[TaskReport] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique_bounded(self):
        for values in (self.cases, self.reports):
            if len({item.key for item in values}) != len(values):
                raise ValueError("duplicate case or report key")
        if len(self.model_dump_json().encode()) > 2 * 1024 * 1024:
            raise ValueError("sync exceeds 2 MiB")
        return self


GET_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string", "format": "uuid"},
        "provider": {"type": "string", "minLength": 1, "maxLength": 64},
        "session_id": {"type": "string", "minLength": 1, "maxLength": 512},
        "idempotency_key": {"type": "string", "pattern": KEY},
        "version": {"type": "integer", "minimum": 1},
        "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 24000},
    },
    "required": ["project_id"],
    "oneOf": [
        {"required": ["provider", "session_id"], "not": {"required": ["idempotency_key"]}},
        {"required": ["idempotency_key"], "not": {"anyOf": [
            {"required": ["provider"]}, {"required": ["session_id"]},
            {"required": ["version"]}, {"required": ["offset"]}, {"required": ["limit"]},
        ]}},
    ],
    "allOf": [{
        "if": {"required": ["offset"], "properties": {"offset": {"minimum": 1}}},
        "then": {"required": ["version"]},
    }],
    "additionalProperties": False,
}
