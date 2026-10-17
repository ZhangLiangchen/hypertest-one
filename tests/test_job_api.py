from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from test_test_design import create_run

from hypertest.api.schemas import MissionCreate
from hypertest.application.jobs import cancel_job, record_worker_heartbeat
from hypertest.application.services import create_mission
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionStatus, MissionType
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob, WorkerHeartbeat
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    Mission,
    MissionAttempt,
    OutboxEvent,
    Requirement,
    Verdict,
)
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://hypertest"
    ) as instance:
        yield instance


@pytest.fixture
async def job_run() -> AsyncIterator[CanonicalRun]:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
    try:
        yield run
    finally:
        # These API tests never start a worker. Leave no queued test work behind.
        async with AsyncSessionLocal() as session:
            jobs = list(
                await session.scalars(
                    select(DurableJob.id).where(
                        DurableJob.test_run_id == run.id,
                        DurableJob.status.in_(ACTIVE_JOB_STATUSES),
                    )
                )
            )
            for job_id in jobs:
                await cancel_job(session, job_id)


@pytest.mark.parametrize(
    "operation",
    [
        "ADVANCE_RUN",
        "EXECUTE_MISSION",
        "EXECUTE_TESTS",
        "EVALUATE_GATE",
        "PREPARE_WORKSPACE",
    ],
)
async def test_job_submission_returns_durable_202_without_inline_work(
    client: AsyncClient,
    job_run: CanonicalRun,
    operation: str,
) -> None:
    workspace = f"/workspace/nonexistent-job-fixture-{job_run.id}"
    payload = {}
    mission_id = None
    if operation in {"ADVANCE_RUN", "EXECUTE_MISSION", "EXECUTE_TESTS"}:
        payload["workspace"] = workspace
    if operation == "EXECUTE_TESTS":
        payload["idempotency_key"] = "execution-from-job:v1"
    if operation == "EXECUTE_MISSION":
        async with AsyncSessionLocal() as session:
            mission = await create_mission(
                session,
                job_run.id,
                MissionCreate(
                    mission_type=MissionType.ANALYZE_REQUIREMENTS,
                    objective="Deferred requirement analysis",
                    spec={},
                    idempotency_key="mission-for-job:v1",
                ),
            )
            mission_id = mission.id
    request = {"operation": operation, "idempotency_key": "submit:v1", "payload": payload}
    if mission_id:
        request["mission_id"] = str(mission_id)
    response = await client.post(f"/api/v1/test-runs/{job_run.id}/jobs", json=request)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "QUEUED"
    assert job["job_type"] == operation
    assert job["project_id"] == str(job_run.project_id)
    assert job["test_run_id"] == str(job_run.id)
    assert job["mission_id"] == (str(mission_id) if mission_id else None)
    assert job["attempts"] == 0
    assert job["worker_id"] is None
    assert job["started_at"] is None
    assert job["result"] is None
    assert job["lease_expires_at"] is None
    detail = await client.get(f"/api/v1/jobs/{job['id']}")
    assert detail.status_code == 200
    assert detail.json() == job
    listed = await client.get(f"/api/v1/test-runs/{job_run.id}/jobs")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [job["id"]]
    async with AsyncSessionLocal() as session:
        assert session.bind is not None and session.bind.dialect.name == "postgresql"
        persisted = await session.get(DurableJob, UUID(job["id"]))
        assert persisted is not None and persisted.status.value == "QUEUED"
        for model, criterion in (
            (MissionAttempt, MissionAttempt.mission_id == mission_id),
            (AgentSessionRecord, AgentSessionRecord.test_run_id == job_run.id),
            (CanonicalExecution, CanonicalExecution.test_run_id == job_run.id),
            (Verdict, Verdict.test_run_id == job_run.id),
            (Requirement, Requirement.source_snapshot_id == job_run.source_snapshot_id),
        ):
            assert (
                await session.scalar(select(func.count()).select_from(model).where(criterion)) == 0
            )
        if mission_id:
            mission = await session.get(Mission, mission_id)
            assert mission is not None and mission.status is MissionStatus.CREATED


