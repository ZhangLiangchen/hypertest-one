"""Project management behavior remains independent of retired SessionTask."""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from hypertest.api.schemas import ProjectCreate
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.main import app


@pytest.fixture
async def management_context(monkeypatch):
    monkeypatch.setattr(get_settings(), "connector_operator_key", "task-sync-fixture-operator")
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("MANAGE"), name="Synthetic project"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        yield {"c": client, "project_id": str(project.id), "auth": {"client_instance_id": str(uuid4())}}


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



async def test_project_with_native_run_can_archive_but_cannot_delete(management_context, monkeypatch):
    from test_native_intake import proposal

    f = management_context
    path = f"/api/v1/projects/{f['project_id']}"
    project = (await f["c"].get(path)).json()
    monkeypatch.setattr(get_settings(), "native_intake_enabled", True)
    monkeypatch.setattr(get_settings(), "native_project_keys", [project["key"]])
    admitted = await f["c"].post("/api/v1/native-runs", json=proposal(f["project_id"]),
        headers={"X-Hypertest-Operator-Key": "task-sync-fixture-operator"})
    assert admitted.status_code == 201, admitted.text
    rejected = await f["c"].delete(path, params={"expected_version": 1})
    assert rejected.status_code == 409 and "native test runs" in rejected.text
    archived = await f["c"].patch(path, json={"expected_version": 1, "status": "ARCHIVED"})
    assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"
