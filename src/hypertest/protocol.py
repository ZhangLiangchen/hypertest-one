from __future__ import annotations

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
