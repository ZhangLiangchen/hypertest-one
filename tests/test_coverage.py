import pytest

from hypertest.application.coverage import RiskCoverageEvaluator
from hypertest.common.ids import public_key, uuid7
from hypertest.domain.enums import RiskCategory
from hypertest.domain.enums import TestCaseType as CaseType
from hypertest.domain.models import Risk


@pytest.mark.parametrize(
    ("category", "specialized_dimension"),
    [
        (RiskCategory.FUNCTIONAL, None),
        (RiskCategory.BOUNDARY, CaseType.BOUNDARY),
        (RiskCategory.FAILURE, CaseType.FAILURE),
        (RiskCategory.CONCURRENCY, CaseType.CONCURRENCY),
        (RiskCategory.SECURITY, CaseType.SECURITY),
        (RiskCategory.PERFORMANCE, CaseType.PERFORMANCE),
        (RiskCategory.RELIABILITY, CaseType.RECOVERY),
        (RiskCategory.DATA, None),
    ],
)
def test_baseline_requires_functional_and_risk_specific_design_dimensions(
    category: RiskCategory, specialized_dimension: CaseType | None
) -> None:
    evaluator = RiskCoverageEvaluator()
    required = {CaseType.FUNCTIONAL}
    if specialized_dimension is not None:
        required.add(specialized_dimension)
    assert evaluator.required_dimensions(category) == required


def test_one_test_case_cannot_satisfy_multidimensional_risk_coverage() -> None:
    risk = Risk(id=uuid7(), key=public_key("RISK"), category=RiskCategory.CONCURRENCY)
    evaluator = RiskCoverageEvaluator()
    partial = evaluator.evaluate(risk, {CaseType.FUNCTIONAL, CaseType.SECURITY})
    assert partial.risk_id == risk.id
    assert partial.risk_key == risk.key
    assert not partial.complete
    assert partial.missing_dimensions == [CaseType.CONCURRENCY]
    complete = evaluator.evaluate(risk, {CaseType.CONCURRENCY, CaseType.FUNCTIONAL})
    assert complete.complete
    assert complete.missing_dimensions == []


def test_policy_can_extend_dimensions_without_changing_planner() -> None:
    class StricterCoverageEvaluator(RiskCoverageEvaluator):
        def required_dimensions(self, category: RiskCategory) -> set[CaseType]:
            return super().required_dimensions(category) | {CaseType.FAILURE}

    risk = Risk(id=uuid7(), key=public_key("RISK"), category=RiskCategory.SECURITY)
    evaluator = StricterCoverageEvaluator()
    covered = {CaseType.FUNCTIONAL, CaseType.SECURITY}
    assert not evaluator.evaluate(risk, covered).complete
    assert evaluator.evaluate(risk, covered).missing_dimensions == [CaseType.FAILURE]
    assert evaluator.evaluate(risk, covered | {CaseType.FAILURE}).complete
