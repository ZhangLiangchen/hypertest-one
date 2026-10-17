"""PostgreSQL ownership constraints and admission races with legacy inline work."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from test_test_design import ProposalHarness, create_run, requirement_proposal

from hypertest.api.schemas import MissionCreate
from hypertest.application import controller
from hypertest.application.jobs import cancel_job, submit_job
from hypertest.application.services import ConflictError, create_mission
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionStatus, MissionType
from hypertest.domain.jobs import JobType
from hypertest.domain.models import MissionAttempt, Requirement


async def _mission(session: AsyncSession, run_id: UUID):
    return await create_mission(
        session,
        run_id,
        MissionCreate(
            mission_type=MissionType.ANALYZE_REQUIREMENTS,
            objective="Ownership constraint fixture",
            spec={},
            idempotency_key=public_key("OWN"),
        ),
    )


async def _job(
    session: AsyncSession,
    run_id: UUID,
    operation: JobType,
    mission_id: UUID | None = None,
) -> UUID:
    payload = {}
    if operation in {JobType.ADVANCE_RUN, JobType.EXECUTE_MISSION, JobType.EXECUTE_TESTS}:
        payload["workspace"] = "."
    if operation is JobType.EXECUTE_TESTS:
        payload["idempotency_key"] = public_key("EXREQ")
    job = await submit_job(
        session,
        run_id,
        operation,
        payload=payload,
        idempotency_key=public_key("JOBREQ"),
        mission_id=mission_id,
    )
    job_id = job.id
    # Constraint fixtures must not leave runnable requests for a live worker.
    await cancel_job(session, job_id)
    return job_id


async def _insert_work(
    session: AsyncSession,
    kind: str,
    run_id: UUID,
    mission_id: UUID,
    owner_id: UUID | None,
) -> UUID:
    work_id = uuid7()
    if kind == "attempt":
        await session.execute(
            text("""
INSERT INTO mission_attempts (id, mission_id, durable_job_id, attempt_no, status, provider_metadata)
VALUES (:id, :mission, :owner, 1, 'CREATED', CAST('{}' AS json))
"""),
            {"id": work_id, "mission": mission_id, "owner": owner_id},
        )
    else:
        await session.execute(
            text("""
