"""Versioned deterministic policy compilation, independent of Agents and storage.

Missing coverage configuration preserves the v1 baseline. An explicit category
rule replaces that category's specialized dimensions, while FUNCTIONAL is always
required. The normalized rules expose that mandatory minimum rather than treating
an empty configuration as a waiver.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hypertest.domain.enums import FindingSeverity, RiskCategory, TestCaseType

BASELINE_DIMENSIONS_BY_CATEGORY = {
    RiskCategory.BOUNDARY: TestCaseType.BOUNDARY,
    RiskCategory.FAILURE: TestCaseType.FAILURE,
    RiskCategory.CONCURRENCY: TestCaseType.CONCURRENCY,
    RiskCategory.SECURITY: TestCaseType.SECURITY,
    RiskCategory.PERFORMANCE: TestCaseType.PERFORMANCE,
    RiskCategory.RELIABILITY: TestCaseType.RECOVERY,
}


class InvalidPolicyError(ValueError):
    """A policy cannot be interpreted by this version of HyperTest."""


def _hash(value: dict[str, Any]) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _dimension_list(value: Any) -> Any:
    if not isinstance(value, list):
        raise ValueError("dimensions must be a JSON array")
    if any(not isinstance(item, str) for item in value):
        raise ValueError("each dimension must be a TestCaseType name")
    if len(value) != len(set(value)):
        raise ValueError("dimensions must not contain duplicates")
    return value


class CoveragePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["risk-design-policy/v1"] = "risk-design-policy/v1"
    default_dimensions: tuple[TestCaseType, ...] = (TestCaseType.FUNCTIONAL,)
    by_category: dict[RiskCategory, tuple[TestCaseType, ...]] = Field(default_factory=dict)

    @field_validator("default_dimensions", mode="before")
    @classmethod
    def validate_default_dimensions(cls, value: Any) -> Any:
        return _dimension_list(value)

    @field_validator("by_category", mode="before")
    @classmethod
    def validate_category_dimensions(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("by_category must be an object keyed by RiskCategory")
        for dimensions in value.values():
            _dimension_list(dimensions)
        return value

    def required_dimensions(self, category: RiskCategory) -> set[TestCaseType]:
        required = {TestCaseType.FUNCTIONAL, *self.default_dimensions}
        if category in self.by_category:
            required.update(self.by_category[category])
        elif specialized := BASELINE_DIMENSIONS_BY_CATEGORY.get(category):
            required.add(specialized)
        return required

    @property
    def effective_rules(self) -> dict[str, Any]:
        """Fully resolved dimensions; aliases and input order do not affect identity."""
        return {
            "version": self.version,
            "required_dimensions": {
                category.value: sorted(item.value for item in self.required_dimensions(category))
                for category in RiskCategory
            },
        }

    @property
    def effective_policy_hash(self) -> str:
        return _hash(self.effective_rules)

    @property
    def rule_version(self) -> str:
        baseline = CoveragePolicy()
        if self.effective_rules == baseline.effective_rules:
            return "risk-design-baseline/v1"
        return self.version


class GatePolicyConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    blocking_finding_severities: tuple[FindingSeverity, ...] = (
        FindingSeverity.BLOCKER,
        FindingSeverity.CRITICAL,
    )

    @field_validator("blocking_finding_severities", mode="before")
    @classmethod
    def validate_severities(cls, value: Any) -> Any:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("blocking_finding_severities must be an array of FindingSeverity names")
        if len(value) != len(set(value)):
            raise ValueError("blocking_finding_severities must not contain duplicates")
        return value


class CompiledPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_version: Literal["mvp/v1"] = "mvp/v1"
    gate: GatePolicyConfiguration = Field(default_factory=GatePolicyConfiguration)
    coverage: CoveragePolicy = Field(default_factory=CoveragePolicy)

    @property
    def effective_policy_hash(self) -> str:
        return _hash({
            "gate_version": self.gate_version,
            "gate": {
                "blocking_finding_severities": sorted({
                    FindingSeverity.BLOCKER.value,
                    *(item.value for item in self.gate.blocking_finding_severities),
                }),
            },
            "coverage": self.coverage.effective_rules,
        })


def compile_policy(value: dict[str, Any]) -> CompiledPolicy:
    """Reject unsupported rules before they can acquire immutable snapshot semantics."""
    try:
        return CompiledPolicy.model_validate(value)
    except ValidationError as exc:
        raise InvalidPolicyError(f"invalid compiled policy: {exc}") from exc