async def test_job_idempotency_replays_same_input_and_rejects_conflicting_requests(
    client: AsyncClient,
    job_run: CanonicalRun,
) -> None:
    endpoint = f"/api/v1/test-runs/{job_run.id}/jobs"
    request = {"operation": "EVALUATE_GATE", "idempotency_key": "same-request:v1", "payload": {}}
    first = await client.post(endpoint, json=request)
    assert first.status_code == 202
    job_id = first.json()["id"]
    replay = await client.post(endpoint, json={**request, "payload": {"finalize": True}})
    assert replay.status_code == 202
    assert replay.json()["id"] == job_id
    conflicting_payload = await client.post(
        endpoint, json={**request, "payload": {"finalize": False}}
    )
    assert conflicting_payload.status_code == 409
    conflicting_type = await client.post(
        endpoint, json={**request, "operation": "PREPARE_WORKSPACE"}
    )
    assert conflicting_type.status_code == 409
    competing = await client.post(
        endpoint, json={**request, "idempotency_key": "competing-request:v1"}
    )
    assert competing.status_code == 409
    async with AsyncSessionLocal() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DurableJob)
                .where(
                    DurableJob.test_run_id == job_run.id,
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.entity_id == UUID(job_id),
                    AuditEvent.action == "job.queued",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.aggregate_id == UUID(job_id),
                    OutboxEvent.event_type == "job.queued",
                )
            )
            == 1
        )


