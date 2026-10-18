"""Real PostgreSQL/API binding contracts, not real image/model acceptance.

The resolver substitutes a declared immutable image identity only. Gate coverage
uses the existing provider fixture plus a real explicitly enabled LocalRunner;
neither is claimed as the final real-model/Docker/API acceptance.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_bootstrap_idempotency import BASE_INPUT, create_original, saved_state
from test_delivery_loop import configure_workspace, prepare_delivery

from hypertest.application import bootstrap, gate
from hypertest.application.executions import execute_test_run
from hypertest.application.services import canonical_json_sha256
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import ExecutionOutcome, VerdictDecision, VerdictStatus
from hypertest.domain.environments import EnvironmentRequest
from hypertest.domain.models import (
    AuditEvent,
    OutboxEvent,
    PolicySnapshot,
    Project,
    SourceSnapshot,
    Verdict,
)
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app
from hypertest.runner import environments
from hypertest.runner.environments import SCHEMA_VERSION, profile_manifest

IMAGE_A = "sha256:" + "a" * 64
IMAGE_B = "sha256:" + "b" * 64
API_REQUEST = {"profile_id": "python-api-v1", "service": {"app": "application:app"}}
API_V2_REQUEST = {**API_REQUEST, "profile_id": "python-api-v2"}
EXECUTED_V1_LAUNCHER_SHA256 = "7f2c37e97c21c118eeca1cf929a338f9c97b26e50cbbf31a575ed855616e3815"
EXECUTED_V1_LOCKS = {
    "python-api-v1": "67b4693d830ec8127bf2164acbcc4a5044d6e9997173656186f31655dce337df",
    "python-pytest-v1": "12c17eed82377b0eb50c790e4a5741cd7b7529554e826bd221f31a4b2c4b2780",
}


def binding(request: EnvironmentRequest, image_id: str = IMAGE_A) -> dict:
    """A platform-resolver contract double; no Docker or registry is contacted."""
    manifest = profile_manifest(request.profile_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "request": request.model_dump(mode="json", exclude_none=True),
        "image_id": image_id, "image_os": "linux", "image_architecture": "amd64",
        **{key: value for key, value in manifest.items() if key != "profile_id"},
    }


def resolver(monkeypatch, *, image_id: str = IMAGE_A):
    observations = []

    async def resolve(request):
        observations.append(request)
        return binding(request, image_id)

    monkeypatch.setattr(bootstrap, "resolve_environment", resolve)
    return observations


async def project(client: AsyncClient) -> tuple[UUID, str]:
    response = await client.post("/api/v1/projects", json={
        "key": public_key("ENV"), "name": "Controlled environment binding contracts",
    })
    assert response.status_code == 201, response.text
    project_id = UUID(response.json()["id"])
    return project_id, f"/api/v1/projects/{project_id}/runs/bootstrap"


async def project_state(project_id: UUID) -> dict:
    """Full scoped rows and physical input bytes, including rejected-create side effects."""
    async with AsyncSessionLocal() as db:
        runs = list(await db.scalars(select(CanonicalRun.id).where(CanonicalRun.project_id == project_id)))
        state = {}
        for model, condition in (
            (Project, Project.id == project_id),
            (CanonicalRun, CanonicalRun.project_id == project_id),
            (SourceSnapshot, SourceSnapshot.project_id == project_id),
            (PolicySnapshot, PolicySnapshot.project_id == project_id),
            (AuditEvent, AuditEvent.project_id == project_id),
            (OutboxEvent, OutboxEvent.aggregate_id.in_(runs)),
        ):
            rows = (await db.execute(select(model.__table__).where(condition).order_by(model.id))).mappings()
            state[model.__tablename__] = [dict(row) for row in rows]
    root = Path(get_settings().artifact_root)
    state["artifact_bytes"] = {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }
    return state


@pytest.mark.asyncio
async def test_legacy_bootstrap_keeps_sql_null_and_original_source_fingerprint(monkeypatch):
    async def forbidden(_request):
        pytest.fail("legacy requests must not resolve or invent an environment")

    monkeypatch.setattr(bootstrap, "resolve_environment", forbidden)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, payload, run = await create_original(client)
    async with AsyncSessionLocal() as db:
        snapshot = await db.get(SourceSnapshot, UUID(run["source_snapshot_id"]))
        assert snapshot.environment_definition is None
        # JSON null and SQL NULL both decode to Python None; only SQL NULL is
        # the original contract and satisfies the legacy migration boundary.
        assert await db.scalar(select(SourceSnapshot.id).where(
            SourceSnapshot.id == snapshot.id, SourceSnapshot.environment_definition.is_(None),
        )) == snapshot.id
        expected = {
            "project_id": run["project_id"], "repository_url": payload["repository_url"],
            "commit_sha": payload["commit_sha"],
            "prd_sha256": hashlib.sha256(payload["prd_text"].encode()).hexdigest(),
            "configuration_sha256": hashlib.sha256(payload["configuration_text"].encode()).hexdigest(),
        }
        assert snapshot.source_fingerprint == canonical_json_sha256(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("environment_request", [API_REQUEST, API_V2_REQUEST], ids=["retained-v1", "current-v2"])
async def test_typed_request_freezes_platform_binding_without_rewriting_input_bytes(monkeypatch, environment_request):
    calls = resolver(monkeypatch)
    prd, configuration = "\ufeff需求：真实 API。\r\n保留换行。\n", "arbitrary legacy config\r\n非 JSON: unchanged\n"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, run = await create_original(client, environment=copy.deepcopy(environment_request),
                                          prd_text=prd, configuration_text=configuration)
    assert len(calls) == 1
    async with AsyncSessionLocal() as db:
        snapshot = await db.get(SourceSnapshot, UUID(run["source_snapshot_id"]))
        expected = binding(EnvironmentRequest.model_validate(environment_request))
        assert snapshot.environment_definition == expected
        assert snapshot.environment_definition["request"]["service"] == {
            "app": "application:app", "health_path": "/health", "startup_timeout_seconds": 30,
        }
        assert Path(snapshot.prd_artifact_uri).read_bytes() == prd.encode("utf-8")
        configuration_path = Path(get_settings().artifact_root) / "inputs" / f"{snapshot.configuration_sha256}.txt"
        assert configuration_path.read_bytes() == configuration.encode("utf-8")
        assert snapshot.configuration_sha256 == hashlib.sha256(configuration.encode()).hexdigest()
        assert gate._semantic_row(snapshot)["environment_definition"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("tag_state", ["moved", "missing"])
@pytest.mark.parametrize("environment_request", [API_REQUEST, API_V2_REQUEST], ids=["retained-v1", "current-v2"])
async def test_normalized_replay_returns_original_run_without_resolving_tag_again(monkeypatch, tag_state, environment_request):
    resolver(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path, payload, run = await create_original(client, environment=copy.deepcopy(environment_request))
        original = await saved_state(run)
        calls = []

        async def changed_tag(request):
            calls.append(request)
            if tag_state == "missing":
                raise RuntimeError("original mutable tag is no longer available")
            return binding(request, IMAGE_B)

        monkeypatch.setattr(bootstrap, "resolve_environment", changed_tag)
        equivalent = {**payload, "environment": {
            "profile_id": environment_request["profile_id"],
            "service": {"startup_timeout_seconds": 30, "health_path": "/health", "app": "application:app"},
        }}
        repeated = await client.post(path, json=equivalent)
        assert repeated.status_code == 201, repeated.text
        assert repeated.json() == run
        assert not calls
        assert await saved_state(run) == original


ENVIRONMENT_CONFLICTS = [
    pytest.param({"profile_id": "python-pytest-v1"}, id="profile"),
    pytest.param({"profile_id": "python-api-v1", "service": {"app": "different:app"}}, id="app"),
    pytest.param({"profile_id": "python-api-v1", "service": {"app": "application:app", "health_path": "/ready"}}, id="health"),
    pytest.param({"profile_id": "python-api-v1", "service": {"app": "application:app", "startup_timeout_seconds": 31}}, id="startup-timeout"),
    pytest.param(None, id="environment-removed"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ENVIRONMENT_CONFLICTS)
async def test_changed_environment_request_conflicts_before_resolution_or_writes(monkeypatch, changed):
    resolver(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path, payload, run = await create_original(client, environment=copy.deepcopy(API_REQUEST))
        original = await saved_state(run)

        async def forbidden(_request):
            pytest.fail("conflicting same-key requests must not inspect Docker")

        monkeypatch.setattr(bootstrap, "resolve_environment", forbidden)
        request = {**payload, "environment": changed}
        if changed is None:
            request.pop("environment")
        response = await client.post(path, json=request)
        assert response.status_code == 409, response.text
        assert await saved_state(run) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("untrusted", [
    {**API_REQUEST, "image_id": IMAGE_B},
    {**API_REQUEST, "environment_definition": {"image_id": IMAGE_B}},
    {"profile_id": "python-api-v1", "service": {"app": "application:app", "command": "private shell"}},
])
async def test_api_rejects_raw_binding_or_command_fields_without_side_effects(monkeypatch, untrusted):
    async def forbidden(_request):
        pytest.fail("invalid environment input must not reach the resolver")

    monkeypatch.setattr(bootstrap, "resolve_environment", forbidden)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id, path = await project(client)
        before = await project_state(project_id)
        result = await client.post(path, json={**copy.deepcopy(BASE_INPUT), "environment": untrusted})
        assert result.status_code == 422, result.text
        assert await project_state(project_id) == before


@pytest.mark.asyncio
async def test_new_request_with_changed_image_creates_a_distinct_immutable_snapshot(monkeypatch):
    resolver(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path, payload, first = await create_original(client, environment=copy.deepcopy(API_REQUEST))
        resolver(monkeypatch, image_id=IMAGE_B)
        response = await client.post(path, json={**payload, "idempotency_key": "environment:new-image"})
        assert response.status_code == 201, response.text
        second = response.json()
    assert second["id"] != first["id"]
    assert second["source_snapshot_id"] != first["source_snapshot_id"]
    async with AsyncSessionLocal() as db:
        before = await db.get(SourceSnapshot, UUID(first["source_snapshot_id"]))
        after = await db.get(SourceSnapshot, UUID(second["source_snapshot_id"]))
        assert before.environment_definition["image_id"] == IMAGE_A
        assert after.environment_definition["image_id"] == IMAGE_B
        assert before.prd_sha256 == after.prd_sha256
        assert before.configuration_sha256 == after.configuration_sha256
        assert before.source_fingerprint != after.source_fingerprint


@pytest.mark.asyncio
async def test_environment_resolution_does_not_hold_the_project_row_lock(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id, path = await project(client)
        acquired = []

        async def inspect(request):
            async with AsyncSessionLocal() as competitor:
                assert await competitor.scalar(select(Project.id).where(
                    Project.id == project_id,
                ).with_for_update(nowait=True)) == project_id
                acquired.append(project_id)
                await competitor.commit()
            return binding(request)

        monkeypatch.setattr(bootstrap, "resolve_environment", inspect)
        response = await client.post(path, json={**copy.deepcopy(BASE_INPUT), "environment": API_REQUEST})
        assert response.status_code == 201, response.text
        assert acquired == [project_id]


@pytest.mark.asyncio
async def test_concurrent_same_request_keeps_first_binding_when_tag_moves_during_resolution(monkeypatch):
    first_resolving, second_resolving, first_committed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def inspect(request):
        calls.append(request)
        if len(calls) == 1:
            first_resolving.set()
            await asyncio.wait_for(second_resolving.wait(), timeout=10)
            return binding(request, IMAGE_A)
        second_resolving.set()
        await asyncio.wait_for(first_committed.wait(), timeout=10)
        return binding(request, IMAGE_B)

    monkeypatch.setattr(bootstrap, "resolve_environment", inspect)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id, path = await project(client)
        payload = {**copy.deepcopy(BASE_INPUT), "environment": copy.deepcopy(API_REQUEST)}

        async def first_request():
            response = await client.post(path, json=payload)
            first_committed.set()
            return response

        first = asyncio.create_task(first_request())
        await asyncio.wait_for(first_resolving.wait(), timeout=10)
        second = asyncio.create_task(client.post(path, json=payload))
        try:
            responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=15)
        finally:
            for task in (first, second):
                if not task.done():
                    task.cancel()
            await asyncio.gather(first, second, return_exceptions=True)
        assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
        assert responses[0].json() == responses[1].json()
        assert len(calls) == 2
        state = await project_state(project_id)
        assert len(state["test_runs"]) == len(state["source_snapshots"]) == len(state["policy_snapshots"]) == 1
        assert state["source_snapshots"][0]["environment_definition"]["image_id"] == IMAGE_A
        assert len(state["audit_events"]) == len(state["outbox_events"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["rewrite", "clear", "delete"])
async def test_environment_binding_is_protected_by_existing_snapshot_history_guards(monkeypatch, mutation):
    resolver(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, run = await create_original(client, environment=copy.deepcopy(API_REQUEST))
    before = await saved_state(run)
    async with AsyncSessionLocal() as db:
        if mutation == "rewrite":
            statement = "UPDATE source_snapshots SET environment_definition=jsonb_set(environment_definition,'{image_id}',to_jsonb(CAST(:value AS text))) WHERE id=:id"
        elif mutation == "clear":
            statement = "UPDATE source_snapshots SET environment_definition=NULL WHERE id=:id"
        else:
            statement = "DELETE FROM source_snapshots WHERE id=:id"
        with pytest.raises(DBAPIError, match="source_snapshots is immutable"):
            async with db.begin_nested():
                await db.execute(text(statement), {"id": UUID(run["source_snapshot_id"]), "value": IMAGE_B})
    assert await saved_state(run) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("malformation", ["empty", "array", "missing", "image", "profile", "dependencies", "architecture"])
async def test_database_check_rejects_malformed_binding_on_insert(monkeypatch, malformation):
    resolver(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, run = await create_original(client)
    invalid = binding(EnvironmentRequest.model_validate(API_REQUEST))
    if malformation == "empty":
        invalid = {}
    elif malformation == "array":
        invalid = []
    elif malformation == "missing":
        invalid.pop("launcher_sha256")
    elif malformation == "image":
        invalid["image_id"] = "mutable:latest"
    elif malformation == "profile":
        invalid["request"]["profile_id"] = "arbitrary-image"
    elif malformation == "dependencies":
        invalid["dependencies"] = []
    else:
        invalid["image_architecture"] = ""
    before = await saved_state(run)
    async with AsyncSessionLocal() as db:
        source = await db.get(SourceSnapshot, UUID(run["source_snapshot_id"]))
        with pytest.raises(IntegrityError, match="ck_source_environment_binding"):
            async with db.begin_nested():
                db.add(SourceSnapshot(
                    id=uuid7(), project_id=source.project_id, repository_url=source.repository_url,
                    commit_sha=source.commit_sha, prd_sha256=source.prd_sha256,
                    configuration_sha256=source.configuration_sha256,
                    source_fingerprint=hashlib.sha256(str(uuid7()).encode()).hexdigest(),
                    environment_definition=invalid,
                ))
                await db.flush()
    assert await saved_state(run) == before


@pytest.mark.asyncio
async def test_legacy_final_keeps_pre_binding_semantics_and_original_verdict_identity(tmp_path, monkeypatch):
    """Create old-shape FINAL from real local facts, then use the new serializer."""
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    current_serializer = gate._semantic_row
    # This is the pre-0011 SourceSnapshot semantic shape, independent of the
    # new mapper's optional column. Other entity semantics are unchanged.
    legacy_fields = ("id", "project_id", "repository_url", "commit_sha", "branch",
                     "prd_sha256", "prd_artifact_uri", "configuration_sha256", "source_fingerprint")

    def legacy_serializer(instance):
        if isinstance(instance, SourceSnapshot):
            return {name: gate._json_value(getattr(instance, name)) for name in legacy_fields}
        return current_serializer(instance)

    async with AsyncSessionLocal() as db:
        state = await prepare_delivery(db, source, commit, repository_url)
        snapshot = await db.get(SourceSnapshot, state.run.source_snapshot_id)
        assert snapshot.environment_definition is None
        execution = await execute_test_run(db, state.run.id, str(source), backend="local",
                                           idempotency_key="legacy-environment-contract")
        assert execution.outcome is ExecutionOutcome.PASS
        with monkeypatch.context() as old_runtime:
            old_runtime.setattr(gate, "_semantic_row", legacy_serializer)
            original = await gate.evaluate_gate(db, state.run.id)
        assert original.status is VerdictStatus.FINAL
        assert original.decision is VerdictDecision.RELEASE_READY
        original_identity = (original.id, original.state_snapshot_hash, original.evidence_manifest_sha256,
                             original.sequence_no, original.finalized_at)
        assert current_serializer(snapshot) == legacy_serializer(snapshot)
        repeated = await gate.evaluate_gate(db, state.run.id)
        assert original_identity == (repeated.id, repeated.state_snapshot_hash, repeated.evidence_manifest_sha256,
                                     repeated.sequence_no, repeated.finalized_at)
        assert await db.scalar(select(func.count()).select_from(Verdict).where(
            Verdict.test_run_id == state.run.id, Verdict.status == VerdictStatus.FINAL,
        )) == 1


@pytest.mark.parametrize("profile_id", EXECUTED_V1_LOCKS)
def test_executed_v1_profiles_keep_their_original_launcher_and_dependency_identity(profile_id):
    """These bytes identify images that already produced real execution history."""
    manifest = profile_manifest(profile_id)
    assert manifest["launcher_sha256"] == EXECUTED_V1_LAUNCHER_SHA256
    assert manifest["dependency_lock_sha256"] == EXECUTED_V1_LOCKS[profile_id]
    if profile_id == "python-api-v1":
        frozen = binding(EnvironmentRequest.model_validate(API_REQUEST))
        assert environments.validate_binding_content(frozen).profile_id == profile_id


@pytest.mark.asyncio
async def test_catalog_offers_current_v2_while_retained_v1_is_still_a_valid_binding(monkeypatch):
    inspected = []

    async def inspect(_image, manifest):
        inspected.append(manifest["profile_id"])
        return {"Id": IMAGE_A, "Os": "linux", "Architecture": "amd64"}

    monkeypatch.setattr(environments, "inspect_bound_image", inspect)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/execution-environments")
    assert response.status_code == 200, response.text
    profiles = response.json()["profiles"]
    assert [(item["profile_id"], item["kind"]) for item in profiles] == [
        ("python-pytest-v1", "pytest"), ("python-api-v2", "asgi"),
    ]
    assert inspected == ["python-pytest-v1", "python-api-v2"]
    assert all(item["available"] is True and item["network"] == "none" for item in profiles)
    # Being absent from the new-Run selector must not invalidate saved v1 data.
    assert environments.validate_binding_content(
        binding(EnvironmentRequest.model_validate(API_REQUEST)),
    ).profile_id == "python-api-v1"


@pytest.mark.asyncio
async def test_v2_is_a_new_request_and_cannot_rebind_or_mutate_saved_v1_history(monkeypatch):
    resolver(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path, original_payload, first = await create_original(client, environment=copy.deepcopy(API_REQUEST))
        source_path = f"/api/v1/source-snapshots/{first['source_snapshot_id']}"
        original_source = await client.get(source_path)
        assert original_source.status_code == 200, original_source.text
        original_rows = await saved_state(first)
        async with AsyncSessionLocal() as db:
            source = await db.get(SourceSnapshot, UUID(first["source_snapshot_id"]))
            original_state_hash = canonical_json_sha256(gate._semantic_row(source))

        async def forbidden(_request):
            pytest.fail("same-key environment conflicts and legacy replays must not resolve images")

        monkeypatch.setattr(bootstrap, "resolve_environment", forbidden)
        conflicting = {**original_payload, "environment": copy.deepcopy(API_V2_REQUEST)}
        response = await client.post(path, json=conflicting)
        assert response.status_code == 409, response.text
        assert await saved_state(first) == original_rows

        calls = resolver(monkeypatch, image_id=IMAGE_B)
        response = await client.post(path, json={**conflicting, "idempotency_key": "environment:explicit-v2"})
        assert response.status_code == 201, response.text
        second = response.json()
        assert len(calls) == 1 and calls[0].profile_id == "python-api-v2"
        assert first["id"] != second["id"] and first["source_snapshot_id"] != second["source_snapshot_id"]

        monkeypatch.setattr(bootstrap, "resolve_environment", forbidden)
        replay = await client.post(path, json=original_payload)
        assert replay.status_code == 201 and replay.json() == first
        reread = await client.get(source_path)
        assert reread.status_code == 200 and reread.json() == original_source.json()

    async with AsyncSessionLocal() as db:
        original = await db.get(SourceSnapshot, UUID(first["source_snapshot_id"]))
        current = await db.get(SourceSnapshot, UUID(second["source_snapshot_id"]))
        assert canonical_json_sha256(gate._semantic_row(original)) == original_state_hash
        assert original.source_fingerprint == original_source.json()["source_fingerprint"]
        assert original.environment_definition["request"]["profile_id"] == "python-api-v1"
        assert original.environment_definition["launcher_sha256"] == EXECUTED_V1_LAUNCHER_SHA256
        assert current.environment_definition["request"]["profile_id"] == "python-api-v2"
        assert current.environment_definition["image_id"] == IMAGE_B
        assert current.environment_definition["launcher_sha256"] != original.environment_definition["launcher_sha256"]
        assert original.source_fingerprint != current.source_fingerprint
        assert original.prd_sha256 == current.prd_sha256
        assert original.configuration_sha256 == current.configuration_sha256
