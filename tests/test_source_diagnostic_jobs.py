"""Persist safe source observations through real PostgreSQL jobs and HTTP reads."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import ProjectCreate
from hypertest.application import controller, persistent, workspaces
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.jobs import (
    cancel_job,
    claim_job,
    recover_expired_jobs,
    retry_job,
    submit_job,
)
from hypertest.application.services import create_project
from hypertest.application.source_diagnostics import SourcePreparationError
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.bindings import RunExecutionBinding
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import AgentSessionRecord, AuditEvent, Evidence, Mission, OutboxEvent
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.harness_bridge.protocol import PROFILE
from hypertest.main import app
from hypertest.runner.backends import ProcessResult, run_process
from hypertest.worker import run_claimed_job

SECRET = "source-diagnostic-secret-must-not-escape"


async def source_job(mode="prepare"):
    async with AsyncSessionLocal() as session:
        project = await create_project(session, ProjectCreate(
            key=public_key("DIAG"), name="Source failure observations",
        ))
        run = await bootstrap_run(session, project.id, RunBootstrap(
            repository_url="https://github.com/example/source-observations.git",
            commit_sha="a" * 40, prd_text="Test the pinned application's behavior.",
        ))
        payload = {} if mode == "prepare" else {"prepare_workspace": True, "backend": "local"}
        if mode == "persistent":
            payload.update(backend="docker", execution_profile=PROFILE)
        job = await submit_job(session, run.id,
            JobType.PREPARE_WORKSPACE if mode == "prepare" else JobType.ADVANCE_RUN,
            payload=payload, idempotency_key="source-diagnostic-job")
        claimed = await claim_job(session, "source-diagnostic-worker")
        assert claimed.id == job.id
        return run, claimed


@pytest.mark.parametrize("mode", ["prepare", "legacy", "persistent"])
async def test_all_preparation_entrypoints_persist_diagnostic_before_any_agent_or_facts(
    tmp_path, monkeypatch, mode,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "harness_mode", "bridge" if mode == "persistent" else "direct")

    async def fingerprint(_self):
        return "test-preflight-only"

    async def cleanup(*_args, **_kwargs):
        return {}

    async def capabilities():
        return {"profile": PROFILE, "host_id": settings.bridge_host_id}

    monkeypatch.setattr(controller.LocalRunner, "fingerprint", fingerprint)
    monkeypatch.setattr(persistent.DockerRunner, "fingerprint", fingerprint)
    monkeypatch.setattr(persistent, "bridge_client", lambda: SimpleNamespace(capabilities=capabilities))
    monkeypatch.setattr("hypertest.worker.cleanup_job_resources", cleanup)
    run, job = await source_job(mode)

    async def process(command, **kwargs):
        if "fetch" in command:
            # Real preparation flow, injected Git output for a deterministic
            # security regression. This is not live model/Runner acceptance.
            return ProcessResult(b"", f"fatal: Authentication failed for https://u:{SECRET}@github.com/x/y".encode(), 128)
        return await run_process(command, **kwargs)

    monkeypatch.setattr(workspaces, "run_process", process)
    finished = await run_claimed_job(job)
    assert finished.status is JobStatus.FAILED
    assert finished.error_code == "SOURCE_PREPARATION_FAILED"
    diagnostic = finished.result["source_preparation_diagnostic"]
    assert finished.result["reason"] == "SOURCE_PREPARATION_FAILED"
    assert diagnostic["stage"] == "fetch_commit"
    assert diagnostic["category"] == "authentication"
    assert diagnostic["exit_code"] == 128
    assert SECRET not in str(finished.result) + finished.error_message
    async with AsyncSessionLocal() as session:
        for model in (RunExecutionBinding, AgentSessionRecord, Mission, CanonicalExecution, Evidence):
            assert await session.scalar(select(func.count()).select_from(model).where(
                model.test_run_id == run.id,
            )) == 0
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == job.id, AuditEvent.action == "job.failed",
        )) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_id == job.id, OutboxEvent.event_type == "job.failed",
        )) == 1
        original = await session.get(DurableJob, job.id)
        retry = await retry_job(session, job.id, idempotency_key="inspect-and-retry")
        assert retry.retry_of_job_id == job.id
        assert retry.payload == original.payload
        assert retry.result is None
        await cancel_job(session, retry.id)
        original.error_message = "rewrite historical diagnosis"
        with pytest.raises(DBAPIError, match="terminal job is immutable"):
            await session.commit()
        await session.rollback()


async def test_api_reprojects_allowlisted_diagnostic_without_rewriting_history():
    run, job = await source_job()
    poisoned = SourcePreparationError(stage="fetch_commit", category="network").diagnostic
    poisoned.update(summary=SECRET, action=SECRET, stderr=SECRET, command=SECRET)

    async def fail(_session, _job):
        error = SourcePreparationError(stage="fetch_commit", category="network")
        error.diagnostic = poisoned
        raise error

    finished = await run_claimed_job(job, dispatcher=fail)
    assert SECRET not in str(finished.result)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        for path in (f"/api/v1/jobs/{job.id}", f"/api/v1/test-runs/{run.id}/jobs"):
            response = await client.get(path)
            assert response.status_code == 200
            assert SECRET not in response.text
        response = await client.post(f"/api/v1/jobs/{job.id}/retry", json={"idempotency_key": "web-retry"})
        assert response.status_code == 202
        retried = response.json()
        assert retried["retry_of_job_id"] == str(job.id)
        assert retried["result"] is None
        await client.post(f"/api/v1/jobs/{retried['id']}/cancel")
    async with AsyncSessionLocal() as session:
        original = await session.get(DurableJob, job.id)
        assert original.result == finished.result


@pytest.mark.parametrize("stop", ["cancel", "expire"])
async def test_late_diagnostic_does_not_replace_cancellation_or_expired_lease(stop):
    _run, job = await source_job()

    async def fail(_session, _job):
        async with AsyncSessionLocal() as observer:
            if stop == "cancel":
                await cancel_job(observer, job.id)
            else:
                stored = await observer.get(DurableJob, job.id)
                stored.lease_expires_at = await observer.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
                await observer.commit()
        raise SourcePreparationError(stage="fetch_commit", category="network")

    finished = await run_claimed_job(job, dispatcher=fail)
    async with AsyncSessionLocal() as session:
        if stop == "expire":
            assert finished is None
            await recover_expired_jobs(session)
        stored = await session.get(DurableJob, job.id)
        assert stored.status is (JobStatus.CANCELLED if stop == "cancel" else JobStatus.INTERRUPTED)
        assert stored.result is None
        assert stored.error_code != "SOURCE_PREPARATION_FAILED"