async def test_job_cancel_and_retry_preserve_the_original_request_and_history(
    client: AsyncClient,
    job_run: CanonicalRun,
) -> None:
    first = await client.post(
        f"/api/v1/test-runs/{job_run.id}/jobs",
        json={
            "operation": "ADVANCE_RUN",
            "idempotency_key": "first-attempt:v1",
            "payload": {"workspace": f"/workspace/not-yet-prepared-{job_run.id}", "max_steps": 2},
        },
    )
    assert first.status_code == 202
    original = first.json()
    original_id = original["id"]
    cancelled = await client.post(f"/api/v1/jobs/{original_id}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["finished_at"] is not None
    assert cancelled.json()["cancel_requested_at"] is not None
    repeated = await client.post(f"/api/v1/jobs/{original_id}/cancel")
    assert repeated.status_code == 202
    assert repeated.json() == cancelled.json()
    retry = await client.post(
        f"/api/v1/jobs/{original_id}/retry", json={"idempotency_key": "retry:v1"}
    )
    assert retry.status_code == 202, retry.text
    replacement = retry.json()
    assert replacement["id"] != original_id
    assert replacement["retry_of_job_id"] == original_id
    assert replacement["status"] == "QUEUED"
    assert replacement["payload"] == original["payload"]
    assert replacement["job_type"] == original["job_type"]
    assert replacement["attempts"] == 0
    replay = await client.post(
        f"/api/v1/jobs/{original_id}/retry", json={"idempotency_key": "retry:v1"}
    )
    assert replay.status_code == 202
    assert replay.json()["id"] == replacement["id"]
    invalid_retry = await client.post(
        f"/api/v1/jobs/{replacement['id']}/retry",
        json={
            "idempotency_key": "retry-queued-work:v1",
        },
    )
    assert invalid_retry.status_code == 409
    unchanged = await client.get(f"/api/v1/jobs/{original_id}")
    assert unchanged.json() == cancelled.json()
    history = await client.get(f"/api/v1/test-runs/{job_run.id}/jobs")
    assert [item["id"] for item in history.json()] == [replacement["id"], original_id]
    async with AsyncSessionLocal() as session:
        for model, criterion in (
            (
                AuditEvent,
                (AuditEvent.entity_id == UUID(original_id))
                & (AuditEvent.action == "job.cancelled"),
            ),
            (
                OutboxEvent,
                (OutboxEvent.aggregate_id == UUID(original_id))
                & (OutboxEvent.event_type == "job.cancelled"),
            ),
        ):
            assert (
                await session.scalar(select(func.count()).select_from(model).where(criterion)) == 1
            )


async def test_job_mission_references_are_relational_and_scoped_to_the_requested_run(
    client: AsyncClient,
    job_run: CanonicalRun,
) -> None:
    async with AsyncSessionLocal() as session:
        other_run = await create_run(session)
        foreign_mission = await create_mission(
            session,
            other_run.id,
            MissionCreate(
                mission_type=MissionType.ANALYZE_REQUIREMENTS,
                objective="Belongs to another run",
                spec={},
                idempotency_key="foreign-mission:v1",
            ),
        )
    endpoint = f"/api/v1/test-runs/{job_run.id}/jobs"
    base = {
        "operation": "EXECUTE_MISSION",
        "idempotency_key": "scoped-mission:v1",
        "payload": {"workspace": "/workspace"},
    }
    for reference in (None, str(uuid7()), str(foreign_mission.id)):
        response = await client.post(endpoint, json={**base, "mission_id": reference})
        assert response.status_code == 409, response.text
    unexpected_reference = await client.post(
        endpoint,
        json={
            "operation": "EVALUATE_GATE",
            "idempotency_key": "unexpected-mission:v1",
            "mission_id": str(foreign_mission.id),
            "payload": {},
        },
    )
    assert unexpected_reference.status_code == 409
    assert (await client.get(endpoint)).json() == []


@pytest.mark.parametrize(
    ("job_request", "status"),
    [
        ({"operation": "UNRECOGNIZED", "idempotency_key": "invalid:v1"}, 422),
        (
            {"operation": "EVALUATE_GATE", "idempotency_key": "invalid:v1", "command": "ignored"},
            422,
        ),
        ({"operation": "ADVANCE_RUN", "idempotency_key": "invalid:v1", "payload": {}}, 422),
        (
            {
                "operation": "ADVANCE_RUN",
                "idempotency_key": "invalid:v1",
                "payload": {"workspace": "/workspace", "command": "ignored"},
            },
            409,
        ),
        (
            {
                "operation": "PREPARE_WORKSPACE",
                "idempotency_key": "invalid:v1",
                "payload": {"workspace": "/workspace"},
            },
            409,
        ),
    ],
)
async def test_job_input_validation_cannot_smuggle_execution_options(
    client: AsyncClient,
    job_run: CanonicalRun,
    job_request: dict,
    status: int,
) -> None:
    response = await client.post(f"/api/v1/test-runs/{job_run.id}/jobs", json=job_request)
    assert response.status_code == status, response.text
    assert (await client.get(f"/api/v1/test-runs/{job_run.id}/jobs")).json() == []


async def test_job_endpoints_return_not_found_for_unknown_references(client: AsyncClient) -> None:
    unknown = uuid7()
    assert (await client.get(f"/api/v1/jobs/{unknown}")).status_code == 404
    assert (await client.post(f"/api/v1/jobs/{unknown}/cancel")).status_code == 404
    assert (
        await client.post(f"/api/v1/jobs/{unknown}/retry", json={"idempotency_key": "retry:v1"})
    ).status_code == 404
    assert (await client.get(f"/api/v1/test-runs/{unknown}/jobs")).status_code == 404
    response = await client.post(
        f"/api/v1/test-runs/{unknown}/jobs",
        json={
            "operation": "EVALUATE_GATE",
            "idempotency_key": "missing-run:v1",
            "payload": {},
        },
    )
    assert response.status_code == 404


async def test_capabilities_reflect_a_real_postgresql_worker_heartbeat(client: AsyncClient) -> None:
    worker_id = public_key("API_WORKER")
    try:
        async with AsyncSessionLocal() as session:
            await record_worker_heartbeat(session, worker_id)
        response = await client.get("/api/v1/capabilities")
        assert response.status_code == 200
        worker = response.json()["worker"]
        assert worker["available"] is True
        assert worker["active_workers"] >= 1
        assert worker["last_seen_at"] is not None
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id)
            )
            await session.commit()
