from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.models import AuditEvent, OutboxEvent, PolicySnapshot, SourceSnapshot
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app

BASE_INPUT = {
    "repository_url": "https://github.com/example/checkout",
    "commit_sha": "a1b2c3d4" * 5,
    "branch": "main",
    "prd_text": "Checkout must preserve the submitted quantity and reject negative quantities.",
    "configuration_text": '{"feature_enabled": true}',
    "policy": {
        "coverage": {
            "default_dimensions": ["FUNCTIONAL", "FAILURE"],
            "by_category": {"SECURITY": ["FUNCTIONAL", "SECURITY"]},
        },
        "gate": {"blocking_finding_severities": ["BLOCKER", "CRITICAL"]},
    },
    "idempotency_key": "bootstrap:original-request",
}


async def create_original(client: AsyncClient, **changes: Any) -> tuple[str, dict, dict]:
    project = await client.post(
        "/api/v1/projects",
        json={"key": public_key("BOOTSTRAP"), "name": "Bootstrap request identity"},
    )
    assert project.status_code == 201, project.text
    path = f"/api/v1/projects/{project.json()['id']}/runs/bootstrap"
    payload = {**copy.deepcopy(BASE_INPUT), **changes}
    response = await client.post(path, json=payload)
    assert response.status_code == 201, response.text
    return path, payload, response.json()


async def saved_state(run: dict) -> dict:
    """Read complete stored rows and input bytes to catch writes on rejected retries."""
    project_id = UUID(run["project_id"])
    async with AsyncSessionLocal() as session:
        state = {}
        for model, condition in (
            (CanonicalRun, CanonicalRun.project_id == project_id),
            (SourceSnapshot, SourceSnapshot.project_id == project_id),
            (PolicySnapshot, PolicySnapshot.project_id == project_id),
            (AuditEvent, AuditEvent.project_id == project_id),
            (OutboxEvent, OutboxEvent.aggregate_id == UUID(run["id"])),
        ):
            rows = (await session.execute(
                select(model.__table__).where(condition).order_by(model.id)
            )).mappings().all()
            state[model.__tablename__] = [dict(row) for row in rows]
    root = Path(get_settings().artifact_root)
    state["input_artifacts"] = {
        str(path.relative_to(root)): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in root.rglob("*") if path.is_file()
    }
    return state


CONFLICTING_INPUTS = [
    pytest.param({"prd_text": BASE_INPUT["prd_text"] + " New requirement."}, id="prd"),
    pytest.param({"configuration_text": '{"feature_enabled":true}'}, id="configuration-bytes"),
    pytest.param({"repository_url": "https://github.com/example/another"}, id="repository"),
    pytest.param({"commit_sha": "b" * 40}, id="commit"),
    pytest.param({"policy": {
        **copy.deepcopy(BASE_INPUT["policy"]),
        "gate": {"blocking_finding_severities": ["MAJOR"]},
    }}, id="gate"),
    pytest.param({"policy": {"coverage": {"default_dimensions": ["FUNCTIONAL"]}}}, id="coverage"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", CONFLICTING_INPUTS)
async def test_conflicting_bootstrap_retry_returns_409_without_writing_inputs(changes: dict) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        path, payload, run = await create_original(client)
        original = await saved_state(run)
        response = await client.post(path, json={**payload, **changes})
        assert response.status_code == 409, response.text
        assert "idempotency key" in response.json()["detail"]
        assert await saved_state(run) == original
        replay = await client.post(path, json=payload)
        assert replay.status_code == 201, replay.text
        assert replay.json() == run
        assert await saved_state(run) == original


@pytest.mark.asyncio
async def test_normalized_bootstrap_retry_reuses_original_run_and_immutable_snapshots() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        path, payload, run = await create_original(client)
        original = await saved_state(run)
        equivalent = {
            **payload,
            "repository_url": f"  {payload['repository_url']}  ",
            "commit_sha": payload["commit_sha"].upper(),
            "branch": " main ",
            "policy": {
                "gate": {"blocking_finding_severities": ["CRITICAL", "BLOCKER"]},
                "gate_version": "mvp/v1",
                "coverage": {
                    "by_category": {"SECURITY": ["SECURITY", "FUNCTIONAL"]},
                    "default_dimensions": ["FAILURE", "FUNCTIONAL"],
                    "version": "risk-design-policy/v1",
                },
            },
        }
        response = await client.post(path, json=equivalent)
        assert response.status_code == 201, response.text
        assert response.json() == run
        assert await saved_state(run) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["release", None])
async def test_branch_reference_label_does_not_change_bootstrap_identity(branch: str | None) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        path, payload, run = await create_original(client)
        original = await saved_state(run)
        response = await client.post(path, json={**payload, "branch": branch})
        assert response.status_code == 201, response.text
        assert response.json() == run
        assert await saved_state(run) == original


@pytest.mark.asyncio
async def test_explicit_default_policy_and_blank_branch_are_equivalent_on_retry() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        path, payload, run = await create_original(client, policy={}, branch=None)
        original = await saved_state(run)
        response = await client.post(path, json={
            **payload,
            "branch": "  ",
            "policy": {
                "gate_version": "mvp/v1",
                "gate": {"blocking_finding_severities": ["CRITICAL", "BLOCKER"]},
                "coverage": {"version": "risk-design-policy/v1", "default_dimensions": ["FUNCTIONAL"]},
            },
        })
        assert response.status_code == 201, response.text
        assert response.json() == run
        assert await saved_state(run) == original


@pytest.mark.asyncio
async def test_bootstrap_retry_reuses_shared_source_when_branch_label_differs() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hypertest") as client:
        path, payload, first = await create_original(client)
        second_input = {
            **payload, "branch": "release", "idempotency_key": "bootstrap:second-request",
        }
        created = await client.post(path, json=second_input)
        assert created.status_code == 201, created.text
        second = created.json()
        assert second["id"] != first["id"]
        assert second["source_snapshot_id"] == first["source_snapshot_id"]
        original = await saved_state(second)
        response = await client.post(path, json=second_input)
        assert response.status_code == 201, response.text
        assert response.json() == second
        assert await saved_state(second) == original
