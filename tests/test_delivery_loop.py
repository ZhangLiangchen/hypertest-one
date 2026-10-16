from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_test_design import (
    ProposalHarness,
    case_proposal,
    requirement_proposal,
    risk_proposal,
)

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import MissionCreate, ProjectCreate
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.executions import execute_test_run, read_evidence_content
from hypertest.application.findings import transition_finding
from hypertest.application.gate import evaluate_gate
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import execute_mission
from hypertest.application.services import create_mission, create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    CaseResult,
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionStatus,
    FindingStatus,
    ImplementationValidationStatus,
    MissionAttemptStatus,
    MissionType,
    ProposalStatus,
    TrustLevel,
    VerdictDecision,
    VerdictStatus,
)
from hypertest.domain.models import (
    AuditEvent,
    Evidence,
    ExecutionEvidence,
    ExecutionTestCase,
    Finding,
    FindingEvidence,
    ImplementationTestCase,
    OutboxEvent,
    Requirement,
    Risk,
    VerdictEvidence,
    VerdictFinding,
)
from hypertest.domain.models import (
    TestCase as CanonicalCase,
)
from hypertest.domain.models import (
    TestImplementation as CanonicalImplementation,
)
from hypertest.domain.models import (
    TestRun as CanonicalRun,
)

PRD_TEXT = "Checkout submits sharing an idempotency key must create exactly one order."
GENERATED_TEST = """from concurrent.futures import ThreadPoolExecutor
from checkout import order_count, submit_order

def test_checkout_idempotency():
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(submit_order, ["same-checkout"] * 16))
    assert results == ["same-checkout"] * 16
    assert order_count() == 1
"""


def configure_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, broken: bool = False
) -> tuple[Path, str, str]:
    """A real, clean source commit; agent-generated tests are separate stored artifacts."""
    settings = get_settings()
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "runner_allow_local", True)
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    source = tmp_path / "repo"
    source.mkdir()
    insertion = (
        "        orders.append(key)"
        if broken
        else ("        if key not in orders:\n            orders.append(key)")
    )
    (source / "checkout.py").write_text(
        "from threading import Lock\n"
        "orders = []\n"
        "lock = Lock()\n\n"
        "def submit_order(key):\n"
        "    with lock:\n"
        f"{insertion}\n"
        "    return key\n\n"
        "def order_count():\n"
        "    return len(orders)\n"
    )
    repository_url = "https://example.invalid/hypertest-delivery.git"
    for args in (
        ["init", "--initial-branch=main"],
        ["config", "user.name", "HyperTest Integration"],
        ["config", "user.email", "integration@example.invalid"],
        ["remote", "add", "origin", repository_url],
        ["add", "checkout.py"],
        ["commit", "-m", "Add checkout source snapshot"],
    ):
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, commit, repository_url


@dataclass
class DeliveryState:
    run: CanonicalRun
    requirement: Requirement
    risk: Risk
    cases: list[CanonicalCase]
    implementation: CanonicalImplementation


