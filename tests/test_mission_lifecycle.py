from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_runtime_controls import PausedHarness
from test_test_design import ProposalHarness, create_run, requirement_proposal

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.api.schemas import MissionCreate
from hypertest.application import verifier
from hypertest.application.jobs import JobLeaseLost
from hypertest.application.lifecycle import record_mission_event
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import MissionRuntimeError, execute_mission
from hypertest.application.services import create_mission
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    AgentSessionStatus,
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    ProposalStatus,
)
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    Mission,
    MissionAttempt,
    MissionProposal,
    OutboxEvent,
    Requirement,
)
from hypertest.main import app


async def event_pair(
    session: AsyncSession, mission_id: UUID, action: str
) -> tuple[AuditEvent, OutboxEvent]:
    """Each durable lifecycle transition has exactly one matching outbox entry."""
    audits = list(
        await session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "Mission",
                AuditEvent.entity_id == mission_id,
                AuditEvent.action == action,
            )
        )
    )
    outbox = list(
        await session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_type == "Mission",
                OutboxEvent.aggregate_id == mission_id,
                OutboxEvent.event_type == action,
            )
        )
    )
    assert len(audits) == len(outbox) == 1
    audit, event = audits[0], outbox[0]
    assert audit.event_metadata["event_key"] == event.payload["event_key"]
    assert event.payload["mission_id"] == str(mission_id)
    return audit, event


async def assert_no_accepted_output(
    session: AsyncSession, mission_id: UUID, snapshot_id: UUID
) -> None:
    assert await session.scalar(
        select(func.count())
        .select_from(Requirement)
        .where(Requirement.source_snapshot_id == snapshot_id)
    ) == 0
    assert await session.scalar(
        select(func.count())
        .select_from(MissionProposal)
        .where(
            MissionProposal.mission_id == mission_id,
            MissionProposal.status == ProposalStatus.ACCEPTED,
        )
    ) == 0
    assert await session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.entity_id == mission_id,
            AuditEvent.action == "mission.completed",
        )
    ) == 0
    assert await session.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.aggregate_id == mission_id,
            OutboxEvent.event_type == "mission.completed",
        )
    ) == 0


@pytest.mark.asyncio
async def test_verified_result_commits_canonical_state_and_replay_safe_mission_events() -> None:
    async with AsyncSessionLocal() as session:
        assert session.bind is not None and session.bind.dialect.name == "postgresql"
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission_id = plan.mission.id
        repeated = await plan_next_mission(session, run.id)
        assert repeated.mission is not None and repeated.mission.id == mission_id
        for action in ("mission.created", "mission.ready"):
            audit, event = await event_pair(session, mission_id, action)
            assert audit.actor_type == "SYSTEM"
            assert event.payload["attempt_id"] is None
        result = await execute_mission(
            session,
            mission_id,
            ".",
            harness=ProposalHarness([requirement_proposal()]),
        )
        assert result.mission.status is MissionStatus.COMPLETED
        assert result.attempt.status is MissionAttemptStatus.ACCEPTED
        assert len(result.requirements) == len(result.proposals) == 1

        # Inspect through a different transaction, proving the complete result is
        # durable rather than merely present in the runtime's identity map.
        async with AsyncSessionLocal() as observer:
            requirement = await observer.get(Requirement, result.requirements[0].id)
            proposal = await observer.get(MissionProposal, result.proposals[0].id)
            assert requirement is not None
            assert proposal is not None and proposal.status is ProposalStatus.ACCEPTED
            assert proposal.accepted_entity_id == requirement.id
            assert requirement.created_by_ref == str(result.attempt.id)
            for action in ("mission.dispatched", "mission.started", "mission.completed"):
                audit, event = await event_pair(observer, mission_id, action)
                assert audit.actor_type == "SYSTEM"
                assert audit.test_run_id == run.id
                assert audit.event_metadata["attempt_id"] == str(result.attempt.id)
                assert event.payload["attempt_id"] == str(result.attempt.id)

        for action in ("mission.dispatched", "mission.started", "mission.completed"):
            await record_mission_event(session, result.mission, action, attempt=result.attempt)
        await session.commit()
        for action in ("mission.dispatched", "mission.started", "mission.completed"):
            await event_pair(session, mission_id, action)


@pytest.mark.asyncio
async def test_rejected_result_records_retry_transition_without_canonical_output() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        invalid = requirement_proposal()
        invalid["object_payload"]["title"] = ""
        result = await execute_mission(
            session, plan.mission.id, ".", harness=ProposalHarness([invalid])
        )
        assert result.mission.status is MissionStatus.RETRYING
        assert result.attempt.status is MissionAttemptStatus.REJECTED
        assert result.attempt.error_code == "INVALID_REQUIREMENT"
        assert len(result.proposals) == 1
        assert result.proposals[0].status is ProposalStatus.REJECTED
        await assert_no_accepted_output(session, result.mission.id, run.source_snapshot_id)
        audit, event = await event_pair(session, result.mission.id, "mission.result_rejected")
        assert audit.actor_type == "SYSTEM"
        assert audit.after_state["status"] == "RETRYING"
        assert event.payload["error_code"] == "INVALID_REQUIREMENT"


