"""Credential-bearing repository identities never enter new state or Agent context."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import PolicySnapshotCreate, ProjectCreate, SourceSnapshotCreate
from hypertest.api.schemas import TestRunCreate as RunCreate
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import MissionRuntimeError, execute_mission
from hypertest.application.services import (
    canonical_json_sha256,
    create_policy_snapshot,
    create_project,
    create_test_run,
)
from hypertest.common.ids import public_key, uuid7
from hypertest.common.repositories import validate_repository_origin
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionStatus
from hypertest.domain.models import AgentSessionRecord, MissionAttempt, Project, SourceSnapshot
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app

FAKE_TOKEN = "fake-origin-token-for-tests"
HTTP_TOKEN_ORIGIN = f"https://{FAKE_TOKEN}@github.com/example/project"
SSH_PASSWORD_ORIGIN = f"ssh://git:{FAKE_TOKEN}@example.invalid/project.git"

REJECTED_ORIGINS = [
    pytest.param(HTTP_TOKEN_ORIGIN, id="https-token-user"),
    pytest.param(f"http://user:{FAKE_TOKEN}@example.invalid/repo", id="http-password"),
    pytest.param("https://@github.com/example/project", id="https-empty-user"),
    pytest.param(f"https://:{FAKE_TOKEN}@github.com/example/project", id="https-empty-user-password"),
    pytest.param(SSH_PASSWORD_ORIGIN, id="ssh-password"),
    pytest.param("ssh://git:@example.invalid/project.git", id="ssh-empty-password"),
    pytest.param(f"ftp://git:{FAKE_TOKEN}@example.invalid/project", id="ftp-password"),
    pytest.param(f"git://git:{FAKE_TOKEN}@example.invalid/project", id="git-password"),
    pytest.param(f"file://git:{FAKE_TOKEN}@example.invalid/project", id="file-password"),
    pytest.param(f"https://user:{FAKE_TOKEN}%40host@example.invalid/project", id="encoded-password"),
    pytest.param(f"https://{FAKE_TOKEN}@[invalid/project", id="malformed-authority"),
]


@pytest.mark.parametrize("origin", REJECTED_ORIGINS)
def test_embedded_credentials_and_malformed_url_errors_are_redacted(origin):
    with pytest.raises(ValueError) as rejected:
        validate_repository_origin(origin)
    assert origin not in str(rejected.value)
    assert FAKE_TOKEN not in str(rejected.value)


@pytest.mark.parametrize("origin", [
    "https://github.com/example/project.git",
    "http://git.example.invalid/team/project",
    "ssh://git@example.invalid/team/project.git",
    "git@example.invalid:team/project.git",
    "/srv/git/project.git",
    "../local-origin.git",
    "file:///srv/git/project.git",
    "  https://github.com/example/project.git  ",
])
def test_credential_free_origins_are_preserved_without_rewriting(origin):
    assert validate_repository_origin(origin) == origin


@pytest.mark.parametrize("schema,fields", [
    (ProjectCreate, {"key": "ORIGIN_GUARD", "name": "Credential-free project"}),
    (SourceSnapshotCreate, {"commit_sha": "a" * 40, "prd_sha256": "b" * 64, "configuration_sha256": "c" * 64}),
    (RunBootstrap, {"commit_sha": "a" * 40, "prd_text": "Expected behavior"}),
])
def test_all_repository_creation_schemas_reject_credentials_without_echo(schema, fields):
    with pytest.raises(ValidationError) as rejected:
        schema(repository_url=HTTP_TOKEN_ORIGIN, **fields)
    assert FAKE_TOKEN not in str(rejected.value)
    assert HTTP_TOKEN_ORIGIN not in str(rejected.value)
    assert "embedded credentials" in str(rejected.value)


@pytest.mark.asyncio
async def test_project_rejection_creates_no_rows_or_input_artifacts():
    key = public_key("ORIGIN")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        response = await client.post("/api/v1/projects", json={
            "key": key, "name": "Rejected origin", "repository_url": HTTP_TOKEN_ORIGIN,
            "test_framework_repository_url": "https://git.example.invalid/framework.git",
        })
    assert response.status_code == 422
    assert FAKE_TOKEN not in response.text
    assert HTTP_TOKEN_ORIGIN not in response.text
    assert all(set(error) <= {"type", "loc", "msg"} for error in response.json()["detail"])
    async with AsyncSessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(Project).where(Project.key == key)) == 0
    assert not any(path.is_file() for path in Path(get_settings().artifact_root).rglob("*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", [HTTP_TOKEN_ORIGIN, SSH_PASSWORD_ORIGIN])
async def test_source_and_bootstrap_rejection_writes_no_snapshot_run_or_artifact(origin):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        created = await client.post("/api/v1/projects", json={
            "key": public_key("ORIGIN"), "name": "Repository origin rejection",
            "repository_url": "https://git.example.invalid/sut.git",
            "test_framework_repository_url": "https://git.example.invalid/framework.git",
        })
        assert created.status_code == 201
        project_id = created.json()["id"]
        snapshot = await client.post(f"/api/v1/projects/{project_id}/source-snapshots", json={
            "repository_url": origin, "commit_sha": "a" * 40,
            "prd_sha256": "b" * 64, "configuration_sha256": "c" * 64,
        })
        run = await client.post(f"/api/v1/projects/{project_id}/runs/bootstrap", json={
            "repository_url": origin, "commit_sha": "a" * 40,
            "prd_text": "No input should be stored", "configuration_text": "{}",
            "idempotency_key": "credentials-rejected",
        })
    for response in (snapshot, run):
        assert response.status_code == 422
        assert FAKE_TOKEN not in response.text
        assert origin not in response.text
        assert all(set(error) <= {"type", "loc", "msg"} for error in response.json()["detail"])
    async with AsyncSessionLocal() as session:
        for model in (SourceSnapshot, CanonicalRun):
            assert await session.scalar(select(func.count()).select_from(model).where(
                model.project_id == UUID(project_id),
            )) == 0
    assert not any(path.is_file() for path in Path(get_settings().artifact_root).rglob("*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", [HTTP_TOKEN_ORIGIN, SSH_PASSWORD_ORIGIN])
async def test_legacy_snapshot_credentials_block_before_agent_and_preserve_history(origin):
    class ForbiddenHarness:
        sessions_created = 0

        async def create_session(self, workspace):
            self.sessions_created += 1
            raise AssertionError("A credential-bearing snapshot must never reach an Agent")

    async with AsyncSessionLocal() as session:
        project = await create_project(session, ProjectCreate(
            key=public_key("ORIGIN"), name="Legacy repository identity",
        ))
        # Direct ORM insertion represents historical data predating input guards.
        snapshot = SourceSnapshot(
            id=uuid7(), project_id=project.id, repository_url=origin,
            commit_sha="a" * 40, prd_sha256="b" * 64, configuration_sha256="c" * 64,
            source_fingerprint=hashlib.sha256(str(project.id).encode()).hexdigest(),
        )
        session.add(snapshot)
        await session.commit()
        policy = await create_policy_snapshot(session, PolicySnapshotCreate(
            project_id=project.id, policy_version="origin-guard-v1",
            content_sha256=canonical_json_sha256({}),
        ))
        run = await create_test_run(session, RunCreate(
            project_id=project.id, source_snapshot_id=snapshot.id, policy_snapshot_id=policy.id,
        ))
        planned = await plan_next_mission(session, run.id)
        harness = ForbiddenHarness()
        with pytest.raises(MissionRuntimeError, match="embedded credentials") as rejected:
            await execute_mission(session, planned.mission.id, str(Path.cwd()), harness=harness)
        assert FAKE_TOKEN not in str(rejected.value)
        assert origin not in str(rejected.value)
        assert harness.sessions_created == 0
        assert planned.mission.status is MissionStatus.READY
        assert await session.scalar(select(func.count()).select_from(MissionAttempt).where(
            MissionAttempt.mission_id == planned.mission.id,
        )) == 0
        assert await session.scalar(select(func.count()).select_from(AgentSessionRecord).where(
            AgentSessionRecord.test_run_id == run.id,
        )) == 0
        await session.refresh(snapshot)
        assert snapshot.repository_url == origin
