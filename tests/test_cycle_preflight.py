"""Runner readiness precedes paid Agent work and Git, without creating facts."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from test_test_design import create_run

from hypertest.application import controller
from hypertest.application.gate import evaluate_gate
from hypertest.application.jobs import (
    FencedAsyncSession,
    cancel_job,
    claim_job,
    finish_job,
    recover_expired_jobs,
    submit_job,
)
from hypertest.application.services import ConflictError
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal, engine
from hypertest.domain.enums import VerdictDecision
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import AgentSessionRecord, Evidence, Mission, MissionAttempt
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.runner import backends
from hypertest.runner.backends import LocalRunner, ProcessResult
from hypertest.worker import run_claimed_job


async def queued_cycle(session, backend="docker"):
    run = await create_run(session)
    job = await submit_job(
        session, run.id, JobType.ADVANCE_RUN,
        payload={"prepare_workspace": True, "backend": backend},
        idempotency_key="preflight-cycle",
    )
    claimed = await claim_job(session, "preflight-fixture")
    assert claimed.id == job.id
    return run.id, claimed


def forbid_downstream(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("Runner preflight must stop before Git, Planner, or Agent")

    for name in ("prepare_managed_workspace", "plan_next_mission", "execute_mission"):
        monkeypatch.setattr(controller, name, forbidden)


async def assert_no_testing_facts(run_id):
    async with AsyncSessionLocal() as session:
        for model in (Mission, AgentSessionRecord, CanonicalExecution, Evidence):
            assert await session.scalar(select(func.count()).select_from(model).where(
                model.test_run_id == run_id,
            )) == 0
        assert await session.scalar(select(func.count()).select_from(MissionAttempt).join(
            Mission, MissionAttempt.mission_id == Mission.id,
        ).where(Mission.test_run_id == run_id)) == 0


def inspected_image():
    return ProcessResult(json.dumps({
        "Id": "sha256:preflight-fixture", "Os": "linux", "Architecture": "amd64",
    }).encode(), b"", 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["daemon", "image", "binary"])
async def test_docker_preflight_failure_prevents_git_agent_and_execution(monkeypatch, unavailable):
    forbid_downstream(monkeypatch)
    commands = []

    async def inspect(command, **_options):
        commands.append(command)
        if unavailable == "binary":
            raise FileNotFoundError("docker executable is unavailable")
        if command[:3] != ["docker", "image", "inspect"]:
            # Failed Job cleanup performs read-only labelled resource discovery.
            assert command[:3] in (["docker", "ps", "-aq"], ["docker", "volume", "ls"])
            return ProcessResult(b"", b"", 1 if unavailable == "daemon" else 0)
        stderr = b"Cannot connect to Docker daemon" if unavailable == "daemon" else b"No such image"
        return ProcessResult(b"", stderr, 1)

    monkeypatch.setattr(backends, "run_process", inspect)
    async with AsyncSessionLocal() as session:
        run_id, job = await queued_cycle(session)
    finished = await run_claimed_job(job)
    assert finished.status is JobStatus.FAILED
    assert "runner preflight failed" in finished.error_message
    assert finished.result is None
    assert sum(command[:3] == ["docker", "image", "inspect"] for command in commands) == 1
    await assert_no_testing_facts(run_id)


@pytest.mark.asyncio
async def test_local_preflight_preserves_explicit_development_opt_in(monkeypatch):
    forbid_downstream(monkeypatch)
    monkeypatch.setattr(get_settings(), "runner_allow_local", False)
    async with AsyncSessionLocal() as session:
        run_id, job = await queued_cycle(session, backend="local")
    finished = await run_claimed_job(job)
    assert finished.status is JobStatus.FAILED
    assert "HYPERTEST_RUNNER_ALLOW_LOCAL=true" in finished.error_message
    await assert_no_testing_facts(run_id)


@pytest.mark.asyncio
async def test_enabled_local_preflight_precedes_preparation_and_does_not_create_facts(monkeypatch):
    monkeypatch.setattr(get_settings(), "runner_allow_local", True)
    order = []
    fingerprint = LocalRunner.fingerprint

    async def observe_fingerprint(runner):
        order.append("preflight")
        return await fingerprint(runner)

    async def prepare(_session, _run_id):
        order.append("prepare")
        return {"workspace": "."}

    async def plan(_session, _run_id):
        order.append("plan")
        return SimpleNamespace(mission=None, reason="NO_TESTING_FACTS")

    monkeypatch.setattr(LocalRunner, "fingerprint", observe_fingerprint)
    monkeypatch.setattr(controller, "prepare_managed_workspace", prepare)
    monkeypatch.setattr(controller, "plan_next_mission", plan)
    async with AsyncSessionLocal() as session:
        run_id, job = await queued_cycle(session, backend="local")
    finished = await run_claimed_job(job)
    assert finished.status is JobStatus.SUCCEEDED
    assert finished.result == {"reason": "NO_TESTING_FACTS", "steps": [], "workspace": "."}
    assert order == ["preflight", "prepare", "plan"]
    await assert_no_testing_facts(run_id)


@pytest.mark.asyncio
async def test_docker_preflight_releases_run_and_job_locks_before_io(monkeypatch):
    async with AsyncSessionLocal() as session:
        run_id, job = await queued_cycle(session)

    async def inspect(_command, **_options):
        async with AsyncSessionLocal() as competitor:
            assert await competitor.scalar(select(CanonicalRun.id).where(
                CanonicalRun.id == run_id,
            ).with_for_update(nowait=True)) == run_id
            assert await competitor.scalar(select(DurableJob.id).where(
                DurableJob.id == job.id,
            ).with_for_update(nowait=True)) == job.id
            await competitor.commit()
        return inspected_image()

    async def prepare(_session, _run_id):
        return {"workspace": "."}

    async def plan(_session, _run_id):
        return SimpleNamespace(mission=None, reason="NO_TESTING_FACTS")

    monkeypatch.setattr(backends, "run_process", inspect)
    monkeypatch.setattr(controller, "prepare_managed_workspace", prepare)
    monkeypatch.setattr(controller, "plan_next_mission", plan)
    # Isolate the dispatcher's transaction: a real Worker monitor independently
    # locks this Job while heartbeating, which can legitimately race NOWAIT.
    # Keep the actual lease fence and both NOWAIT assertions, without treating
    # a different transaction's short-lived heartbeat lock as a retained I/O lock.
    async with FencedAsyncSession(
        bind=engine, expire_on_commit=False, job_id=job.id,
        lease_token=job.lease_token, test_run_id=run_id,
    ) as controlled:
        result = await controller.advance_run(controlled, run_id, **job.payload)
    async with AsyncSessionLocal() as session:
        finished = await finish_job(session, job.id, job.lease_token, result=result)
        assert finished.status is JobStatus.SUCCEEDED
    await assert_no_testing_facts(run_id)


@pytest.mark.asyncio
async def test_lease_expiry_during_preflight_cannot_prepare_or_dispatch_agent(monkeypatch):
    forbid_downstream(monkeypatch)
    async with AsyncSessionLocal() as session:
        run_id, job = await queued_cycle(session)

    async def inspect(command, **_options):
        if command[:3] != ["docker", "image", "inspect"]:
            assert command[:3] in (["docker", "ps", "-aq"], ["docker", "volume", "ls"])
            return ProcessResult(b"", b"", 0)
        async with AsyncSessionLocal() as observer:
            stored = await observer.get(DurableJob, job.id)
            now = await observer.scalar(select(func.clock_timestamp()))
            stored.lease_expires_at = now - timedelta(seconds=1)
            await observer.commit()
        return inspected_image()

    monkeypatch.setattr(backends, "run_process", inspect)
    assert await run_claimed_job(job) is None
    async with AsyncSessionLocal() as session:
        await recover_expired_jobs(session)
        stored = await session.get(DurableJob, job.id)
        assert stored.status is JobStatus.INTERRUPTED
        assert stored.result is None
    await assert_no_testing_facts(run_id)


@pytest.mark.asyncio
async def test_direct_cycle_rechecks_admission_after_preflight(monkeypatch):
    forbid_downstream(monkeypatch)
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        run_id = run.id
        queued_id = None

        async def inspect(_command, **_options):
            nonlocal queued_id
            async with AsyncSessionLocal() as competitor:
                queued = await submit_job(
                    competitor, run_id, JobType.ADVANCE_RUN,
                    payload={"prepare_workspace": True}, idempotency_key="during-preflight",
                )
                queued_id = queued.id
            return inspected_image()

        monkeypatch.setattr(backends, "run_process", inspect)
        try:
            with pytest.raises(ConflictError, match="active background work"):
                await controller.advance_run(session, run_id, prepare_workspace=True)
        finally:
            await session.rollback()
            if queued_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cancel_job(cleanup, queued_id)
        assert queued_id is not None
    await assert_no_testing_facts(run_id)


@pytest.mark.asyncio
async def test_cycle_rejects_uncontrolled_runner_backend(monkeypatch):
    forbid_downstream(monkeypatch)
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        with pytest.raises(ConflictError, match="unsupported runner backend"):
            await controller.advance_run(session, run.id, prepare_workspace=True, backend="shell")
    await assert_no_testing_facts(run.id)


@pytest.mark.asyncio
async def test_explicit_gate_evaluation_remains_independent_of_runner_readiness(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("Gate-only evaluation does not require a Runner")

    monkeypatch.setattr(backends, "run_process", forbidden)
    monkeypatch.setattr(LocalRunner, "fingerprint", forbidden)
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        verdict = await evaluate_gate(session, run.id)
        assert verdict.decision is VerdictDecision.BLOCKED
    await assert_no_testing_facts(run.id)
