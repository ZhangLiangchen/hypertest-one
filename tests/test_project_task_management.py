"""Real DB checks of manual management, preserved result history and tombstones."""
import asyncio
import json
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_session_tasks import body, sync
from test_session_tasks import context as _management_context

from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.models import AuditEvent, OutboxEvent
from hypertest.domain.session_tasks import (
    CaseRevision,
    ReportRevision,
    SyncReceipt,
    TaskManagementRevision,
)

management_context = _management_context


async def test_manual_edit_versions_preserve_agent_results_and_fixed_pages(management_context):
    f = management_context
    payload = body(f)
    first = (await sync(f, payload)).json()
    task_id = first["task_id"]
    original = (await f["c"].get(f"/api/v1/tasks/{task_id}")).json()
    changed = await f["c"].patch(f"/api/v1/tasks/{task_id}", json={
        "expected_version": 1, "title": "Manually edited", "objective": "New scope",
        "plan_markdown": "# Manual plan", "status": "COMPLETED"})
    assert changed.status_code == 200, changed.text
    document = changed.json()
    assert document["task"]["version"] == 2
    assert document["task"]["reported_result"] == "FAIL"
    assert document["task"]["last_synced_at"] == original["task"]["last_synced_at"]
    assert document["task"]["last_managed_at"]
    assert document["cases"] == original["cases"] and document["reports"] == original["reports"]
    assert document["task"]["owner_actor_ref"] == original["task"]["owner_actor_ref"]
    assert [h["action"] for h in document["management_history"]] == ["UPDATE"]
    assert len(document["sync_history"]) == 1
    old = await f["c"].get(f"/api/v1/tasks/{task_id}", params={"version": 1})
    assert old.json()["task"] == original["task"]
    pinned = await f["c"].get("/api/v1/interactive/tasks/by-session", headers=f["headers"], params={
        "project_id": f["project_id"], "provider": payload["provider"],
        "session_id": payload["session_id"], "version": 2})
    assert json.loads(pinned.json()["content"])["task"] == document["task"]
    assert (await f["c"].patch(f"/api/v1/tasks/{task_id}", json={"expected_version": 1,
        "status": "BLOCKED"})).status_code == 409
    assert (await sync(f, {**payload, "expected_version": 1, "idempotency_key": "stale-agent"})).status_code == 409
    # An unchanged patch does not manufacture another history revision.
    noop = await f["c"].patch(f"/api/v1/tasks/{task_id}", json={"expected_version": 2,
        "status": "COMPLETED"})
    assert noop.json()["task"]["version"] == 2
    # Human workflow status can reopen without erasing the Agent's failed result.
    reopened = await f["c"].patch(f"/api/v1/tasks/{task_id}", json={"expected_version": 2,
        "status": "IN_PROGRESS"})
    assert reopened.json()["task"]["version"] == 3
    assert reopened.json()["task"]["reported_result"] == "FAIL"
    continued = await sync(f, {**payload, "expected_version": 3, "idempotency_key": "agent-after-manual"})
    assert continued.json()["version"] == 4
    assert (await sync(f, payload)).json() == first