async def prepare_delivery(
    session: AsyncSession, source: Path, commit: str, repository_url: str
) -> DeliveryState:
    project = await create_project(
        session,
        ProjectCreate(key=f"DELIVERY_{public_key('IT')[-12:]}", name="Delivery loop integration"),
    )
    run = await bootstrap_run(
        session,
        project.id,
        RunBootstrap(repository_url=repository_url, commit_sha=commit, prd_text=PRD_TEXT),
    )
    requirements_plan = await plan_next_mission(session, run.id)
    assert requirements_plan.mission is not None
    assert requirements_plan.mission.mission_type is MissionType.ANALYZE_REQUIREMENTS
    requirement_harness = ProposalHarness([requirement_proposal()])
    requirements = await execute_mission(
        session,
        requirements_plan.mission.id,
        workspace=str(source),
        harness=requirement_harness,
    )
    assert requirement_harness.contract is not None
    assert requirement_harness.contract["context"]["prd_text"] == PRD_TEXT
    assert requirement_harness.contract["context"]["commit_sha"] == commit
    requirement = requirements.requirements[0]
    risks_plan = await plan_next_mission(session, run.id)
    assert risks_plan.mission is not None
    assert risks_plan.mission.mission_type is MissionType.ANALYZE_RISKS
    risks = await execute_mission(
        session,
        risks_plan.mission.id,
        workspace=str(source),
        harness=ProposalHarness([risk_proposal(requirement.key)]),
    )
    risk = risks.risks[0]
    design_plan = await plan_next_mission(session, run.id)
    assert design_plan.mission is not None
    assert design_plan.mission.mission_type is MissionType.DESIGN_TESTS
    designed = await execute_mission(
        session,
        design_plan.mission.id,
        workspace=str(source),
        harness=ProposalHarness(
            [
                case_proposal(risk.key),
                case_proposal(risk.key, proposal_key="concurrent-case", test_type="CONCURRENCY"),
            ]
        ),
    )
    assert len(designed.test_cases) == 2
    implementation_plan = await plan_next_mission(session, run.id)
    assert implementation_plan.reason == "IMPLEMENTATION_COVERAGE_GAP"
    assert implementation_plan.mission is not None
    assert implementation_plan.mission.mission_type is MissionType.IMPLEMENT_TESTS
    repeated = await plan_next_mission(session, run.id)
    assert repeated.mission is not None
    assert repeated.mission.id == implementation_plan.mission.id
    implementation = await execute_mission(
        session,
        implementation_plan.mission.id,
        workspace=str(source),
        harness=ProposalHarness(
            [
                {
                    "proposal_type": "TEST_IMPLEMENTATION",
                    "operation": "CREATE",
                    "idempotency_key": "checkout.idempotency.pytest:v1",
                    "object_payload": {
                        "test_case_keys": [case.key for case in designed.test_cases],
                        "repository_url": repository_url,
                        "commit_sha": commit,
                        "file_path": "tests/test_checkout_generated.py",
                        "symbol": "test_checkout_idempotency",
                        "framework": "pytest",
                        "language": "python",
                        "code": GENERATED_TEST,
                    },
                }
            ]
        ),
    )
    assert implementation.attempt.status is MissionAttemptStatus.ACCEPTED
    assert len(implementation.implementations) == 1
    asset = implementation.implementations[0]
    assert asset.validation_status is ImplementationValidationStatus.PENDING
    assert asset.source_sha256 == hashlib.sha256(GENERATED_TEST.encode()).hexdigest()
    assert asset.artifact_uri == f"sha256:{asset.source_sha256}"
    assert not (source / asset.file_path).exists()
    for case in designed.test_cases:
        assert await session.get(ImplementationTestCase, (asset.id, case.id)) is not None
    next_plan = await plan_next_mission(session, run.id)
    assert next_plan.reason == "EXECUTION_REQUIRED"
    assert next_plan.mission is None
    return DeliveryState(run, requirement, risk, designed.test_cases, asset)


def finding_proposal(state: DeliveryState, evidence_keys: list[str]) -> dict[str, Any]:
    return {
        "proposal_type": "FINDING",
        "operation": "CREATE",
        "idempotency_key": "checkout.duplicate-orders:diagnosis:v1",
        "object_payload": {
            "classification": "PRODUCT_DEFECT",
            "severity": "CRITICAL",
            "title": "Concurrent submissions create duplicate checkout orders",
            "description": "The observed checkout order count exceeds one for a repeated idempotency key.",
            "root_cause": "Order insertion does not check whether the key is already persisted.",
            "confidence": 0.99,
            "evidence_keys": evidence_keys,
            "test_case_keys": [case.key for case in state.cases],
            "requirement_keys": [state.requirement.key],
            "risk_keys": [state.risk.key],
        },
    }


async def diagnose_failure(session: AsyncSession, state: DeliveryState, source: Path) -> Finding:
    plan = await plan_next_mission(session, state.run.id)
    assert plan.reason == "FAILURE_DIAGNOSIS_REQUIRED"
    assert plan.mission is not None
    assert plan.mission.mission_type is MissionType.DIAGNOSE_FAILURE
    evidence_keys = list(
        await session.scalars(
            select(Evidence.key).where(
                Evidence.test_run_id == state.run.id,
                Evidence.evidence_type.in_([EvidenceType.JUNIT, EvidenceType.EXECUTION_METADATA]),
            )
        )
    )
    assert len(evidence_keys) == 2
    result = await execute_mission(
        session,
        plan.mission.id,
        workspace=str(source),
        harness=ProposalHarness([finding_proposal(state, evidence_keys)]),
    )
    assert result.attempt.status is MissionAttemptStatus.ACCEPTED
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.status is FindingStatus.NEW
    assert (
        await session.scalar(
            select(func.count())
            .select_from(FindingEvidence)
            .where(
                FindingEvidence.finding_id == finding.id,
            )
        )
        == 2
    )
    return finding


