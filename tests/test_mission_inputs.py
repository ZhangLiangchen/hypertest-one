"""PostgreSQL clarification/queue contracts; these are not model or Runner E2E tests."""
from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from test_test_design import create_run

from hypertest.application import inputs
from hypertest.application.inputs import answer_input_request, pause_job_for_input
from hypertest.application.jobs import (
    JobLeaseLost,
    cancel_job,
    claim_job,
    finish_job,
    submit_job,
)
from hypertest.application.planner import plan_next_mission
from hypertest.application.services import ConflictError
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import AgentSessionStatus, MissionAttemptStatus, MissionStatus
from hypertest.domain.inputs import InputRequestStatus, MissionInputRequest
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob, JobStatus, JobType
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    Mission,
    MissionAttempt,
    OutboxEvent,
)
from hypertest.main import app
from hypertest.worker import run_claimed_job


@dataclass
class OwnedTurn:
    run_id: UUID
    mission_id: UUID
    attempt_id: UUID
    agent_id: UUID
    job_id: UUID
    token: UUID
    expires: datetime
    spec: dict[str, Any]
    spec_sha256: str
    marker: dict[str, Any]

    @property
    def result(self) -> dict[str, Any]:
        return {"steps": [{"step": 1, "mission_id": str(self.mission_id)}],
                "workspace": ".", "_waiting_input": deepcopy(self.marker)}


@pytest.fixture
async def owned_turn(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[OwnedTurn]:
    # Exercise real ORM ownership and transactions, without external cleanup I/O.
    async def no_docker_resources(job_id: UUID) -> dict[str, int]:
        return {"containers_removed": 0, "volumes_removed": 0}

    monkeypatch.setattr("hypertest.runner.backends.cleanup_docker_job_resources", no_docker_resources)
    monkeypatch.setattr("hypertest.agent.snapshot.cleanup_managed_agent_workspace", lambda _: False)
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission = (await plan_next_mission(session, run.id)).mission
        assert mission is not None
        job = await submit_job(session, run.id, JobType.EXECUTE_MISSION, payload={"workspace": "."},
                               idempotency_key="input-contract", mission_id=mission.id)
        now = await session.scalar(select(func.clock_timestamp()))
        token, expires, native_thread = uuid7(), now + timedelta(minutes=10), str(uuid7())
        job.status, job.lease_token, job.worker_id = JobStatus.RUNNING, token, "input-contract-worker"
        job.attempts, job.started_at, job.heartbeat_at, job.lease_expires_at = 1, now, now, expires
        agent = AgentSessionRecord(id=uuid7(), test_run_id=run.id, provider="codex", harness="contract-test",
                                   provider_session_id=native_thread, workspace_id=".",
                                   status=AgentSessionStatus.RUNNING)
        session.add(agent)
        await session.flush()
        attempt = MissionAttempt(id=uuid7(), mission_id=mission.id, durable_job_id=job.id, attempt_no=1,
                                 agent_session_id=agent.id, status=MissionAttemptStatus.RUNNING,
                                 started_at=now, provider="codex", harness="contract-test")
        mission.status, mission.current_attempt_no = MissionStatus.RUNNING, 1
        mission.row_version += 1
        session.add(attempt)
        await session.commit()
        turn = OwnedTurn(run.id, mission.id, attempt.id, agent.id, job.id, token, expires,
                         deepcopy(mission.spec), mission.spec_sha256, {
                             "mission_id": str(mission.id), "attempt_id": str(attempt.id),
                             "agent_session_id": str(agent.id), "workspace_id": ".",
                             "provider_session_id": native_thread,
                             "provider_metadata": {"native_thread": native_thread},
                             "request": {"question_id": "zero-policy", "question": "Is zero supported?",
                                         "options": ["yes", "no"]},
                         })
    try:
        yield turn
    finally:
        async with AsyncSessionLocal() as session:
            job = await session.get(DurableJob, turn.job_id)
            if job.status in ACTIVE_JOB_STATUSES:
                job = await cancel_job(session, job.id)
                if job.status is JobStatus.CANCEL_REQUESTED:
                    await finish_job(session, job.id, job.lease_token)


async def pause(turn: OwnedTurn) -> UUID:
    async with AsyncSessionLocal() as session:
        job = await pause_job_for_input(session, turn.job_id, turn.token, result=turn.result)
        return UUID(job.result["input_request_id"])


async def answer_and_claim(turn: OwnedTurn, request_id: UUID) -> DurableJob:
    async with AsyncSessionLocal() as session:
        await answer_input_request(session, request_id, answer="zero is supported",
                                   expected_row_version=1, idempotency_key="answer-zero")
        claimed = await claim_job(session, "input-resume-worker", lease_seconds=600)
        assert claimed is not None and claimed.id == turn.job_id
        return claimed


async def event_counts(session, entity_id: UUID) -> tuple[int, int]:
    audit = await session.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.entity_id == entity_id))
    outbox = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.aggregate_id == entity_id))
    return audit, outbox


