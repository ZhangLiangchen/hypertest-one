"""Cloud/Local Project seams; synthetic management only, no Agent or SUT execution."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from test_cloud_tasks import cloud_context as _cloud_context
from test_cloud_tasks import configuration, draft, inputs, post, read_all

from hypertest.application import cloud_tasks as service
from hypertest.application.management import manage_project
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudTask
from hypertest.domain.models import Project

cloud_context = _cloud_context


@pytest.mark.parametrize("cancelled", [False, True])
async def test_any_retained_cloud_task_blocks_project_delete_but_allows_archive(cloud_context, cancelled):
    f = cloud_context
    accepted = await draft(f)
    if cancelled:
        result = await post(f, "CANCEL_TASK", 1, task_id=accepted["task_id"], reason="Retain cancelled fixture history")
        assert result.status_code == 200, result.text
        current_version = result.json()["version"]
    else:
        current_version = 1
    path = f"/api/v1/projects/{f['project_id']}"
    denied = await f["client"].delete(path, params={"expected_version": 1})
    assert denied.status_code == 409 and "1 cloud tasks" in denied.text
    archived = await f["client"].patch(path, json={"expected_version": 1, "status": "ARCHIVED"})
    assert archived.status_code == 200 and archived.json()["row_version"] == 2
    assert archived.json()["deleted_at"] is None
    original = await read_all(f, accepted["task_id"], 1)
    current = await read_all(f, accepted["task_id"], current_version)
    assert original["task"]["status"] == "DRAFT"
    assert current["task"]["status"] == ("CANCELLED" if cancelled else "DRAFT")


async def test_deleted_project_stops_cloud_admission_but_preserves_original_key_get(cloud_context):
    f = cloud_context
    other = await f["client"].post("/api/v1/interactive/registrations", headers=f["operator_headers"], json={
        "actor_ref": "another-cloud-reader-" + uuid4().hex, "client_instance_id": str(uuid4()),
        "project_id": f["project_id"], "scopes": ["cloud:read"]})
    assert other.status_code == 201
    configured = await post(f, "CONFIGURE", operation_key="retained-cloud-config", configuration=configuration())
    assert configured.status_code == 200, configured.text
    original = configured.json()
    path = f"/api/v1/projects/{f['project_id']}"
    assert (await f["client"].delete(path, params={"expected_version": 1})).status_code == 200
    receipt = await f["client"].get(
        f"/api/v1/cloud/projects/{f['project_id']}/operations/retained-cloud-config", headers=f["headers"])
    assert receipt.status_code == 200 and receipt.json() == original
    rejected = await f["client"].get(
        f"/api/v1/cloud/projects/{f['project_id']}/operations/retained-cloud-config", headers={
            "Authorization": "Bearer " + other.json()["integration_token"]})
    assert rejected.status_code == 403
    absent = await f["client"].get(
        f"/api/v1/cloud/projects/{f['project_id']}/operations/never-sent", headers=f["headers"])
    assert absent.status_code == 404 and "does not authorize replay" in absent.text
    for suffix in ("configuration", "credentials", "tasks"):
        assert (await f["client"].get(f"/api/v1/cloud/projects/{f['project_id']}/{suffix}",
                                      headers=f["headers"])).status_code == 404
    assert (await f["client"].get(f"/api/v1/projects/{f['project_id']}/task-directory",
                                  headers=f["headers"])).status_code == 404
    assert (await post(f, "CONFIGURE", 1, configuration=configuration())).status_code == 404
    assert (await post(f, "CREATE_TASK", title="No resurrection", config_id=original["config_id"],
                       inputs=inputs())).status_code == 404
    # A POST is not the recovery path, even with the original accepted key.
    assert (await post(f, "CONFIGURE", operation_key="retained-cloud-config",
                       configuration=configuration())).status_code == 404
    assert (await f["client"].get(path, params={"include_deleted": True})).json()["row_version"] == 2


@pytest.mark.parametrize("operation", ["CONFIGURE", "CREATE_TASK", "STORE_CREDENTIAL"])
async def test_waiting_cloud_write_rechecks_project_after_delete_commits(cloud_context, monkeypatch, operation):
    f = cloud_context
    fields = {"configuration": configuration()}
    if operation == "CREATE_TASK":
        configured = await post(f, "CONFIGURE", **fields)
        assert configured.status_code == 200
        fields = {"title": "Waiting admission", "config_id": configured.json()["config_id"], "inputs": inputs()}
    elif operation == "STORE_CREDENTIAL":
        fields = {"kind": "GIT_TOKEN", "label": "Synthetic credential", "purpose": "git:read",
                  "allowed_targets": [configuration()["sut"]["url"]], "allowed_actions": ["git:read"],
                  "secret": "synthetic-not-a-real-credential"}
    entered = asyncio.Event()
    original = service.project

    async def observed(*args, **kwargs):
        if kwargs.get("lock"):
            entered.set()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "project", observed)
    pending = None
    try:
        async with AsyncSessionLocal() as blocker:
            await blocker.scalar(select(Project).where(Project.id == UUID(f["project_id"])).with_for_update())
            pending = asyncio.create_task(post(f, operation, **fields))
            await asyncio.wait_for(entered.wait(), timeout=10)
            deleted = await manage_project(blocker, UUID(f["project_id"]), 1, action="DELETE")
            assert deleted.deleted_at is not None
            denied = await asyncio.wait_for(pending, timeout=10)
        assert denied.status_code == 404
        async with AsyncSessionLocal() as db:
            assert await db.scalar(select(func.count()).select_from(CloudTask).where(
                CloudTask.project_id == UUID(f["project_id"]))) == 0
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_cloud_admission_holds_project_lock_until_task_commit(cloud_context, monkeypatch):
    f = cloud_context
    configured = await post(f, "CONFIGURE", configuration=configuration())
    assert configured.status_code == 200
    entered, release = asyncio.Event(), asyncio.Event()
    original = service._configuration

    async def gated(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "_configuration", gated)
    pending = asyncio.create_task(post(f, "CREATE_TASK", title="Admission holds shared parent lock",
        config_id=configured.json()["config_id"], inputs=inputs()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError) as blocked:
                await db.scalar(select(Project).where(Project.id == UUID(f["project_id"]))
                                .with_for_update(nowait=True))
            assert blocked.value.orig.sqlstate == "55P03"  # PostgreSQL lock_not_available.
            await db.rollback()
        release.set()
        created = await asyncio.wait_for(pending, timeout=10)
        assert created.status_code == 200, created.text
        denied = await f["client"].delete(f"/api/v1/projects/{f['project_id']}", params={"expected_version": 1})
        assert denied.status_code == 409 and "cloud tasks" in denied.text
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_mixed_directory_omits_deleted_local_task_without_erasing_its_receipt(cloud_context):
    f = cloud_context
    cloud = await draft(f)
    payload = {"project_id": f["project_id"], "provider": "codex", "session_id": str(uuid4()),
        "idempotency_key": "local-directory-tombstone", "expected_version": 0, "title": "Local fixture",
        "objective": "Retain original failed result", "status": "IN_PROGRESS", "reported_result": "FAIL",
        "plan_markdown": "Synthetic management fixture", "cases": [], "reports": []}
    local = await f["client"].post("/api/v1/interactive/tasks/sync", headers=f["headers"], json=payload)
    assert local.status_code == 200, local.text
    local_receipt = local.json()
    deleted = await f["client"].delete(f"/api/v1/tasks/{local_receipt['task_id']}", params={"expected_version": 1})
    assert deleted.status_code == 200
    for headers in (f["headers"], f["operator_headers"]):
        directory = await f["client"].get(f"/api/v1/projects/{f['project_id']}/task-directory", headers=headers)
        assert directory.status_code == 200
        assert [(item["task_kind"], item["task_id"]) for item in directory.json()["items"]] == [
            ("CLOUD_TASK", cloud["task_id"])]
    receipt = await f["client"].get("/api/v1/interactive/tasks/syncs/by-key", headers=f["headers"], params={
        "project_id": f["project_id"], "idempotency_key": payload["idempotency_key"]})
    assert receipt.status_code == 200 and receipt.json() == local_receipt


async def test_directory_projection_preserves_unsynced_nulls_and_real_management_time():
    project_id = uuid4()
    created = datetime(2026, 10, 23, tzinfo=UTC)
    managed = created + timedelta(minutes=1)
    rows = [SimpleNamespace(id=uuid4(), title="Awaiting binding", provider=None, source=None,
                            status="DRAFT", reported_result="NOT_RUN", version=1,
                            created_at=created, last_managed_at=None, last_synced_at=None),
            SimpleNamespace(id=uuid4(), title="Bound, awaiting sync", provider="codex", source=None,
                            status="DRAFT", reported_result="NOT_RUN", version=2,
                            created_at=created, last_managed_at=managed, last_synced_at=None)]
    db = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(deleted_at=None)),
                         scalars=AsyncMock(return_value=rows))
    result = await service.directory(db, project_id, actor_ref="operator:fixture", local_allowed=True,
                                     cloud_allowed=False, operator=True)
    assert result["total"] == 2
    assert [item["title"] for item in result["items"]] == ["Bound, awaiting sync", "Awaiting binding"]
    assert result["items"][0]["updated_at"] == managed.isoformat()
    assert result["items"][1]["updated_at"] == created.isoformat()
    assert result["items"][1]["provider"] is None
    assert all(item["source"] is None and item["last_synced_at"] is None for item in result["items"])