@pytest.mark.asyncio
async def test_canonical_delivery_loop_runs_real_tests_and_finalizes_release_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        assert session.bind is not None and session.bind.dialect.name == "postgresql"
        state = await prepare_delivery(session, source, commit, repository_url)
        before_execution = await evaluate_gate(session, state.run.id, finalize=False)
        assert before_execution.decision is VerdictDecision.BLOCKED
        assert before_execution.status is VerdictStatus.DRAFT
        execution = await execute_test_run(
            session,
            state.run.id,
            str(source),
            backend="local",
            idempotency_key="official-checkout:v1",
        )
        assert execution.status is ExecutionStatus.COMPLETED
        assert execution.outcome is ExecutionOutcome.PASS
        assert execution.exit_code == 0
        assert execution.source_commit == commit
        replay = await execute_test_run(
            session,
            state.run.id,
            str(source),
            backend="local",
            idempotency_key="official-checkout:v1",
        )
        assert replay.id == execution.id
        await session.refresh(state.implementation)
        assert state.implementation.validation_status is ImplementationValidationStatus.VALIDATED
        results = list(
            await session.scalars(
                select(ExecutionTestCase).where(
                    ExecutionTestCase.execution_id == execution.id,
                )
            )
        )
        assert len(results) == len(state.cases)
        assert {result.result for result in results} == {CaseResult.PASS}
        evidence = list(
            await session.scalars(select(Evidence).where(Evidence.test_run_id == state.run.id))
        )
        assert {item.evidence_type for item in evidence} == {
            EvidenceType.JUNIT,
            EvidenceType.STDOUT,
            EvidenceType.STDERR,
            EvidenceType.EXECUTION_METADATA,
        }
        for item in evidence:
            assert item.status is EvidenceStatus.VERIFIED
            assert item.trust_level is TrustLevel.RUNNER
            assert hashlib.sha256(read_evidence_content(item)).hexdigest() == item.sha256
            assert await session.get(ExecutionEvidence, (execution.id, item.id)) is not None
        final_plan = await plan_next_mission(session, state.run.id)
        assert final_plan.reason == "VERDICT_REQUIRED"
        assert final_plan.mission is None
        verdict = await evaluate_gate(session, state.run.id)
        assert verdict.status is VerdictStatus.FINAL
        assert verdict.decision is VerdictDecision.RELEASE_READY
        assert len(verdict.state_snapshot_hash) == 64
        assert len(verdict.evidence_manifest_sha256) == 64
        assert verdict.finalized_at is not None
        for item in evidence:
            assert await session.get(VerdictEvidence, (verdict.id, item.id)) is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.entity_id == execution.id,
                    AuditEvent.action == "execution.completed",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.aggregate_id == verdict.id,
                    OutboxEvent.event_type == "verdict.finalized",
                )
            )
            == 1
        )
        repeated_verdict = await evaluate_gate(session, state.run.id)
        assert repeated_verdict.id == verdict.id


