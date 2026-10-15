"""Deterministic design coverage derived solely from snapshot-scoped canonical state.

This boundary can later receive compiled policy rules without changing Planner or UI.
Design coverage does not claim implementation, execution, or evidence coverage.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import RiskCoverageRead, TestRunCoverageRead
from hypertest.application.services import get_test_run
from hypertest.domain.enums import (
    RequirementLifecycle,
    RiskCategory,
    RiskLifecycle,
    TestCaseLifecycle,
    TestCaseType,
)
from hypertest.domain.models import Requirement, RequirementRisk, Risk, RiskTestCase, TestCase


class RiskCoverageEvaluator:
    """Baseline v1: functional plus a risk-specific dimension, when applicable.

    Categories without a specialized baseline require FUNCTIONAL. Reliability maps
    to RECOVERY. A policy-aware evaluator can replace this instance in the read service.
    """

    version = "risk-design-baseline/v1"
    dimensions_by_category = {
        RiskCategory.BOUNDARY: TestCaseType.BOUNDARY,
        RiskCategory.FAILURE: TestCaseType.FAILURE,
        RiskCategory.CONCURRENCY: TestCaseType.CONCURRENCY,
        RiskCategory.SECURITY: TestCaseType.SECURITY,
        RiskCategory.PERFORMANCE: TestCaseType.PERFORMANCE,
        RiskCategory.RELIABILITY: TestCaseType.RECOVERY,
    }

    def required_dimensions(self, category: RiskCategory) -> set[TestCaseType]:
        required = {TestCaseType.FUNCTIONAL}
        if dimension := self.dimensions_by_category.get(category):
            required.add(dimension)
        return required

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
    engine = evaluator or RiskCoverageEvaluator()
    coverage = [engine.evaluate(risk, dimensions[risk.id]) for risk in risks]
    return TestRunCoverageRead(
        requirement_count=len(requirements),
        risk_count=len(risks),
        test_case_count=len(cases),
        risk_identification_coverage=len(identified) / len(requirements) if requirements else None,
        risk_test_coverage=sum(item.complete for item in coverage) / len(risks) if risks else None,
        risks=coverage,
    )
