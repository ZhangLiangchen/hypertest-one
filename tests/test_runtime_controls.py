from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_test_design import ProposalHarness, create_run, requirement_proposal

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import MissionRuntimeError, execute_mission
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import AgentSessionStatus, MissionAttemptStatus, MissionStatus
from hypertest.domain.enums import TestRunStatus as RunStatus
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    MissionAttempt,
    MissionProposal,
    Requirement,
)
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app


class PausedHarness(ProposalHarness):
    """Keep external work paused after the runtime reserves a PostgreSQL attempt."""

    def __init__(self) -> None:
        super().__init__([requirement_proposal()])
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sessions_created = 0
        self.interrupted = 0
        self.closed = 0

    async def create_session(self, workspace: str) -> AgentSession:
        self.sessions_created += 1
        return await super().create_session(workspace)

    async def execute(self, session: AgentSession, mission: dict) -> AsyncIterator[AgentEvent]:
        self.started.set()
        await self.release.wait()
        async for event in super().execute(session, mission):
            yield event

    async def interrupt(self, session: AgentSession) -> None:
        self.interrupted += 1
        self.release.set()

    async def close(self, session: AgentSession) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_concurrent_mission_requests_reserve_one_attempt_and_external_session() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission_id = plan.mission.id
        harness = PausedHarness()
        first = asyncio.create_task(execute_mission(session, mission_id, ".", harness=harness))
        try:
            await asyncio.wait_for(harness.started.wait(), timeout=3)
            async with AsyncSessionLocal() as competitor:
                with pytest.raises(MissionRuntimeError, match="RUNNING"):
                    await execute_mission(competitor, mission_id, ".", harness=harness)
            assert harness.sessions_created == 1
        finally:
            harness.release.set()
            result = await asyncio.wait_for(first, timeout=3)
        assert result.attempt.status is MissionAttemptStatus.ACCEPTED
        assert harness.closed == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MissionAttempt)
                .where(
                    MissionAttempt.mission_id == mission_id,
                )
            )
            == 1
        )
        assert len(result.requirements) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_target", ["mission", "test_run"])
async def test_cancellation_interrupts_external_work_and_prevents_canonical_commits(
    cancel_target: str,
) -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        snapshot_id, run_id = run.source_snapshot_id, run.id
        plan = await plan_next_mission(session, run_id)
        assert plan.mission is not None
        mission_id = plan.mission.id
        harness = PausedHarness()
        running = asyncio.create_task(execute_mission(session, mission_id, ".", harness=harness))
        try:
            await asyncio.wait_for(harness.started.wait(), timeout=3)
            if cancel_target == "mission":
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://hypertest"
                ) as client:
                    cancelled = await client.post(f"/api/v1/missions/{mission_id}/cancel")
                    assert cancelled.status_code == 200
            else:
                async with AsyncSessionLocal() as controller:
                    cancelled_run = await controller.scalar(
                        select(CanonicalRun)
                        .where(
                            CanonicalRun.id == run_id,
                        )
                        .with_for_update()
                    )
                    assert cancelled_run is not None
                    cancelled_run.status = RunStatus.CANCELLED
                    await controller.commit()
            result = await asyncio.wait_for(running, timeout=3)
        finally:
            if not running.done():
                harness.release.set()
                await asyncio.wait_for(running, timeout=3)
        assert result.attempt.status is MissionAttemptStatus.CANCELLED
        if cancel_target == "mission":
            assert result.mission.status is MissionStatus.CANCELLED
        assert result.requirements == []
        assert result.proposals == []
        assert harness.interrupted == 1
        assert harness.closed == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Requirement)
                .where(
                    Requirement.source_snapshot_id == snapshot_id,
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MissionProposal)
                .where(
                    MissionProposal.mission_id == mission_id,
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.test_run_id == run_id,
                    AuditEvent.action == "requirement.accepted",
                )
            )
            == 0
        )
        agent_session = await session.get(AgentSessionRecord, result.attempt.agent_session_id)
        assert agent_session is not None
        assert agent_session.status is AgentSessionStatus.CLOSED


@pytest.mark.asyncio
async def test_mission_timeout_interrupts_external_work_and_preserves_failed_attempt() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        snapshot_id = run.source_snapshot_id
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission = plan.mission
        mission.spec = {**mission.spec, "constraints": {"max_duration_seconds": 0.1}}
        await session.commit()
        harness = PausedHarness()
        with pytest.raises(MissionRuntimeError, match="time limit"):
            await asyncio.wait_for(
                execute_mission(session, mission.id, ".", harness=harness),
                timeout=3,
            )
        assert harness.sessions_created == 1
        assert harness.interrupted == 1
        assert harness.closed == 1
        await session.refresh(mission)
        assert mission.status is MissionStatus.RETRYING
        attempt = await session.scalar(
            select(MissionAttempt).where(
                MissionAttempt.mission_id == mission.id,
            )
        )
        assert attempt is not None
        assert attempt.status is MissionAttemptStatus.FAILED
        assert attempt.error_code == "MISSION_TIMEOUT"
        assert attempt.finished_at is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Requirement)
                .where(
                    Requirement.source_snapshot_id == snapshot_id,
                )
            )
            == 0
        )
