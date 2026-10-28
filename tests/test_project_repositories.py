"""Project repository roles and task-scoped source selection."""
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hypertest.api.cloud_schemas import Repository
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.main import app


def test_cloud_repository_selector_is_optional_without_rewriting_legacy():
    url = "https://git.example.invalid/team/repo.git"
    assert Repository(url=url).model_dump(mode="json") == {"url": url, "credential_version_id": None}
    old = {"url": url, "default_selector": {"kind": "BRANCH", "value": "main",
        "feat": None, "checkout_strategy": "HEAD", "base_ref": None}, "credential_version_id": None}
    assert Repository.model_validate(old).model_dump(mode="json") == old


async def test_project_repositories_and_task_sources_preserve_history(monkeypatch):
    monkeypatch.setattr(get_settings(), "connector_operator_key", "fixture-project-source")
    headers = {"X-Hypertest-Operator-Key": "fixture-project-source"}
    sut = "https://git.example.invalid/team/sut.git"
    framework = "https://git.example.invalid/team/framework.git"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        base = {"key": public_key("SOURCES"), "name": "Project repositories"}
        for source in ({}, {"repository_url": sut}, {"repository_url": " ", "test_framework_repository_url": framework},
                       {"repository_url": sut, "test_framework_repository_url": "https://u:secret@git.invalid/r"},
                       {"repository_url": sut, "test_framework_repository_url": "https://git.invalid/r?token=secret"}):
            response = await client.post("/api/v1/projects", json={**base, **source})
            assert response.status_code == 422
            assert "secret" not in response.text
        created = await client.post("/api/v1/projects", json={**base, "repository_url": sut,
            "test_framework_repository_url": framework})
        assert created.status_code == 201, created.text
        project = created.json()
        assert project["repository_url"] == sut and project["test_framework_repository_url"] == framework
        denied_patch = await client.patch(f"/api/v1/projects/{project['id']}", json={"expected_version": 1,
            "test_framework_repository_url": "https://git.invalid/r?token=secret"})
        assert denied_patch.status_code == 422 and "secret" not in denied_patch.text
        same = await client.post("/api/v1/projects", json={"key": public_key("SAME"), "name": "Same repo",
            "repository_url": sut, "test_framework_repository_url": sut})
        assert same.status_code == 201
        request = {"project_id": project["id"], "idempotency_key": "create-source-selection",
            "title": "Task", "expected_project_version": 1,
            "sut_branch": "feature/sut", "framework_branch": "feature/test"}
        created_task = await client.post("/api/v1/local-archive/tasks", headers=headers, json=request)
        assert created_task.status_code == 200, created_task.text
        task = created_task.json()["task"]
        assert (task["sut_repository_url"], task["test_framework_repository_url"], task["sut_branch"], task["framework_branch"]) == (
            sut, framework, "feature/sut", "feature/test")
        modified = await client.patch(f"/api/v1/projects/{project['id']}", json={"expected_version": 1,
            "repository_url": "https://git.example.invalid/new/sut.git", "test_framework_repository_url": sut})
        assert modified.status_code == 200
        replay = await client.post("/api/v1/local-archive/tasks", headers=headers, json=request)
        assert replay.json() == created_task.json()
        stale = await client.post("/api/v1/local-archive/tasks", headers=headers,
            json={**request, "idempotency_key": "stale-project"})
        assert stale.status_code == 409 and "ARCHIVE_PROJECT_VERSION_CONFLICT" in stale.text
        conflict = await client.post("/api/v1/local-archive/tasks", headers=headers,
            json={**request, "sut_branch": "another"})
        assert conflict.status_code == 409
        read = await client.get(f"/api/v1/local-archive/tasks/{task['id']}", headers=headers,
            params={"project_id": project["id"]})
        assert read.json()["task"]["sut_repository_url"] == sut
        assert read.json()["task"]["framework_branch"] == "feature/test"
        for invalid in (" ", "foo\nbar", "foo bar"):
            rejected = await client.post("/api/v1/local-archive/tasks", headers=headers,
                json={**request, "idempotency_key": "bad-branch", "sut_branch": invalid})
            assert rejected.status_code == 422
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE local_archive_tasks SET sut_branch='other', version=version+1 WHERE id=:id"),
                {"id": UUID(task["id"])})
            await db.commit()
        await db.rollback()
