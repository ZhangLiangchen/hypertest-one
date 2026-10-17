from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from hypertest.domain.enums import (
    Priority,
    ProposalOperation,
    ProposalType,
    RequirementSourceType,
    RequirementType,
    RiskCategory,
    RiskProbability,
    RiskSeverity,
    TestCaseType,
)


class ProposalSubmission(BaseModel):
    proposal_type: ProposalType
    operation: ProposalOperation
    idempotency_key: str = Field(min_length=1, max_length=512)
    object_payload: dict[str, Any]
    rationale: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class MissionResultSubmission(BaseModel):
    protocol: str = "hypertest.tmp/v1alpha1"
    mission_id: str
    status: Literal["COMPLETED", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"]
    summary: str = ""
    proposals: list[ProposalSubmission] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    execution_requests: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class RequirementProposalPayload(BaseModel):
    logical_key: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1)
    requirement_type: RequirementType = RequirementType.FUNCTIONAL
    priority: Priority = Priority.P1
    source_type: RequirementSourceType = RequirementSourceType.PRD
    source_ref: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class RiskProposalPayload(BaseModel):
    requirement_keys: list[str] = Field(min_length=1)
    category: RiskCategory
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1)
    severity: RiskSeverity = RiskSeverity.MEDIUM
    probability: RiskProbability = RiskProbability.UNKNOWN
    rationale: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class TestCaseProposalPayload(BaseModel):
    """An agent's proposed test intent; canonical references are resolved by HyperTest."""

    risk_keys: list[str] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1)
    test_type: TestCaseType
    priority: Priority = Priority.P1
    preconditions: list[str] = Field(default_factory=list)
    expected_result: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("risk_keys")
    @classmethod
    def validate_risk_keys(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("risk keys must not be blank")
        return sorted({value.strip() for value in values})

    @field_validator("title", "description", "expected_result")
    @classmethod
    def validate_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("test intent text must not be blank")
        return value


class TestImplementationProposalPayload(BaseModel):
    """A proposed executable location, never an agent's claim of a passing test."""

    test_case_keys: list[str] = Field(min_length=1)
    repository_url: str = Field(min_length=1)
    commit_sha: str = Field(min_length=7, max_length=64)
    file_path: str = Field(min_length=1, max_length=1024)
    symbol: str = Field(
        min_length=1, max_length=512,
        pattern=r"^(?:[A-Za-z_][A-Za-z0-9_]*::)*test_[A-Za-z0-9_]+$",
    )
    framework: Literal["pytest"] = "pytest"
    language: Literal["python"] = "python"
    code: str | None = Field(default=None, min_length=1, max_length=1_000_000)

    @field_validator("test_case_keys")
    @classmethod
    def validate_case_keys(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("test case keys must not be blank")
        return sorted({value.strip() for value in values})

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or "\x00" in value
            or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or not path.parts
            or path.parts[0] != "tests"
            or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path.parts)
            or path.suffix != ".py"
            or value.startswith("-")
        ):
            raise ValueError("file_path must be a safe relative Python file path under tests/")
        return path.as_posix()

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_]*::)*test_[A-Za-z0-9_]+", value):
            raise ValueError("symbol must identify a pytest test function, optionally inside classes")
        return value

    @field_validator("repository_url")
    @classmethod
    def normalize_repository(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            raise ValueError("repository_url must not be blank")
        return value

    @field_validator("commit_sha")
    @classmethod
    def normalize_commit(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("code")
    @classmethod
    def validate_python_source(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                compile(ast.parse(value), "<proposed-test>", "exec")
            except (SyntaxError, ValueError, TypeError) as exc:
                raise ValueError("generated test source must compile as Python") from exc
        return value
