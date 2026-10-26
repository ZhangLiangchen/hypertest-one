"""Explicit Local collaboration intents; these never authorize test execution."""
import json
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from hypertest.api.task_schemas import (
    KEY,
    ReportedResult,
    TaskCase,
    TaskInput,
    TaskReport,
    TaskStatus,
)

COLLABORATION_PROFILE = "local-task-collaboration/v1alpha1"


class ContributionInput(TaskInput):
    kind: Literal["PLAN", "CASE", "REPORT", "REVIEW"]
    stable_key: str = Field(pattern=KEY)
    expected_revision: int = Field(ge=0)
    content: dict

    @model_validator(mode="after")
    def normalize_content(self):
        if self.kind in {"CASE", "REPORT"}:
            if "key" in self.content:
                raise ValueError("contribution key belongs in stable_key")
            model = TaskCase if self.kind == "CASE" else TaskReport
            self.content = model(key=self.stable_key, **self.content).model_dump(mode="json", exclude={"key"})
        if len(json.dumps(self.content, ensure_ascii=False, allow_nan=False).encode()) > 524288:
            raise ValueError("contribution exceeds 512 KiB")
        return self


class ContributionReference(TaskInput):
    contribution_id: UUID
    revision: int = Field(ge=1)
    disposition: Literal["ADOPTED", "MERGED", "DIVERGENCE", "DEFERRED"]
    shared_key: str | None = Field(default=None, pattern=KEY)


class PublicationSummary(TaskInput):
    title: str = Field(min_length=1, max_length=512, pattern=r"\S")
    objective: str = Field(default="", max_length=16000)
    status: TaskStatus
    plan_markdown: str = Field(default="", max_length=262144)
    reported_result: ReportedResult
    contribution_refs: list[ContributionReference] = Field(default_factory=list, max_length=400)
    completion_basis: str = Field(default="", max_length=16000)
    unresolved_items: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def explicit_completion(self):
        if self.status == "COMPLETED" and not self.completion_basis.strip():
            raise ValueError("completed publication requires an explicit completion basis")
        if len({str(item.contribution_id) for item in self.contribution_refs}) != len(self.contribution_refs):
            raise ValueError("duplicate contribution reference")
        if any(len(item) > 16000 for item in self.unresolved_items):
            raise ValueError("unresolved item exceeds 16000 characters")
        return self


class CollaborationMemberOperation(TaskInput):
    profile: Literal[COLLABORATION_PROFILE] = COLLABORATION_PROFILE
    project_id: UUID
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    session_id: str = Field(min_length=1, max_length=512, pattern=r"\S")
    operation: Literal["JOIN", "CONTRIBUTE", "PUBLISH"]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(pattern=KEY)
    contributions: list[ContributionInput] | None = Field(default=None, min_length=1, max_length=200)
    primary_generation: int | None = Field(default=None, ge=1)
    summary: PublicationSummary | None = None

    @model_validator(mode="after")
    def operation_fields(self):
        allowed = {"JOIN": set(), "CONTRIBUTE": {"contributions"},
                   "PUBLISH": {"primary_generation", "summary"}}[self.operation]
        supplied = {name for name in ("contributions", "primary_generation", "summary")
                    if getattr(self, name) is not None}
        if supplied != allowed:
            raise ValueError("operation payload fields do not match operation")
        if self.contributions and len({(x.kind, x.stable_key) for x in self.contributions}) != len(self.contributions):
            raise ValueError("duplicate contribution namespace")
        if len(self.model_dump_json().encode()) > 2 * 1024 * 1024:
            raise ValueError("collaboration intent exceeds 2 MiB")
        return self


class HandoffManifest(TaskInput):
    materials: list[str] = Field(default_factory=list, max_length=200)
    unresolved_items: list[str] = Field(default_factory=list, max_length=200)
    private_journals_observed: Literal[False] = False

    @model_validator(mode="after")
    def bounded(self):
        if any(len(x) > 16000 for x in self.materials + self.unresolved_items):
            raise ValueError("handoff item exceeds 16000 characters")
        return self


class CollaborationOperatorOperation(TaskInput):
    profile: Literal[COLLABORATION_PROFILE] = COLLABORATION_PROFILE
    operation: Literal["ENABLE", "AUTHORIZE", "REVOKE", "HANDOFF"]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(pattern=KEY)
    actor_ref: str | None = Field(default=None, max_length=255)
    provider: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    session_id: str | None = Field(default=None, min_length=1, max_length=512, pattern=r"\S")
    assignment: str = Field(default="", max_length=16000)
    participant_id: UUID | None = None
    expected_primary_generation: int | None = Field(default=None, ge=1)
    handoff: HandoffManifest | None = None

    @model_validator(mode="after")
    def operation_fields(self):
        fields = {"actor_ref", "provider", "session_id", "participant_id", "expected_primary_generation", "handoff"}
        supplied = {key for key in fields if getattr(self, key) is not None}
        allowed = {"ENABLE": set(), "AUTHORIZE": {"actor_ref", "provider", "session_id"},
                   "REVOKE": {"participant_id"},
                   "HANDOFF": {"participant_id", "expected_primary_generation", "handoff"}}[self.operation]
        if supplied != allowed or (self.operation != "AUTHORIZE" and self.assignment):
            raise ValueError("operation payload fields do not match operation")
        return self
