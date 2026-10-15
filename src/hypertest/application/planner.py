from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import MissionCreate
from hypertest.application.services import create_mission, get_test_run
from hypertest.domain.enums import (
    MissionStatus,
    MissionType,
    Priority,
    RequirementLifecycle,
)
from hypertest.domain.models import Mission, Requirement, RequirementRisk, utcnow


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
        select(RequirementRisk.requirement_id).where(
            RequirementRisk.requirement_id == Requirement.id
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
                idempotency_key=(
                    f"{test_run.key}:ANALYZE_RISKS:{_target_hash(keys)}"
                ),
                created_by="planner",
            ),
        )
        return PlannerResult(await _mark_ready(session, mission), "RISK_COVERAGE_GAP")

    return PlannerResult(None, "RISK_COVERAGE_COMPLETE")
