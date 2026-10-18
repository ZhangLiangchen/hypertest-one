"""Real PostgreSQL ownership, immutable history and dual-scope input contracts."""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_test_design import create_run

from hypertest.application.bindings import (
    activate_run_binding,
    assert_binding_claim,
    create_run_binding,
    recover_run_binding,
    transition_binding,
)
from hypertest.application.inputs import answer_input_request, cancel_open_inputs
from hypertest.application.jobs import JobLeaseLost, submit_job
from hypertest.application.planner import plan_next_mission
from hypertest.application.run_inputs import consume_run_input_request, pause_run_for_input
from hypertest.application.services import ConflictError
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
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
from hypertest.domain.run_inputs import RunInputRequest
from hypertest.main import app


async def own_job(session, job):
    now = await session.scalar(select(func.clock_timestamp()))
    job.status, job.worker_id, job.lease_token = JobStatus.RUNNING, "binding-test-worker", uuid7()
    job.started_at, job.heartbeat_at, job.lease_expires_at = now, now, now + timedelta(minutes=5)
    job.attempts += 1
    await session.commit()
    return job.lease_token


@pytest.fixture
async def bound_run():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        job = await submit_job(session, run.id, JobType.ADVANCE_RUN, payload={"workspace": "."}, idempotency_key="binding")
        token = await own_job(session, job)
        binding = await create_run_binding(session, run.id, job_id=job.id, lease_token=token,
                                           logical_worker_id=uuid7(), harness_host_id="host-test",
                                           workspace_id=str(uuid7()))
        await session.commit()
        native = str(uuid7())
        await activate_run_binding(session, binding.id, 1, job_id=job.id, lease_token=token, provider_session_id=native)
        await session.commit()
        value = {"run_id": run.id, "binding_id": binding.id, "agent_id": binding.primary_agent_session_id,
                 "job_id": job.id, "token": token, "native": native, "workspace": binding.workspace_id,
                 "logical_worker_id": binding.logical_worker_id}
    try:
        yield value
    finally:
        async with AsyncSessionLocal() as session:
            job = await session.get(DurableJob, value["job_id"])
            await cancel_open_inputs(session, job)
            if job.status in ACTIVE_JOB_STATUSES:
                job.status, job.finished_at, job.lease_expires_at = JobStatus.FAILED, await session.scalar(select(func.clock_timestamp())), None
            await session.commit()


async def pause(bound):
    async with AsyncSessionLocal() as session:
        job = await pause_run_for_input(session, bound["binding_id"], 1, job_id=bound["job_id"],
            lease_token=bound["token"], input_request={"question_id": "report-decision", "question": "Generate the report?", "options": ["yes", "no"]},
            checkpoint={"steps": [{"accepted": True}], "workspace": bound["workspace"]})
        return UUID(job.result["input_request_id"])


@pytest.mark.asyncio
async def test_binding_identity_native_session_and_epoch_are_database_protected(bound_run):
    bound = bound_run
    for field, value, message in (
        ("logical_worker_id", uuid7(), "ownership is immutable"),
        ("workspace_id", "replacement", "ownership is immutable"),
        ("binding_epoch", 2, "invalid run binding transition|only explicit recovery"),
    ):
        async with AsyncSessionLocal() as session:
            row = await session.get(RunExecutionBinding, bound["binding_id"])
            setattr(row, field, value)
            with pytest.raises(DBAPIError, match=message):
                await session.commit()
            await session.rollback()
    async with AsyncSessionLocal() as session:
        agent = await session.get(AgentSessionRecord, bound["agent_id"])
        agent.provider_session_id = str(uuid7())
        with pytest.raises(DBAPIError, match="native session reference is immutable"):
            await session.commit()
        await session.rollback()
        session.add(AgentSessionRecord(test_run_id=bound["run_id"], provider="codex", harness="codex", workspace_id="new"))
        with pytest.raises(DBAPIError, match="cannot create a replacement session"):
            await session.commit()
        await session.rollback()
        binding = await session.get(RunExecutionBinding, bound["binding_id"])
        await session.delete(binding)
        with pytest.raises(DBAPIError, match="binding history is immutable"):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", ["epoch", "claim", "worker", "host"])