class ErrorHarness(ProposalHarness):
    async def execute(
        self, session: AgentSession, mission: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(
            type="ERROR",
            payload={"error_code": "PROVIDER_ERROR", "message": "provider private diagnostic"},
        )


class InvalidResultHarness(ProposalHarness):
    async def execute(
        self, session: AgentSession, mission: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="RESULT_SUBMITTED", payload={
            "mission_id": mission["mission_id"], "status": "INVALID", "proposals": [],
        })


@pytest.mark.asyncio
async def test_invalid_result_envelope_is_rejected_and_retained_for_review() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission_id = plan.mission.id
        with pytest.raises(MissionRuntimeError, match="TMP schema"):
            await execute_mission(session, mission_id, ".", harness=InvalidResultHarness([]))
        attempt = await session.scalar(select(MissionAttempt).where(
            MissionAttempt.mission_id == mission_id,
        ))
        assert attempt is not None and attempt.status is MissionAttemptStatus.REJECTED
        assert attempt.error_code == "RESULT_SCHEMA_ERROR"
        assert attempt.result_payload["status"] == "INVALID"
        agent = await session.get(AgentSessionRecord, attempt.agent_session_id)
        assert agent is not None and agent.status is AgentSessionStatus.CLOSED
        audit, event = await event_pair(session, mission_id, "mission.result_rejected")
        assert audit.after_state["status"] == "RETRYING"
        assert event.payload["error_code"] == "RESULT_SCHEMA_ERROR"
        assert "result_payload" not in event.payload
        await assert_no_accepted_output(session, mission_id, run.source_snapshot_id)


class LeaseLostHarness(PausedHarness):
    async def execute(
        self, session: AgentSession, mission: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="MISSION_STARTED", payload={})
        raise JobLeaseLost("another worker owns this mission job")


@pytest.mark.asyncio
async def test_lost_worker_lease_propagates_without_acceptance_or_fake_failure_transition() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission_id = plan.mission.id
        harness = LeaseLostHarness()
        with pytest.raises(JobLeaseLost, match="another worker"):
            await execute_mission(session, mission_id, ".", harness=harness)
        assert harness.closed == 1
        await session.refresh(plan.mission)
        assert plan.mission.status is MissionStatus.RUNNING
        attempt = await session.scalar(
            select(MissionAttempt).where(MissionAttempt.mission_id == mission_id)
        )
        assert attempt is not None and attempt.status is MissionAttemptStatus.RUNNING
        # Only the lease/recovery owner may retire this attempt; the stale worker
        # cannot synthesize a provider failure or acceptance to bypass that fence.
        await assert_no_accepted_output(session, mission_id, run.source_snapshot_id)
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == mission_id,
            AuditEvent.action == "mission.attempt_failed",
        )) == 0


@pytest.mark.asyncio
async def test_provider_failure_event_records_code_without_provider_diagnostics() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission_id = plan.mission.id
        with pytest.raises(MissionRuntimeError, match="Agent provider process exited unsuccessfully"):
            await execute_mission(session, mission_id, ".", harness=ErrorHarness([]))
        attempt = await session.scalar(
            select(MissionAttempt).where(MissionAttempt.mission_id == mission_id)
        )
        assert attempt is not None
        assert attempt.status is MissionAttemptStatus.FAILED
        assert attempt.error_code == "PROVIDER_ERROR"
        assert attempt.error_message == "Agent provider process exited unsuccessfully"
        assert "provider private diagnostic" not in str(attempt.provider_metadata)
        audit, event = await event_pair(session, mission_id, "mission.attempt_failed")
        assert audit.event_metadata["error_code"] == event.payload["error_code"] == "PROVIDER_ERROR"
        assert "provider private diagnostic" not in str(audit.event_metadata)
        assert "provider private diagnostic" not in str(event.payload)
        await assert_no_accepted_output(session, mission_id, run.source_snapshot_id)


@pytest.mark.asyncio
async def test_timeout_persists_failed_attempt_and_paired_timeout_event() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission = await create_mission(
            session,
            run.id,
            MissionCreate(
                mission_type=MissionType.ANALYZE_REQUIREMENTS,
                objective="Exercise an immutable mission with a short execution budget",
                idempotency_key="lifecycle-timeout",
                spec={"constraints": {"max_duration_seconds": 0.1}},
            ),
        )
        mission_id = mission.id
        harness = PausedHarness()
        with pytest.raises(MissionRuntimeError, match="time limit"):
            await asyncio.wait_for(
                execute_mission(session, mission_id, ".", harness=harness), timeout=3
            )
        assert harness.interrupted == harness.closed == 1
        await session.refresh(mission)
        assert mission.status is MissionStatus.RETRYING
        attempt = await session.scalar(
            select(MissionAttempt).where(MissionAttempt.mission_id == mission_id)
        )
        assert attempt is not None
        assert attempt.status is MissionAttemptStatus.FAILED
        assert attempt.error_code == "MISSION_TIMEOUT"
        assert attempt.finished_at is not None
        audit, event = await event_pair(session, mission_id, "mission.timed_out")
        assert audit.after_state["status"] == "RETRYING"
        assert audit.event_metadata["error_code"] == event.payload["error_code"] == "MISSION_TIMEOUT"
        await assert_no_accepted_output(session, mission_id, run.source_snapshot_id)


