"""ADR-028: retired Local tasks do not affect current domains.

Requires a dedicated synthetic PostgreSQL test database, migrated through 0033.
"""
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_local_archive import archive_context as archive_context

from hypertest.api.schemas import ProjectCreate
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudTask, ProjectCloudConfigRevision
from hypertest.domain.local_archive import LocalArchiveTask
from hypertest.domain.models import AuditEvent, OutboxEvent
from hypertest.domain.session_tasks import ReportRevision, SessionTask, SyncReceipt
from hypertest.main import app

TABLES = (
    "session_tasks", "session_task_management_revisions", "session_case_revisions",
    "session_report_revisions", "session_sync_receipts", "session_task_operation_receipts",
    "session_task_sources", "session_task_participants", "session_contribution_revisions",
    "session_task_publications", "session_collaboration_receipts",
)


async def test_retired_routes_and_capabilities():
    task, project = uuid4(), uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        for method, path in (
            ("post", f"/api/v1/projects/{project}/local-tasks"),
            ("get", f"/api/v1/projects/{project}/local-tasks/by-key"),
            ("post", "/api/v1/interactive/tasks/sync"),
            ("post", "/api/v1/interactive/tasks/bind"),
            ("get", "/api/v1/interactive/tasks/syncs/by-key"),
            ("get", f"/api/v1/tasks/{task}"),
            ("post", f"/api/v1/tasks/{task}/restore"),
            ("post", f"/api/v1/interactive/tasks/{task}/collaboration"),
        ):
            assert (await client.request(method, path, json={})).status_code in (404, 405)
        response = await client.get("/api/v1/interactive/capabilities")
        assert response.status_code == 200
        tools = {tool["name"] for tool in response.json()["tools"]}
        assert not tools.intersection({"hypertest_sync_task", "hypertest_get_task", "hypertest_bind_task",
                                       "hypertest_get_task_binding", "hypertest_join_task",
                                       "hypertest_contribute_task", "hypertest_publish_task",
                                       "hypertest_get_task_collaboration"})


async def test_migration_removes_only_retired_session_data():
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("RETIRE"), name="synthetic"))
        project_id = project.id
        now = datetime.now(UTC)
        old = SessionTask(project_id=project_id, provider="codex", session_id=str(uuid4()),
            owner_actor_ref="synthetic", title="old", objective="", status="DRAFT", plan_markdown="",
            reported_result="NOT_RUN", source="AGENT_REPORTED", version=1, last_synced_at=now)
        archive = LocalArchiveTask(project_id=project_id, creator_actor_ref="operator:synthetic",
            title="new", objective="", version=1, archive_version=1, status="DRAFT",
            reported_result="NOT_RUN", updated_at=now)
        cloud_config = ProjectCloudConfigRevision(project_id=project_id, revision=1,
            configuration={}, digest="a" * 64, created_by="synthetic")
        db.add_all([old, archive, cloud_config])
        await db.flush()
        db.add(ReportRevision(task_id=old.id, key="original", revision=1, task_version=1,
            title="Old report", markdown="synthetic", reported_result="FAIL", source="AGENT_REPORTED"))
        db.add(SyncReceipt(task_id=old.id, project_id=project_id, actor_ref="synthetic",
            idempotency_key="synthetic", input_digest="a" * 64, task_version=1,
            request_payload={}, task_snapshot={}, response={}))
        cloud = CloudTask(project_id=project_id, owner_actor_ref="synthetic", title="cloud",
            config_id=cloud_config.id, inputs={}, status="DRAFT", reported_result="NOT_RUN", version=1)
        db.add(cloud)
        for kind, obj in (("SessionTask", old), ("Project", project)):
            db.add(AuditEvent(project_id=project_id, actor_type="USER", actor_ref="synthetic",
                action="synthetic", entity_type=kind, entity_id=obj.id))
            db.add(OutboxEvent(aggregate_type=kind, aggregate_id=obj.id, event_type="synthetic", payload={}))
        await db.commit()
        old_id, archive_id, cloud_id = old.id, archive.id, cloud.id

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0034_remove_legacy_session_tasks.py"
    spec = importlib.util.spec_from_file_location("retire_session_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with AsyncSessionLocal() as db:
        conn = await db.connection()
        def apply(sync_conn):
            with Operations.context(MigrationContext.configure(sync_conn)):
                module.upgrade()
        assert (await db.execute(text("SELECT count(*) FROM session_report_revisions WHERE task_id=:id"), {"id": old_id})).scalar_one() == 1
        assert (await db.execute(text("SELECT count(*) FROM session_sync_receipts WHERE task_id=:id"), {"id": old_id})).scalar_one() == 1
        assert (await db.execute(text("SELECT count(*) FROM session_task_sources WHERE task_id=:id"), {"id": old_id})).scalar_one() == 1
        # An unexpected FK is never swept up with CASCADE. A savepoint rolls
        # back the failed migration before retrying the intended table list.
        savepoint = await db.begin_nested()
        await db.execute(text("CREATE TABLE unexpected_session_link (task_id UUID REFERENCES session_tasks(id))"))
        with pytest.raises(DBAPIError):
            await conn.run_sync(apply)
        await savepoint.rollback()
        assert await db.get(LocalArchiveTask, archive_id)
        assert await db.get(CloudTask, cloud_id)
        await conn.run_sync(apply)
        for table in TABLES:
            assert (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
        assert await db.get(LocalArchiveTask, archive_id)
        assert await db.get(CloudTask, cloud_id)
        assert await db.scalar(select(AuditEvent.id).where(AuditEvent.entity_type == "Project", AuditEvent.entity_id == project_id))
        assert not await db.scalar(select(AuditEvent.id).where(AuditEvent.entity_type == "SessionTask", AuditEvent.entity_id == old_id))
        assert await db.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_type == "Project", OutboxEvent.aggregate_id == project_id))
        assert not await db.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_type == "SessionTask", OutboxEvent.aggregate_id == old_id))
        # Preserve other synthetic tests if invoked as part of a suite.
        await db.rollback()


async def test_archive_project_delete_is_blocked(archive_context):
    f = archive_context
    response = await f["client"].delete(f"/api/v1/projects/{f['project_id']}", params={"expected_version": 1})
    assert response.status_code == 409 and "local archive tasks" in response.text
