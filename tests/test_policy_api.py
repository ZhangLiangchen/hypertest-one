from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from hypertest.application.services import canonical_json_sha256
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.models import AuditEvent, PolicySnapshot, SourceSnapshot
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://hypertest"
    ) as instance:
        yield instance


@pytest.fixture
async def project_id(client: AsyncClient) -> UUID:
    response = await client.post(
        "/api/v1/projects",
        json={
            "key": public_key("POLICY_API"),
            "name": "Policy API integration",
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


async def test_policy_snapshot_api_accepts_strict_rules_and_verifiable_canonical_hash(
    client: AsyncClient,
    project_id: UUID,
) -> None:
    policy = {
        "gate_version": "mvp/v1",
        "coverage": {
            "version": "risk-design-policy/v1",
            "default_dimensions": ["FUNCTIONAL", "FAILURE"],
            "by_category": {"SECURITY": ["SECURITY", "RECOVERY"]},
        },
    }
    digest = canonical_json_sha256(policy)
    payload = {
        "project_id": str(project_id),
        "policy_version": "strict/v1",
        "content_sha256": digest.upper(),
        "compiled_policy": policy,
    }
    response = await client.post("/api/v1/policy-snapshots", json=payload)
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert snapshot["compiled_policy"] == policy
    assert snapshot["content_sha256"] == digest
    replay = await client.post(
        "/api/v1/policy-snapshots",
        json={
            **payload,
            "compiled_policy": {"coverage": policy["coverage"], "gate_version": "mvp/v1"},
        },
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == snapshot["id"]
    read = await client.get(f"/api/v1/policy-snapshots/{snapshot['id']}")
    assert read.status_code == 200
    assert read.json()["compiled_policy"] == policy
    async with AsyncSessionLocal() as session:
        assert session.bind is not None and session.bind.dialect.name == "postgresql"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PolicySnapshot)
                .where(
                    PolicySnapshot.project_id == project_id,
                )
            )
            == 1
        )


INVALID_POLICIES = [
    {"unsupported_rule": True},
    {"gate_version": "mvp/v2"},
    {"coverage": {"version": "risk-design-policy/v2"}},
    {"coverage": {"default_dimensions": ["UNKNOWN_DIMENSION"]}},
    {"coverage": {"by_category": {"UNKNOWN_RISK_CATEGORY": ["FUNCTIONAL"]}}},
    {"coverage": {"default_dimensions": ["SECURITY", "SECURITY"]}},
    {"coverage": {"unknown_coverage_rule": True}},
    {"gate": {"blocking_finding_severities": ["UNKNOWN_SEVERITY"]}},
]


@pytest.mark.parametrize("policy", INVALID_POLICIES)
async def test_policy_snapshot_api_rejects_unknown_rules_versions_and_dimensions(
    client: AsyncClient,
    project_id: UUID,
    policy: dict[str, Any],
) -> None:
    response = await client.post(
        "/api/v1/policy-snapshots",
        json={
            "project_id": str(project_id),
            "policy_version": "invalid/v1",
            "content_sha256": canonical_json_sha256(policy),
            "compiled_policy": policy,
        },
    )
    assert response.status_code == 422, response.text
    async with AsyncSessionLocal() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PolicySnapshot)
                .where(
                    PolicySnapshot.project_id == project_id,
                )
            )
            == 0
        )


async def test_policy_content_hash_mismatch_returns_422_without_snapshot(
    client: AsyncClient,
    project_id: UUID,
) -> None:
    response = await client.post(
        "/api/v1/policy-snapshots",
        json={
            "project_id": str(project_id),
            "policy_version": "baseline/v1",
            "content_sha256": "0" * 64,
            "compiled_policy": {},
        },
    )
    assert response.status_code == 422
    assert "content_sha256" in response.json()["detail"]
    async with AsyncSessionLocal() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PolicySnapshot)
                .where(
                    PolicySnapshot.project_id == project_id,
                )
            )
            == 0
        )


@pytest.mark.parametrize(
    "policy",
    [
        {"unsupported_rule": True},
        {"gate_version": "mvp/v2"},
        {"coverage": {"version": "risk-design-policy/v2"}},
        {"coverage": {"by_category": {"SECURITY": ["UNKNOWN_DIMENSION"]}}},
    ],
)
async def test_invalid_bootstrap_policy_creates_no_partial_run_or_input_artifacts(
    client: AsyncClient,
    project_id: UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: dict[str, Any],
) -> None:
    artifacts = tmp_path / "invalid-policy-artifacts"
    monkeypatch.setattr(get_settings(), "artifact_root", str(artifacts))
    response = await client.post(
        f"/api/v1/projects/{project_id}/runs/bootstrap",
        json={
            "repository_url": "https://example.invalid/policy-api.git",
            "commit_sha": "a" * 40,
            "prd_text": "Addition returns the sum of two integers.",
            "policy": policy,
            "idempotency_key": "invalid-policy-bootstrap:v1",
        },
    )
    assert response.status_code == 422, response.text
    assert not artifacts.exists()
    async with AsyncSessionLocal() as session:
        for model in (CanonicalRun, SourceSnapshot, PolicySnapshot):
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.project_id == project_id,
                    )
                )
                == 0
            )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.project_id == project_id,
                    AuditEvent.action == "test_run.created",
                )
            )
            == 0
        )


async def test_bootstrap_policy_is_pinned_and_exposed_to_run_coverage(
    client: AsyncClient,
    project_id: UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "artifact_root", str(tmp_path / "valid-policy-artifacts"))
    rules = {"coverage": {"default_dimensions": ["FUNCTIONAL", "FAILURE", "RECOVERY"]}}
    response = await client.post(
        f"/api/v1/projects/{project_id}/runs/bootstrap",
        json={
            "repository_url": "https://example.invalid/policy-api.git",
            "commit_sha": "b" * 40,
            "prd_text": "Addition returns the sum of two integers.",
            "policy": rules,
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()
    policy = await client.get(f"/api/v1/policy-snapshots/{run['policy_snapshot_id']}")
    assert policy.status_code == 200
    expected = {"gate_version": "mvp/v1", **rules}
    assert policy.json()["compiled_policy"] == expected
    assert policy.json()["content_sha256"] == canonical_json_sha256(expected)
    coverage = await client.get(f"/api/v1/test-runs/{run['id']}/coverage")
    assert coverage.status_code == 200
    assert coverage.json()["rule_version"] == "risk-design-policy/v1"
    assert len(coverage.json()["effective_policy_hash"]) == 64