INSERT INTO test_executions (
    id, key, test_run_id, durable_job_id, idempotency_key, purpose, runner_backend,
    environment_id, environment_fingerprint, source_commit, execution_spec_sha256,
    spec, status, queued_at, created_at, row_version
) VALUES (
    :id, :key, :run, :owner, :key, 'OFFICIAL', 'ownership-fixture', 'ownership-fixture',
    repeat('a', 64), repeat('b', 40), repeat('c', 64), CAST('{}' AS json),
    'QUEUED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1
)
"""),
            {"id": work_id, "key": public_key("EX"), "run": run_id, "owner": owner_id},
        )
    return work_id


@pytest.mark.parametrize("kind", ["attempt", "execution"])
@pytest.mark.parametrize("invalid_owner", ["different_run", "wrong_operation"])
async def test_database_rejects_cross_run_and_wrong_operation_ownership(
    kind: str,
    invalid_owner: str,
) -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission = await _mission(session, run.id)
        run_id, mission_id = run.id, mission.id
        if invalid_owner == "different_run":
            other = await create_run(session)
            owner_id = await _job(session, other.id, JobType.ADVANCE_RUN)
            message = "durable work and job must belong to the same test run"
        else:
            owner_id = await _job(session, run_id, JobType.EVALUATE_GATE)
            message = (
                "job cannot own this mission attempt"
                if kind == "attempt"
                else "job cannot own this execution"
            )
        with pytest.raises(DBAPIError, match=message):
            async with session.begin_nested():
                await _insert_work(session, kind, run_id, mission_id, owner_id)

        # The direct operation remains a valid owner for the same canonical run.
        valid_operation = JobType.EXECUTE_MISSION if kind == "attempt" else JobType.EXECUTE_TESTS
        valid_owner = await _job(
            session,
            run_id,
            valid_operation,
            mission_id if kind == "attempt" else None,
        )
        work_id = await _insert_work(session, kind, run_id, mission_id, valid_owner)
        await session.commit()
        table = "mission_attempts" if kind == "attempt" else "test_executions"
        assert (
            await session.scalar(
                text(f"SELECT durable_job_id FROM {table} WHERE id=:id"),
                {
                    "id": work_id,
                },
            )
            == valid_owner
        )


async def test_execute_mission_job_cannot_own_another_mission_in_the_same_run() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        original = await _mission(session, run.id)
        unrelated = await _mission(session, run.id)
        run_id, original_id, unrelated_id = run.id, original.id, unrelated.id
        owner = await _job(session, run_id, JobType.EXECUTE_MISSION, original_id)
        with pytest.raises(DBAPIError, match="job cannot own this mission attempt"):
            async with session.begin_nested():
                await _insert_work(session, "attempt", run_id, unrelated_id, owner)


@pytest.mark.parametrize("kind", ["attempt", "execution"])
async def test_database_never_reassigns_or_clears_existing_work_ownership(kind: str) -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission = await _mission(session, run.id)
        run_id, mission_id = run.id, mission.id
        original_owner = await _job(session, run_id, JobType.ADVANCE_RUN)
        other_owner = await _job(session, run_id, JobType.ADVANCE_RUN)
        work_id = await _insert_work(session, kind, run_id, mission_id, original_owner)
        await session.commit()
        table = "mission_attempts" if kind == "attempt" else "test_executions"
        for replacement in (other_owner, None):
            with pytest.raises(
                DBAPIError, match="durable work ownership is immutable|execution input is immutable"
            ):
                async with session.begin_nested():
                    await session.execute(
                        text(f"UPDATE {table} SET durable_job_id=:owner WHERE id=:id"),
                        {
                            "owner": replacement,
                            "id": work_id,
                        },
                    )
        assert (
            await session.scalar(
                text(f"SELECT durable_job_id FROM {table} WHERE id=:id"),
                {
                    "id": work_id,
                },
            )
            == original_owner
        )


@pytest.mark.parametrize("kind", ["attempt", "execution"])
async def test_legacy_unowned_work_remains_valid_and_cannot_be_retroactively_claimed(
    kind: str,
) -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        mission = await _mission(session, run.id)
        run_id, mission_id = run.id, mission.id
        owner_id = await _job(session, run_id, JobType.ADVANCE_RUN)
        work_id = await _insert_work(session, kind, run_id, mission_id, None)
        await session.commit()
        table = "mission_attempts" if kind == "attempt" else "test_executions"
        assert (
            await session.scalar(
                text(f"SELECT durable_job_id FROM {table} WHERE id=:id"),
                {
                    "id": work_id,
                },
            )
            is None
        )
        with pytest.raises(
            DBAPIError, match="durable work ownership is immutable|execution input is immutable"
        ):
            async with session.begin_nested():
                await session.execute(
                    text(f"UPDATE {table} SET durable_job_id=:owner WHERE id=:id"),
                    {
                        "owner": owner_id,
                        "id": work_id,
                    },
                )


async def test_legacy_advance_rechecks_job_admission_after_planner_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountingHarness(ProposalHarness):
        def __init__(self):
            super().__init__([requirement_proposal()])
            self.created = 0

        async def create_session(self, workspace):
            self.created += 1
            return await super().create_session(workspace)

    original_plan = controller.plan_next_mission
    queued_id = None
    planned_mission_id = None

    async def plan_then_queue(session, run_id):
        nonlocal queued_id, planned_mission_id
        result = await original_plan(session, run_id)
        assert result.mission is not None
        assert result.mission.status is MissionStatus.READY
        planned_mission_id = result.mission.id
        # Planner committed READY, opening the exact admission window under test.
        async with AsyncSessionLocal() as competitor:
            job = await submit_job(
                competitor,
                run_id,
                JobType.ADVANCE_RUN,
                payload={"workspace": "."},
                idempotency_key="queued-after-ready:v1",
            )
            queued_id = job.id
        return result

    monkeypatch.setattr(controller, "plan_next_mission", plan_then_queue)
    harness = CountingHarness()
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        run_id, snapshot_id = run.id, run.source_snapshot_id
        try:
            with pytest.raises(ConflictError, match="active background work"):
                await controller.advance_run(session, run_id, workspace=".", harness=harness)
        finally:
            # Release the guard's aggregate lock before cancelling in another session.
            await session.rollback()
            if queued_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cancel_job(cleanup, queued_id)
        assert queued_id is not None
        assert harness.created == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Requirement)
                .where(
                    Requirement.source_snapshot_id == snapshot_id,
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MissionAttempt)
                .where(
                    MissionAttempt.mission_id == planned_mission_id,
                )
            )
            == 0
        )
