from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import MissionCreate
from hypertest.application.coverage import get_test_run_coverage
from hypertest.application.lifecycle import record_mission_event
from hypertest.application.services import create_mission, get_test_run
from hypertest.domain.enums import (
    CaseResult,
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionPurpose,
    ExecutionStatus,
    ImplementationValidationStatus,
    MissionStatus,
    MissionType,
    Priority,
    RequirementLifecycle,
    RiskLifecycle,
    TestCaseLifecycle,
    TestRunStatus,
    TrustLevel,
)
from hypertest.domain.models import (
    Evidence,
    ExecutionEvidence,
    ExecutionTestCase,
    ImplementationTestCase,
    Mission,
    Requirement,
    RequirementRisk,
    Risk,
    SourceSnapshot,
    TestCase,
    TestExecution,
    TestImplementation,
    TestRun,
    utcnow,
)


@dataclass(slots=True)
class PlannerResult:
    mission: Mission | None
    reason: str


def _target_hash(values: list[str]) -> str:
    payload = "|".join(sorted(values)).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


async def _create_planned_mission(
    session: AsyncSession, test_run_id: UUID, payload: MissionCreate
) -> Mission:
    """Preserve cancelled intent history while allowing an explicit new plan."""
    base = payload.idempotency_key
    missions = list(
        await session.scalars(select(Mission).where(Mission.test_run_id == test_run_id))
    )
    by_key = {mission.idempotency_key: mission for mission in missions}
    key = base
    generation = 0
    while key in by_key and by_key[key].status in {MissionStatus.CANCELLED, MissionStatus.EXPIRED}:
        generation += 1
        key = f"{base}:generation:{generation}"
    if key in by_key:
        return by_key[key]
    return await create_mission(
        session, test_run_id, payload.model_copy(update={"idempotency_key": key})
    )


