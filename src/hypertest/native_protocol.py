"""ADR-017 intake contracts. These describe observations, never Runner facts."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hypertest.common.repositories import validate_repository_origin

PROFILE = "native-framework-intake/v1alpha1"
POLICY = "native-material-gate/v1alpha1"
MAX_MATERIAL = 2 * 1024 * 1024
MAX_TOTAL = 6 * 1024 * 1024
Digest = str


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def bounded_text(self):
        def check(value):
            if isinstance(value, str) and ("\x00" in value or not value.strip()):
                raise ValueError("text must be nonblank and contain no NUL")
            if isinstance(value, str) and len(value) > 16000:
                raise ValueError("text exceeds 16000 characters")
            if isinstance(value, dict):
                for key, item in value.items():
                    if len(key) > 255:
                        raise ValueError("metadata key exceeds 255 characters")
                    if key != "content_base64":
                        check(item)
            if isinstance(value, list):
                for item in value:
                    check(item)
        # Empty stderr is represented by empty base64, which is valid material.
        check(self.model_dump(exclude={"content_base64"}))
        return self


class SutIdentity(StrictModel):
    repository_url: str = Field(max_length=2048)
    source_commit: str | None = Field(default=None, pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    binary_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_association: Literal["DECLARED", "UNVERIFIED", "UNKNOWN"] = "UNVERIFIED"
    local_changes: str = Field(default="not observed", max_length=16000)

    @field_validator("repository_url")
    @classmethod
    def safe_origin(cls, value):
        return validate_repository_origin(value)

    @model_validator(mode="after")
    def identity_required(self):
        if not self.source_commit and not self.binary_sha256:
            raise ValueError("SUT needs an exact source commit or binary digest")
        return self


class FrameworkIdentity(StrictModel):
    repository_url: str = Field(max_length=2048)
    commit_sha: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    local_changes: str = Field(max_length=16000)

    @field_validator("repository_url")
    @classmethod
    def safe_origin(cls, value):
        return validate_repository_origin(value)


class TestAsset(StrictModel):
    path: str = Field(max_length=2048)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class NativeInputs(StrictModel):
    sut: SutIdentity
    framework: FrameworkIdentity
    test_assets: list[TestAsset] = Field(min_length=1, max_length=200)
    environment: dict[str, str] = Field(min_length=1, max_length=64)
    environment_variable_names: list[str] = Field(default_factory=list, max_length=64)
    authorization_scope: str = Field(max_length=4000)
    source_transfer: Literal["NONE"] = "NONE"

    @field_validator("environment_variable_names")
    @classmethod
    def env_names_only(cls, values):
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) for v in values):
            raise ValueError("environment variables must contain names only")
        return values


class NativeCaseProposal(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    title: str = Field(max_length=512)
    requirement_ref: str = Field(max_length=2048)
    risk_ref: str = Field(max_length=2048)
    expected_result: str = Field(max_length=8000)
    implementation_ref: str = Field(max_length=2048)


class NativePlanProposal(StrictModel):
    objective: str = Field(max_length=4000)
    scope: str = Field(max_length=8000)
    requirement_refs: list[str] = Field(min_length=1, max_length=200)
    risk_refs: list[str] = Field(min_length=1, max_length=200)
    inputs: NativeInputs
    cases: list[NativeCaseProposal] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def case_references(self):
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > 512 * 1024:
            raise ValueError("native plan exceeds 512 KiB")
        if len({c.key for c in self.cases}) != len(self.cases):
            raise ValueError("case keys must be unique within the plan")
        if len({c.implementation_ref for c in self.cases}) != len(self.cases):
            raise ValueError("native report identifiers must be unique within the plan")
        for case in self.cases:
            if case.requirement_ref not in self.requirement_refs or case.risk_ref not in self.risk_refs:
                raise ValueError("case references must belong to the proposed plan")
        return self


class CreateNativeRun(StrictModel):
    profile: Literal["native-framework-intake/v1alpha1"] = PROFILE
    project_id: UUID
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    session_ref: str = Field(max_length=512, description="Contribution label; not native session proof")
    plan: NativePlanProposal


class NativeWrite(StrictModel):
    contributor_id: UUID
    generation: int = Field(ge=1)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class NativeCaseObservation(StrictModel):
    case_key: str = Field(max_length=128)
    result: Literal["PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN"]


class NativeMaterialInput(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,255}$")
    kind: Literal["STDOUT", "STDERR", "REPORT", "CONTEXT"]
    format: Literal["TEXT", "CONSUMER_PARITY_JSONL", "JUNIT_XML"]
    content_base64: str = Field(max_length=2_796_204)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    def content(self) -> bytes:
        try:
            value = base64.b64decode(self.content_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("material must be valid base64") from None
        if len(value) > MAX_MATERIAL:
            raise ValueError("material exceeds 2 MiB")
        if hashlib.sha256(value).hexdigest() != self.sha256:
            raise ValueError("material digest mismatch")
        return value


class SubmitNativeExecution(NativeWrite):
    command: list[str] = Field(min_length=1, max_length=128)
    cwd: str = Field(max_length=4096)
    framework: str = Field(max_length=255)
    started_at: datetime
    finished_at: datetime
    exit_code: int = Field(ge=-255, le=255)
    results: list[NativeCaseObservation] = Field(min_length=1, max_length=200)
    materials: list[NativeMaterialInput] = Field(min_length=1, max_length=8)
    retry_of_execution_id: UUID | None = None

    @model_validator(mode="after")
    def bounded_execution(self):
        if not self.started_at.tzinfo or not self.finished_at.tzinfo or self.finished_at < self.started_at:
            raise ValueError("execution requires ordered timezone-aware timestamps")
        if len({r.case_key for r in self.results}) != len(self.results):
            raise ValueError("case observations must be unique")
        if len({m.name for m in self.materials}) != len(self.materials):
            raise ValueError("material names must be unique")
        if sum(len(m.content()) for m in self.materials) > MAX_TOTAL:
            raise ValueError("execution materials exceed 6 MiB")
        return self


class NativeHandoff(NativeWrite):
    successor_session_ref: str = Field(max_length=512)
    remaining_work: list[str] = Field(min_length=1, max_length=100)
    reason: str = Field(max_length=4000)


class NativeUncertainty(NativeWrite):
    external_operation_ref: str = Field(max_length=2048)
    reason: str = Field(max_length=4000)


class OperatorReadbackAttestation(StrictModel):
    kind: Literal["ORIGINAL_OPERATION_READBACK", "EXECUTION_CONTROL_READBACK"]
    source_ref: str = Field(max_length=2048)
    operation_ref: str = Field(max_length=2048)
    observed_at: datetime
    result: Literal["OBSERVED_SUCCEEDED", "OBSERVED_FAILED", "NOT_PERFORMED", "NOT_FOUND", "UNKNOWN"]
    raw_material_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    operator_attests_original_readback: Literal[True]

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value):
        if not value.tzinfo:
            raise ValueError("readback timestamp must have a timezone")
        return value


class NativeReconciliation(NativeWrite):
    resolution: Literal["OBSERVED_SUCCEEDED", "OBSERVED_FAILED", "NOT_PERFORMED", "NOT_FOUND", "UNKNOWN"]
    observed_operation_ref: str = Field(max_length=2048)
    material: NativeMaterialInput
    attestation: OperatorReadbackAttestation
    reason: str = Field(max_length=4000)

    @model_validator(mode="after")
    def same_readback(self):
        if (self.attestation.operation_ref != self.observed_operation_ref or
            self.attestation.result != self.resolution or
            self.attestation.raw_material_sha256 != self.material.sha256):
            raise ValueError("Operator attestation must bind exact operation, result and original material")
        return self
