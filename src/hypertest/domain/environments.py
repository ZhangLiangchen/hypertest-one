"""Provider-independent, immutable requests for operator-controlled environments."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    app: str = Field(max_length=256, pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$")
    health_path: str = Field(default="/health", min_length=1, max_length=256)
    startup_timeout_seconds: int = Field(default=30, ge=1, le=120, strict=True)

    @field_validator("health_path")
    @classmethod
    def local_health_path(cls, value: str) -> str:
        import re

        if (not re.fullmatch(r"/[A-Za-z0-9_./~-]*", value)
            or "//" in value or ".." in value or "%" in value):
            raise ValueError("health_path must be a local absolute path without query or traversal")
        return value


class EnvironmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: Literal["python-pytest-v1", "python-api-v1"]
    service: ServiceRequest | None = None

    @model_validator(mode="after")
    def service_matches_profile(self):
        if (self.profile_id == "python-api-v1") != (self.service is not None):
            raise ValueError("python-api-v1 requires service; python-pytest-v1 forbids service")
        return self
