from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hypertest.connector.source import validate_origin


class SourceTransferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    node_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    origin: str = Field(min_length=1, max_length=2048)
    commit_sha: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    ref: str | None = Field(default=None, max_length=255)
    policy_version: str = Field(min_length=1, max_length=64)

    @field_validator("origin")
    @classmethod
    def safe_origin(cls, value):
        return validate_origin(value)


class SourceAcquisitionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transfer_id: UUID
    request_id: UUID
    project_id: UUID
    node_id: UUID
    origin: str = Field(max_length=2048)
    ref: str | None = Field(default=None, max_length=255)
    commit_sha: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    root_tree: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    policy_version: str = Field(min_length=1, max_length=64)
    bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bundle_size: int = Field(ge=1, le=50331648)
    result: str = Field(pattern=r"^ACQUIRED$")


class SourceTransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    request_id: UUID
    node_id: UUID
    origin: str
    commit_sha: str
    ref: str | None
    policy_version: str
    status: str
    root_tree: str | None
    bundle_sha256: str | None
    bundle_size: int | None
    error_code: str | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
