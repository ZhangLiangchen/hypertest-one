from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.api.schemas import (
    MissionCreate,
    PolicySnapshotCreate,
    ProjectCreate,
    SourceSnapshotCreate,
    TestRunCreate,
)
from hypertest.application.runtime import execute_mission
from hypertest.application.services import (
    canonical_json_sha256,
    create_mission,
    create_policy_snapshot,
    create_project,
    create_source_snapshot,
    create_test_run,
)
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    ProposalStatus,
)
from hypertest.domain.models import AuditEvent, OutboxEvent, Requirement


class FakeRequirementHarness:
    def __init__(self, proposal_key: str) -> None:
        self.proposal_key = proposal_key

    async def create_session(self, workspace: str) -> AgentSession:
        return AgentSession(id=public_key("AS"), provider="fake")

    async def execute(
        self,
        session: AgentSession,
        mission: dict,
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="MISSION_STARTED", payload={"provider": "fake"})
        yield AgentEvent(
            type="RESULT_SUBMITTED",
            payload={
                "protocol": "hypertest.tmp/v1alpha1",
                "mission_id": mission["mission_id"],
                "status": "COMPLETED",
                "summary": "one atomic requirement identified",
                "proposals": [
                    {
                        "proposal_type": "REQUIREMENT",
                        "operation": "CREATE",
                        "idempotency_key": self.proposal_key,
                        "object_payload": {
                            "logical_key": "payment.daily_limit",
                            "title": "Enforce daily transfer limit",
                            "description": "The transfer total must not exceed the configured daily limit.",
                            "requirement_type": "FUNCTIONAL",
                            "priority": "P0",
                            "source_type": "PRD",
                            "source_ref": "PRD#3.2",
                            "confidence": 0.97,
                        },
                        "rationale": "Explicit behavior in PRD section 3.2",
                        "confidence": 0.97,
                    }
                ],
            },
        )
        yield AgentEvent(type="MISSION_FINISHED", payload={"provider": "fake"})

    async def interrupt(self, session: AgentSession) -> None:
        return None

    async def close(self, session: AgentSession) -> None:
        return None


@pytest.mark.asyncio
async def test_agent_result_commits_canonical_requirement_with_audit_and_outbox() -> None:
    async with AsyncSessionLocal() as session:
        suffix = public_key("IT").replace("-", "")[-12:]
        project = await create_project(
            session,
            ProjectCreate(
                key=f"CANONICAL_{suffix}",
                name="Canonical Loop Integration",
            ),
        )
        snapshot = await create_source_snapshot(
            session,
            project.id,
            SourceSnapshotCreate(
                repository_url="https://example.invalid/repo.git",
                commit_sha="abcdef1234567890",
                prd_sha256="a" * 64,
                configuration_sha256="b" * 64,
            ),
        )
        policy = await create_policy_snapshot(
            session,
            PolicySnapshotCreate(
                project_id=project.id,
                policy_version="test-v1",
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
        mission = await create_mission(
            session,
            test_run.id,
            MissionCreate(
                mission_type=MissionType.ANALYZE_REQUIREMENTS,
                objective="Extract atomic requirements from PRD and implementation context",
                spec={"context": {"source_snapshot": str(snapshot.id)}},
                idempotency_key=f"{test_run.key}:ANALYZE_REQUIREMENTS",
            ),
        )

        first = await execute_mission(
            session,
            mission.id,
            workspace=".",
            harness=FakeRequirementHarness("payment.daily_limit:v1"),
        )

        assert first.mission.status is MissionStatus.COMPLETED
        assert first.attempt.status is MissionAttemptStatus.ACCEPTED
        assert len(first.requirements) == 1
        assert len(first.proposals) == 1
        assert first.proposals[0].status is ProposalStatus.ACCEPTED
        requirement_id = first.requirements[0].id
        assert first.proposals[0].accepted_entity_id == requirement_id

        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.entity_id == requirement_id)
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.aggregate_id == requirement_id)
        )
        assert audit_count == 1
        assert outbox_count == 1

        second_mission = await create_mission(
            session,
            test_run.id,
            MissionCreate(
                mission_type=MissionType.ANALYZE_REQUIREMENTS,
                objective="Re-analyze the same source without duplicating canonical state",
                spec={"context": {"source_snapshot": str(snapshot.id)}},
                idempotency_key=f"{test_run.key}:ANALYZE_REQUIREMENTS:RECHECK",
            ),
        )
        second = await execute_mission(
            session,
            second_mission.id,
            workspace=".",
            harness=FakeRequirementHarness("payment.daily_limit:v1:recheck"),
        )

        assert second.requirements[0].id == requirement_id
        requirement_count = await session.scalar(
            select(func.count())
            .select_from(Requirement)
            .where(Requirement.source_snapshot_id == snapshot.id)
        )
        audit_count_after = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.entity_id == requirement_id)
        )
        outbox_count_after = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.aggregate_id == requirement_id)
        )
        assert requirement_count == 1
        assert audit_count_after == 1
        assert outbox_count_after == 1
