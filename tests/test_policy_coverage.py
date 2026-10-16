"""Strict policy compilation and real PostgreSQL policy-pinned coverage integration."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import PolicySnapshotCreate, ProjectCreate, SourceSnapshotCreate
from hypertest.api.schemas import TestRunCreate as RunCreate
from hypertest.application.coverage import RiskCoverageEvaluator, get_test_run_coverage
from hypertest.application.gate import evaluate_gate
from hypertest.application.planner import plan_next_mission
from hypertest.application.policy import InvalidPolicyError, compile_policy
from hypertest.application.services import (
    canonical_json_sha256,
    create_policy_snapshot,
    create_project,
    create_source_snapshot,
    create_test_run,
)
from hypertest.application.verifier import verify_mission_result
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    CaseResult,
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionPurpose,
    ExecutionStatus,
    MissionAttemptStatus,
    MissionType,
    RiskCategory,
    TrustLevel,
    VerdictDecision,
)
from hypertest.domain.enums import TestCaseType as CaseType
from hypertest.domain.models import (
    Evidence,
    ExecutionEvidence,
    ExecutionTestCase,
    Mission,
    MissionAttempt,
    PolicySnapshot,
    Requirement,
    RequirementRisk,
    Risk,
    RiskTestCase,
    utcnow,
)
from hypertest.domain.models import TestCase as CanonicalCase
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.protocol import MissionResultSubmission
from hypertest.runner.artifacts import store_content

STRICT_POLICY = {
    "coverage": {
        "version": "risk-design-policy/v1",
        "default_dimensions": ["FUNCTIONAL", "FAILURE"],
        "by_category": {"FUNCTIONAL": ["RECOVERY"]},
    }
}


@pytest.mark.parametrize("value", [
    None,
    [],
    {"unknown": True},
    {"gate_version": "mvp/v2"},
    {"coverage": None},
    {"coverage": []},
    {"coverage": {"unknown": True}},
    {"coverage": {"version": "risk-design-policy/v2"}},
    {"coverage": {"default_dimensions": "FUNCTIONAL"}},
    {"coverage": {"default_dimensions": [True]}},
    {"coverage": {"default_dimensions": ["FUNCTIONAL", "FUNCTIONAL"]}},
    {"coverage": {"default_dimensions": ["UNRECOGNIZED"]}},
    {"coverage": {"by_category": []}},
    {"coverage": {"by_category": {"UNRECOGNIZED": []}}},
    {"coverage": {"by_category": {"SECURITY": "SECURITY"}}},
    {"coverage": {"by_category": {"SECURITY": ["MISSING_DIMENSION"]}}},
    {"gate": None},
    {"gate": {"unsupported": True}},
    {"gate": {"blocking_finding_severities": "BLOCKER"}},
    {"gate": {"blocking_finding_severities": [None]}},
    {"gate": {"blocking_finding_severities": ["UNRECOGNIZED"]}},
])
def test_policy_rejects_unknown_or_malformed_rules(value: Any) -> None:
    with pytest.raises(InvalidPolicyError):
        compile_policy(value)


def test_effective_coverage_rules_are_normalized_and_functional_cannot_be_waived() -> None:
    first = compile_policy({"coverage": {
        "default_dimensions": ["RECOVERY", "FAILURE"],
        "by_category": {"SECURITY": ["PERFORMANCE", "BOUNDARY"]},
    }})
    reordered = compile_policy({"coverage": {
        "by_category": {"SECURITY": ["BOUNDARY", "PERFORMANCE"]},
        "default_dimensions": ["FAILURE", "RECOVERY", "FUNCTIONAL"],
    }})
    assert first.coverage.effective_policy_hash == reordered.coverage.effective_policy_hash
    assert first.effective_policy_hash == reordered.effective_policy_hash
    assert first.coverage.required_dimensions(RiskCategory.SECURITY) == {
        CaseType.FUNCTIONAL, CaseType.RECOVERY, CaseType.FAILURE,
        CaseType.PERFORMANCE, CaseType.BOUNDARY,
    }
    # Omitted categories retain their specialized baseline, even with global additions.
    assert CaseType.CONCURRENCY in first.coverage.required_dimensions(RiskCategory.CONCURRENCY)
    explicit_specialized_waiver = compile_policy({"coverage": {
        "default_dimensions": [], "by_category": {"SECURITY": []},
    }})
    assert explicit_specialized_waiver.coverage.required_dimensions(RiskCategory.SECURITY) == {
        CaseType.FUNCTIONAL,
    }
    assert explicit_specialized_waiver.coverage.rule_version == "risk-design-policy/v1"
    assert compile_policy({}).coverage.rule_version == RiskCoverageEvaluator.version
    assert compile_policy({"coverage": {"default_dimensions": []}}).coverage.rule_version == (
        "risk-design-baseline/v1"
    )


async def _policy(session: AsyncSession, project_id, value: dict[str, Any]) -> PolicySnapshot:
    return await create_policy_snapshot(session, PolicySnapshotCreate(
        project_id=project_id, policy_version="policy-coverage/v1",
        content_sha256=canonical_json_sha256(value), compiled_policy=value,
    ))


async def _seed(session: AsyncSession) -> tuple[CanonicalRun, CanonicalRun, Risk, CanonicalCase]:
    assert session.bind is not None and session.bind.dialect.name == "postgresql"
    project = await create_project(session, ProjectCreate(
        key=public_key("POLICY"), name="Immutable policy coverage integration",
    ))
    snapshot = await create_source_snapshot(session, project.id, SourceSnapshotCreate(
        repository_url="https://example.invalid/policy.git", commit_sha="a" * 40,
        prd_sha256="b" * 64, configuration_sha256="c" * 64,
    ))
    baseline_policy = await _policy(session, project.id, {})
    stricter_policy = await _policy(session, project.id, STRICT_POLICY)
    baseline = await create_test_run(session, RunCreate(
        project_id=project.id, source_snapshot_id=snapshot.id,
        policy_snapshot_id=baseline_policy.id,
    ))
    stricter = await create_test_run(session, RunCreate(
        project_id=project.id, source_snapshot_id=snapshot.id,
        policy_snapshot_id=stricter_policy.id,
    ))
    requirement = Requirement(
        key=public_key("REQ"), project_id=project.id, source_snapshot_id=snapshot.id,
        title="Create a single order", description="Every request creates one order.",
        requirement_type="FUNCTIONAL", priority="P0", source_type="PRD",
        source_fingerprint="d" * 64, lifecycle_status="ACTIVE", created_by_type="USER",
    )
    risk = Risk(
        key=public_key("RK"), project_id=project.id, source_snapshot_id=snapshot.id,
        risk_fingerprint="e" * 64, category="FUNCTIONAL", title="Duplicate order",
        description="A request may create multiple orders.", severity="HIGH", probability="MEDIUM",
        lifecycle_status="OPEN", created_by_type="USER",
    )
    case = CanonicalCase(
        key=public_key("TC"), project_id=project.id, source_snapshot_id=snapshot.id,
        case_fingerprint="f" * 64, title="Create an order", description="Submit and count orders.",
        test_type="FUNCTIONAL", priority="P0", preconditions=[], expected_result="One order.",
        lifecycle_status="ACTIVE", created_by_type="USER",
    )
    session.add_all([requirement, risk, case])
    await session.flush()
    session.add_all([
        RequirementRisk(requirement_id=requirement.id, risk_id=risk.id),
        RiskTestCase(risk_id=risk.id, test_case_id=case.id),
    ])
    await session.commit()
    for item in (requirement, risk, case):
        await session.refresh(item)
    return baseline, stricter, risk, case


async def _official_pass(session: AsyncSession, run: CanonicalRun, case: CanonicalCase) -> None:
    execution = CanonicalExecution(
        key=public_key("EX"), test_run_id=run.id, idempotency_key=public_key("EXEC"),
        purpose=ExecutionPurpose.OFFICIAL, runner_backend="pytest-local", environment_id="policy-test",
        environment_fingerprint="1" * 64, source_commit="a" * 40,
        execution_spec_sha256="2" * 64, spec={}, status=ExecutionStatus.COMPLETED,
        outcome=ExecutionOutcome.PASS, exit_code=0, finished_at=utcnow(),
    )
    session.add(execution)
    await session.flush()
    session.add(ExecutionTestCase(execution_id=execution.id, test_case_id=case.id, result=CaseResult.PASS))
    for kind in (EvidenceType.EXECUTION_METADATA, EvidenceType.JUNIT):
        content = f"{execution.key}:{kind.value}".encode()
        digest, uri = store_content(content)
        evidence = Evidence(
            key=public_key("EV"), test_run_id=run.id, execution_id=execution.id,
            evidence_type=kind, trust_level=TrustLevel.RUNNER, artifact_uri=uri,
            sha256=digest, size_bytes=len(content), collector="policy-integration-runner",
            source="policy-integration-runner", status=EvidenceStatus.VERIFIED, verified_at=utcnow(),
        )
        session.add(evidence)
        await session.flush()
        session.add(ExecutionEvidence(execution_id=execution.id, evidence_id=evidence.id))
    await session.commit()


@pytest.mark.asyncio
async def test_runs_share_canonical_facts_but_pin_policy_for_planner_coverage_and_gate() -> None:
    async with AsyncSessionLocal() as session:
        baseline, stricter, risk, case = await _seed(session)
        ordinary = await get_test_run_coverage(session, baseline.id)
        strict = await get_test_run_coverage(session, stricter.id)
        assert ordinary.risk_test_coverage == 1
        assert strict.risk_test_coverage == 0
        assert strict.risks[0].missing_dimensions == [CaseType.FAILURE, CaseType.RECOVERY]
        assert strict.rule_version == "risk-design-policy/v1"
        assert ordinary.rule_version == "risk-design-baseline/v1"
        assert ordinary.effective_policy_hash != strict.effective_policy_hash

        planned = await plan_next_mission(session, stricter.id)
        assert planned.mission is not None
        assert planned.mission.mission_type is MissionType.DESIGN_TESTS
        criteria = planned.mission.spec["acceptance_criteria"]
        assert criteria["coverage_rule_version"] == strict.rule_version
        assert criteria["coverage_policy_hash"] == strict.effective_policy_hash
        assert criteria["risk_coverage_gaps"] == [{
            "risk_key": risk.key, "missing_dimensions": ["FAILURE", "RECOVERY"],
        }]
        assert (await plan_next_mission(session, stricter.id)).mission.id == planned.mission.id

        # Future policy creation does not reinterpret either existing run.
        await _policy(session, baseline.project_id, {"coverage": {
            "default_dimensions": ["SECURITY"],
        }})
        assert (await get_test_run_coverage(session, baseline.id)).model_dump() == ordinary.model_dump()
        assert (await get_test_run_coverage(session, stricter.id)).model_dump() == strict.model_dump()
        await _official_pass(session, baseline, case)
        await _official_pass(session, stricter, case)
        assert (await evaluate_gate(session, baseline.id)).decision is VerdictDecision.RELEASE_READY
        blocked = await evaluate_gate(session, stricter.id)
        assert blocked.decision is VerdictDecision.BLOCKED
        assert "required test design dimensions are incomplete" in blocked.reason


async def _submit_dimension(
    session: AsyncSession, mission: Mission, risk: Risk, dimension: CaseType, attempt_no: int,
):
    mission.test_run = await session.get(CanonicalRun, mission.test_run_id)
    attempt = MissionAttempt(
        mission_id=mission.id, attempt_no=attempt_no, status=MissionAttemptStatus.RUNNING,
    )
    session.add(attempt)
    await session.commit()
    result = MissionResultSubmission.model_validate({
        "protocol": "hypertest.tmp/v1alpha1", "mission_id": mission.key,
        "status": "COMPLETED", "summary": "Proposed one test dimension.",
        "proposals": [{
            "proposal_type": "TEST_CASE", "operation": "CREATE",
            "idempotency_key": f"{dimension.value}:v1",
            "object_payload": {
                "risk_keys": [risk.key], "title": f"Check {dimension.value.lower()}",
                "description": f"Verify {dimension.value.lower()} behavior of order creation.",
                "test_type": dimension.value, "priority": "P0", "preconditions": [],
                "expected_result": "The persisted order state remains correct.", "confidence": 0.95,
            },
        }],
    })
    return await verify_mission_result(session, mission, attempt, result)


@pytest.mark.asyncio
async def test_policy_dimensions_drive_verifier_progress_and_incremental_planner_convergence() -> None:
    async with AsyncSessionLocal() as session:
        _, run, risk, _ = await _seed(session)
        mission = (await plan_next_mission(session, run.id)).mission
        assert mission is not None
        unrelated = await _submit_dimension(session, mission, risk, CaseType.SECURITY, 1)
        assert not unrelated.accepted
        assert any(item["code"] == "NO_COVERAGE_PROGRESS" for item in unrelated.errors)
        accepted = await _submit_dimension(session, mission, risk, CaseType.FAILURE, 2)
        assert accepted.accepted
        assert (await get_test_run_coverage(session, run.id)).risks[0].missing_dimensions == [CaseType.RECOVERY]
        remaining = (await plan_next_mission(session, run.id)).mission
        assert remaining is not None and remaining.id != mission.id
        assert remaining.mission_type is MissionType.DESIGN_TESTS
        accepted = await _submit_dimension(session, remaining, risk, CaseType.RECOVERY, 1)
        assert accepted.accepted
        assert (await get_test_run_coverage(session, run.id)).risk_test_coverage == 1
        assert (await plan_next_mission(session, run.id)).mission.mission_type is MissionType.IMPLEMENT_TESTS


@pytest.mark.asyncio
async def test_invalid_policy_is_rejected_before_persisting_snapshot() -> None:
    async with AsyncSessionLocal() as session:
        project = await create_project(session, ProjectCreate(
            key=public_key("POLICY"), name="Invalid policy cannot acquire snapshot semantics",
        ))
        with pytest.raises((InvalidPolicyError, ValueError)):
            await _policy(session, project.id, {"coverage": {"by_category": {"SECURITY": ["TYPO"]}}})
        assert await session.scalar(select(func.count()).select_from(PolicySnapshot).where(
            PolicySnapshot.project_id == project.id,
        )) == 0
