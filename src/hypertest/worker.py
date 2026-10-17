"""Independent PostgreSQL worker: ``python -m hypertest.worker [--once]``.

API processes only enqueue requests. SIGTERM cancels active external work and
records interruption; hard crashes are recovered after lease expiration, with
explicit operator retry instead of automatically replaying external work.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.jobs import (
    FencedAsyncSession,
    JobLeaseLost,
    claim_job,
    cleanup_job_resources,
    finish_job,
    heartbeat_job,
    record_worker_heartbeat,
    recover_expired_jobs,
)
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal, engine
from hypertest.domain.enums import ExecutionPurpose, ExecutionStatus, MissionAttemptStatus
from hypertest.domain.jobs import DurableJob, JobStatus, JobType

logger = logging.getLogger("hypertest.worker")
Dispatcher = Callable[[AsyncSession, DurableJob], Awaitable[dict[str, Any]]]


class JobDispatchError(RuntimeError):
    """A controlled stop with recorded progress, never synthetic testing facts."""

    def __init__(self, error_code: str, message: str, result: dict[str, Any]):
        super().__init__(message)
        self.error_code, self.result = error_code, result


async def dispatch_job(session: AsyncSession, job: DurableJob) -> dict[str, Any]:
    payload = dict(job.payload)
    if job.job_type is JobType.ADVANCE_RUN:
        from hypertest.application.controller import advance_run
        result = await advance_run(session, job.test_run_id, **payload)
        if result["reason"] in {"MISSION_REJECTED", "MISSION_FAILED"}:
            raise JobDispatchError(
                result["reason"], "mission stopped; inspect its recorded details before retry", result,
            )
        return result
    if job.job_type is JobType.EXECUTE_MISSION:
        from hypertest.application.runtime import execute_mission
        result = await execute_mission(session, job.mission_id, **payload)
        recorded = {"mission_id": str(result.mission.id), "mission_key": result.mission.key,
                    "attempt_id": str(result.attempt.id), "status": result.mission.status.value}
        if result.attempt.status is not MissionAttemptStatus.ACCEPTED:
            raise JobDispatchError(
                "MISSION_REJECTED", "mission proposals rejected; inspect its recorded details before retry",
                {"reason": "MISSION_REJECTED", **recorded},
            )
        return recorded
    if job.job_type is JobType.EXECUTE_TESTS:
        from hypertest.application.executions import execute_test_run
        payload["purpose"] = ExecutionPurpose(payload["purpose"])
        # An explicit job retry creates a new immutable execution request; repeating
        # delivery of the same job still returns its original execution.
        payload["idempotency_key"] = f"job:{job.id}"
        execution = await execute_test_run(session, job.test_run_id, **payload)
        if execution.status is not ExecutionStatus.COMPLETED:
            raise RuntimeError(f"runner did not complete: {execution.error_code or execution.status.value}")
        return {"execution_id": str(execution.id), "execution_key": execution.key,
                "status": execution.status.value, "outcome": execution.outcome.value}
    if job.job_type is JobType.EVALUATE_GATE:
        from hypertest.application.gate import evaluate_gate
        verdict = await evaluate_gate(session, job.test_run_id, **payload)
        return {"verdict_id": str(verdict.id), "verdict_key": verdict.key,
                "decision": verdict.decision.value, "status": verdict.status.value}
    if job.job_type is JobType.PREPARE_WORKSPACE:
        from hypertest.application.workspaces import prepare_workspace
        return await prepare_workspace(session, job.test_run_id)
    raise ValueError(f"unsupported job type: {job.job_type}")


async def run_claimed_job(job: DurableJob, *, dispatcher: Dispatcher = dispatch_job) -> DurableJob | None:
    """Execute one claimed job; injected dispatchers are for PostgreSQL integration tests."""
    settings = get_settings()
    lease_token = job.lease_token
    assert lease_token is not None
    monitored_status: JobStatus | None = None
    monitor_error: Exception | None = None
    worker_id = job.worker_id
    assert worker_id is not None

    async def execute() -> dict[str, Any]:
        async with FencedAsyncSession(
            bind=engine, expire_on_commit=False,
            job_id=job.id, lease_token=lease_token, test_run_id=job.test_run_id,
        ) as session:
            from hypertest.runner.backends import runner_job_id

            context = runner_job_id.set(str(job.id))
            try:
                return await dispatcher(session, job)
            finally:
                runner_job_id.reset(context)

    handler = asyncio.create_task(execute())

    async def monitor() -> None:
        nonlocal monitored_status, monitor_error
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    monitored_status = await heartbeat_job(
                        session, job.id, lease_token, lease_seconds=settings.worker_lease_seconds,
                    )
                    await record_worker_heartbeat(session, worker_id, job.id)
                if monitored_status is JobStatus.CANCEL_REQUESTED:
                    handler.cancel()
                    return
            except Exception as exc:
                monitor_error = exc
                handler.cancel()
                return
            await asyncio.sleep(settings.worker_heartbeat_seconds)

    monitor_task = asyncio.create_task(monitor())
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    interrupted = False
    try:
        result = await handler
    except asyncio.CancelledError:
        if monitored_status is not JobStatus.CANCEL_REQUESTED:
            error_code = "WORKER_HEARTBEAT_FAILED" if monitor_error else "WORKER_SHUTDOWN"
            error_message = "Worker interrupted external work; inspect before explicit retry"
            interrupted = True
    except JobLeaseLost:
        # A recovery transaction owns canonical cleanup. Never bypass the fence.
        logger.warning("Lease lost for job %s", job.key)
        error_code, error_message, interrupted = "JOB_LEASE_LOST", "Worker ownership was revoked", True
    except JobDispatchError as exc:
        result = exc.result
        error_code, error_message = exc.error_code, str(exc)[:2048]
        logger.warning("Job %s stopped (%s)", job.key, error_code)
    except Exception as exc:
        error_code, error_message = type(exc).__name__.upper()[:64], str(exc)[:2048]
        logger.warning("Job %s failed (%s)", job.key, error_code)
    finally:
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)
        if not handler.done():
            handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
    try:
        async with AsyncSessionLocal() as session:
            finished = await finish_job(session, job.id, lease_token, result=result,
                                        error_code=error_code, error_message=error_message,
                                        interrupted=interrupted)
            if finished.status is not JobStatus.SUCCEEDED:
                await cleanup_job_resources(session, finished)
            return finished
    except JobLeaseLost:
        logger.warning("Job %s interrupted after ownership loss; lease recovery will preserve history", job.key)
        return None
    finally:
        async with AsyncSessionLocal() as session:
            await record_worker_heartbeat(session, worker_id)


async def run_worker(*, once: bool = False) -> None:
    settings = get_settings()
    if not 0 < settings.worker_heartbeat_seconds < settings.worker_lease_seconds:
        raise ValueError("worker heartbeat must be positive and shorter than the lease")
    if settings.worker_poll_seconds <= 0:
        raise ValueError("worker poll interval must be positive")
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid7().hex}"
    stopping = asyncio.Event()
    active: asyncio.Task | None = None

    def stop() -> None:
        stopping.set()
        if active is not None:
            active.cancel()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop)
    logger.info("Worker %s ready", worker_id)
    try:
        while not stopping.is_set():
            try:
                async with AsyncSessionLocal() as session:
                    await record_worker_heartbeat(session, worker_id)
                    recovered = await recover_expired_jobs(session)
                    for job in recovered:
                        logger.warning("Recovered %s as %s; explicit retry required", job.key, job.status.value)
                    job = await claim_job(session, worker_id, lease_seconds=settings.worker_lease_seconds)
                if job is not None:
                    active = asyncio.create_task(run_claimed_job(job))
                    await active
                    active = None
                elif not once:
                    try:
                        await asyncio.wait_for(stopping.wait(), timeout=settings.worker_poll_seconds)
                    except TimeoutError:
                        pass
                if once:
                    return
            except (DBAPIError, OSError) as exc:
                # SQLAlchemy context managers roll back failed transactions. A
                # claimed job remains durable and expires instead of replaying
                # external work when a transient DB connection disappears.
                active = None
                logger.warning("Worker database operation interrupted (%s); retrying connection", type(exc).__name__)
                if once:
                    raise
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=settings.worker_poll_seconds)
                except TimeoutError:
                    pass
    finally:
        # Mark this worker immediately unavailable, preserving historical liveness.
        from datetime import timedelta

        from sqlalchemy import func, update

        from hypertest.domain.jobs import WorkerHeartbeat

        try:
            async with AsyncSessionLocal() as session:
                await session.execute(update(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id).values(
                    last_seen_at=func.clock_timestamp() - timedelta(seconds=settings.worker_lease_seconds * 3),
                    active_job_id=None,
                ))
                await session.commit()
        except (DBAPIError, OSError):
            logger.warning("Worker heartbeat will expire because the database is unavailable during shutdown")
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="recover expired leases and process at most one queued job")
    args = parser.parse_args()
    logging.basicConfig(level=get_settings().log_level)
    asyncio.run(run_worker(once=args.once))


if __name__ == "__main__":
    main()
