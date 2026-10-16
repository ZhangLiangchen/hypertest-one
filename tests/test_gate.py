"""Real PostgreSQL coverage of finding governance and deterministic release decisions."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import PolicySnapshotCreate, ProjectCreate, SourceSnapshotCreate
from hypertest.api.schemas import TestRunCreate as RunCreate
from hypertest.application.findings import transition_finding, verify_findings
from hypertest.application.gate import evaluate_gate
from hypertest.application.services import (
    ConflictError,
    create_policy_snapshot,
    create_project,
    create_source_snapshot,
    create_test_run,
)
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    CaseResult,
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionPurpose,
    ExecutionStatus,
    FindingResolution,
    FindingStatus,
    MissionType,
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
    FindingRequirement,
    FindingRisk,
    FindingTestCase,
    Mission,
    MissionAttempt,
    OutboxEvent,
    Requirement,
    RequirementRisk,
    Risk,
    RiskTestCase,
    Verdict,
    VerdictEvidence,
    VerdictFinding,
    utcnow,
)
from hypertest.domain.models import TestCase as CanonicalCase
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.protocol import MissionResultSubmission
from hypertest.runner.artifacts import artifact_root, store_content


async def _seed(session: AsyncSession) -> tuple[CanonicalRun, Requirement, Risk, CanonicalCase]:
    assert session.bind is not None and session.bind.dialect.name == "postgresql"
    suffix = public_key("GATE")
    project = await create_project(session, ProjectCreate(key=suffix, name="Quality gate integration"))
    snapshot = await create_source_snapshot(session, project.id, SourceSnapshotCreate(
        repository_url="https://example.invalid/gate.git", commit_sha="a" * 40,
        prd_sha256="b" * 64, configuration_sha256="c" * 64,
    ))
    policy = await create_policy_snapshot(session, PolicySnapshotCreate(
        project_id=project.id, policy_version="gate-baseline/v1", content_sha256="d" * 64,
    ))
    run = await create_test_run(session, RunCreate(project_id=project.id,
        source_snapshot_id=snapshot.id, policy_snapshot_id=policy.id))
    requirement = Requirement(key=public_key("REQ"), project_id=project.id,
        source_snapshot_id=snapshot.id, title="A checkout creates one order",
        description="One order must be persisted.", requirement_type="FUNCTIONAL", priority="P0",
        source_type="PRD", source_fingerprint="e" * 64, lifecycle_status="ACTIVE", created_by_type="USER")
    risk = Risk(key=public_key("RK"), project_id=project.id, source_snapshot_id=snapshot.id,
        risk_fingerprint="f" * 64, category="FUNCTIONAL", title="Duplicate order", description="Checkout may duplicate an order.",
        severity="HIGH", probability="MEDIUM", lifecycle_status="OPEN", created_by_type="USER")
    case = CanonicalCase(key=public_key("TC"), project_id=project.id,
        source_snapshot_id=snapshot.id, case_fingerprint="1" * 64,
        title="Submit checkout", description="Submit once and count persisted orders.", test_type="FUNCTIONAL",
        priority="P1", preconditions=[], expected_result="Exactly one order.", lifecycle_status="ACTIVE", created_by_type="USER")
    session.add_all([requirement, risk, case])
    await session.flush()
    session.add_all([RequirementRisk(requirement_id=requirement.id, risk_id=risk.id),
                     RiskTestCase(risk_id=risk.id, test_case_id=case.id)])
    await session.commit()
    return run, requirement, risk, case


async def _official(
    session: AsyncSession, run: CanonicalRun, case: CanonicalCase, *,
    result: CaseResult = CaseResult.PASS, trust: TrustLevel = TrustLevel.RUNNER,
    commit: str = "a" * 40, include_junit: bool = True,
    evidence_status: EvidenceStatus = EvidenceStatus.VERIFIED,
    purpose: ExecutionPurpose = ExecutionPurpose.OFFICIAL,
) -> tuple[CanonicalExecution, list[Evidence]]:
    execution = CanonicalExecution(key=public_key("EX"), test_run_id=run.id,
        idempotency_key=public_key("EXEC"), purpose=purpose,
        runner_backend="pytest-local", environment_id="integration", environment_fingerprint="2" * 64,
        source_commit=commit, execution_spec_sha256="3" * 64, spec={}, status=ExecutionStatus.COMPLETED,
        outcome=ExecutionOutcome.FAIL if result is CaseResult.FAIL else ExecutionOutcome.PASS,
        exit_code=1 if result is CaseResult.FAIL else 0, finished_at=utcnow())
    session.add(execution)
    await session.flush()
    session.add(ExecutionTestCase(execution_id=execution.id, test_case_id=case.id, result=result))
    evidence = []
    for kind in [EvidenceType.EXECUTION_METADATA, *([EvidenceType.JUNIT] if include_junit else [])]:
        content = f"{execution.key}:{kind.value}".encode()
        sha256, uri = store_content(content)
        item = Evidence(key=public_key("EV"), test_run_id=run.id, execution_id=execution.id,
            evidence_type=kind, trust_level=trust, artifact_uri=uri, sha256=sha256,
            size_bytes=len(content), collector="integration-runner", source="integration-runner",
            status=evidence_status, verified_at=utcnow() if evidence_status is EvidenceStatus.VERIFIED else None)
        session.add(item)
        await session.flush()
        session.add(ExecutionEvidence(execution_id=execution.id, evidence_id=item.id))
        evidence.append(item)
    await session.commit()
    return execution, evidence


async def _proposal(
    session: AsyncSession, run: CanonicalRun, evidence: list[str], *,
    cases: list[str], requirements: list[str], risks: list[str], title: str = "Duplicate order observed",
    description: str = "Checkout creates two orders for the same request.",
    additional_payload: dict | None = None,
):
    mission = Mission(key=public_key("MIS"), test_run_id=run.id, mission_type=MissionType.DIAGNOSE_FAILURE,
        objective="Explain official execution failure", spec={}, spec_sha256="4" * 64,
        status="RUNNING", idempotency_key=public_key("DIAG"), created_by="planner")
    mission.test_run = run
    session.add(mission)
    await session.flush()
    attempt = MissionAttempt(mission_id=mission.id, attempt_no=1, status="RUNNING")
    session.add(attempt)
    await session.commit()
    payload = {"classification": "PRODUCT_DEFECT", "severity": "BLOCKER", "title": title,
               "description": description, "confidence": 0.96, "evidence_keys": evidence,
               "test_case_keys": cases, "requirement_keys": requirements, "risk_keys": risks,
               **(additional_payload or {})}
    result = MissionResultSubmission.model_validate({"protocol": "hypertest.tmp/v1alpha1",
        "mission_id": mission.key, "status": "COMPLETED", "summary": "Finding proposed for verification",
        "proposals": [{"proposal_type": "FINDING", "operation": "CREATE",
                       "idempotency_key": "diagnosis:v1", "object_payload": payload}]})
    return await verify_findings(session, mission, attempt, result)


@pytest.mark.asyncio
async def test_gate_is_append_only_audited_and_idempotent_over_semantic_state() -> None:
    async with AsyncSessionLocal() as session:
        run, requirement, _, case = await _seed(session)
        await _official(session, run, case)
        first = await evaluate_gate(session, run.id)
        assert first.decision is VerdictDecision.RELEASE_READY
        assert first.status is VerdictStatus.FINAL
        assert first.sequence_no == 1
        assert len(first.state_snapshot_hash) == len(first.evidence_manifest_sha256) == 64
        assert (await evaluate_gate(session, run.id)).id == first.id
        requirement.updated_at = utcnow() + timedelta(hours=1)
        await session.commit()
        assert (await evaluate_gate(session, run.id)).id == first.id
        requirement.description = "Exactly one durable order must be persisted."
        await session.commit()
        second = await evaluate_gate(session, run.id)
        assert second.id != first.id and second.sequence_no == 2
        assert second.state_snapshot_hash != first.state_snapshot_hash
        assert await session.scalar(select(func.count()).select_from(VerdictEvidence).where(VerdictEvidence.verdict_id == second.id)) == 2
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == second.id, AuditEvent.action == "verdict.finalized")) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == second.id, OutboxEvent.event_type == "verdict.finalized")) == 1
        first.reason = "Rewrite history"
        with pytest.raises(DBAPIError, match="immutable|append.only"):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["missing", "skipped", "agent", "wrong_commit", "unverified", "no_junit", "exploratory", "error"])
async def test_gate_never_passes_without_every_active_case_and_official_evidence(condition: str) -> None:
    async with AsyncSessionLocal() as session:
        run, _, _, case = await _seed(session)
        if condition != "missing":
            await _official(session, run, case,
                result=CaseResult.SKIPPED if condition == "skipped" else CaseResult.ERROR if condition == "error" else CaseResult.PASS,
                trust=TrustLevel.AGENT_REPORTED if condition == "agent" else TrustLevel.RUNNER,
                commit="9" * 40 if condition == "wrong_commit" else "a" * 40,
                include_junit=condition != "no_junit",
                evidence_status=EvidenceStatus.COLLECTED if condition == "unverified" else EvidenceStatus.VERIFIED,
                purpose=ExecutionPurpose.EXPLORATORY if condition == "exploratory" else ExecutionPurpose.OFFICIAL)
        verdict = await evaluate_gate(session, run.id)
        assert verdict.decision is VerdictDecision.BLOCKED
        assert verdict.reason


@pytest.mark.asyncio
async def test_gate_uses_latest_official_attempt_and_blocks_empty_canonical_state() -> None:
    async with AsyncSessionLocal() as session:
        run, _, _, case = await _seed(session)
        await _official(session, run, case)
        passed = await evaluate_gate(session, run.id)
        await _official(session, run, case, result=CaseResult.FAIL)
        failed = await evaluate_gate(session, run.id)
        assert failed.decision is VerdictDecision.RELEASE_BLOCKED
        assert failed.sequence_no == passed.sequence_no + 1
        assert (await session.get(Verdict, passed.id)).decision is VerdictDecision.RELEASE_READY
        case.lifecycle_status = "DEPRECATED"
        await session.commit()
        assert (await evaluate_gate(session, run.id)).decision is VerdictDecision.BLOCKED


@pytest.mark.asyncio
async def test_finding_proposals_deduplicate_link_canonical_state_and_require_controlled_confirmation() -> None:
    async with AsyncSessionLocal() as session:
        run, requirement, risk, case = await _seed(session)
        _, evidence = await _official(session, run, case)
        ready = await evaluate_gate(session, run.id)
        run_id, ready_hash = run.id, ready.state_snapshot_hash
        first = await _proposal(session, run, [evidence[0].key], cases=[case.key], requirements=[requirement.key], risks=[risk.key])
        assert first.accepted and len(first.findings) == 1
        finding = first.findings[0]
        finding_id = finding.id
        assert finding.status is FindingStatus.NEW
        assert await session.get(FindingEvidence, (finding.id, evidence[0].id)) is not None
        assert await session.get(FindingTestCase, (finding.id, case.id)) is not None
        assert await session.get(FindingRequirement, (finding.id, requirement.id)) is not None
        assert await session.get(FindingRisk, (finding.id, risk.id)) is not None
        duplicate = await _proposal(session, run, [evidence[0].key], cases=[case.key], requirements=[requirement.key], risks=[risk.key], title="Same defect, different display title", description="Checkout  creates two orders\nfor the same request.")
        assert duplicate.accepted and duplicate.findings[0].id == finding.id
        assert await session.scalar(select(func.count()).select_from(Finding).where(Finding.test_run_id == run.id)) == 1
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == finding.id, AuditEvent.action == "finding.accepted")) == 1
        with pytest.raises(ConflictError, match="invalid finding transition"):
            await transition_finding(session, finding_id, FindingStatus.CONFIRMED, reason="Review")
        await session.rollback()
        finding = await transition_finding(session, finding_id, FindingStatus.TRIAGED, reason="Reviewed failure", expected_row_version=1)
        with pytest.raises(ConflictError, match="changed"):
            await transition_finding(session, finding_id, FindingStatus.CONFIRMED, reason="Confirm", expected_row_version=1)
        await session.rollback()
        finding = await transition_finding(session, finding_id, FindingStatus.CONFIRMED, reason="Runner evidence confirms defect", expected_row_version=2)
        blocked = await evaluate_gate(session, run_id)
        assert blocked.decision is VerdictDecision.RELEASE_BLOCKED
        assert blocked.state_snapshot_hash != ready_hash
        assert await session.get(VerdictFinding, (blocked.id, finding.id)) is not None
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == finding.id, OutboxEvent.event_type == "finding.confirmed")) == 1
        with pytest.raises(ConflictError, match="requires a resolution"):
            await transition_finding(session, finding_id, FindingStatus.RESOLVED, reason="Resolved")
        await session.rollback()
        await transition_finding(session, finding_id, FindingStatus.RESOLVED, FindingResolution.FIXED, reason="Verified fix")
        assert (await evaluate_gate(session, run_id)).decision is VerdictDecision.RELEASE_READY


@pytest.mark.asyncio
async def test_agent_evidence_cannot_confirm_product_defect_or_set_canonical_status() -> None:
    async with AsyncSessionLocal() as session:
        run, requirement, risk, case = await _seed(session)
        _, evidence = await _official(session, run, case, trust=TrustLevel.AGENT_REPORTED)
        rejected = await _proposal(session, run, [evidence[0].key], cases=[case.key], requirements=[requirement.key], risks=[risk.key], additional_payload={"status": "CONFIRMED"})
        assert not rejected.accepted
        assert rejected.errors[0]["code"] == "INVALID_FINDING"
        assert await session.scalar(select(func.count()).select_from(Finding).where(Finding.test_run_id == run.id)) == 0
        proposal = await _proposal(session, run, [evidence[0].key], cases=[case.key], requirements=[], risks=[])
        assert proposal.accepted
        finding = await transition_finding(session, proposal.findings[0].id, FindingStatus.TRIAGED, reason="Needs independent verification")
        with pytest.raises(ConflictError, match="trusted verified"):
            await transition_finding(session, finding.id, FindingStatus.CONFIRMED, reason="Agent claims defect")
        await session.rollback()


@pytest.mark.asyncio
async def test_findings_reject_foreign_snapshot_or_unverified_evidence_atomically() -> None:
    async with AsyncSessionLocal() as session:
        run, requirement, risk, case = await _seed(session)
        foreign_run, _, _, foreign_case = await _seed(session)
        _, foreign_evidence = await _official(session, foreign_run, foreign_case)
        rejected = await _proposal(session, run, [foreign_evidence[0].key], cases=[case.key], requirements=[requirement.key], risks=[risk.key])
        assert not rejected.accepted
        assert rejected.errors[0]["code"] == "UNKNOWN_EVIDENCE"
        _, evidence = await _official(session, run, case, evidence_status=EvidenceStatus.COLLECTED)
        rejected = await _proposal(session, run, [evidence[0].key], cases=[foreign_case.key], requirements=[], risks=[])
        assert not rejected.accepted
        assert {item["code"] for item in rejected.errors} == {"UNKNOWN_TEST_CASE", "UNVERIFIED_EVIDENCE"}
        assert await session.scalar(select(func.count()).select_from(Finding).where(Finding.test_run_id == run.id)) == 0


@pytest.mark.asyncio
async def test_concurrent_gate_evaluation_reuses_same_final_verdict() -> None:
    async with AsyncSessionLocal() as session:
        run, _, _, case = await _seed(session)
        await _official(session, run, case)
        run_id: UUID = run.id

    async def evaluate() -> UUID:
        async with AsyncSessionLocal() as concurrent:
            return (await evaluate_gate(concurrent, run_id)).id

    first, second = await asyncio.gather(evaluate(), evaluate())
    assert first == second


@pytest.mark.asyncio
async def test_missing_verified_artifact_blocks_release_and_cannot_reuse_prior_verdict() -> None:
    async with AsyncSessionLocal() as session:
        run, _, _, case = await _seed(session)
        _, evidence = await _official(session, run, case)
        first = await evaluate_gate(session, run.id)
        assert first.decision is VerdictDecision.RELEASE_READY
        junit = next(item for item in evidence if item.evidence_type is EvidenceType.JUNIT)
        (artifact_root() / "sha256" / junit.sha256[:2] / junit.sha256).unlink()
        second = await evaluate_gate(session, run.id)
        assert second.id != first.id
        assert second.state_snapshot_hash != first.state_snapshot_hash
        assert second.decision is VerdictDecision.BLOCKED
        assert second.sequence_no == first.sequence_no + 1
        assert (await evaluate_gate(session, run.id)).id == second.id


@pytest.mark.asyncio
async def test_finding_rejects_evidence_from_different_source_commit() -> None:
    async with AsyncSessionLocal() as session:
        run, requirement, risk, case = await _seed(session)
        _, evidence = await _official(session, run, case, commit="9" * 40)
        result = await _proposal(session, run, [evidence[0].key], cases=[case.key],
                                 requirements=[requirement.key], risks=[risk.key])
        assert not result.accepted
        assert result.errors[0]["code"] == "EVIDENCE_SNAPSHOT_MISMATCH"


@pytest.mark.asyncio
async def test_pending_official_rerun_blocks_previous_successful_case_results() -> None:
    async with AsyncSessionLocal() as session:
        run, _, _, case = await _seed(session)
        await _official(session, run, case)
        passed = await evaluate_gate(session, run.id)
        pending = CanonicalExecution(key=public_key("EX"), test_run_id=run.id,
            idempotency_key=public_key("PENDING"), purpose=ExecutionPurpose.OFFICIAL,
            runner_backend="docker", environment_id="integration", environment_fingerprint="2" * 64,
            source_commit="a" * 40, execution_spec_sha256="3" * 64, spec={},
            status=ExecutionStatus.RUNNING, started_at=utcnow())
        session.add(pending)
        await session.flush()
        session.add(ExecutionTestCase(execution_id=pending.id, test_case_id=case.id,
                                     result=CaseResult.NOT_RUN))
        await session.commit()
        current = await evaluate_gate(session, run.id)
        assert current.decision is VerdictDecision.BLOCKED
        assert "RUNNING" in current.reason
        assert current.sequence_no == passed.sequence_no + 1


@pytest.mark.asyncio
async def test_product_defect_confirmation_rechecks_supporting_artifact_integrity() -> None:
    async with AsyncSessionLocal() as session:
        run, requirement, risk, case = await _seed(session)
        _, evidence = await _official(session, run, case)
        result = await _proposal(session, run, [evidence[0].key], cases=[case.key],
                                 requirements=[requirement.key], risks=[risk.key])
        finding_id = result.findings[0].id
        await transition_finding(session, finding_id, FindingStatus.TRIAGED, reason="Inspect evidence")
        item = evidence[0]
        (artifact_root() / "sha256" / item.sha256[:2] / item.sha256).unlink()
        with pytest.raises(ConflictError, match="intact artifacts"):
            await transition_finding(session, finding_id, FindingStatus.CONFIRMED,
                                     reason="Evidence was collected earlier")
        await session.rollback()