async def test_binding_claim_rejects_stale_or_foreign_owner(bound_run, wrong):
    bound = bound_run
    kwargs = {"job_id": bound["job_id"], "lease_token": uuid7() if wrong == "claim" else bound["token"],
              "logical_worker_id": uuid7() if wrong == "worker" else bound["logical_worker_id"],
              "harness_host_id": "other" if wrong == "host" else "host-test"}
    async with AsyncSessionLocal() as session:
        with pytest.raises(JobLeaseLost):
            await assert_binding_claim(session, bound["binding_id"], 2 if wrong == "epoch" else 1, **kwargs)


@pytest.mark.asyncio
async def test_boundary_answer_resumes_same_job_and_session_without_reopening_stage(bound_run):
    bound = bound_run
    async with AsyncSessionLocal() as session:
        mission = (await plan_next_mission(session, bound["run_id"])).mission
        now = await session.scalar(select(func.clock_timestamp()))
        attempt = MissionAttempt(id=uuid7(), mission_id=mission.id, attempt_no=1, durable_job_id=bound["job_id"],
                                 agent_session_id=bound["agent_id"], provider="codex", harness="codex",
                                 status=MissionAttemptStatus.ACCEPTED, started_at=now, finished_at=now)
        session.add(attempt)
        mission.status, mission.current_attempt_no = MissionStatus.COMPLETED, 1
        mission.completed_at = now
        await session.commit()
        mission_id, attempt_id = mission.id, attempt.id
        job = await pause_run_for_input(session, bound["binding_id"], 1, job_id=bound["job_id"], lease_token=bound["token"],
            input_request={"question_id": "complete-stage", "question": "Proceed?", "options": []},
            checkpoint={"steps": [{"mission_id": str(mission.id)}]}, context_mission_id=mission.id, context_attempt_id=attempt.id)
        request_id = UUID(job.result["input_request_id"])
        assert job.status is JobStatus.WAITING_INPUT and job.lease_token is None
        binding = await session.get(RunExecutionBinding, bound["binding_id"])
        assert binding.status is BindingStatus.WAITING_INPUT and binding.binding_epoch == 1
        assert (await session.get(AgentSessionRecord, bound["agent_id"])).provider_session_id == bound["native"]
    answer = {"answer": "  Continue\n继续。 ", "expected_row_version": 1, "idempotency_key": "answer-boundary"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listing = await client.get(f"/api/v1/test-runs/{bound['run_id']}/input-requests")
        assert listing.status_code == 200
        assert listing.json()[0]["scope"] == "run" and listing.json()[0]["mission_id"] is None
        assert listing.json()[0]["context_mission_id"] == str(mission_id)
        accepted = await client.post(f"/api/v1/input-requests/{request_id}/answer", json=answer)
        assert accepted.status_code == 202 and accepted.json()["job"]["id"] == str(bound["job_id"])
        repeated = await client.post(f"/api/v1/input-requests/{request_id}/answer", json=answer)
        assert repeated.json() == accepted.json()
    async with AsyncSessionLocal() as session:
        job = await session.get(DurableJob, bound["job_id"])
        token = await own_job(session, job)
        request = await consume_run_input_request(session, request_id, binding_id=bound["binding_id"], binding_epoch=1,
            job_id=job.id, lease_token=token, provider_session_id=bound["native"], workspace_id=bound["workspace"])
        assert request.status is InputRequestStatus.CONSUMED and request.answer == answer["answer"]
        binding = await session.get(RunExecutionBinding, bound["binding_id"])
        assert binding.status is BindingStatus.ACTIVE and binding.binding_epoch == 1
        assert (await session.get(Mission, mission_id)).status is MissionStatus.COMPLETED
        assert (await session.get(MissionAttempt, attempt_id)).status is MissionAttemptStatus.ACCEPTED
        assert await session.scalar(select(func.count()).select_from(AgentSessionRecord).where(AgentSessionRecord.test_run_id == bound["run_id"])) == 1
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == request_id)) == 3
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == request_id)) == 3


