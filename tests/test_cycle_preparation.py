"""One durable cycle prepares pinned source and retains inspectable stop history."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from test_controller import CycleHarness
from test_delivery_loop import PRD_TEXT, configure_workspace
from test_test_design import create_run

from hypertest.api.delivery_schemas import RunAdvance, RunBootstrap
from hypertest.api.schemas import ProjectCreate
from hypertest.application import controller
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.jobs import (
    cancel_job,
    claim_job,
    recover_expired_jobs,
    retry_job,
    submit_job,
)
from hypertest.application.runtime import execute_mission
from hypertest.application.services import ConflictError, create_project
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionStatus
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import Mission, MissionAttempt
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.worker import run_claimed_job


async def new_cycle(session, repository_url, commit):
    project = await create_project(session, ProjectCreate(
        key=f"PREPCYCLE_{public_key('IT')[-12:]}", name="Automatic source cycle",
    ))
    run = await bootstrap_run(session, project.id, RunBootstrap(
        repository_url=repository_url, commit_sha=commit, prd_text=PRD_TEXT,
    ))
    job = await submit_job(session, run.id, JobType.ADVANCE_RUN,
                           payload={"prepare_workspace": True, "backend": "local"},
                           idempotency_key="automatic-cycle")
    claimed = await claim_job(session, "cycle-preparation-fixture")
    assert claimed.id == job.id
    return run, claimed


def fixture_missions(monkeypatch, harness):
    async def execute(session, mission_id, workspace, **_options):
        return await execute_mission(session, mission_id, workspace, harness=harness)

    monkeypatch.setattr(controller, "execute_mission", execute)


@pytest.mark.asyncio
async def test_one_durable_cycle_prepares_without_row_locks_and_reaches_real_pytest_verdict(
    tmp_path, monkeypatch,
):
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        run, job = await new_cycle(session, repository_url, commit)
        run_id, job_id = run.id, job.id

    async def prepare(session, received_run_id):
        assert received_run_id == run_id
        assert not session.in_transaction()
        # A second connection must acquire both rows while Git would run here.
        # Holding either lock across I/O would time out and fail this cycle.
        async with AsyncSessionLocal() as competitor:
            await asyncio.wait_for(competitor.scalar(select(CanonicalRun.id).where(
                CanonicalRun.id == run_id,
            ).with_for_update()), timeout=2)
            await asyncio.wait_for(competitor.scalar(select(DurableJob.id).where(
                DurableJob.id == job_id,
            ).with_for_update()), timeout=2)
            await competitor.commit()
        return {"workspace": str(source)}

    monkeypatch.setattr(controller, "prepare_managed_workspace", prepare)
    fixture_missions(monkeypatch, CycleHarness())
    finished = await run_claimed_job(job)
    assert finished.status is JobStatus.SUCCEEDED
    assert finished.result["reason"] == "VERDICT_FINALIZED"
    assert finished.result["workspace"] == str(source)
    assert [step["action"] for step in finished.result["steps"]] == ["mission"] * 4 + [
        "execution", "verdict",
    ]
    async with AsyncSessionLocal() as session:
        attempts = list(await session.scalars(select(MissionAttempt).where(
            MissionAttempt.durable_job_id == job_id,
        )))
        assert len(attempts) == 4
        assert (await session.get(DurableJob, job_id)).payload["prepare_workspace"] is True


@pytest.mark.asyncio
async def test_automatic_preparation_failure_never_dispatches_agent(tmp_path, monkeypatch):
    _source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        run, job = await new_cycle(session, repository_url, commit)
        run_id = run.id

    async def prepare(_session, _run_id):
        raise ConflictError("pinned repository is unavailable")

    async def forbidden_agent(*_args, **_kwargs):
        pytest.fail("Agent must not run before successful source preparation")

    monkeypatch.setattr(controller, "prepare_managed_workspace", prepare)
    monkeypatch.setattr(controller, "execute_mission", forbidden_agent)
    finished = await run_claimed_job(job)
    assert finished.status is JobStatus.FAILED
    assert "pinned repository is unavailable" in finished.error_message
    async with AsyncSessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(Mission).where(
            Mission.test_run_id == run_id,
        )) == 0
        assert await session.scalar(select(func.count()).select_from(MissionAttempt).where(
            MissionAttempt.durable_job_id == job.id,
        )) == 0


@pytest.mark.asyncio
async def test_lease_expiring_during_preparation_cannot_dispatch_agent(tmp_path, monkeypatch):
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        run, job = await new_cycle(session, repository_url, commit)
        run_id, job_id = run.id, job.id

    async def prepare(_session, _run_id):
        async with AsyncSessionLocal() as observer:
            stored = await observer.get(DurableJob, job_id)
            now = await observer.scalar(select(func.clock_timestamp()))
            stored.lease_expires_at = now - timedelta(seconds=1)
            await observer.commit()
        return {"workspace": str(source)}

    async def forbidden_agent(*_args, **_kwargs):
        pytest.fail("An expired source-preparation owner cannot dispatch a Mission")

    monkeypatch.setattr(controller, "prepare_managed_workspace", prepare)
    monkeypatch.setattr(controller, "execute_mission", forbidden_agent)
    assert await run_claimed_job(job) is None
    async with AsyncSessionLocal() as session:
        await recover_expired_jobs(session)
        stored = await session.get(DurableJob, job_id)
        assert stored.status is JobStatus.INTERRUPTED
        assert stored.result is None
        assert await session.scalar(select(func.count()).select_from(Mission).where(
            Mission.test_run_id == run_id,
        )) == 0


class PartialDesignHarness(CycleHarness):
    async def execute(self, session, mission):
        if mission["type"] == "DESIGN_TESTS":
            yield SimpleNamespace(type="RESULT_SUBMITTED", payload={
                "mission_id": mission["mission_id"], "status": "PARTIAL",
                "summary": "This fixture intentionally leaves design unfinished.", "proposals": [],
            })
        else:
            async for event in super().execute(session, mission):
                yield event


@pytest.mark.asyncio
async def test_rejected_cycle_keeps_failed_job_steps_workspace_and_mission_identity(
    tmp_path, monkeypatch,
):
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        _run, job = await new_cycle(session, repository_url, commit)

    async def prepare(_session, _run_id):
        return {"workspace": str(source)}

    monkeypatch.setattr(controller, "prepare_managed_workspace", prepare)
    fixture_missions(monkeypatch, PartialDesignHarness())
    finished = await run_claimed_job(job)
    assert finished.status is JobStatus.FAILED
    assert finished.error_code == "MISSION_REJECTED"
    result = finished.result
    assert result["reason"] == "MISSION_REJECTED"
    assert result["workspace"] == str(source)
    assert len(result["steps"]) == 3
    assert [step["status"] for step in result["steps"]] == ["COMPLETED", "COMPLETED", "RETRYING"]
    assert result["steps"][-1]["id"] == result["mission_id"]
    async with AsyncSessionLocal() as session:
        stored = await session.get(DurableJob, job.id)
        assert stored.result == result
        stored.result = {**result, "reason": "rewrite-history"}
        with pytest.raises(DBAPIError, match="terminal job is immutable"):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_failed_mission_stop_is_not_reported_as_active_work(monkeypatch):
    monkeypatch.setattr(get_settings(), "runner_allow_local", True)
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission_id = uuid7()

        async def failed_plan(_session, _run_id):
            return SimpleNamespace(mission=SimpleNamespace(
                id=mission_id, status=MissionStatus.FAILED,
            ))

        async def forbidden_agent(*_args, **_kwargs):
            pytest.fail("A failed Mission must not be silently replayed")

        monkeypatch.setattr(controller, "plan_next_mission", failed_plan)
        monkeypatch.setattr(controller, "execute_mission", forbidden_agent)
        result = await controller.advance_run(session, run.id, workspace=".", backend="local")
        assert result == {"reason": "MISSION_FAILED", "steps": [], "workspace": ".",
                          "mission_id": str(mission_id)}


@pytest.mark.asyncio
async def test_legacy_cycle_payload_replay_and_retry_do_not_rewrite_history():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        legacy_payload = {"workspace": ".", "backend": "local",
                          "timeout_seconds": 300, "max_steps": 12}
        legacy = DurableJob(id=uuid7(), key=public_key("JOB"), project_id=run.project_id,
                            test_run_id=run.id, job_type=JobType.ADVANCE_RUN,
                            status=JobStatus.FAILED, payload=legacy_payload,
                            idempotency_key="old-cycle-without-new-default")
        session.add(legacy)
        await session.commit()
        legacy_id = legacy.id
        replay = await submit_job(session, run.id, JobType.ADVANCE_RUN,
                                  payload={**legacy_payload, "prepare_workspace": False},
                                  idempotency_key=legacy.idempotency_key)
        assert replay.id == legacy_id
        assert replay.payload == legacy_payload
        with pytest.raises(ConflictError, match="different job request"):
            await submit_job(session, run.id, JobType.ADVANCE_RUN,
                             payload={"prepare_workspace": True, "backend": "local"},
                             idempotency_key=legacy.idempotency_key)
        await session.rollback()
        retried = await retry_job(session, legacy_id, idempotency_key="new-cycle-retry")
        assert retried.retry_of_job_id == legacy_id
        assert retried.payload == {**legacy_payload, "prepare_workspace": False}
        assert (await session.get(DurableJob, legacy_id)).payload == legacy_payload
        assert (await retry_job(session, legacy_id, idempotency_key="new-cycle-retry")).id == retried.id
        await cancel_job(session, retried.id)


@pytest.mark.parametrize("payload", [
    {}, {"workspace": " "}, {"workspace": ".", "prepare_workspace": True},
])
def test_cycle_source_modes_require_exactly_one_valid_choice(payload):
    with pytest.raises(ValidationError, match="choose either"):
        RunAdvance.model_validate(payload)


def test_cycle_source_modes_keep_legacy_manual_and_new_automatic_requests():
    assert RunAdvance.model_validate({"workspace": "."}).prepare_workspace is False
    assert RunAdvance.model_validate({"prepare_workspace": True}).workspace is None
