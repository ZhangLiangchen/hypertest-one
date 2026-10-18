"""Real PostgreSQL control-contract tests; no model or official Runner is substituted."""

from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from test_test_design import create_run, requirement_proposal

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.application.inputs import answer_input_request, pause_job_for_input
from hypertest.application.jobs import FencedAsyncSession, finish_job
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import MissionRuntimeError, execute_mission
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal, engine
from hypertest.domain.enums import AgentSessionStatus, MissionAttemptStatus, MissionStatus
from hypertest.domain.inputs import InputRequestStatus, MissionInputRequest
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    MissionAttempt,
    Requirement,
    utcnow,
)
from hypertest.protocol import MissionResultSubmission


class ClarifyingHarness:
    def __init__(self, *, missing_session=False, wait_again=False):
        self.created = self.restored = self.resumed = self.closed = 0
        self.contract = None
        self.session = None
        self.missing_session = missing_session
        self.wait_again = wait_again

    async def create_session(self, workspace):
        self.created += 1
        return AgentSession(public_key("AS"), "codex", str(uuid7()))

    async def execute(self, session, mission):
        self.session = session
        self.contract = deepcopy(mission)
        yield AgentEvent("RESULT_SUBMITTED", {
            "protocol": mission["protocol"], "mission_id": mission["mission_id"],
            "status": "WAITING_INPUT", "proposals": [],
            "input_request": {"question_id": "zero-policy", "question": "Is zero supported?",
                              "options": ["yes", "no"]},
        })

    async def restore_session(self, session, workspace):
        if self.missing_session:
            raise RuntimeError("native provider session is missing")
        self.restored += 1
        self.session = session
        return session

    async def resume(self, session, mission):
        self.resumed += 1
        self.contract = deepcopy(mission)
        if self.wait_again:
            yield AgentEvent("RESULT_SUBMITTED", {
                "protocol": mission["protocol"], "mission_id": mission["mission_id"],
                "status": "WAITING_INPUT", "proposals": [],
                "input_request": {"question_id": "large-policy", "question": "Are large integers supported?",
                                  "options": []},
            })
            return
        yield AgentEvent("RESULT_SUBMITTED", {
            "protocol": mission["protocol"], "mission_id": mission["mission_id"],
            "status": "COMPLETED", "input_request": None,
            "proposals": [requirement_proposal()],
        })

    async def interrupt(self, session):
        pass

    async def close(self, session):
        self.closed += 1


@pytest.mark.parametrize("changes", [
    {"input_request": None},
    {"proposals": [requirement_proposal()]},
    {"input_request": {"question_id": "q", "question": " ", "options": []}},
    {"input_request": {"question_id": "q", "question": "?", "options": ["yes"] * 2}},
    {"input_request": {"question_id": "q", "question": "?", "options": [str(i) for i in range(9)]}},
])
def test_waiting_input_rejects_missing_question_or_embedded_proposals(changes):
    payload = {"mission_id": "MIS-q", "status": "WAITING_INPUT", "proposals": [],
               "input_request": {"question_id": "q", "question": "Which behavior?", "options": []}}
    with pytest.raises(ValidationError):
        MissionResultSubmission.model_validate({**payload, **changes})


async def reserve_job(session, run, mission):
    now = utcnow()
    job = DurableJob(
        id=uuid7(), key=public_key("JOB"), project_id=run.project_id, test_run_id=run.id,
        mission_id=mission.id, job_type=JobType.EXECUTE_MISSION, status=JobStatus.RUNNING,
        idempotency_key=public_key("test-input"), payload={"workspace": ".", "provider": "codex"},
        attempts=1, lease_token=uuid7(), worker_id="waiting-input-runtime-test",
        heartbeat_at=now, lease_expires_at=now + timedelta(minutes=10), started_at=now,
    )
    session.add(job)
    await session.commit()
    return job


async def initial_wait():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission = (await plan_next_mission(session, run.id)).mission
        frozen = deepcopy(mission.spec), mission.spec_sha256
        job = await reserve_job(session, run, mission)
        ids = run.id, mission.id, job.id, job.lease_token
    harness = ClarifyingHarness()
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=ids[2],
                                  lease_token=ids[3], test_run_id=ids[0]) as session:
        result = await execute_mission(session, ids[1], ".", harness=harness)
        assert result.waiting_input is not None
        assert result.mission.status is MissionStatus.RUNNING  # Worker owns the atomic pause.
        assert result.attempt.status is MissionAttemptStatus.RUNNING
        assert await session.scalar(select(func.count()).select_from(Requirement).where(
            Requirement.source_snapshot_id == run.source_snapshot_id)) == 0
        marker = result.waiting_input
    assert harness.closed == 0
    async with AsyncSessionLocal() as session:
        paused = await pause_job_for_input(session, ids[2], ids[3], result={
            "reason": "WAITING_INPUT", "steps": [], "workspace": ".", "_waiting_input": marker,
        })
        assert paused.status is JobStatus.WAITING_INPUT and paused.lease_token is None
        question = await session.scalar(select(MissionInputRequest).where(
            MissionInputRequest.durable_job_id == ids[2]))
        return ids, frozen, marker, question.id, question.row_version, harness