@pytest.mark.asyncio
async def test_task_cancellation_interrupts_closes_and_durably_records_interruption() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission_id, snapshot_id = plan.mission.id, run.source_snapshot_id
        harness = PausedHarness()
        running = asyncio.create_task(execute_mission(session, mission_id, ".", harness=harness))
        try:
            await asyncio.wait_for(harness.started.wait(), timeout=3)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(running, timeout=3)
        finally:
            if not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
        assert harness.interrupted == harness.closed == 1

        async with AsyncSessionLocal() as observer:
            mission = await observer.get(Mission, mission_id)
            attempt = await observer.scalar(
                select(MissionAttempt).where(MissionAttempt.mission_id == mission_id)
            )
            assert mission is not None and mission.status is MissionStatus.RETRYING
            assert attempt is not None and attempt.status is MissionAttemptStatus.FAILED
            assert attempt.error_code == "EXECUTION_INTERRUPTED"
            assert attempt.finished_at is not None
            agent = await observer.get(AgentSessionRecord, attempt.agent_session_id)
            assert agent is not None and agent.closed_at is not None
            assert agent.status is AgentSessionStatus.FAILED
            audit, event = await event_pair(observer, mission_id, "mission.interrupted")
            assert audit.event_metadata["error_code"] == "EXECUTION_INTERRUPTED"
            assert event.payload["attempt_id"] == str(attempt.id)
            await assert_no_accepted_output(observer, mission_id, snapshot_id)


@pytest.mark.asyncio
async def test_user_cancel_and_runtime_observation_share_one_cancellation_event() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission_id = plan.mission.id
        harness = PausedHarness()
        running = asyncio.create_task(execute_mission(session, mission_id, ".", harness=harness))
        try:
            await asyncio.wait_for(harness.started.wait(), timeout=3)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://hypertest"
            ) as client:
                for _ in range(2):
                    response = await client.post(f"/api/v1/missions/{mission_id}/cancel")
                    assert response.status_code == 200
                    assert response.json()["status"] == "CANCELLED"
            result = await asyncio.wait_for(running, timeout=3)
        finally:
            if not running.done():
                harness.release.set()
                await asyncio.gather(running, return_exceptions=True)
        assert harness.interrupted == harness.closed == 1
        assert result.mission.status is MissionStatus.CANCELLED
        assert result.attempt.status is MissionAttemptStatus.CANCELLED
        assert result.requirements == result.proposals == []
        audit, event = await event_pair(session, mission_id, "mission.cancelled")
        assert audit.actor_type == "USER" and audit.actor_ref == "web"
        assert event.payload["actor_type"] == "USER"
        await assert_no_accepted_output(session, mission_id, run.source_snapshot_id)


@pytest.mark.asyncio
async def test_completion_event_failure_rolls_back_entire_canonical_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = verifier.record_mission_event

    async def reject_completion(
        session: AsyncSession, mission: Mission, action: str, **kwargs: Any
    ) -> None:
        if action == "mission.completed":
            raise RuntimeError("injected lifecycle persistence failure")
        await original(session, mission, action, **kwargs)

    monkeypatch.setattr(verifier, "record_mission_event", reject_completion)
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission_id, snapshot_id = plan.mission.id, run.source_snapshot_id
        with pytest.raises(RuntimeError, match="injected lifecycle persistence failure"):
            await execute_mission(
                session, mission_id, ".", harness=ProposalHarness([requirement_proposal()])
            )

    async with AsyncSessionLocal() as observer:
        await assert_no_accepted_output(observer, mission_id, snapshot_id)
        mission = await observer.get(Mission, mission_id)
        attempt = await observer.scalar(
            select(MissionAttempt).where(MissionAttempt.mission_id == mission_id)
        )
        assert mission is not None and mission.status is MissionStatus.RUNNING
        assert mission.completed_at is None
        assert attempt is not None and attempt.status is MissionAttemptStatus.RUNNING
        assert attempt.result_payload is None
        assert await observer.scalar(
            select(func.count())
            .select_from(MissionProposal)
            .where(MissionProposal.mission_id == mission_id)
        ) == 0
        assert await observer.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.test_run_id == mission.test_run_id,
                AuditEvent.action == "requirement.accepted",
            )
        ) == 0
        assert await observer.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.event_type == "requirement.accepted",
                OutboxEvent.payload["mission_id"].as_string() == str(mission_id),
            )
        ) == 0
        await event_pair(observer, mission_id, "mission.dispatched")
        await event_pair(observer, mission_id, "mission.started")
