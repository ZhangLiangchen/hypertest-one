"""Deterministic design coverage derived solely from snapshot-scoped canonical state.

Rules come from the immutable PolicySnapshot pinned by each TestRun.
Design coverage does not claim implementation, execution, or evidence coverage.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import RiskCoverageRead, TestRunCoverageRead
from hypertest.application.policy import (
    BASELINE_DIMENSIONS_BY_CATEGORY,
    CoveragePolicy,
    compile_policy,
)
from hypertest.application.services import ConflictError, get_test_run
from hypertest.domain.enums import (
    RequirementLifecycle,
    RiskCategory,
    RiskLifecycle,
    TestCaseLifecycle,
    TestCaseType,
)
from hypertest.domain.models import (
    PolicySnapshot,
    Requirement,
    RequirementRisk,
    Risk,
    RiskTestCase,
    TestCase,
)


class RiskCoverageEvaluator:
    """Evaluate deterministic dimensional rules without Agent claims or stored coverage."""

    version = "risk-design-baseline/v1"
    dimensions_by_category = BASELINE_DIMENSIONS_BY_CATEGORY

    def __init__(self, policy: CoveragePolicy | None = None) -> None:
        self.policy = policy or CoveragePolicy()
        self.version = self.policy.rule_version

    @property
    def effective_policy_hash(self) -> str:
        return self.policy.effective_policy_hash

    def required_dimensions(self, category: RiskCategory) -> set[TestCaseType]:
        return self.policy.required_dimensions(category)

    def evaluate(self, risk: Risk, covered: set[TestCaseType]) -> RiskCoverageRead:
        required = self.required_dimensions(risk.category)
        missing = required - covered
        return RiskCoverageRead(
            risk_id=risk.id,
            risk_key=risk.key,
            required_dimensions=sorted(required),
            covered_dimensions=sorted(covered),
            missing_dimensions=sorted(missing),
            complete=not missing,
        )


def get_coverage_evaluator(snapshot: PolicySnapshot) -> RiskCoverageEvaluator:
    """Compile only the TestRun's pinned policy; newer project policies are irrelevant."""
    return RiskCoverageEvaluator(compile_policy(snapshot.compiled_policy).coverage)


async def get_test_run_coverage(
    session: AsyncSession,
    test_run_id: UUID,
    evaluator: RiskCoverageEvaluator | None = None,
) -> TestRunCoverageRead:
    test_run = await get_test_run(session, test_run_id)
    requirements = list(
        await session.scalars(
            select(Requirement).where(
                Requirement.project_id == test_run.project_id,
                Requirement.source_snapshot_id == test_run.source_snapshot_id,
                Requirement.lifecycle_status == RequirementLifecycle.ACTIVE,
            )
        )
    )
    risks = list(
        await session.scalars(
            select(Risk)
            .where(
                Risk.project_id == test_run.project_id,
                Risk.source_snapshot_id == test_run.source_snapshot_id,
                Risk.lifecycle_status != RiskLifecycle.OBSOLETE,
            )
            .order_by(Risk.key)
        )
    )
    cases = list(
        await session.scalars(
            select(TestCase).where(
                TestCase.project_id == test_run.project_id,
                TestCase.source_snapshot_id == test_run.source_snapshot_id,
                TestCase.lifecycle_status == TestCaseLifecycle.ACTIVE,
            )
        )
    )
    requirement_ids = {item.id for item in requirements}
    risk_ids = {item.id for item in risks}
    case_ids = {item.id for item in cases}
    identified = (
        set(
            await session.scalars(
                select(RequirementRisk.requirement_id).where(
                    RequirementRisk.requirement_id.in_(requirement_ids),
                    RequirementRisk.risk_id.in_(risk_ids),
                )
            )
        )
        if requirement_ids and risk_ids
        else set()
    )
    dimensions: dict[UUID, set[TestCaseType]] = defaultdict(set)
    if risk_ids and case_ids:
        links = await session.execute(
            select(RiskTestCase.risk_id, TestCase.test_type)
            .join(TestCase, TestCase.id == RiskTestCase.test_case_id)
            .where(RiskTestCase.risk_id.in_(risk_ids), TestCase.id.in_(case_ids))
        )
        for risk_id, test_type in links:
            dimensions[risk_id].add(test_type)
    if evaluator is None:
        snapshot = await session.get(PolicySnapshot, test_run.policy_snapshot_id)
        if snapshot is None or snapshot.project_id != test_run.project_id:
            raise ConflictError("test run has no valid immutable policy snapshot")
        evaluator = get_coverage_evaluator(snapshot)
    engine = evaluator
    coverage = [engine.evaluate(risk, dimensions[risk.id]) for risk in risks]
    return TestRunCoverageRead(
        requirement_count=len(requirements),
        risk_count=len(risks),
        test_case_count=len(cases),
        risk_identification_coverage=len(identified) / len(requirements) if requirements else None,
        risk_test_coverage=sum(item.complete for item in coverage) / len(risks) if risks else None,
        risks=coverage,
        rule_version=engine.version,
        effective_policy_hash=engine.effective_policy_hash,
    )