@pytest.mark.asyncio
async def test_explicit_recovery_fences_then_advances_once_without_rebinding(bound_run):
    bound = bound_run
    async with AsyncSessionLocal() as session:
        binding = await session.get(RunExecutionBinding, bound["binding_id"])
        await transition_binding(session, binding, BindingStatus.RECOVERY_REQUIRED, reason="worker_lost")
        job = await session.get(DurableJob, bound["job_id"])
        job.status, job.finished_at, job.lease_expires_at = JobStatus.INTERRUPTED, await session.scalar(select(func.clock_timestamp())), None
        await session.commit()
        version = binding.row_version
        kwargs = {"expected_epoch": 1, "expected_row_version": version, "provider_session_id": bound["native"],
                  "workspace_id": bound["workspace"], "harness_host_id": "host-test", "workspace_verified": True}
        with pytest.raises(ConflictError, match="fenced old calls"):
            await recover_run_binding(session, binding.id, prior_calls_fenced=False, **kwargs)
        await session.rollback()
        recovered = await recover_run_binding(session, bound["binding_id"], prior_calls_fenced=True, **kwargs)
        await session.commit()
        assert recovered.binding_epoch == 2 and recovered.primary_agent_session_id == bound["agent_id"]
        assert recovered.logical_worker_id == bound["logical_worker_id"]
        with pytest.raises(ConflictError):
            await recover_run_binding(session, recovered.id, prior_calls_fenced=True, **kwargs)


@pytest.mark.asyncio
async def test_run_question_cancellation_preserves_answer_and_does_not_increase_epoch(bound_run):
    bound = bound_run
    request_id = await pause(bound)
    async with AsyncSessionLocal() as session:
        await answer_input_request(session, request_id, answer="keep this", expected_row_version=1, idempotency_key="keep")
        job = await session.get(DurableJob, bound["job_id"])
        await cancel_open_inputs(session, job)
        job.status, job.finished_at = JobStatus.CANCELLED, await session.scalar(select(func.clock_timestamp()))
        await session.commit()
        request = await session.get(RunInputRequest, request_id)
        assert request.status is InputRequestStatus.CANCELLED and request.answer == "keep this"
        binding = await session.get(RunExecutionBinding, bound["binding_id"])
        assert binding.binding_epoch == 1
        with pytest.raises(ConflictError):
            await answer_input_request(session, request_id, answer="replace", expected_row_version=3, idempotency_key="replace")
        await session.rollback()
        with pytest.raises(DBAPIError, match="question and ownership are immutable"):
            await session.execute(text("UPDATE run_input_requests SET question='rewrite' WHERE id=:id"), {"id": request_id})
        await session.rollback()


@pytest.mark.asyncio
async def test_dual_scope_questions_share_one_database_reservation(bound_run):
    import asyncio

    bound = bound_run
    async with AsyncSessionLocal() as session:
        mission = (await plan_next_mission(session, bound["run_id"])).mission
        attempt = MissionAttempt(id=uuid7(), mission_id=mission.id, attempt_no=1, durable_job_id=bound["job_id"],
                                 agent_session_id=bound["agent_id"], provider="codex", harness="codex",
                                 status=MissionAttemptStatus.ACCEPTED)
        mission.status, mission.current_attempt_no = MissionStatus.COMPLETED, 1
        session.add(attempt)
        await session.commit()
        mission_id, attempt_id = mission.id, attempt.id
    common = {"test_run_id": bound["run_id"], "agent_session_id": bound["agent_id"], "durable_job_id": bound["job_id"],
              "question": "One question at a time", "options": [], "status": InputRequestStatus.PENDING, "row_version": 1}
    async with AsyncSessionLocal() as first:
        run_question = RunInputRequest(id=uuid7(), key=public_key("Q"), binding_id=bound["binding_id"], question_id="first", **common)
        first.add(run_question)
        await first.flush()

        async def concurrent_other_scope():
            async with AsyncSessionLocal() as second:
                second.add(MissionInputRequest(id=uuid7(), key=public_key("Q"), mission_id=mission_id,
                                              attempt_id=attempt_id, question_id="second", **common))
                with pytest.raises(DBAPIError, match="already has an open human input"):
                    await second.commit()
                await second.rollback()

        task = asyncio.create_task(concurrent_other_scope())
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
            await first.commit()
            await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with AsyncSessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(MissionInputRequest).where(MissionInputRequest.test_run_id == bound["run_id"])) == 0
        assert await session.scalar(select(func.count()).select_from(RunInputRequest).where(RunInputRequest.test_run_id == bound["run_id"])) == 1