@pytest.mark.asyncio
async def test_worker_pause_answer_api_retry_and_same_job_new_lease(owned_turn: OwnedTurn) -> None:
    turn = owned_turn
    async with AsyncSessionLocal() as session:
        original = await session.get(DurableJob, turn.job_id)
        original_payload, original_started = deepcopy(original.payload), original.started_at

    async def dispatch(session, job):
        await session.commit()  # Use the real lease-fenced Worker dispatch boundary.
        return turn.result

    waiting = await run_claimed_job(original, dispatcher=dispatch)
    assert waiting.status is JobStatus.WAITING_INPUT
    assert waiting.lease_token is waiting.worker_id is waiting.lease_expires_at is waiting.heartbeat_at is None
    request_id = UUID(waiting.result["input_request_id"])
    async with AsyncSessionLocal() as session:
        request = await session.get(MissionInputRequest, request_id)
        assert request.status is InputRequestStatus.PENDING and request.row_version == 1
        assert (await session.get(Mission, turn.mission_id)).status is MissionStatus.WAITING_INPUT
        assert (await session.get(MissionAttempt, turn.attempt_id)).status is MissionAttemptStatus.RUNNING
        assert (await session.get(AgentSessionRecord, turn.agent_id)).status is AgentSessionStatus.WAITING_INPUT
        assert await claim_job(session, "cannot-claim-waiting") is None
        with pytest.raises(ConflictError, match="active work"):
            await submit_job(session, turn.run_id, JobType.EVALUATE_GATE, payload={}, idempotency_key="other")
        await session.rollback()

    answer = "  零值有效\nKeep the original text.  "
    payload = {"answer": answer, "expected_row_version": 1, "idempotency_key": "answer-zero"}
    endpoint = f"/api/v1/input-requests/{request_id}/answer"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        listed = await client.get(f"/api/v1/test-runs/{turn.run_id}/input-requests")
        assert listed.status_code == 200 and [q["id"] for q in listed.json()] == [str(request_id)]
        assert (await client.get(f"/api/v1/input-requests/{request_id}")).status_code == 200
        assert (await client.post(endpoint, json={**payload, "expected_row_version": 2})).status_code == 409
        accepted = await client.post(endpoint, json=payload)
        assert accepted.status_code == 202
        assert accepted.json()["input_request"]["answer"] == answer
        assert accepted.json()["input_request"]["row_version"] == 2
        assert accepted.json()["job"]["id"] == str(turn.job_id)
        assert accepted.json()["job"]["status"] == "QUEUED"
        repeated = await client.post(endpoint, json=payload)
        assert repeated.status_code == 202 and repeated.json() == accepted.json()
        for changes in ({"answer": "different"}, {"idempotency_key": "different-key"}):
            assert (await client.post(endpoint, json={**payload, **changes})).status_code == 409
        for changes in ({"answer": " "}, {"answer": "bad\x00answer"}, {"expected_row_version": 0}):
            assert (await client.post(endpoint, json={**payload, **changes})).status_code == 422
        async with AsyncSessionLocal() as session:
            assert await event_counts(session, request_id) == (2, 2)
            resumed = await claim_job(session, "new-owner", lease_seconds=600)
            assert resumed is not None and resumed.id == turn.job_id and resumed.attempts == 2
            assert resumed.lease_token != turn.token and resumed.started_at == original_started
            assert resumed.payload == original_payload
            token = resumed.lease_token
        retry_during_claim = await client.post(endpoint, json=payload)
        assert retry_during_claim.status_code == 202 and retry_during_claim.json()["job"]["status"] == "RUNNING"
        async with AsyncSessionLocal() as session:
            with pytest.raises(JobLeaseLost):
                await finish_job(session, turn.job_id, turn.token)
            request = await session.get(MissionInputRequest, request_id)
            request.status, request.consumed_at = InputRequestStatus.CONSUMED, await session.scalar(select(func.clock_timestamp()))
            request.row_version += 1
            await session.commit()
            await finish_job(session, turn.job_id, token, error_code="TEST_RESUME_FINISHED")
        after_terminal = await client.post(endpoint, json=payload)
        assert after_terminal.status_code == 202 and after_terminal.json()["input_request"]["status"] == "CONSUMED"
    async with AsyncSessionLocal() as session:
        request = await session.get(MissionInputRequest, request_id)
        assert (request.test_run_id, request.mission_id, request.attempt_id, request.agent_session_id,
                request.durable_job_id) == (turn.run_id, turn.mission_id, turn.attempt_id, turn.agent_id, turn.job_id)
        assert request.answer == answer and request.question == "Is zero supported?"
        assert await event_counts(session, request_id) == (2, 2)
        mission = await session.get(Mission, turn.mission_id)
        assert (mission.spec, mission.spec_sha256, mission.current_attempt_no) == (turn.spec, turn.spec_sha256, 1)
        assert await session.scalar(select(func.count()).select_from(MissionAttempt).where(
            MissionAttempt.mission_id == turn.mission_id)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("answered", [False, True], ids=["waiting", "answered-queued"])
async def test_cancel_closes_waiting_or_answered_queue_and_keeps_history(owned_turn, answered):
    turn = owned_turn
    request_id = await pause(turn)
    async with AsyncSessionLocal() as session:
        if answered:
            await answer_input_request(session, request_id, answer="zero is supported",
                                       expected_row_version=1, idempotency_key="answer-zero")
        cancelled = await cancel_job(session, turn.job_id)
        assert cancelled.status is JobStatus.CANCELLED and cancelled.finished_at is not None
        request = await session.get(MissionInputRequest, request_id)
        assert request.status is InputRequestStatus.CANCELLED and request.cancelled_at is not None
        assert request.row_version == (3 if answered else 2)
        assert request.answer == ("zero is supported" if answered else None)
        assert (await session.get(Mission, turn.mission_id)).status is MissionStatus.CANCELLED
        assert (await session.get(MissionAttempt, turn.attempt_id)).status is MissionAttemptStatus.CANCELLED
        assert (await session.get(AgentSessionRecord, turn.agent_id)).status is AgentSessionStatus.CLOSED
        assert await event_counts(session, request_id) == ((3, 3) if answered else (2, 2))
        job_events = list(await session.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == turn.job_id)))
        assert "job.cancelled" in job_events and "job.resources_cleanup" in job_events
        assert await claim_job(session, "after-cancel") is None
        if answered:
            # A retry confirms the original answer even though cancellation won later.
            repeated, same_job = await answer_input_request(session, request_id, answer="zero is supported",
                                                           expected_row_version=1, idempotency_key="answer-zero")
            assert repeated.status is InputRequestStatus.CANCELLED and same_job.status is JobStatus.CANCELLED
        with pytest.raises(ConflictError):
            await answer_input_request(session, request_id, answer="late different answer",
                                       expected_row_version=3 if answered else 2, idempotency_key="late")


