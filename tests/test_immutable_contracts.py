"""PostgreSQL regression checks for frozen snapshots and Mission work contracts."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from test_test_design import ProposalHarness, create_run, requirement_proposal

from hypertest.api.schemas import MissionCreate
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import execute_mission
from hypertest.application.services import canonical_json_sha256, create_mission
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionAttemptStatus, MissionStatus, MissionType, Priority
from hypertest.domain.models import Mission, PolicySnapshot, SourceSnapshot


async def rejects_mutation(
    session: AsyncSession, statement: str, parameters: dict[str, Any], message: str
) -> None:
    # Savepoints keep deliberately rejected SQL from invalidating fixture IDs or history.
    with pytest.raises(DBAPIError, match=message):
        async with session.begin_nested():
            await session.execute(text(statement), parameters)


@pytest.mark.parametrize(
    ("model", "table", "column", "value"),
    [
        (SourceSnapshot, "source_snapshots", "commit_sha", "9" * 40),
        (SourceSnapshot, "source_snapshots", "prd_sha256", "9" * 64),
        (SourceSnapshot, "source_snapshots", "configuration_sha256", "9" * 64),
        (SourceSnapshot, "source_snapshots", "branch", "rewritten"),
        (PolicySnapshot, "policy_snapshots", "content_sha256", "9" * 64),
        (PolicySnapshot, "policy_snapshots", "policy_version", "rewritten"),
        (PolicySnapshot, "policy_snapshots", "artifact_uri", "/rewritten-policy"),
    ],
)
async def test_snapshot_rows_reject_direct_sql_changes(model, table, column, value) -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        snapshot_id = run.source_snapshot_id if model is SourceSnapshot else run.policy_snapshot_id
        await rejects_mutation(
            session,
            f"UPDATE {table} SET {column}=:value WHERE id=:id",
            {"value": value, "id": snapshot_id},
            f"{table} is immutable",
        )
        # Re-saving identical values is harmless, including JSON object key ordering.
        await session.execute(text(f"UPDATE {table} SET {column}={column} WHERE id=:id"),
                              {"id": snapshot_id})
        await session.commit()


async def test_policy_json_and_snapshot_orm_updates_are_guarded() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        snapshot = await session.get(SourceSnapshot, run.source_snapshot_id)
        assert snapshot is not None
        snapshot_id = snapshot.id
        with pytest.raises(DBAPIError, match="source_snapshots is immutable"):
            async with session.begin_nested():
                snapshot.repository_url = "https://example.invalid/rewritten.git"
                await session.flush()
        await session.refresh(snapshot)
        assert snapshot.id == snapshot_id
        assert snapshot.repository_url == "https://example.invalid/test-design.git"
        await rejects_mutation(
            session,
            "UPDATE policy_snapshots SET compiled_policy=CAST(:value AS json) WHERE id=:id",
            {"value": '{"gate":{"blocking_finding_severities":[]}}', "id": run.policy_snapshot_id},
            "policy_snapshots is immutable",
        )


async def test_unreferenced_snapshots_cannot_be_deleted() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        source = SourceSnapshot(
            project_id=run.project_id,
            repository_url="https://example.invalid/unused.git",
            commit_sha="1" * 40,
            prd_sha256="2" * 64,
            configuration_sha256="3" * 64,
            source_fingerprint="4" * 64,
        )
        policy = PolicySnapshot(
            project_id=run.project_id,
            policy_name="Unused policy",
            policy_version="1",
            content_sha256="5" * 64,
        )
        session.add_all([source, policy])
        await session.commit()
        # Neither object has a TestRun FK; the invariant must hold independently.
        for table, snapshot_id in (("source_snapshots", source.id), ("policy_snapshots", policy.id)):
            await rejects_mutation(
                session, f"DELETE FROM {table} WHERE id=:id", {"id": snapshot_id},
                f"{table} is immutable",
            )


async def test_ready_mission_freezes_every_contract_field() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        planned = await plan_next_mission(session, run.id)
        mission = planned.mission
        assert mission is not None and mission.status is MissionStatus.READY
        mission_id = mission.id
        changes = {
            "id": uuid7(),
            "key": public_key("MIS"),
            "test_run_id": uuid7(),
            "mission_type": MissionType.ANALYZE_RISKS.value,
            "priority": Priority.P3.value,
            "objective": "Changed objective",
            "protocol_version": "rewritten/v1",
            "spec_sha256": "9" * 64,
            "idempotency_key": "rewritten:request",
            "created_by": "rewritten-actor",
            "created_at": datetime.now(UTC) + timedelta(days=1),
        }
        for column, value in changes.items():
            await rejects_mutation(
                session, f"UPDATE missions SET {column}=:value WHERE id=:id",
                {"value": value, "id": mission_id}, "mission contract is immutable",
            )
        await rejects_mutation(
            session, "UPDATE missions SET spec=CAST(:value AS json) WHERE id=:id",
            {"value": '{"targets":{"requirements":["unrelated"]}}', "id": mission_id},
            "mission contract is immutable",
        )
        await session.execute(text("UPDATE missions SET spec=spec WHERE id=:id"), {"id": mission_id})
        await session.commit()


@pytest.mark.parametrize("status", ["READY", "RUNNING", "RETRYING", "COMPLETED", "CANCELLED"])
async def test_mission_cannot_thaw_or_delete_its_contract_after_leaving_created(status) -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        planned = await plan_next_mission(session, run.id)
        assert planned.mission is not None
        mission_id = planned.mission.id
        await session.execute(
            text("UPDATE missions SET status=:status, row_version=row_version+1 WHERE id=:id"),
            {"status": status, "id": mission_id},
        )
        await session.commit()
        for statement in (
            "UPDATE missions SET status='CREATED' WHERE id=:id",
            "UPDATE missions SET objective='Rewritten history' WHERE id=:id",
            "DELETE FROM missions WHERE id=:id",
        ):
            await rejects_mutation(session, statement, {"id": mission_id}, "mission contract is immutable")


async def test_draft_editing_and_normal_planner_runtime_remain_supported() -> None:
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        draft = await create_mission(
            session, run.id,
            MissionCreate(
                mission_type=MissionType.ANALYZE_REQUIREMENTS,
                objective="Draft objective",
                spec={"context": {}},
                idempotency_key="editable-draft",
            ),
        )
        assert draft.status is MissionStatus.CREATED
        draft.objective = "Revised draft objective"
        draft.spec = {"context": {"source_snapshot": str(run.source_snapshot_id)}}
        draft.spec_sha256 = canonical_json_sha256(draft.spec)
        await session.commit()
        draft_id = draft.id
        await session.delete(draft)
        await session.commit()
        assert await session.get(Mission, draft_id) is None

        planned = await plan_next_mission(session, run.id)
        assert planned.mission is not None
        mission_id = planned.mission.id
        contract_hash = planned.mission.spec_sha256
        completed = await execute_mission(
            session, mission_id, workspace=".",
            harness=ProposalHarness([requirement_proposal()]),
        )
        assert completed.mission.status is MissionStatus.COMPLETED
        assert completed.attempt.status is MissionAttemptStatus.ACCEPTED
        assert completed.mission.spec_sha256 == contract_hash
        assert len(completed.requirements) == 1
        await rejects_mutation(
            session, "UPDATE missions SET objective='Changed after acceptance' WHERE id=:id",
            {"id": mission_id}, "mission contract is immutable",
        )
