"""Explicit Local artifact archive: typed content, never execution authority."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from hypertest.api.task_schemas import KEY, ReportedResult, TaskInput, TaskStatus

PROFILE = "local-artifact-archive/v1alpha1"
MAX_BYTES = 2 * 1024 * 1024


class ArchiveOrigin(TaskInput):
    origin_provider: str | None = Field(default=None, max_length=64)
    origin_session_ref: str | None = Field(default=None, max_length=512)
    producer: str | None = Field(default=None, max_length=512)
    source_ref: str | None = Field(default=None, max_length=2048)
    test_started_at: str | None = Field(default=None, max_length=64)
    test_finished_at: str | None = Field(default=None, max_length=64)
    report_created_at: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def timestamps(self):
        from datetime import datetime
        for name in ("test_started_at", "test_finished_at", "report_created_at"):
            value = getattr(self, name)
            if value is not None:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("source timestamps require an explicit timezone")
        return self


class ArchiveAsset(TaskInput):
    stable_key: str = Field(pattern=KEY)
    title: str = Field(min_length=1, max_length=512, pattern=r"\S")
    origin: ArchiveOrigin = Field(default_factory=ArchiveOrigin)


class ArchivePlan(ArchiveAsset):
    kind: Literal["PLAN"]
    markdown: str = Field(min_length=1, max_length=262144)
    reported_result: ReportedResult = "NOT_RUN"
    artifact_uri: str | None = Field(default=None, max_length=2048)


class ArchiveReport(ArchiveAsset):
    kind: Literal["REPORT"]
    markdown: str = Field(min_length=1, max_length=262144)
    reported_result: ReportedResult = "UNKNOWN"
    artifact_uri: str | None = Field(default=None, max_length=2048)


class ArchiveCase(ArchiveAsset):
    kind: Literal["CASE"]
    steps: list[str] = Field(default_factory=list, max_length=100)
    expected: str = Field(default="", max_length=16000)
    actual: str = Field(default="", max_length=16000)
    reported_result: ReportedResult = "NOT_RUN"
    implementation_ref: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def steps_bounded(self):
        if any(len(step) > 16000 for step in self.steps):
            raise ValueError("case step exceeds 16000 characters")
        return self


class SubtaskUpdate(TaskInput):
    status: TaskStatus | None = None
    reported_result: ReportedResult | None = None

    @model_validator(mode="after")
    def explicit_values(self):
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("subtask updates require explicit non-null fields")
        return self


class ArchiveSubmit(TaskInput):
    profile: Literal[PROFILE] = PROFILE
    project_id: UUID
    task_id: UUID
    subtask_id: UUID | None = None
    idempotency_key: str = Field(pattern=KEY)
    expected_archive_version: int = Field(ge=1)
    assets: list[Annotated[ArchivePlan | ArchiveCase | ArchiveReport, Field(discriminator="kind")]] = Field(default_factory=list, max_length=232)
    subtask_update: SubtaskUpdate | None = None

    @model_validator(mode="after")
    def limits(self):
        if self.subtask_id is None and "subtask_update" in self.model_fields_set:
            raise ValueError("TASK target does not accept subtask_update")
        if "subtask_update" in self.model_fields_set and self.subtask_update is None:
            raise ValueError("subtask_update cannot be null")
        if len({(asset.kind, asset.stable_key) for asset in self.assets}) != len(self.assets):
            raise ValueError("duplicate asset kind/stable_key")
        for kind, limit in (("PLAN", 16), ("CASE", 200), ("REPORT", 16)):
            if sum(asset.kind == kind for asset in self.assets) > limit:
                raise ValueError(f"too many {kind} assets")
        if len(self.model_dump_json().encode("utf-8")) > MAX_BYTES:
            raise ValueError("archive exceeds 2 MiB")
        return self

    def wire(self):
        body = self.model_dump(mode="json")
        if self.subtask_update is None:
            body.pop("subtask_update")
        else:
            body["subtask_update"] = self.subtask_update.model_dump(exclude_unset=True)
        return body


class ArchiveManagement(TaskInput):
    project_id: UUID
    idempotency_key: str = Field(pattern=KEY)


class ArchiveTaskCreate(ArchiveManagement):
    title: str = Field(min_length=1, max_length=512, pattern=r"\S")
    objective: str = Field(default="", max_length=16000)
    owner_uploader_actor_ref: str | None = Field(default=None, max_length=255)
    expected_project_version: int | None = Field(default=None, ge=1)
    sut_branch: str | None = Field(default=None, min_length=1, max_length=255, pattern=r"^[^\x00-\x20\x7f]+$")
    framework_branch: str | None = Field(default=None, min_length=1, max_length=255, pattern=r"^[^\x00-\x20\x7f]+$")


class ArchiveTaskUpdate(ArchiveManagement):
    expected_task_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=512, pattern=r"\S")
    objective: str | None = Field(default=None, max_length=16000)

    @model_validator(mode="after")
    def explicit_values(self):
        for name in self.model_fields_set & {"title", "objective"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ArchiveSubtaskCreate(ArchiveManagement):
    expected_task_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=512, pattern=r"\S")
    objective: str = Field(default="", max_length=16000)


class ArchiveAuthorize(ArchiveManagement):
    expected_task_version: int = Field(ge=1)
    subtask_id: UUID | None = None
    uploader_actor_ref: str | None = Field(max_length=255)


class SubtaskVersion(TaskInput):
    subtask_id: UUID
    archive_version: int = Field(ge=1)


class ArchivePublish(ArchiveManagement):
    expected_task_version: int = Field(ge=1)
    root_archive_version: int = Field(ge=1)
    subtask_versions: list[SubtaskVersion] = Field(default_factory=list, max_length=200)
    asset_revision_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    summary: str = Field(min_length=1, max_length=262144)
    status: TaskStatus
    reported_result: ReportedResult

    @model_validator(mode="after")
    def unique_refs(self):
        if len({item.subtask_id for item in self.subtask_versions}) != len(self.subtask_versions):
            raise ValueError("duplicate subtask version")
        if len(set(self.asset_revision_ids)) != len(self.asset_revision_ids):
            raise ValueError("duplicate asset revision")
        return self
