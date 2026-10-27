"""Cutover refuses new Local sync writes while preserving accepted original keys."""
from pathlib import Path
from uuid import uuid4

from test_local_task_collaboration import member, op
from test_session_tasks import body, sync
from test_session_tasks import context as context

from hypertest.config import get_settings
from hypertest.local_sync.__main__ import hook


async def test_cutover_keeps_sync_bind_create_and_collaboration_receipts(context, monkeypatch):
    f = context
    monkeypatch.setattr(get_settings(), "local_session_writes_enabled", True)
    create_body = {"idempotency_key": "legacy-create", "title": "Preserved legacy task"}
    create_path = f"/api/v1/projects/{f['project_id']}/local-tasks"
    created = await f["c"].post(create_path, json=create_body)
    assert created.status_code == 200
    task_id = created.json()["task"]["id"]
    bind_body = {"project_id": f["project_id"], "task_id": task_id, "provider": "codex",
                 "session_id": "old-session-" + uuid4().hex, "expected_version": 1,
                 "idempotency_key": "legacy-bind"}
    bound = await f["c"].post("/api/v1/interactive/tasks/bind", headers=f["headers"], json=bind_body)
    assert bound.status_code == 200
    original = body(f, task_id=task_id, expected_version=2, session_id=bind_body["session_id"])
    accepted = await sync(f, original)
    assert accepted.status_code == 200
    enabled = await op(f, task_id, "ENABLE", 3, "legacy-enable")
    assert enabled.status_code == 200
    monkeypatch.setattr(get_settings(), "local_session_writes_enabled", False)
    assert (await sync(f, original)).json() == accepted.json()
    assert (await f["c"].post(create_path, json=create_body)).json() == created.json()
    assert (await f["c"].post("/api/v1/interactive/tasks/bind", headers=f["headers"], json=bind_body)).json() == bound.json()
    assert (await op(f, task_id, "ENABLE", 3, "legacy-enable")).json() == enabled.json()
    for response in (
        await sync(f, {**original, "idempotency_key": "new-sync", "expected_version": 4}),
        await f["c"].post(create_path, json={**create_body, "idempotency_key": "new-create"}),
        await f["c"].post("/api/v1/interactive/tasks/bind", headers=f["headers"], json={**bind_body, "idempotency_key": "new-bind"}),
        await member(f, task_id, original["session_id"], "JOIN", 4, "new-join"),
        await op(f, task_id, "ENABLE", 4, "new-enable"),
    ):
        assert response.status_code == 410, response.text
        assert response.json()["detail"] == "LOCAL_SYNC_RETIRED_USE_EXPLICIT_ARCHIVE"
    read = await f["c"].get("/api/v1/interactive/tasks/syncs/by-key", headers=f["headers"],
        params={"project_id": f["project_id"], "idempotency_key": original["idempotency_key"]})
    assert read.json() == accepted.json()
    assert (await f["c"].get(f"/api/v1/tasks/{task_id}", params={"version": 3})).json()["task"]["reported_result"] == "FAIL"


async def test_retired_hook_does_not_read_configuration_or_connect():
    assert await hook(Path("/does-not-exist/private.json")) == {"status": "IGNORED", "code": "LOCAL_SYNC_RETIRED"}
