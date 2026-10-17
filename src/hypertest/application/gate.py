"""Deterministic quality decisions from canonical coverage and trusted Runner facts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.coverage import get_test_run_coverage
from hypertest.application.findings import TRUSTED_EVIDENCE_LEVELS
from hypertest.application.policy import compile_policy
from hypertest.application.services import ConflictError, NotFoundError, canonical_json_sha256
from hypertest.common.ids import public_key
from hypertest.domain.enums import (
    CaseResult,
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionPurpose,
    ExecutionStatus,
    FindingClassification,
    FindingSeverity,
    FindingStatus,
    TestCaseLifecycle,
    TestRunStatus,
    VerdictDecision,
    VerdictScope,
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
    ImplementationTestCase,
    OutboxEvent,
    PolicySnapshot,
    Requirement,
    RequirementRisk,
    Risk,
    RiskTestCase,
    SourceSnapshot,
    TestCase,
    TestExecution,
    TestImplementation,
    TestRun,
    Verdict,
    VerdictEvidence,
    VerdictFinding,
    utcnow,
)
from hypertest.runner.artifacts import ArtifactIntegrityError, read_evidence_content


@dataclass(frozen=True, slots=True)
class GatePolicy:
    """Explicit, deterministic extension boundary for compiled BUGate policy.

    v1 never waives official execution, trusted evidence, or complete case results.
    More policy dimensions can be added here without changing Planner or Agent.
    """

    version: str = "canonical-gate/v1"
    blocking_finding_severities: tuple[FindingSeverity, ...] = (
        FindingSeverity.BLOCKER,
        FindingSeverity.CRITICAL,
    )

    @classmethod
    def from_snapshot(cls, snapshot: PolicySnapshot) -> GatePolicy:
        configured = set(compile_policy(snapshot.compiled_policy).gate.blocking_finding_severities)
        # A confirmed blocker cannot be waived by the MVP baseline policy.
        configured.add(FindingSeverity.BLOCKER)
        return cls(blocking_finding_severities=tuple(sorted(configured)))


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    return value


def _semantic_row(instance: Any) -> dict[str, Any]:
    """Serialize mapped scalar semantics, excluding volatile timestamps/counters."""
    excluded = {
        "row_version",
        "created_at",
        "updated_at",
        "queued_at",
        "started_at",
        "finished_at",
        "verified_at",
        "resolved_at",
        "finalized_at",
        "revoked_at",
    }
    return {
        column.key: _json_value(getattr(instance, column.key))
        for column in instance.__mapper__.columns
        if column.key not in excluded
    }


def _sorted_rows(instances: list[Any]) -> list[dict[str, Any]]:
    return sorted((_semantic_row(item) for item in instances), key=canonical_json_sha256)


async def _state_snapshot(
    session: AsyncSession,
    run: TestRun,
    policy: PolicySnapshot,
    executions: list[TestExecution],
    evidence: list[Evidence],
    findings: list[Finding],
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "gate_rule_version": GatePolicy().version,
        "test_run": {
            "id": str(run.id),
            "project_id": str(run.project_id),
            "source_snapshot_id": str(run.source_snapshot_id),
            "policy_snapshot_id": str(run.policy_snapshot_id),
            "cancelled": run.status is TestRunStatus.CANCELLED,
        },
        "policy": _semantic_row(policy),
        "source_snapshot": _semantic_row(await session.get(SourceSnapshot, run.source_snapshot_id)),
        "executions": _sorted_rows(executions),
        "evidence": _sorted_rows(evidence),
        "findings": _sorted_rows(findings),
    }
    objects: dict[type, list[Any]] = {}
    for model in (Requirement, Risk, TestCase, TestImplementation):
        objects[model] = list(
            await session.scalars(
                select(model).where(
                    model.project_id == run.project_id,
                    model.source_snapshot_id == run.source_snapshot_id,
                )
            )
        )
        state[model.__tablename__] = _sorted_rows(objects[model])
    scopes = (
        (
            RequirementRisk,
            RequirementRisk.requirement_id,
            [item.id for item in objects[Requirement]],
        ),
        (RiskTestCase, RiskTestCase.risk_id, [item.id for item in objects[Risk]]),
        (
            ImplementationTestCase,
            ImplementationTestCase.implementation_id,
            [item.id for item in objects[TestImplementation]],
        ),
        (ExecutionTestCase, ExecutionTestCase.execution_id, [item.id for item in executions]),
        (ExecutionEvidence, ExecutionEvidence.execution_id, [item.id for item in executions]),
        (FindingEvidence, FindingEvidence.finding_id, [item.id for item in findings]),
        (FindingRequirement, FindingRequirement.finding_id, [item.id for item in findings]),
        (FindingRisk, FindingRisk.finding_id, [item.id for item in findings]),
        (FindingTestCase, FindingTestCase.finding_id, [item.id for item in findings]),
    )
    for model, field, ids in scopes:
        links = list(await session.scalars(select(model).where(field.in_(ids)))) if ids else []
        state[model.__tablename__] = _sorted_rows(links)
    return state


async def evaluate_gate(
    session: AsyncSession,
    run_id: UUID,
    finalize: bool = True,
) -> Verdict:
    # Keep the Run -> SourceSnapshot lock order used by canonical proposal commits.
    # A run lock alone cannot protect canonical state shared with other runs that
    # reference this same immutable source snapshot.
    run = await session.scalar(
        select(TestRun)
        .where(TestRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise NotFoundError("test run not found")
    policy_snapshot = await session.get(PolicySnapshot, run.policy_snapshot_id)
    source = await session.scalar(
        select(SourceSnapshot)
        .where(SourceSnapshot.id == run.source_snapshot_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if policy_snapshot is None or source is None:
        raise ConflictError("test run has no valid immutable source/policy snapshot")
    policy = GatePolicy.from_snapshot(policy_snapshot)
    coverage = await get_test_run_coverage(session, run.id)
    cases = list(
        await session.scalars(
            select(TestCase).where(
                TestCase.project_id == run.project_id,
                TestCase.source_snapshot_id == run.source_snapshot_id,
                TestCase.lifecycle_status == TestCaseLifecycle.ACTIVE,
            )
        )
    )
    executions = list(
        await session.scalars(
            select(TestExecution)
            .where(
                TestExecution.test_run_id == run.id,
            )
            .order_by(TestExecution.queued_at.desc(), TestExecution.id.desc())
        )
    )
    evidence = list(await session.scalars(select(Evidence).where(Evidence.test_run_id == run.id)))
    findings = list(await session.scalars(select(Finding).where(Finding.test_run_id == run.id)))
    case_ids = {item.id for item in cases}
    official_ids = {item.id for item in executions if item.purpose is ExecutionPurpose.OFFICIAL}
    results = (
        list(
            await session.scalars(
                select(ExecutionTestCase).where(
                    ExecutionTestCase.execution_id.in_(official_ids),
                    ExecutionTestCase.test_case_id.in_(case_ids),
                )
            )
        )
        if official_ids and case_ids
        else []
    )
    results_by_execution: dict[UUID, dict[UUID, ExecutionTestCase]] = {}
    for result in results:
        results_by_execution.setdefault(result.execution_id, {})[result.test_case_id] = result
    latest: dict[UUID, tuple[TestExecution, ExecutionTestCase]] = {}
    for execution in executions:
        if execution.purpose is not ExecutionPurpose.OFFICIAL:
            continue
        for case_id, result in results_by_execution.get(execution.id, {}).items():
            latest.setdefault(case_id, (execution, result))
    trusted: dict[UUID, Evidence] = {}
    artifact_integrity: dict[str, bool] = {}
    for item in evidence:
        if (
            item.status is not EvidenceStatus.VERIFIED
            or item.trust_level not in TRUSTED_EVIDENCE_LEVELS
        ):
            continue
        try:
            read_evidence_content(item)
        except ArtifactIntegrityError:
            artifact_integrity[str(item.id)] = False
        else:
            artifact_integrity[str(item.id)] = True
            trusted[item.id] = item
    evidence_by_execution: dict[UUID, set[EvidenceType]] = {}
    if official_ids and trusted:
        for execution_id, evidence_id in await session.execute(
            select(
                ExecutionEvidence.execution_id,
                ExecutionEvidence.evidence_id,
            ).where(
                ExecutionEvidence.execution_id.in_(official_ids),
                ExecutionEvidence.evidence_id.in_(trusted),
            )
        ):
            evidence_by_execution.setdefault(execution_id, set()).add(
                trusted[evidence_id].evidence_type
            )
    reasons: list[str] = []
    blocking_failure = False
    if run.status is TestRunStatus.CANCELLED:
        reasons.append("TestRun is cancelled.")
    if not coverage.requirement_count or not coverage.risk_count or not cases:
        reasons.append("Requirements, risks, and active test cases must all be present.")
    if coverage.risk_identification_coverage != 1 or coverage.risk_test_coverage != 1:
        reasons.append("Risk identification and required test design dimensions are incomplete.")
    for case in sorted(cases, key=lambda item: item.key):
        pair = latest.get(case.id)
        if pair is None:
            reasons.append(f"{case.key}: no official execution result.")
            continue
        execution, result = pair
        if execution.source_commit != source.commit_sha:
            reasons.append(f"{case.key}: latest official execution has a different source commit.")
            continue
        if execution.status is not ExecutionStatus.COMPLETED:
            reasons.append(f"{case.key}: latest official execution is {execution.status.value}.")
            continue
        if result.result is CaseResult.FAIL or execution.outcome is ExecutionOutcome.FAIL:
            blocking_failure = True
            reasons.append(f"{case.key}: latest official execution failed.")
        elif (
            result.result is not CaseResult.PASS
            or execution.outcome is not ExecutionOutcome.PASS
            or execution.exit_code != 0
        ):
            reasons.append(
                f"{case.key}: no successful official case result ({result.result.value})."
            )
        required_types = {EvidenceType.EXECUTION_METADATA, EvidenceType.JUNIT}
        if not required_types.issubset(evidence_by_execution.get(execution.id, set())):
            reasons.append(
                f"{case.key}: verified trusted execution metadata and JUnit evidence are required."
            )
    blocking_findings = [
        item
        for item in findings
        if item.status is FindingStatus.CONFIRMED
        and item.classification is FindingClassification.PRODUCT_DEFECT
        and item.severity in policy.blocking_finding_severities
    ]
    if blocking_findings:
        blocking_failure = True
        reasons.append(
            "Confirmed product defects block release: "
            + ", ".join(sorted(item.key for item in blocking_findings))
            + "."
        )
    if not reasons:
        decision = VerdictDecision.RELEASE_READY
        reason = "Complete risk design coverage; every active test case passed its latest official execution with verified trusted evidence; no policy-blocking confirmed product defect."
    else:
        decision = VerdictDecision.RELEASE_BLOCKED if blocking_failure else VerdictDecision.BLOCKED
        reason = "\n".join(reasons)
    state = await _state_snapshot(session, run, policy_snapshot, executions, evidence, findings)
    state["artifact_integrity"] = artifact_integrity
    # Never let an older inconsistent decision reuse the same canonical state hash.
    # The hash binds the evidence-backed decision as well as its canonical inputs.
    state["decision"] = decision.value
    state_hash = canonical_json_sha256(state)
    manifest_hash = canonical_json_sha256(
        {
            "evidence": sorted(
                (
                    {"id": str(item.id), "sha256": item.sha256, "type": item.evidence_type.value}
                    for item in trusted.values()
                ),
                key=lambda item: item["id"],
            )
        }
    )
    verdict_status = VerdictStatus.FINAL if finalize else VerdictStatus.DRAFT
    existing = await session.scalar(
        select(Verdict)
        .where(
            Verdict.test_run_id == run.id,
            Verdict.policy_snapshot_id == policy_snapshot.id,
            Verdict.state_snapshot_hash == state_hash,
            Verdict.decision == decision,
            Verdict.evidence_manifest_sha256 == manifest_hash,
            Verdict.status == verdict_status,
            Verdict.scope == VerdictScope.TEST_RUN,
        )
        .order_by(Verdict.sequence_no.desc())
    )
    if existing is not None:
        if finalize and run.current_verdict_id != existing.id:
            run.current_verdict_id = existing.id
            run.row_version += 1
        await session.commit()
        return existing
    sequence_no = (
        await session.scalar(
            select(func.max(Verdict.sequence_no)).where(
                Verdict.test_run_id == run.id,
            )
        )
        or 0
    ) + 1
    verdict = Verdict(
        key=public_key("VER"),
        test_run_id=run.id,
        scope=VerdictScope.TEST_RUN,
        sequence_no=sequence_no,
        decision=decision,
        status=verdict_status,
        reason=reason,
        policy_snapshot_id=policy_snapshot.id,
        state_snapshot_hash=state_hash,
        evidence_manifest_sha256=manifest_hash,
        issued_by_type="SYSTEM",
        issued_by_ref=policy.version,
        finalized_at=utcnow() if finalize else None,
    )
    try:
        session.add(verdict)
        await session.flush()
        session.add_all(
            VerdictEvidence(verdict_id=verdict.id, evidence_id=item.id) for item in trusted.values()
        )
        session.add_all(
            VerdictFinding(verdict_id=verdict.id, finding_id=item.id) for item in findings
        )
        if finalize:
            run.current_verdict_id = verdict.id
            run.row_version += 1
            if run.status is not TestRunStatus.CANCELLED:
                run.status = (
                    TestRunStatus.COMPLETED
                    if decision is VerdictDecision.RELEASE_READY
                    else TestRunStatus.BLOCKED
                )
                run.completed_at = utcnow() if decision is VerdictDecision.RELEASE_READY else None
        action = "verdict.finalized" if finalize else "verdict.drafted"
        payload = {
            "verdict_id": str(verdict.id),
            "test_run_id": str(run.id),
            "decision": decision.value,
            "sequence_no": sequence_no,
            "state_snapshot_hash": state_hash,
            "evidence_manifest_sha256": manifest_hash,
        }
        session.add(
            AuditEvent(
                project_id=run.project_id,
                test_run_id=run.id,
                actor_type="SYSTEM",
                actor_ref=policy.version,
                action=action,
                entity_type="Verdict",
                entity_id=verdict.id,
                after_state=payload,
                event_metadata={"reason": reason},
            )
        )
        session.add(
            OutboxEvent(
                aggregate_type="Verdict",
                aggregate_id=verdict.id,
                event_type=action,
                payload=payload,
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(verdict)
    return verdict
