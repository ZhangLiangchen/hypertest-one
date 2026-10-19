"""Read-boundary projection of deliberately injected Operational diagnostics."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.job_schemas import JobRead
from hypertest.api.schemas import ProjectCreate
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.jobs import claim_job, submit_job
from hypertest.application.services import create_project
from hypertest.application.source_diagnostics import SourcePreparationError
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.main import app
from hypertest.worker import JobDispatchError, run_claimed_job

SECRET = "injected-source-read-boundary-canary"


def diagnostic_result(case):
    expected = SourcePreparationError(stage="fetch_commit", category="network").diagnostic
    injected = {**expected, "summary": SECRET, "action": SECRET,
                "stderr": SECRET, "command": SECRET, "repository_url": SECRET}
    if case == "unknown_schema":
        injected["schema_version"] = SECRET
    elif case == "unknown_stage":
        injected["stage"] = SECRET
    elif case == "unknown_category":
        injected["category"] = SECRET
    elif case == "invalid_type":
        injected["timed_out"] = SECRET
    return {
        "reason": "SOURCE_PREPARATION_FAILED", "source_preparation_diagnostic": injected,
    }, expected


@pytest.mark.parametrize("case", [
    "valid", "unknown_schema", "unknown_stage", "unknown_category", "invalid_type",
])
def test_job_read_schema_reprojects_existing_data_without_mutating_it(case):
    result, expected = diagnostic_result(case)
    original = deepcopy(result)
    now = datetime.now(UTC)
    record = {
        "id": uuid4(), "key": "JOB-source-read-test", "project_id": uuid4(),
        "test_run_id": uuid4(), "mission_id": None, "retry_of_job_id": None,
        "job_type": JobType.PREPARE_WORKSPACE, "status": JobStatus.FAILED,
        "idempotency_key": "read-test", "payload": {}, "result": result,
        "error_code": "SOURCE_PREPARATION_FAILED", "error_message": "Source preparation failed",
        "attempts": 1, "worker_id": "read-test", "heartbeat_at": now,
        "lease_expires_at": None, "created_at": now, "updated_at": now,
        "started_at": now, "finished_at": now, "cancel_requested_at": None,
    }
    projected = JobRead.model_validate(record).model_dump(mode="json")
    assert SECRET not in str(projected)
    if case == "valid":
        assert projected["result"]["source_preparation_diagnostic"] == expected
    else:
        assert projected["result"] == {"reason": "SOURCE_PREPARATION_FAILED"}
    assert result == original
    assert record["result"] is result


@pytest.mark.parametrize("case", [
    "valid", "unknown_schema", "unknown_stage", "unknown_category", "invalid_type",
])
async def test_real_job_api_projects_injected_persisted_payload_and_preserves_terminal_history(
    monkeypatch, case,
):
    # The controlled dispatcher deliberately bypasses SourcePreparationError's
    # write-side projection to exercise the independent HTTP read boundary.
    # This is injected Operational test data, not Canonical state or live Git.
    injected, expected = diagnostic_result(case)
    original = deepcopy(injected)

    async def cleanup(*_args, **_kwargs):
        return {}

    monkeypatch.setattr("hypertest.worker.cleanup_job_resources", cleanup)
    async with AsyncSessionLocal() as session:
        project = await create_project(session, ProjectCreate(
            key=public_key("READDIAG"), name="Source diagnostic read boundary",
        ))
        run = await bootstrap_run(session, project.id, RunBootstrap(
            repository_url="https://github.com/example/read-diagnostic-boundary.git",
            commit_sha="a" * 40, prd_text="Test immutable input and read projection.",
        ))
        submitted = await submit_job(session, run.id, JobType.PREPARE_WORKSPACE,
            payload={}, idempotency_key="read-boundary-job")
        job = await claim_job(session, "read-boundary-worker")
        assert job.id == submitted.id

    async def injected_failure(_session, _job):
        raise JobDispatchError("SOURCE_PREPARATION_FAILED", "Source preparation failed", injected)

    finished = await run_claimed_job(job, dispatcher=injected_failure)
    assert finished.status is JobStatus.FAILED
    assert finished.result == original
    assert SECRET in str(finished.result)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        for path in (f"/api/v1/jobs/{job.id}", f"/api/v1/test-runs/{run.id}/jobs"):
            response = await client.get(path)
            assert response.status_code == 200
            assert SECRET not in response.text
            record = response.json() if isinstance(response.json(), dict) else response.json()[0]
            assert record["id"] == str(job.id)
            if case == "valid":
                assert record["result"]["source_preparation_diagnostic"] == expected
            else:
                assert record["result"] == {"reason": "SOURCE_PREPARATION_FAILED"}

    async with AsyncSessionLocal() as session:
        preserved = await session.get(DurableJob, job.id)
        assert preserved.status is JobStatus.FAILED
        assert preserved.result == original
        assert SECRET in str(preserved.result)
    assert injected == original
