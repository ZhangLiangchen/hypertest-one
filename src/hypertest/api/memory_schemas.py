"""Explicit experience input only: never a prompt, conversation or task sync payload."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROFILE = "hypertest-project-memory/v1alpha1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalSource(StrictModel):
    mode: Literal["LOCAL"]
    task_id: UUID
    task_version: int = Field(ge=1)
    report_id: UUID


class CloudSource(StrictModel):
    mode: Literal["CLOUD"]
    task_id: UUID
    task_version: int = Field(ge=1)
    attempt_id: UUID
    asset_revision_id: UUID


MemorySource = Annotated[LocalSource | CloudSource, Field(discriminator="mode")]


class Mutation(StrictModel):
    project_id: UUID
    operation_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_version: int = Field(ge=0)


class Experience(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=16000)
    applicability: str = Field(default="", max_length=2000)
    observed_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("observed_at", "expires_at")
    @classmethod
    def aware_dates(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Timestamp requires timezone")
        return value


class Configure(Mutation):
    operation: Literal["CONFIGURE"]
    enabled: bool


class CreateCandidate(Mutation, Experience):
    operation: Literal["CREATE_CANDIDATE"]
    source: MemorySource


class Publish(Mutation, Experience):
    operation: Literal["PUBLISH", "REVISE"]
    entry_id: UUID
    publication_note: str = Field(min_length=1, max_length=2000)


class Retract(Mutation):
    operation: Literal["RETRACT"]
    entry_id: UUID
    publication_note: str = Field(min_length=1, max_length=2000)


MemoryMutation = Annotated[Configure | CreateCandidate | Publish | Retract, Field(discriminator="operation")]


class CloudQueryContext(StrictModel):
    mode: Literal["CLOUD"] = "CLOUD"
    task_id: UUID
    attempt_id: UUID
    task_version: int = Field(ge=1)


class MemoryQuery(StrictModel):
    project_id: UUID
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=20)
    source: MemorySource | None = None
    context: CloudQueryContext | None = None