@pytest.mark.asyncio
async def test_legacy_sessions_cannot_be_promoted_or_rewritten_as_a_binding():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        legacy = AgentSessionRecord(test_run_id=run.id, provider="codex", harness="old", workspace_id="old",
                                    provider_session_id=str(uuid7()), status=AgentSessionStatus.CLOSED)
        session.add(legacy)
        await session.commit()
        job = await submit_job(session, run.id, JobType.ADVANCE_RUN, payload={"workspace": "."}, idempotency_key="legacy-new-binding")
        token = await own_job(session, job)
        run_id, job_id = run.id, job.id
        with pytest.raises(ConflictError, match="legacy session history"):
            await create_run_binding(session, run_id, job_id=job_id, lease_token=token, logical_worker_id=uuid7(),
                                     harness_host_id="host-test", workspace_id="new")
        await session.rollback()
        job = await session.get(DurableJob, job_id)
        job.status, job.finished_at, job.lease_expires_at = JobStatus.FAILED, await session.scalar(select(func.clock_timestamp())), None
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(RunExecutionBinding).where(RunExecutionBinding.test_run_id == run_id)) == 0


@pytest.mark.asyncio
async def test_single_active_attempt_is_enforced_without_blocking_other_runs(bound_run):
    bound = bound_run
    async with AsyncSessionLocal() as session:
        mission = (await plan_next_mission(session, bound["run_id"])).mission
        one = MissionAttempt(id=uuid7(), mission_id=mission.id, attempt_no=1, durable_job_id=bound["job_id"],
                             agent_session_id=bound["agent_id"], provider="codex", harness="codex", status=MissionAttemptStatus.RUNNING)
        session.add(one)
        await session.commit()
        mission_id, attempt_id = mission.id, one.id
        session.add(MissionAttempt(mission_id=mission_id, attempt_no=2, durable_job_id=bound["job_id"],
                    agent_session_id=bound["agent_id"], provider="codex", harness="codex", status=MissionAttemptStatus.RUNNING))
        with pytest.raises(DBAPIError, match="only one active attempt"):
            await session.commit()
        await session.rollback()
        with pytest.raises(ConflictError, match="mission-scoped"):
            await pause_run_for_input(session, bound["binding_id"], 1, job_id=bound["job_id"], lease_token=bound["token"],
                input_request={"question_id": "wrong-scope", "question": "Question?", "options": []}, checkpoint={})
        await session.rollback()
        one = await session.get(MissionAttempt, attempt_id)
        one.status = MissionAttemptStatus.FAILED
        await session.commit()


async def test_run_question_create_replay_returns_original_without_suspending_consumed_answer(bound_run):
    bound = bound_run
    request_id = await pause(bound)
    # A duplicate create can arrive after its claim was released by suspension.
    assert await pause(bound) == request_id
    async with AsyncSessionLocal() as session:
        request, job = await answer_input_request(session, request_id, answer="yes",
            expected_row_version=1, idempotency_key="original-answer")
        token = await own_job(session, job)
        await consume_run_input_request(session, request_id, binding_id=bound["binding_id"], binding_epoch=1,
            job_id=job.id, lease_token=token, provider_session_id=bound["native"], workspace_id=bound["workspace"])
        original_result = dict(job.result)
    assert await pause(bound) == request_id
    async with AsyncSessionLocal() as session:
        request = await session.get(RunInputRequest, request_id)
        job = await session.get(DurableJob, bound["job_id"])
        binding = await session.get(RunExecutionBinding, bound["binding_id"])
        assert request.status is InputRequestStatus.CONSUMED and request.answer == "yes"
        assert job.status is JobStatus.RUNNING and job.lease_token == token and job.result == original_result
        assert binding.status is BindingStatus.ACTIVE and binding.binding_epoch == 1
        assert len(list(await session.scalars(select(RunInputRequest).where(RunInputRequest.binding_id == binding.id)))) == 1
        with pytest.raises(ConflictError, match="different input"):
            await pause_run_for_input(session, binding.id, 1, job_id=job.id, lease_token=token,
                input_request={"question_id":"report-decision","question":"Different question","options":["yes","no"]}, checkpoint={})