async def test_task_delete_restore_parent_protection_and_original_receipts(management_context):
    f = management_context
    payload = body(f)
    receipt = (await sync(f, payload)).json()
    task_id = receipt["task_id"]
    project_id = f["project_id"]
    original = (await f["c"].get(f"/api/v1/tasks/{task_id}")).json()
    blocked = await f["c"].delete(f"/api/v1/projects/{project_id}", params={"expected_version": 1})
    assert blocked.status_code == 409 and "undeleted session tasks" in blocked.text
    deleted = await f["c"].delete(f"/api/v1/tasks/{task_id}", params={"expected_version": 1})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["task"]["deleted_at"] and deleted.json()["task"]["version"] == 2
    assert deleted.json()["task"]["reported_result"] == "FAIL"
    assert (await f["c"].get(f"/api/v1/tasks/{task_id}")).status_code == 404
    assert (await f["c"].get(f"/api/v1/tasks/{task_id}", params={"version": 1})).status_code == 404
    report_id = original["reports"][0]["id"]
    assert (await f["c"].get(f"/api/v1/tasks/{task_id}/reports/{report_id}")).status_code == 404
    listed = await f["c"].get("/api/v1/tasks", params={"project_id": project_id})
    assert listed.json()["total"] == 0
    trash = await f["c"].get("/api/v1/tasks", params={"project_id": project_id, "include_deleted": True})
    assert trash.json()["items"][0]["deleted_at"]
    assert (await sync(f, {**payload, "expected_version": 2, "idempotency_key": "cannot-revive"})).status_code == 409
    assert (await sync(f, {**payload, "expected_version": 0, "idempotency_key": "cannot-recreate"})).status_code == 409
    project_deleted = await f["c"].delete(f"/api/v1/projects/{project_id}", params={"expected_version": 1})
    assert project_deleted.status_code == 200 and project_deleted.json()["row_version"] == 2
    deleted_listing = await f["c"].get("/api/v1/tasks", params={"project_id": project_id, "include_deleted": True})
    assert deleted_listing.status_code == 200 and deleted_listing.json()["total"] == 1
    assert (await f["c"].get(f"/api/v1/tasks/{task_id}", params={"include_deleted": True})).status_code == 200
    assert (await f["c"].post(f"/api/v1/tasks/{task_id}/restore", json={"expected_version": 2})).status_code == 404
    assert (await f["c"].get(f"/api/v1/projects/{project_id}")).status_code == 404
    assert (await f["c"].get(f"/api/v1/projects/{project_id}", params={"include_deleted": True})).json()["deleted_at"]
    assert project_id not in [p["id"] for p in (await f["c"].get("/api/v1/projects")).json()]
    lookup = await f["c"].get("/api/v1/interactive/tasks/syncs/by-key", headers=f["headers"], params={
        "project_id": project_id, "idempotency_key": payload["idempotency_key"]})
    assert lookup.json() == receipt
    assert (await sync(f, body(f, idempotency_key="new-on-deleted-project"))).status_code == 404
    assert (await f["c"].post(f"/api/v1/projects/{project_id}/restore", json={"expected_version": 1})).status_code == 409
    restored_project = await f["c"].post(f"/api/v1/projects/{project_id}/restore", json={"expected_version": 2})
    assert restored_project.json()["deleted_at"] is None and restored_project.json()["row_version"] == 3
    restored = await f["c"].post(f"/api/v1/tasks/{task_id}/restore", json={"expected_version": 2})
    assert restored.status_code == 200, restored.text
    assert restored.json()["task"]["version"] == 3 and restored.json()["task"]["deleted_at"] is None
    assert restored.json()["reports"] == original["reports"]
    assert restored.json()["cases"] == original["cases"]
    assert [r["action"] for r in restored.json()["management_history"]] == ["DELETE", "RESTORE"]
    async with AsyncSessionLocal() as db:
        for model, expected in ((SyncReceipt, 1), (TaskManagementRevision, 2),
                                (CaseRevision, 1), (ReportRevision, 1)):
            assert await db.scalar(select(func.count()).select_from(model).where(model.task_id == UUID(task_id))) == expected
        for model, field in ((AuditEvent, AuditEvent.entity_id), (OutboxEvent, OutboxEvent.aggregate_id)):
            assert await db.scalar(select(func.count()).select_from(model).where(field == UUID(task_id))) == 3