@pytest.mark.asyncio
async def test_actual_failure_produces_diagnosis_finding_and_blocked_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch, broken=True)
    async with AsyncSessionLocal() as session:
        state = await prepare_delivery(session, source, commit, repository_url)
        execution = await execute_test_run(
            session,
            state.run.id,
            str(source),
            backend="local",
            idempotency_key="official-failure:v1",
        )
        assert execution.status is ExecutionStatus.COMPLETED
        assert execution.outcome is ExecutionOutcome.FAIL
        assert execution.exit_code == 1
        finding = await diagnose_failure(session, state, source)
        await transition_finding(
            session,
            finding.id,
            FindingStatus.TRIAGED,
            reason="Review actual failing checkout evidence",
            expected_row_version=finding.row_version,
        )
        await transition_finding(
            session,
            finding.id,
            FindingStatus.CONFIRMED,
            reason="Verified JUnit and source show a repeatable product defect",
            expected_row_version=finding.row_version,
        )
        assert finding.status is FindingStatus.CONFIRMED
        verdict = await evaluate_gate(session, state.run.id)
        assert verdict.status is VerdictStatus.FINAL
        assert verdict.decision is VerdictDecision.RELEASE_BLOCKED
        assert finding.key in verdict.reason
        assert await session.get(VerdictFinding, (verdict.id, finding.id)) is not None
        for action in ("finding.accepted", "finding.triaged", "finding.confirmed"):
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.entity_id == finding.id,
                        AuditEvent.action == action,
                    )
                )
                == 1
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["deduplicate", "existing_conflict", "batch_conflict", "shared_symbols"]
)
async def test_implementation_rechecks_preserve_canonical_source_and_shared_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        state = await prepare_delivery(session, source, commit, repository_url)
        mission = await create_mission(
            session,
            state.run.id,
            MissionCreate(
                mission_type=MissionType.IMPLEMENT_TESTS,
                objective="Validate implementation identity and consistent generated module contents",
                spec={},
                idempotency_key=f"implementation-recheck:{mode}",
                created_by="user",
            ),
        )
        payload = {
            "proposal_type": "TEST_IMPLEMENTATION",
            "operation": "CREATE",
            "idempotency_key": "module-proposal:first",
            "object_payload": {
                "test_case_keys": [case.key for case in state.cases],
                "repository_url": repository_url,
                "commit_sha": commit,
                "file_path": state.implementation.file_path,
                "symbol": state.implementation.symbol,
                "code": GENERATED_TEST,
            },
        }
        proposals = [payload]
        if mode == "existing_conflict":
            payload["object_payload"]["code"] = GENERATED_TEST + "\n# conflicting source bytes\n"
        elif mode in {"batch_conflict", "shared_symbols"}:
            module = "def test_first():\n    assert True\n\ndef test_second():\n    assert True\n"
            proposals = [
                {
                    **payload,
                    "idempotency_key": f"module-proposal:{index}",
                    "object_payload": {
                        **payload["object_payload"],
                        "file_path": "tests/test_shared_generated.py",
                        "test_case_keys": [state.cases[index].key],
                        "symbol": symbol,
                        "code": module
                        + (
                            "\n# conflicting source bytes\n"
                            if mode == "batch_conflict" and index
                            else ""
                        ),
                    },
                }
                for index, symbol in enumerate(("test_first", "test_second"))
            ]
        result = await execute_mission(
            session,
            mission.id,
            str(source),
            harness=ProposalHarness(proposals),
        )
        if mode in {"existing_conflict", "batch_conflict"}:
            assert result.attempt.status is MissionAttemptStatus.REJECTED
            assert result.implementations == []
            assert {proposal.status for proposal in result.proposals} == {ProposalStatus.REJECTED}
            assert any(
                error["code"] == "CONFLICTING_IMPLEMENTATION_SOURCE"
                for proposal in result.proposals
                for error in proposal.validation_errors or []
            )
            expected_count = 1
        else:
            assert result.attempt.status is MissionAttemptStatus.ACCEPTED
            if mode == "deduplicate":
                assert result.implementations[0].id == state.implementation.id
                expected_count = 1
            else:
                assert len({item.id for item in result.implementations}) == 2
                assert len({item.source_sha256 for item in result.implementations}) == 1
                assert {item.symbol for item in result.implementations} == {
                    "test_first",
                    "test_second",
                }
                expected_count = 3
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CanonicalImplementation)
                .where(
                    CanonicalImplementation.source_snapshot_id == state.run.source_snapshot_id,
                )
            )
            == expected_count
        )
        assert (
            state.implementation.source_sha256
            == hashlib.sha256(GENERATED_TEST.encode()).hexdigest()
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.entity_id == state.implementation.id,
                    AuditEvent.action == "implementation.accepted",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ExecutionTestCase)
                .where(
                    ExecutionTestCase.test_case_id.in_([case.id for case in state.cases]),
                )
            )
            == 0
        )
