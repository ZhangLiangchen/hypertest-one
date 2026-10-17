from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.api.schemas import (
    PolicySnapshotCreate,
    ProjectCreate,
    SourceSnapshotCreate,
    TestRunCreate,
)
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import execute_mission
from hypertest.application.services import (
    canonical_json_sha256,
    create_policy_snapshot,
    create_project,
    create_source_snapshot,
    create_test_run,
)
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionStatus, MissionType
from hypertest.domain.models import AuditEvent, OutboxEvent, RequirementRisk, Risk


class FakePlannerHarness:
    async def create_session(self, workspace: str) -> AgentSession:
        return AgentSession(id=public_key("AS"), provider="fake")

    async def execute(
        self,
        session: AgentSession,
        mission: dict,
    ) -> AsyncIterator[AgentEvent]:
        mission_type = mission["type"]
        if mission_type == "ANALYZE_REQUIREMENTS":
            proposals = [
                {
                    "proposal_type": "REQUIREMENT",
                    "operation": "CREATE",
                    "idempotency_key": "checkout.submit:v1",
                    "object_payload": {
                        "logical_key": "checkout.submit",
                        "title": "Submit checkout order",
                        "description": "A valid checkout request creates exactly one order.",
                        "requirement_type": "FUNCTIONAL",
                        "priority": "P0",
                        "source_type": "PRD",
                        "source_ref": "PRD#checkout",
                        "confidence": 0.98,
                    },
                }
            ]
        elif mission_type == "ANALYZE_RISKS":
            requirement_key = mission["context"]["requirements"][0]["key"]
            proposals = [
                {
                    "proposal_type": "RISK",
                    "operation": "CREATE",
                    "idempotency_key": "checkout.submit:duplicate-order:v1",
                    "object_payload": {
                        "requirement_keys": [requirement_key],
                        "category": "CONCURRENCY",
                        "title": "Concurrent checkout can create duplicate orders",
                        "description": "Two concurrent submits may both pass idempotency checks.",
                        "severity": "HIGH",
                        "probability": "MEDIUM",
                        "rationale": "The order creation path has an externally visible side effect.",
                        "confidence": 0.91,
                    },
                }
            ]
        else:
            raise AssertionError(f"unexpected mission: {mission_type}")

        yield AgentEvent(
            type="RESULT_SUBMITTED",
            payload={
                "protocol": "hypertest.tmp/v1alpha1",
                "mission_id": mission["mission_id"],
                "status": "COMPLETED",
                "summary": "fake planner mission complete",
                "proposals": proposals,
            },
        )

    async def interrupt(self, session: AgentSession) -> None:
        return None

    async def close(self, session: AgentSession) -> None:
        return None


@pytest.mark.asyncio
async def test_planner_advances_requirement_to_risk_canonical_state() -> None:
    async with AsyncSessionLocal() as session:
        suffix = public_key("IT").replace("-", "")[-12:]
        project = await create_project(
            session,
            ProjectCreate(key=f"PLANNER_{suffix}", name="Planner Risk Integration"),
        )
        snapshot = await create_source_snapshot(
            session,
            project.id,
            SourceSnapshotCreate(
                repository_url="https://example.invalid/planner.git",
                commit_sha="1234567890abcdef",
                prd_sha256="d" * 64,
                configuration_sha256="e" * 64,
            ),
        )
        policy = await create_policy_snapshot(
            session,
            PolicySnapshotCreate(
                project_id=project.id,
                policy_version="planner-v1",
                content_sha256=canonical_json_sha256({}),
            ),
        )
        test_run = await create_test_run(
            session,
            TestRunCreate(
                project_id=project.id,
                source_snapshot_id=snapshot.id,
                policy_snapshot_id=policy.id,
            ),
        )

        first_plan = await plan_next_mission(session, test_run.id)
        assert first_plan.reason == "REQUIREMENTS_MISSING"
        assert first_plan.mission is not None
        assert first_plan.mission.mission_type is MissionType.ANALYZE_REQUIREMENTS
        assert first_plan.mission.status is MissionStatus.READY

        await execute_mission(
            session,
            first_plan.mission.id,
            workspace=".",
            harness=FakePlannerHarness(),
        )

        risk_plan = await plan_next_mission(session, test_run.id)
        assert risk_plan.reason == "RISK_COVERAGE_GAP"
        assert risk_plan.mission is not None
        assert risk_plan.mission.mission_type is MissionType.ANALYZE_RISKS
        assert risk_plan.mission.status is MissionStatus.READY

        duplicate_plan = await plan_next_mission(session, test_run.id)
        assert duplicate_plan.mission is not None
        assert duplicate_plan.mission.id == risk_plan.mission.id

        execution = await execute_mission(
            session,
            risk_plan.mission.id,
            workspace=".",
            harness=FakePlannerHarness(),
        )
        assert len(execution.risks) == 1
        risk = execution.risks[0]

        risk_count = await session.scalar(
            select(func.count()).select_from(Risk).where(Risk.source_snapshot_id == snapshot.id)
        )
        link_count = await session.scalar(
            select(func.count())
            .select_from(RequirementRisk)
            .where(RequirementRisk.risk_id == risk.id)
        )
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.entity_id == risk.id, AuditEvent.action == "risk.accepted")
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.aggregate_id == risk.id, OutboxEvent.event_type == "risk.accepted")
        )
        assert risk_count == 1
        assert link_count == 1
        assert audit_count == 1
        assert outbox_count == 1

        final_plan = await plan_next_mission(session, test_run.id)
        assert final_plan.reason == "TEST_DESIGN_COVERAGE_GAP"
        assert final_plan.mission is not None
        assert final_plan.mission.mission_type is MissionType.DESIGN_TESTS