@pytest.mark.asyncio
async def test_cancellation_between_handler_marker_and_pause_cannot_publish_question(owned_turn, monkeypatch):
    turn = owned_turn
    actual_pause = inputs.pause_job_for_input

    async def cancel_before_pause(session, job_id, lease_token, *, result):
        async with AsyncSessionLocal() as controller:
            cancelled = await cancel_job(controller, job_id)
            assert cancelled.status is JobStatus.CANCEL_REQUESTED
        return await actual_pause(session, job_id, lease_token, result=result)

    monkeypatch.setattr(inputs, "pause_job_for_input", cancel_before_pause)
    async with AsyncSessionLocal() as session:
        job = await session.get(DurableJob, turn.job_id)

    async def dispatch(session, job):
        await session.commit()
        return turn.result

    finished = await run_claimed_job(job, dispatcher=dispatch)
    assert finished.status is JobStatus.CANCELLED
    async with AsyncSessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(MissionInputRequest).where(
            MissionInputRequest.durable_job_id == turn.job_id)) == 0
        assert (await session.get(Mission, turn.mission_id)).status is MissionStatus.CANCELLED
        assert (await session.get(MissionAttempt, turn.attempt_id)).status is MissionAttemptStatus.CANCELLED


@pytest.mark.asyncio
async def test_pause_fences_expiry_after_events_and_rolls_back_every_state(owned_turn, monkeypatch):
    turn = owned_turn
    calls = 0

    async def advancing_database_clock(session):
        nonlocal calls
        calls += 1
        return turn.expires - timedelta(seconds=1) if calls == 1 else turn.expires

    monkeypatch.setattr(inputs, "_now", advancing_database_clock)
    async with AsyncSessionLocal() as session:
        before_events = await event_counts(session, turn.job_id)
        with pytest.raises(JobLeaseLost, match="before suspension commit"):
            await pause_job_for_input(session, turn.job_id, turn.token, result=turn.result)
        assert calls == 2
        job = await session.get(DurableJob, turn.job_id)
        assert job.status is JobStatus.RUNNING and job.lease_token == turn.token and job.result is None
        assert (await session.get(Mission, turn.mission_id)).status is MissionStatus.RUNNING
        assert (await session.get(AgentSessionRecord, turn.agent_id)).status is AgentSessionStatus.RUNNING
        assert (await session.get(MissionAttempt, turn.attempt_id)).provider_metadata == {}
        assert await session.scalar(select(func.count()).select_from(MissionInputRequest).where(
            MissionInputRequest.durable_job_id == turn.job_id)) == 0
        assert await event_counts(session, turn.job_id) == before_events
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == turn.mission_id, AuditEvent.action == "mission.waiting_input")) == 0