async def test_project_edit_validation_conflict_audit_and_deleted_admission(management_context):
    f = management_context
    path = f"/api/v1/projects/{f['project_id']}"
    project = (await f["c"].get(path)).json()
    changed = await f["c"].patch(path, json={"expected_version": 1, "name": "Renamed Project",
        "description": "Manual description", "repository_url": "https://example.invalid/team/repo.git",
        "default_branch": "develop", "status": "ARCHIVED"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["key"] == project["key"] and changed.json()["row_version"] == 2
    assert changed.json()["status"] == "ARCHIVED"
    assert (await f["c"].patch(path, json={"expected_version": 1, "name": "Lost edit"})).status_code == 409
    for changes in ({"key": "OTHER"}, {"name": "  "}, {"status": None},
                    {"repository_url": "https://user:password@example.invalid/repo.git"}):
        assert (await f["c"].patch(path, json={"expected_version": 2, **changes})).status_code == 422
    assert (await f["c"].delete(path)).status_code == 422
    cleared = await f["c"].patch(path, json={"expected_version": 2, "description": None,
                                          "repository_url": None, "status": "ACTIVE"})
    assert cleared.json()["row_version"] == 3 and cleared.json()["repository_url"] is None
    assert (await f["c"].delete(path, params={"expected_version": 3})).status_code == 200
    rejected = await f["c"].post("/api/v1/interactive/registrations", headers={
        "X-Hypertest-Operator-Key": "task-sync-fixture-operator"}, json={
        "actor_ref": "must-not-register", "client_instance_id": f["auth"]["client_instance_id"],
        "project_id": f["project_id"], "scopes": ["task:sync"]})
    assert rejected.status_code == 404
    snapshot = await f["c"].post(path + "/source-snapshots", json={
        "repository_url": "https://example.invalid/repo.git", "commit_sha": "a" * 40,
        "prd_sha256": "a" * 64, "configuration_sha256": "a" * 64})
    assert snapshot.status_code == 404


async def test_manual_task_rejects_identity_and_result_rewrites(management_context):
    f = management_context
    accepted = (await sync(f, body(f))).json()
    path = f"/api/v1/tasks/{accepted['task_id']}"
    for changes in ({"reported_result": "PASS"}, {"provider": "claude"}, {"project_id": f["project_id"]},
                    {"cases": []}, {"title": None}, {"status": "PASS"}, {"title": "  "}):
        assert (await f["c"].patch(path, json={"expected_version": 1, **changes})).status_code == 422
    assert (await f["c"].get(path)).json()["task"]["version"] == 1


async def test_competing_manual_and_agent_edits_only_accept_one_version(management_context):
    f = management_context
    payload = body(f)
    accepted = (await sync(f, payload)).json()
    results = await asyncio.gather(
        f["c"].patch(f"/api/v1/tasks/{accepted['task_id']}", json={"expected_version": 1, "status": "BLOCKED"}),
        sync(f, {**payload, "expected_version": 1, "idempotency_key": "racing-agent", "title": "Agent edit"}))
    assert sorted(result.status_code for result in results) == [200, 409]
    current = (await f["c"].get(f"/api/v1/tasks/{accepted['task_id']}")).json()
    assert current["task"]["version"] == 2
    assert len(current["management_history"]) + len(current["sync_history"]) == 2


async def test_project_delete_cannot_race_new_task_admission(management_context):
    f = management_context
    results = await asyncio.gather(
        f["c"].delete(f"/api/v1/projects/{f['project_id']}", params={"expected_version": 1}),
        sync(f, body(f)))
    assert [r.status_code for r in results] in ([200, 404], [409, 200])


async def test_manual_history_is_database_immutable(management_context):
    f = management_context
    accepted = (await sync(f, body(f))).json()
    task_id = UUID(accepted["task_id"])
    assert (await f["c"].patch(f"/api/v1/tasks/{task_id}", json={"expected_version": 1,
        "status": "BLOCKED"})).status_code == 200
    for statement in (
        "UPDATE session_task_management_revisions SET action='RESTORE' WHERE task_id=:id",
        "DELETE FROM session_task_management_revisions WHERE task_id=:id",
    ):
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(statement), {"id": task_id})
                await db.commit()
            await db.rollback()


@pytest.mark.parametrize("run_kind", ["legacy", "native"])
async def test_project_with_retained_run_history_can_archive_but_cannot_delete(
        management_context, monkeypatch, run_kind):
    from test_native_intake import proposal
    from test_test_design import create_run

    from hypertest.config import get_settings

    f = management_context
    path = f"/api/v1/projects/{f['project_id']}"
    if run_kind == "legacy":
        async with AsyncSessionLocal() as db:
            await create_run(db, UUID(f["project_id"]))
    else:
        project = (await f["c"].get(path)).json()
        monkeypatch.setattr(get_settings(), "native_intake_enabled", True)
        monkeypatch.setattr(get_settings(), "native_project_keys", [project["key"]])
        admitted = await f["c"].post("/api/v1/native-runs", json=proposal(f["project_id"]),
            headers={"X-Hypertest-Operator-Key": "task-sync-fixture-operator"})
        assert admitted.status_code == 201, admitted.text
    rejected = await f["c"].delete(path, params={"expected_version": 1})
    assert rejected.status_code == 409 and f"{run_kind} test runs" in rejected.text
    archived = await f["c"].patch(path, json={"expected_version": 1, "status": "ARCHIVED"})
    assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"


async def test_waiting_sync_rechecks_project_tombstone_after_delete_commits(
        management_context, monkeypatch):
    from hypertest.application import session_tasks as service
    from hypertest.application.management import manage_project
    from hypertest.domain.models import Project

    f = management_context
    entered = asyncio.Event()
    original = service.project

    async def observed(*args, **kwargs):
        if kwargs.get("lock"):
            entered.set()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "project", observed)
    async with AsyncSessionLocal() as blocker:
        await blocker.scalar(select(Project).where(Project.id == UUID(f["project_id"])).with_for_update())
        pending = asyncio.create_task(sync(f, body(f)))
        await asyncio.wait_for(entered.wait(), timeout=10)
        deleted = await manage_project(blocker, UUID(f["project_id"]), 1, action="DELETE")
        assert deleted.deleted_at
        denied = await asyncio.wait_for(pending, timeout=10)
    assert denied.status_code == 404
    trash = await f["c"].get("/api/v1/tasks", params={"project_id": f["project_id"], "include_deleted": True})
    assert trash.json()["total"] == 0
