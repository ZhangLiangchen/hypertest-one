from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import MissionCreate
from hypertest.application.coverage import RiskCoverageEvaluator, get_test_run_coverage
from hypertest.application.services import create_mission, get_test_run
from hypertest.domain.enums import (
    MissionStatus,
    MissionType,
    Priority,
    RequirementLifecycle,
    RiskLifecycle,
)
from hypertest.domain.models import Mission, Requirement, RequirementRisk, Risk, TestCase, utcnow


@dataclass(slots=True)
class PlannerResult:
    mission: Mission | None
    reason: str


def _target_hash(values: list[str]) -> str:
    payload = "|".join(sorted(values)).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


async def _mark_ready(session: AsyncSession, mission: Mission) -> Mission:
    if mission.status is MissionStatus.CREATED:
        mission.status = MissionStatus.READY
        mission.ready_at = utcnow()
        mission.row_version += 1
        await session.commit()
        await session.refresh(mission)
    return mission


async def plan_next_mission(session: AsyncSession, test_run_id: UUID) -> PlannerResult:
    """Create the next deterministic testing mission from canonical state gaps."""

    test_run = await get_test_run(session, test_run_id)
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
        mission = await create_mission(
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
        mission = await create_mission(
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
        return PlannerResult(None, "TEST_DESIGN_COVERAGE_COMPLETE")

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
        requested = pending.spec.get("acceptance_criteria", {}).get("risk_coverage_gaps", [])
        requested_pairs = {
            (gap["risk_key"], dimension)
            for gap in requested
            for dimension in gap["missing_dimensions"]
        }
        if requested_pairs & current_pairs:
            return PlannerResult(await _mark_ready(session, pending), "TEST_DESIGN_COVERAGE_GAP")
        if pending.created_by == "planner" and pending.status in {
            MissionStatus.CREATED,
            MissionStatus.READY,
            MissionStatus.RETRYING,
        }:
            pending.status = MissionStatus.CANCELLED
            pending.cancelled_at = utcnow()
            pending.row_version += 1
            await session.commit()

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
    mission = await create_mission(
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
                    "coverage_rule_version": RiskCoverageEvaluator.version,
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
                f"{_target_hash([RiskCoverageEvaluator.version, *gap_state, *case_state])}"
            ),
            created_by="planner",
        ),
    )
    return PlannerResult(await _mark_ready(session, mission), "TEST_DESIGN_COVERAGE_GAP")