@pytest.mark.asyncio
async def test_generic_resumed_handler_failure_preserves_only_committed_checkpoint(owned_turn):
    turn = owned_turn
    request_id = await pause(turn)
    claimed = await answer_and_claim(turn, request_id)

    async def broken_restore(session, job):
        await session.commit()
        speculative_result = {"steps": [{"uncommitted": True}], "workspace": "/wrong"}
        assert speculative_result != job.result
        raise RuntimeError("provider restore failed before progress could commit")

    failed = await run_claimed_job(claimed, dispatcher=broken_restore)
    assert failed.status is JobStatus.FAILED and failed.error_code == "RUNTIMEERROR"
    assert failed.result["reason"] == "FAILED" and failed.result["resume_stopped"] is True
    assert failed.result["steps"] == turn.result["steps"] and failed.result["workspace"] == "."
    assert failed.result["input_request_id"] == str(request_id)
    async with AsyncSessionLocal() as session:
        request = await session.get(MissionInputRequest, request_id)
        assert request.answer == "zero is supported" and request.status is InputRequestStatus.CANCELLED
        assert (await session.get(MissionAttempt, turn.attempt_id)).status is MissionAttemptStatus.FAILED
        assert (await session.get(Mission, turn.mission_id)).status is MissionStatus.RETRYING


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("question", "rewritten"), ("options", ["rewritten"]),
                                         ("durable_job_id", uuid7()), ("agent_session_id", uuid7())])
