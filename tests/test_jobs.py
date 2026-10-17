"""Real PostgreSQL queue and stale-worker fencing integration tests."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from test_runtime_controls import PausedHarness
from test_test_design import create_run

from hypertest.application.jobs import (
    FencedAsyncSession,
    JobLeaseLost,
    cancel_job,
    claim_job,
    finish_job,
    get_worker_status,
    heartbeat_job,
    record_worker_heartbeat,
    recover_expired_jobs,
    retry_job,
    submit_job,
)
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import execute_mission
from hypertest.application.services import ConflictError
from hypertest.db.session import AsyncSessionLocal, engine
from hypertest.domain.enums import MissionAttemptStatus, MissionStatus
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import AuditEvent, MissionAttempt, OutboxEvent, Requirement
from hypertest.worker import run_claimed_job


@pytest.mark.asyncio
async def test_job_submission_idempotency_exclusion_cancel_and_audit() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        run_id = run.id
        job = await submit_job(session, run_id, JobType.PREPARE_WORKSPACE, payload={}, idempotency_key="prepare")
        job_id = job.id
        repeated = await submit_job(session, run_id, JobType.PREPARE_WORKSPACE, payload={}, idempotency_key="prepare")
        assert job.id == repeated.id
        with pytest.raises(ConflictError, match="different job request"):
            await submit_job(session, run_id, JobType.EVALUATE_GATE, payload={}, idempotency_key="prepare")
        await session.rollback()
        with pytest.raises(ConflictError, match="active work"):
            await submit_job(session, run_id, JobType.PREPARE_WORKSPACE, payload={}, idempotency_key="duplicate-work")
        await session.rollback()
        job = await cancel_job(session, job_id)
        assert job.status is JobStatus.CANCELLED
        assert job.started_at is None
        events = list(await session.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == job.id)))
        assert sorted(events) == ["job.cancelled", "job.queued"]
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)) == 2
        retry = await retry_job(session, job.id, idempotency_key="retry-prepare")
        assert retry.retry_of_job_id == job.id
        assert (await retry_job(session, job.id, idempotency_key="retry-prepare")).id == retry.id
        await cancel_job(session, retry.id)


@pytest.mark.asyncio
async def test_concurrent_submissions_and_skip_locked_claims() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        other_run = await create_run(session)
        run_id, other_id = run.id, other_run.id

    async def submit(run_id, key):
        async with AsyncSessionLocal() as session:
            return await submit_job(session, run_id, JobType.PREPARE_WORKSPACE, payload={}, idempotency_key=key)

    first, repeated = await asyncio.gather(submit(run_id, "concurrent"), submit(run_id, "concurrent"))
    assert first.id == repeated.id
    second = await submit(other_id, "second")

    async def claim(worker_id):
        async with AsyncSessionLocal() as session:
            return await claim_job(session, worker_id)

    claimed = await asyncio.gather(claim("worker-A"), claim("worker-B"))
    assert {job.id for job in claimed} == {first.id, second.id}
    for job in claimed:
        async with AsyncSessionLocal() as session:
            assert await heartbeat_job(session, job.id, job.lease_token) is JobStatus.RUNNING
            await finish_job(session, job.id, job.lease_token, result={"checked": True})


@pytest.mark.asyncio
async def test_database_protects_job_input_and_terminal_history() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        job = await submit_job(session, run.id, JobType.PREPARE_WORKSPACE, payload={}, idempotency_key="immutable")
        job_id = job.id
        job.payload = {"untrusted": "changed"}
        with pytest.raises(DBAPIError, match="input is immutable"):
            await session.commit()
        await session.rollback()
        job = await cancel_job(session, job_id)
        job.error_message = "rewrite terminal history"
        with pytest.raises(DBAPIError, match="terminal job is immutable"):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_expired_worker_clock_skew_cannot_commit_and_requires_explicit_retry() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        run_id, snapshot_id = run.id, run.source_snapshot_id
        mission = (await plan_next_mission(session, run.id)).mission
        assert mission is not None
        mission_id = mission.id
        job = await submit_job(session, run_id, JobType.EXECUTE_MISSION,
                               payload={"workspace": "."}, idempotency_key="execute", mission_id=mission_id)
        job = await claim_job(session, "stale-worker", lease_seconds=30)
        assert job is not None
        job_id, token = job.id, job.lease_token
    harness = PausedHarness()
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=job_id,
                                  lease_token=token, test_run_id=run_id) as fenced:
        task = asyncio.create_task(execute_mission(fenced, mission_id, ".", harness=harness))
        try:
            await asyncio.wait_for(harness.started.wait(), timeout=5)
            async with AsyncSessionLocal() as controller:
                persisted = await controller.get(DurableJob, job_id)
                database_now = await controller.scalar(select(func.clock_timestamp()))
                persisted.lease_expires_at = database_now - timedelta(seconds=1)
                # Simulate a DB clock ahead of the process that created Attempt.
                # Recovery must use the FK, never started_at ordering guesses.
                persisted.started_at = database_now + timedelta(hours=1)
                await controller.commit()
            harness.release.set()
            with pytest.raises(JobLeaseLost):
                await asyncio.wait_for(task, timeout=5)
        finally:
            harness.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert harness.closed == 1
    async with AsyncSessionLocal() as session:
        recovered = await recover_expired_jobs(session)
        assert job_id in {item.id for item in recovered}
        job = await session.get(DurableJob, job_id)
        assert job.status is JobStatus.INTERRUPTED
        assert job.error_code == "WORKER_LEASE_EXPIRED"
        assert await claim_job(session, "replacement-worker") is None
        assert await session.scalar(select(func.count()).select_from(Requirement).where(Requirement.source_snapshot_id == snapshot_id)) == 0
        attempt = await session.scalar(select(MissionAttempt).where(MissionAttempt.mission_id == mission_id))
        assert attempt.status is MissionAttemptStatus.FAILED
        assert attempt.durable_job_id == job_id
        assert attempt.error_code == "WORKER_LEASE_EXPIRED"
        from hypertest.domain.models import Mission
        assert (await session.get(Mission, mission_id)).status is MissionStatus.RETRYING
        retry = await retry_job(session, job_id, idempotency_key="operator-approved-retry")
        assert retry.id != job_id
        assert retry.retry_of_job_id == job_id
        await cancel_job(session, retry.id)
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == job_id, AuditEvent.action == "job.interrupted")) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == job_id, OutboxEvent.event_type == "job.interrupted")) == 1


@pytest.mark.asyncio
async def test_worker_dispatches_commits_then_reports_result() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        job = await submit_job(session, run.id, JobType.PREPARE_WORKSPACE, payload={}, idempotency_key="dispatch")
        job = await claim_job(session, "test-worker")
    async def dispatch(session, job):
        # Exercise the actual fenced session rather than mock the transaction.
        await session.commit()
        return {"workspace": "/workspace", "job_id": str(job.id)}
    result = await run_claimed_job(job, dispatcher=dispatch)
    assert result.status is JobStatus.SUCCEEDED
    assert result.result["job_id"] == str(job.id)


@pytest.mark.asyncio
async def test_worker_cancellation_is_durable_and_fences_running_handler() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission = (await plan_next_mission(session, run.id)).mission
        job = await submit_job(session, run.id, JobType.EXECUTE_MISSION, payload={"workspace": "."},
                               idempotency_key="cancel-active", mission_id=mission.id)
        job = await claim_job(session, "cancel-worker")
        run_id, snapshot_id, job_id, mission_id = run.id, run.source_snapshot_id, job.id, mission.id
    harness = PausedHarness()
    async def dispatch(session, job):
        result = await execute_mission(session, job.mission_id, ".", harness=harness)
        return {"mission_id": str(result.mission.id)}
    running = asyncio.create_task(run_claimed_job(job, dispatcher=dispatch))
    try:
        await asyncio.wait_for(harness.started.wait(), timeout=5)
        async with AsyncSessionLocal() as session:
            cancelled = await cancel_job(session, job_id)
            assert cancelled.status is JobStatus.CANCEL_REQUESTED
        harness.release.set()
        await asyncio.wait_for(running, timeout=10)
    finally:
        harness.release.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)
    async with AsyncSessionLocal() as session:
        job = await session.get(DurableJob, job_id)
        assert job.status is JobStatus.CANCELLED
        assert harness.closed == 1
        assert await session.scalar(select(func.count()).select_from(Requirement).where(Requirement.source_snapshot_id == snapshot_id)) == 0
        attempt = await session.scalar(select(MissionAttempt).where(MissionAttempt.mission_id == mission_id))
        assert attempt.status is MissionAttemptStatus.CANCELLED
        assert (await session.get(DurableJob, job_id)).test_run_id == run_id


@pytest.mark.asyncio
async def test_worker_health_uses_durable_idle_heartbeat() -> None:
    async with AsyncSessionLocal() as session:
        await record_worker_heartbeat(session, "healthy-idle-worker")
        status = await get_worker_status(session)
        assert status["available"] is True
        assert status["active_workers"] >= 1
        assert status["last_seen_at"] is not None


@pytest.mark.asyncio
async def test_expired_runner_cannot_publish_facts_and_recovery_records_case_error(tmp_path, monkeypatch) -> None:
    from test_runner import _setup

    from hypertest.application.executions import execute_test_run
    from hypertest.domain.enums import CaseResult, ExecutionStatus
    from hypertest.domain.models import ExecutionTestCase
    from hypertest.domain.models import TestExecution as CanonicalExecution

    async with AsyncSessionLocal() as session:
        source, run, case, _ = await _setup(
            session, tmp_path, monkeypatch,
            "import time\ndef test_example():\n    time.sleep(0.5)\n    assert True\n",
        )
        run_id, case_id = run.id, case.id
        job = await submit_job(session, run_id, JobType.EXECUTE_TESTS,
                               payload={"workspace": str(source), "backend": "local", "idempotency_key": "runner"},
                               idempotency_key="stale-runner")
        job = await claim_job(session, "stale-runner-worker")
        job_id, token = job.id, job.lease_token
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=job_id,
                                  lease_token=token, test_run_id=run_id) as fenced:
        running = asyncio.create_task(execute_test_run(
            fenced, run_id, str(source), "local", idempotency_key=f"job:{job_id}",
        ))
        try:
            execution_id = None
            for _ in range(100):
                async with AsyncSessionLocal() as observer:
                    execution_id = await observer.scalar(select(CanonicalExecution.id).where(
                        CanonicalExecution.test_run_id == run_id,
                        CanonicalExecution.status == ExecutionStatus.RUNNING,
                    ))
                    if execution_id is not None:
                        persisted = await observer.get(DurableJob, job_id)
                        database_now = await observer.scalar(select(func.clock_timestamp()))
                        persisted.lease_expires_at = database_now - timedelta(seconds=1)
                        persisted.started_at = database_now + timedelta(hours=1)
                        await observer.commit()
                        break
                await asyncio.sleep(0.02)
            assert execution_id is not None
            with pytest.raises(JobLeaseLost):
                await asyncio.wait_for(running, timeout=10)
        finally:
            if not running.done():
                running.cancel()
            await asyncio.gather(running, return_exceptions=True)
    async with AsyncSessionLocal() as session:
        await recover_expired_jobs(session)
        execution = await session.get(CanonicalExecution, execution_id)
        assert execution.status is ExecutionStatus.ERROR
        assert execution.durable_job_id == job_id
        assert execution.error_code == "WORKER_LEASE_EXPIRED"
        fact = await session.get(ExecutionTestCase, (execution_id, case_id))
        assert fact.result is CaseResult.ERROR
        await recover_expired_jobs(session)
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == execution_id, AuditEvent.action == "execution.interrupted",
        )) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_id == execution_id, OutboxEvent.event_type == "execution.interrupted",
        )) == 1
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == execution_id, AuditEvent.action == "execution.completed",
        )) == 0


@pytest.mark.asyncio
async def test_claim_and_cancel_share_run_then_job_lock_order(monkeypatch) -> None:
    """Pause claim before audit FK insertion while cancellation waits on its lock."""
    from hypertest.application import jobs

    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        job = await submit_job(session, run.id, JobType.PREPARE_WORKSPACE, payload={}, idempotency_key="claim-cancel-order")
        job_id = job.id
    paused, release, cancellation_pid_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_event = jobs._event
    cancellation_pid = None

    async def paused_event(session, job, action):
        if action == "job.started":
            paused.set()
            await release.wait()
        await original_event(session, job, action)

    monkeypatch.setattr(jobs, "_event", paused_event)

    async def claim():
        async with AsyncSessionLocal() as session:
            return await claim_job(session, "lock-order-worker")

    async def cancel():
        nonlocal cancellation_pid
        async with AsyncSessionLocal() as session:
            cancellation_pid = await session.scalar(select(func.pg_backend_pid()))
            cancellation_pid_ready.set()
            return await cancel_job(session, job_id)

    claiming = asyncio.create_task(claim())
    cancelling = None
    try:
        await asyncio.wait_for(paused.wait(), timeout=3)
        cancelling = asyncio.create_task(cancel())
        await asyncio.wait_for(cancellation_pid_ready.wait(), timeout=3)
        from sqlalchemy import text
        # Observe PostgreSQL's actual lock wait, without timing assumptions about
        # which coroutine got scheduled first. On Job-first claim this forms the
        # real FK lock inversion; Run-first claim lets cancellation wait safely.
        blocked = False
        for _ in range(100):
            async with AsyncSessionLocal() as observer:
                blocked = await observer.scalar(text(
                    "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                ), {"pid": cancellation_pid})
            if blocked:
                break
            await asyncio.sleep(0.01)
        assert blocked
        release.set()
        claimed, cancelled = await asyncio.wait_for(asyncio.gather(claiming, cancelling), timeout=5)
        assert claimed.id == cancelled.id == job_id
        assert cancelled.status is JobStatus.CANCEL_REQUESTED
        async with AsyncSessionLocal() as session:
            await finish_job(session, job_id, claimed.lease_token)
    finally:
        release.set()
        for task in [claiming, cancelling]:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*[task for task in [claiming, cancelling] if task is not None], return_exceptions=True)