async def _mark_ready(session: AsyncSession, mission: Mission) -> Mission:
    run = await session.get(TestRun, mission.test_run_id)
    assert run is not None
    await session.refresh(run, with_for_update=True)
    await session.refresh(mission, with_for_update=True)
    try:
        if mission.status is MissionStatus.CREATED:
            before_status = mission.status
            mission.status = MissionStatus.READY
            mission.ready_at = utcnow()
            mission.row_version += 1
            await record_mission_event(
                session, mission, "mission.ready", before_status=before_status,
                metadata={"reason": "deterministic planner prepared the immutable mission"},
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return mission


async def _cancel_obsolete_mission(
    session: AsyncSession, mission: Mission, reason: str,
) -> None:
    run = await session.get(TestRun, mission.test_run_id)
    assert run is not None
    await session.refresh(run, with_for_update=True)
    await session.refresh(mission, with_for_update=True)
    try:
        if mission.created_by == "planner" and mission.status in {
            MissionStatus.CREATED, MissionStatus.READY, MissionStatus.RETRYING,
        }:
            before_status = mission.status
            mission.status = MissionStatus.CANCELLED
            mission.cancelled_at = utcnow()
            mission.row_version += 1
            await record_mission_event(
                session, mission, "mission.cancelled", before_status=before_status,
                metadata={"reason": reason},
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def _plan_delivery(session: AsyncSession, test_run: TestRun) -> PlannerResult:
    cases = list(
        await session.scalars(
            select(TestCase)
            .where(
                TestCase.project_id == test_run.project_id,
                TestCase.source_snapshot_id == test_run.source_snapshot_id,
                TestCase.lifecycle_status == TestCaseLifecycle.ACTIVE,
            )
            .order_by(TestCase.key)
        )
    )
    case_ids = {case.id for case in cases}
    implementations = list(
        await session.scalars(
            select(TestImplementation)
            .where(
                TestImplementation.project_id == test_run.project_id,
                TestImplementation.source_snapshot_id == test_run.source_snapshot_id,
            )
            .order_by(TestImplementation.key)
        )
    )
    usable_ids = {
        item.id
        for item in implementations
        if item.validation_status
        in {
            ImplementationValidationStatus.PENDING,
            ImplementationValidationStatus.VALIDATED,
        }
    }
    implemented = (
        set(
            await session.scalars(
                select(ImplementationTestCase.test_case_id).where(
                    ImplementationTestCase.implementation_id.in_(usable_ids),
                    ImplementationTestCase.test_case_id.in_(case_ids),
                )
            )
        )
        if usable_ids and case_ids
        else set()
    )
    missing = [case for case in cases if case.id not in implemented]
    snapshot = await session.get(SourceSnapshot, test_run.source_snapshot_id)
    assert snapshot is not None
    if missing:
        keys = [case.key for case in missing]
        pending = list(
            await session.scalars(
                select(Mission)
                .where(
                    Mission.test_run_id == test_run.id,
                    Mission.mission_type == MissionType.IMPLEMENT_TESTS,
                    Mission.status.in_(
                        [
                            MissionStatus.CREATED,
                            MissionStatus.READY,
                            MissionStatus.DISPATCHED,
                            MissionStatus.RUNNING,
                            MissionStatus.WAITING_INPUT,
                            MissionStatus.WAITING_EXECUTION,
                            MissionStatus.SUBMITTED,
                            MissionStatus.VERIFYING,
                            MissionStatus.RETRYING,
                        ]
                    ),
                )
                .order_by(Mission.created_at, Mission.key)
            )
        )
        for item in pending:
            if set(item.spec.get("targets", {}).get("test_cases", [])) & set(keys):
                return PlannerResult(
                    await _mark_ready(session, item), "IMPLEMENTATION_COVERAGE_GAP"
                )
            if item.created_by == "planner" and item.status in {
                MissionStatus.CREATED,
                MissionStatus.READY,
                MissionStatus.RETRYING,
            }:
                await _cancel_obsolete_mission(
                    session, item, "target test cases no longer require this implementation mission",
                )
        state = [f"{item.id}:{item.validation_status.value}" for item in implementations]
        mission = await _create_planned_mission(
            session,
            test_run.id,
            MissionCreate(
                mission_type=MissionType.IMPLEMENT_TESTS,
                priority=Priority.P0,
                objective="Implement executable pytest tests for the canonical test cases without changing application source.",
                spec={
                    "targets": {"test_cases": keys},
                    "context": {
                        "source_snapshot": str(snapshot.id),
                        "repository_url": snapshot.repository_url,
                        "commit_sha": snapshot.commit_sha,
                        "test_cases": [
                            {
                                "key": case.key,
                                "title": case.title,
                                "description": case.description,
                                "test_type": case.test_type.value,
                                "priority": case.priority.value,
                                "preconditions": case.preconditions,
                                "expected_result": case.expected_result,
                            }
                            for case in missing
                        ],
                        "existing_implementations": [
                            {
                                "key": item.key,
                                "file_path": item.file_path,
                                "symbol": item.symbol,
                                "validation_status": item.validation_status.value,
                            }
                            for item in implementations
                        ],
                    },
                    "constraints": {
                        "framework": "pytest",
                        "language": "python",
                        "generated_test_paths": "tests/**/*.py",
                        "application_source_immutable": True,
                        "submit_generated_source_in_code": True,
                        "shared_module_source": (
                            "Proposals sharing a file_path must contain identical complete module code. "
                            "Use unique file names for different generated source; do not overwrite tracked files "
                            "or replace existing usable test assets."
                        ),
                    },
                    "acceptance_criteria": {
                        "test_case_traceability_required": True,
                        "implementation_progress_required": True,
                        "runner_validation_required": True,
                    },
                },
                idempotency_key=f"{test_run.key}:IMPLEMENT_TESTS:{_target_hash([*keys, *state])}",
                created_by="planner",
            ),
        )
        return PlannerResult(await _mark_ready(session, mission), "IMPLEMENTATION_COVERAGE_GAP")

    rows = await session.execute(
        select(ExecutionTestCase, TestExecution)
        .join(TestExecution, TestExecution.id == ExecutionTestCase.execution_id)
        .where(
            ExecutionTestCase.test_case_id.in_(case_ids),
            TestExecution.test_run_id == test_run.id,
            TestExecution.purpose == ExecutionPurpose.OFFICIAL,
            TestExecution.source_commit == snapshot.commit_sha,
        )
        .order_by(
            TestExecution.queued_at.desc(),
            TestExecution.id.desc(),
        )
    )
    latest: dict[UUID, tuple[ExecutionTestCase, TestExecution]] = {}
    for fact, execution in rows:
        latest.setdefault(fact.test_case_id, (fact, execution))
    if any(case.id not in latest for case in cases):
        return PlannerResult(None, "EXECUTION_REQUIRED")
    terminal = {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.ERROR,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.CANCELLED,
    }
    if any(execution.status not in terminal for _, execution in latest.values()):
        return PlannerResult(None, "EXECUTION_IN_PROGRESS")
    if any(execution.status is ExecutionStatus.CANCELLED for _, execution in latest.values()):
        return PlannerResult(None, "EXECUTION_REQUIRED")
    failures = [
        (fact, execution)
        for fact, execution in latest.values()
        if (
            fact.result is not CaseResult.PASS
            or execution.status is not ExecutionStatus.COMPLETED
            or execution.outcome is not ExecutionOutcome.PASS
        )
    ]
    if not failures:
        return PlannerResult(None, "VERDICT_REQUIRED")
    execution_ids = {execution.id for _, execution in failures}
    evidence = list(
        await session.scalars(
            select(Evidence)
            .join(ExecutionEvidence, ExecutionEvidence.evidence_id == Evidence.id)
            .where(
                Evidence.test_run_id == test_run.id,
                ExecutionEvidence.execution_id.in_(execution_ids),
                Evidence.status == EvidenceStatus.VERIFIED,
                Evidence.trust_level.in_(
                    [TrustLevel.RUNNER, TrustLevel.SYSTEM, TrustLevel.EXTERNAL_VERIFIED]
                ),
            )
            .distinct()
            .order_by(Evidence.key)
        )
    )
    from hypertest.runner.artifacts import ArtifactIntegrityError, read_evidence_content

    evidence_context = []
    for item in evidence:
        try:
            content = read_evidence_content(item)
        except ArtifactIntegrityError:
            continue
        description = {
            "key": item.key,
            "type": item.evidence_type.value,
            "sha256": item.sha256,
            "artifact_uri": item.artifact_uri,
            "summary": item.inline_summary,
        }
        if item.evidence_type in {
            EvidenceType.STDOUT,
            EvidenceType.STDERR,
            EvidenceType.JUNIT,
            EvidenceType.EXECUTION_METADATA,
            EvidenceType.LOG,
            EvidenceType.ENVIRONMENT_FINGERPRINT,
        }:
            description["content"] = content[:65536].decode("utf-8", errors="replace")
            description["truncated"] = len(content) > 65536
        evidence_context.append(description)
    usable_keys = {item["key"] for item in evidence_context}
    evidence = [item for item in evidence if item.key in usable_keys]
    if not evidence:
        # Do not ask an agent to invent a diagnosis unsupported by trusted facts.
        return PlannerResult(None, "VERDICT_REQUIRED")
    failure_state = [
        f"{fact.test_case_id}:{execution.id}:{fact.result.value}:{fact.failure_summary}"
        for fact, execution in failures
    ]
    signature = _target_hash([*failure_state, *[item.sha256 for item in evidence]])
    mission = await _create_planned_mission(
        session,
        test_run.id,
        MissionCreate(
            mission_type=MissionType.DIAGNOSE_FAILURE,
            priority=Priority.P0,
            objective="Diagnose observed official test failures using trusted execution evidence and propose findings.",
            spec={
                "targets": {"executions": sorted({execution.key for _, execution in failures})},
                "context": {
                    "test_cases": [
                        {
                            "key": case.key,
                            "title": case.title,
                            "description": case.description,
                            "expected_result": case.expected_result,
                        }
                        for case in cases
                        if case.id in {fact.test_case_id for fact, _ in failures}
                    ],
                    "executions": [
                        {
                            "key": execution.key,
                            "test_case_key": next(
                                case.key for case in cases if case.id == fact.test_case_id
                            ),
                            "status": execution.status.value,
                            "outcome": execution.outcome.value if execution.outcome else "UNKNOWN",
                            "result": fact.result.value,
                            "failure_summary": fact.failure_summary,
                            "error_code": execution.error_code,
                            "error_message": execution.error_message,
                        }
                        for fact, execution in failures
                    ],
                    "evidence": evidence_context,
                },
                "acceptance_criteria": {
                    "trusted_evidence_required": True,
                    "canonical_case_references_required": True,
                },
            },
            idempotency_key=f"{test_run.key}:DIAGNOSE_FAILURE:{signature}",
            created_by="planner",
        ),
    )
    if mission.status is MissionStatus.COMPLETED:
        return PlannerResult(None, "VERDICT_REQUIRED")
    return PlannerResult(await _mark_ready(session, mission), "FAILURE_DIAGNOSIS_REQUIRED")


async def plan_next_mission(session: AsyncSession, test_run_id: UUID) -> PlannerResult:
    """Create the next deterministic testing mission from canonical state gaps."""

    test_run = await get_test_run(session, test_run_id)
    if test_run.status is TestRunStatus.CANCELLED:
        return PlannerResult(None, "TEST_RUN_CANCELLED")
    requirements = list(
        await session.scalars(
            select(Requirement)
            .where(
                Requirement.source_snapshot_id == test_run.source_snapshot_id,
                Requirement.lifecycle_status == RequirementLifecycle.ACTIVE,
            )
            .order_by(Requirement.key)
        )
    )

    if not requirements:
        mission = await _create_planned_mission(
            session,
            test_run.id,
            MissionCreate(
                mission_type=MissionType.ANALYZE_REQUIREMENTS,
                priority=Priority.P0,
                objective="Extract atomic, independently verifiable requirements from the current source snapshot.",
                spec={
                    "targets": {"source_snapshot": str(test_run.source_snapshot_id)},
                    "context": {"source_snapshot": str(test_run.source_snapshot_id)},
                    "acceptance_criteria": {
                        "atomic_requirements": True,
                        "source_traceability": True,
                    },
                },
                idempotency_key=(
                    f"{test_run.key}:ANALYZE_REQUIREMENTS:{test_run.source_snapshot_id}"
                ),
                created_by="planner",
            ),
        )
        return PlannerResult(await _mark_ready(session, mission), "REQUIREMENTS_MISSING")

    has_risk = exists(
        select(RequirementRisk.requirement_id)
        .join(Risk, Risk.id == RequirementRisk.risk_id)
        .where(
            RequirementRisk.requirement_id == Requirement.id,
            Risk.project_id == test_run.project_id,
            Risk.source_snapshot_id == test_run.source_snapshot_id,
            Risk.lifecycle_status != RiskLifecycle.OBSOLETE,
        )
    )
    missing_risk_requirements = list(
        await session.scalars(
            select(Requirement)
            .where(
                Requirement.source_snapshot_id == test_run.source_snapshot_id,
                Requirement.lifecycle_status == RequirementLifecycle.ACTIVE,
                ~has_risk,
            )
            .order_by(Requirement.key)
        )
    )

    if missing_risk_requirements:
        keys = [requirement.key for requirement in missing_risk_requirements]
        mission = await _create_planned_mission(
            session,
            test_run.id,
            MissionCreate(
                mission_type=MissionType.ANALYZE_RISKS,
                priority=Priority.P0,
                objective="Identify concrete failure modes and quality risks for uncovered requirements.",
                spec={
                    "targets": {"requirements": keys},
                    "context": {
                        "requirements": [
                            {
                                "key": requirement.key,
                                "logical_key": requirement.logical_key,
                                "title": requirement.title,
                                "description": requirement.description,
                                "priority": requirement.priority.value,
                                "source_ref": requirement.source_ref,
                            }
                            for requirement in missing_risk_requirements
                        ]
                    },
                    "acceptance_criteria": {
                        "all_target_requirements_analyzed": True,
                        "risk_traceability_required": True,
                        "required_dimensions": [
                            "FUNCTIONAL",
                            "BOUNDARY",
                            "FAILURE",
                            "CONCURRENCY",
                        ],
                    },
                },
                idempotency_key=(f"{test_run.key}:ANALYZE_RISKS:{_target_hash(keys)}"),
                created_by="planner",
            ),
        )
        return PlannerResult(await _mark_ready(session, mission), "RISK_COVERAGE_GAP")

    coverage = await get_test_run_coverage(session, test_run.id)
    gaps = [item for item in coverage.risks if not item.complete]
    if not gaps:
        return await _plan_delivery(session, test_run)

    # Repeated planning (including partial external progress) must not create
    # competing missions while an immutable design mission is still actionable.
    pending_missions = list(
        await session.scalars(
            select(Mission)
            .where(
                Mission.test_run_id == test_run.id,
                Mission.mission_type == MissionType.DESIGN_TESTS,
                Mission.status.in_(
                    [
                        MissionStatus.CREATED,
                        MissionStatus.READY,
                        MissionStatus.DISPATCHED,
                        MissionStatus.RUNNING,
                        MissionStatus.WAITING_INPUT,
                        MissionStatus.WAITING_EXECUTION,
                        MissionStatus.SUBMITTED,
                        MissionStatus.VERIFYING,
                        MissionStatus.RETRYING,
                    ]
                ),
            )
            .order_by(Mission.created_at, Mission.key)
        )
    )
    current_pairs = {
        (gap.risk_key, dimension.value) for gap in gaps for dimension in gap.missing_dimensions
    }
    for pending in pending_missions:
        criteria = pending.spec.get("acceptance_criteria", {})
        requested = criteria.get("risk_coverage_gaps", [])
        same_policy = criteria.get("coverage_policy_hash") == coverage.effective_policy_hash
        if "coverage_policy_hash" not in criteria:
            # Existing baseline missions remain actionable for their unchanged rules.
            same_policy = coverage.rule_version == "risk-design-baseline/v1"
        requested_pairs = {
            (gap["risk_key"], dimension)
            for gap in requested
            for dimension in gap["missing_dimensions"]
        }
        if same_policy and requested_pairs & current_pairs:
            return PlannerResult(await _mark_ready(session, pending), "TEST_DESIGN_COVERAGE_GAP")
        if pending.created_by == "planner" and pending.status in {
            MissionStatus.CREATED,
            MissionStatus.READY,
            MissionStatus.RETRYING,
        }:
            await _cancel_obsolete_mission(
                session, pending, "target risk gaps or effective coverage policy changed",
            )

    risks = list(
        await session.scalars(
            select(Risk)
            .where(
                Risk.id.in_([gap.risk_id for gap in gaps]),
            )
            .order_by(Risk.key)
        )
    )
    # Lifecycle changes to existing cases must yield a new mission identity if
    # they reopen previously completed gaps. Coverage remains derived, never stored.
    case_state = [
        f"{item.id}:{item.lifecycle_status.value}"
        for item in await session.scalars(
            select(TestCase)
            .where(TestCase.source_snapshot_id == test_run.source_snapshot_id)
            .order_by(TestCase.id)
        )
    ]
    gap_state = [f"{gap.risk_key}:{','.join(gap.missing_dimensions)}" for gap in gaps]
    mission = await _create_planned_mission(
        session,
        test_run.id,
        MissionCreate(
            mission_type=MissionType.DESIGN_TESTS,
            priority=Priority.P0,
            objective="Design verifiable test cases for the missing canonical risk coverage dimensions.",
            spec={
                "targets": {"risks": [risk.key for risk in risks]},
                "context": {
                    "source_snapshot": str(test_run.source_snapshot_id),
                    "policy_snapshot": str(test_run.policy_snapshot_id),
                    "risks": [
                        {
                            "key": risk.key,
                            "title": risk.title,
                            "description": risk.description,
                            "category": risk.category.value,
                            "severity": risk.severity.value,
                            "probability": risk.probability.value,
                            "rationale": risk.rationale,
                        }
                        for risk in risks
                    ],
                    "coverage": [gap.model_dump(mode="json") for gap in gaps],
                },
                "acceptance_criteria": {
                    "risk_traceability_required": True,
                    "coverage_rule_version": coverage.rule_version,
                    "coverage_policy_hash": coverage.effective_policy_hash,
                    "risk_coverage_gaps": [
                        {
                            "risk_key": gap.risk_key,
                            "missing_dimensions": [
                                dimension.value for dimension in gap.missing_dimensions
                            ],
                        }
                        for gap in gaps
                    ],
                },
            },
            idempotency_key=(
                f"{test_run.key}:DESIGN_TESTS:"
                f"{_target_hash([coverage.rule_version, coverage.effective_policy_hash, *gap_state, *case_state])}"
            ),
            created_by="planner",
        ),
    )
    return PlannerResult(await _mark_ready(session, mission), "TEST_DESIGN_COVERAGE_GAP")