async def test_database_rejects_question_or_ownership_rewrite(owned_turn, field, value):
    request_id = await pause(owned_turn)
    async with AsyncSessionLocal() as session:
        request = await session.get(MissionInputRequest, request_id)
        setattr(request, field, value)
        with pytest.raises(DBAPIError, match="question and ownership are immutable"):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_database_rejects_answer_rewrite_deletion_and_closed_history(owned_turn):
    request_id = await pause(owned_turn)
    async with AsyncSessionLocal() as session:
        request, _ = await answer_input_request(session, request_id, answer="original",
                                              expected_row_version=1, idempotency_key="immutable-answer")
        request.answer = "rewritten"
        request.status, request.consumed_at, request.row_version = InputRequestStatus.CONSUMED, request.answered_at, 3
        with pytest.raises(DBAPIError, match="human answer is immutable"):
            await session.commit()
        await session.rollback()
        request = await session.get(MissionInputRequest, request_id)
        await session.delete(request)
        with pytest.raises(DBAPIError, match="append-only"):
            await session.commit()
        await session.rollback()
        request = await session.get(MissionInputRequest, request_id)
        request.status, request.consumed_at, request.row_version = InputRequestStatus.CONSUMED, request.answered_at, 3
        await session.commit()
        request.cancelled_at, request.status, request.row_version = request.answered_at, InputRequestStatus.CANCELLED, 4
        with pytest.raises(DBAPIError, match="closed human input history is immutable"):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,message", [
    ({"status": InputRequestStatus.ANSWERED}, "human input must begin pending"),
    ({"question_id": " "}, "identifier must be bounded"),
    ({"question_id": "q" * 129}, "value too long|identifier must be bounded"),
    ({"options": ["duplicate", "duplicate"]}, "distinct bounded"),
    ({"options": [""]}, "distinct bounded"),
    ({"options": [42]}, "distinct bounded"),
    ({"options": ["x" * 257]}, "distinct bounded"),
    ({"options": [str(i) for i in range(9)]}, "bounded array"),
])
async def test_database_enforces_question_insert_contract(owned_turn, changes, message):
    turn = owned_turn
    values = {"id": uuid7(), "key": public_key("Q"), "test_run_id": turn.run_id,
              "mission_id": turn.mission_id, "attempt_id": turn.attempt_id,
              "agent_session_id": turn.agent_id, "durable_job_id": turn.job_id,
              "question_id": "policy", "question": "Which behavior?", "options": [],
              "status": InputRequestStatus.PENDING, "row_version": 1, **changes}
    async with AsyncSessionLocal() as session:
        session.add(MissionInputRequest(**values))
        with pytest.raises(DBAPIError, match=message):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_database_rejects_cross_run_agent_and_blank_answer_key(owned_turn):
    turn = owned_turn
    async with AsyncSessionLocal() as session:
        other = await create_run(session)
        agent = await session.get(AgentSessionRecord, turn.agent_id)
        agent.test_run_id = other.id
        await session.commit()
        request = MissionInputRequest(id=uuid7(), key=public_key("Q"), test_run_id=turn.run_id,
                                      mission_id=turn.mission_id, attempt_id=turn.attempt_id,
                                      agent_session_id=turn.agent_id, durable_job_id=turn.job_id,
                                      question_id="policy", question="Which behavior?", options=[],
                                      status=InputRequestStatus.PENDING, row_version=1)
        session.add(request)
        with pytest.raises(DBAPIError, match="ownership mismatch"):
            await session.commit()
        await session.rollback()
        agent = await session.get(AgentSessionRecord, turn.agent_id)
        agent.test_run_id = turn.run_id
        await session.commit()
    request_id = await pause(turn)
    async with AsyncSessionLocal() as session:
        request = await session.get(MissionInputRequest, request_id)
        now = await session.scalar(select(func.clock_timestamp()))
        request.status, request.answer = InputRequestStatus.ANSWERED, "valid answer"
        request.answered_at = now
        request.answer_idempotency_key, request.row_version = "  ", 2
        with pytest.raises(DBAPIError, match="idempotency key must be nonblank"):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,message", [
    ({"agent_session_id": str(uuid7())}, "current owned attempt"),
    ({"mission_id": str(uuid7())}, "current owned attempt"),
    ({"workspace_id": "another-workspace"}, "workspace identity changed"),
    ({"provider_session_id": " "}, "resumable session reference"),
])
async def test_pause_rejects_foreign_or_nonresumable_marker_without_state_change(owned_turn, changes, message):
    turn = owned_turn
    result = turn.result
    result["_waiting_input"].update(changes)
    async with AsyncSessionLocal() as session:
        before_events = await event_counts(session, turn.job_id)
        with pytest.raises(ConflictError, match=message):
            await pause_job_for_input(session, turn.job_id, turn.token, result=result)
        await session.rollback()
        job = await session.get(DurableJob, turn.job_id)
        assert job.status is JobStatus.RUNNING and job.lease_token == turn.token and job.result is None
        assert (await session.get(Mission, turn.mission_id)).status is MissionStatus.RUNNING
        assert await session.scalar(select(func.count()).select_from(MissionInputRequest).where(
            MissionInputRequest.durable_job_id == turn.job_id)) == 0
        assert await event_counts(session, turn.job_id) == before_events


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True], ids=["interrupted", "cancelled"])
async def test_terminal_resume_keeps_checkpoint_and_discards_handler_result(owned_turn, cancelled):
    turn = owned_turn
    request_id = await pause(turn)
    claimed = await answer_and_claim(turn, request_id)
    async with AsyncSessionLocal() as session:
        if cancelled:
            await cancel_job(session, turn.job_id)
        finished = await finish_job(session, turn.job_id, claimed.lease_token,
                                    result={"steps": [{"speculative": True}]},
                                    error_code=None if cancelled else "TEST_SHUTDOWN",
                                    interrupted=not cancelled)
        assert finished.status is (JobStatus.CANCELLED if cancelled else JobStatus.INTERRUPTED)
        assert finished.result["reason"] == finished.status.value
        assert finished.result["resume_stopped"] is True
        assert finished.result["steps"] == turn.result["steps"]
        assert finished.result["workspace"] == "." and finished.result["input_request_id"] == str(request_id)


@pytest.mark.asyncio
async def test_database_answer_transition_requires_exactly_one_version_advance(owned_turn):
    request_id = await pause(owned_turn)
    async with AsyncSessionLocal() as session:
        request = await session.get(MissionInputRequest, request_id)
        now = await session.scalar(select(func.clock_timestamp()))
        request.status, request.answer = InputRequestStatus.ANSWERED, "valid answer"
        request.answered_at, request.answer_idempotency_key = now, "version-test"
        request.row_version = 3
        with pytest.raises(DBAPIError, match="version must advance once"):
            await session.commit()
        await session.rollback()
        request = await session.get(MissionInputRequest, request_id)
        assert request.status is InputRequestStatus.PENDING and request.answer is None and request.row_version == 1