async def test_bound_attempt_cannot_move_to_unbound_run_or_reopen_terminal_history(bound_run):
    bound = bound_run
    async with AsyncSessionLocal() as session:
        mission = (await plan_next_mission(session, bound["run_id"])).mission
        attempt = MissionAttempt(id=uuid7(), mission_id=mission.id, attempt_no=1,
            agent_session_id=bound["agent_id"], provider="codex", harness="codex", status=MissionAttemptStatus.ACCEPTED)
        session.add(attempt)
        await session.commit()
        attempt_id = attempt.id
        legacy = await create_run(session)
        other_mission = (await plan_next_mission(session, legacy.id)).mission
        other_id = other_mission.id
    async with AsyncSessionLocal() as session:
        row = await session.get(MissionAttempt, attempt_id)
        row.mission_id = other_id
        with pytest.raises(DBAPIError, match="persistent attempt ownership is immutable"):
            await session.commit()
        await session.rollback()
        row = await session.get(MissionAttempt, attempt_id)
        row.status = MissionAttemptStatus.RUNNING
        with pytest.raises(DBAPIError, match="cannot be reopened"):
            await session.commit()
        await session.rollback()
        row = await session.get(MissionAttempt, attempt_id)
        await session.delete(row)
        with pytest.raises(DBAPIError, match="history cannot be deleted"):
            await session.commit()
        await session.rollback()


@pytest.mark.parametrize("mode", ["direct", "queued"])
async def test_manual_mission_api_cannot_mutate_bound_harness_owned_stages(bound_run, monkeypatch, mode):
    from hypertest.config import get_settings

    monkeypatch.setattr(get_settings(), "execution_mode", mode)
    async with AsyncSessionLocal() as session:
        mission = (await plan_next_mission(session, bound_run["run_id"])).mission
        mission_id = mission.id
        before_status = mission.status
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for endpoint, body in (
            (f"/test-runs/{bound_run['run_id']}/plan-next", {}),
            (f"/test-runs/{bound_run['run_id']}/missions", {"mission_type":"ANALYZE_REQUIREMENTS", "objective":"manual bypass", "spec":{}, "idempotency_key":"bypass"}),
            (f"/missions/{mission_id}/retry", {}),
            (f"/missions/{mission_id}/cancel", {}),
        ):
            response = await client.post("/api/v1"+endpoint, json=body)
            assert response.status_code == 409, response.text
            assert "task controls" in response.text
        assert (await client.get(f"/api/v1/missions/{mission_id}")).status_code == 200
    async with AsyncSessionLocal() as session:
        assert (await session.get(Mission, mission_id)).status is before_status
        assert len(list(await session.scalars(select(Mission).where(Mission.test_run_id == bound_run["run_id"])))) == 1


async def test_synchronous_execution_cannot_reenter_bound_run_even_without_active_job(bound_run, monkeypatch):
    from hypertest.config import get_settings

    monkeypatch.setattr(get_settings(), "execution_mode", "inline")
    async with AsyncSessionLocal() as session:
        mission = (await plan_next_mission(session, bound_run["run_id"])).mission
        mission_id = mission.id
        job = await session.get(DurableJob, bound_run["job_id"])
        job.status, job.lease_expires_at = JobStatus.FAILED, None
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/missions/{mission_id}/execute", json={"workspace":"/tmp/untrusted", "provider":"codex"})
        assert response.status_code == 409 and "persistent missions" in response.text
    async with AsyncSessionLocal() as session:
        assert not list(await session.scalars(select(MissionAttempt).where(MissionAttempt.mission_id == mission_id)))