async def answer_and_claim(job_id, question_id, version, answer):
    async with AsyncSessionLocal() as session:
        await answer_input_request(session, question_id, answer=answer,
                                   expected_row_version=version, idempotency_key=f"answer:{question_id}")
        job = await session.get(DurableJob, job_id)
        assert job.status is JobStatus.QUEUED
        token = uuid7()
        job.status, job.lease_token, job.worker_id = JobStatus.RUNNING, token, "resumed-worker"
        job.lease_expires_at = utcnow() + timedelta(minutes=10)
        job.attempts += 1
        await session.commit()
        return token


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_session", [False, True])
async def test_answer_resumes_same_owned_attempt_after_runtime_recreation(missing_session):
    ids, frozen, marker, question_id, version, first = await initial_wait()
    # A new Worker claim receives a new fence; queue ordering is covered separately.
    token = await answer_and_claim(ids[2], question_id, version, "zero is supported")
    resumed = ClarifyingHarness(missing_session=missing_session)
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=ids[2],
                                  lease_token=token, test_run_id=ids[0]) as session:
        if missing_session:
            with pytest.raises(MissionRuntimeError, match="could not be restored"):
                await execute_mission(session, ids[1], ".", harness=resumed)
            assert resumed.created == resumed.resumed == 0
            await session.rollback()
        else:
            result = await execute_mission(session, ids[1], ".", harness=resumed)
            assert result.attempt.id.hex == marker["attempt_id"].replace("-", "")
            assert result.attempt.agent_session_id.hex == marker["agent_session_id"].replace("-", "")
            assert result.attempt.status is MissionAttemptStatus.ACCEPTED
            assert result.mission.status is MissionStatus.COMPLETED
            assert (result.mission.spec, result.mission.spec_sha256) == frozen
            assert resumed.created == 0 and resumed.restored == resumed.resumed == resumed.closed == 1
            assert resumed.session.id == first.session.id
            assert resumed.session.provider_session_id == first.session.provider_session_id
            assert resumed.contract["context"]["human_inputs"][0]["answer"] == "zero is supported"
            question = await session.get(MissionInputRequest, question_id)
            assert question.status is InputRequestStatus.CONSUMED
            assert question.answer == "zero is supported" and question.consumed_at is not None
            assert await session.scalar(select(func.count()).select_from(MissionAttempt).where(
                MissionAttempt.mission_id == ids[1])) == 1
            assert (await session.get(AgentSessionRecord, result.attempt.agent_session_id)).status is AgentSessionStatus.CLOSED
    async with AsyncSessionLocal() as session:
        await finish_job(session, ids[2], token, result={},
                         error_code="TEST_RESUME_MISSING" if missing_session else None)


@pytest.mark.asyncio
async def test_two_input_rounds_keep_one_attempt_and_distinct_consumption_history():
    ids, frozen, marker, first_id, version, _ = await initial_wait()
    token = await answer_and_claim(ids[2], first_id, version, "zero is supported")
    asking_again = ClarifyingHarness(wait_again=True)
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=ids[2],
                                  lease_token=token, test_run_id=ids[0]) as session:
        again = await execute_mission(session, ids[1], ".", harness=asking_again)
        assert again.waiting_input["attempt_id"] == marker["attempt_id"]
        second_marker = again.waiting_input
    assert asking_again.closed == 0
    async with AsyncSessionLocal() as session:
        job = await pause_job_for_input(session, ids[2], token, result={
            "steps": [], "workspace": ".", "_waiting_input": second_marker,
        })
        question = await session.get(MissionInputRequest, UUID(job.result["input_request_id"]))
        second_id, second_version = question.id, question.row_version
    token = await answer_and_claim(ids[2], second_id, second_version, "large integers are supported")
    final = ClarifyingHarness()
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=ids[2],
                                  lease_token=token, test_run_id=ids[0]) as session:
        accepted = await execute_mission(session, ids[1], ".", harness=final)
        assert accepted.attempt.id == again.attempt.id
        assert (accepted.mission.spec, accepted.mission.spec_sha256) == frozen
        assert len(final.contract["context"]["human_inputs"]) == 2
        questions = list(await session.scalars(select(MissionInputRequest).where(
            MissionInputRequest.attempt_id == accepted.attempt.id)))
        assert len(questions) == 2 and all(q.status is InputRequestStatus.CONSUMED for q in questions)
        resumed_events = list(await session.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == ids[1], AuditEvent.action == "mission.resumed")))
        assert len(resumed_events) == 2
        assert len({event.event_metadata["event_key"] for event in resumed_events}) == 2
    async with AsyncSessionLocal() as session:
        await finish_job(session, ids[2], token, result={})


@pytest.mark.asyncio
async def test_direct_wait_fails_explicitly_without_a_dangling_question():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission = (await plan_next_mission(session, run.id)).mission
        harness = ClarifyingHarness()
        with pytest.raises(MissionRuntimeError, match="durable job"):
            await execute_mission(session, mission.id, ".", harness=harness)
        assert harness.closed == 1
        assert await session.scalar(select(func.count()).select_from(MissionInputRequest).where(
            MissionInputRequest.mission_id == mission.id)) == 0
        await session.refresh(mission)
        assert mission.status is MissionStatus.RETRYING
