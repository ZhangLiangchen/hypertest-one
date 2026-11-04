"""ADR-019 PostgreSQL/API acceptance with synthetic framework reports, no Agent execution."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from hypertest.api.cloud_schemas import (
    CloudConfigure,
    CloudMutation,
    CloudTaskInputs,
    Configuration,
    TaskInputs,
)
from hypertest.api.schemas import ProjectCreate
from hypertest.application import cloud_tasks as service
from hypertest.application.services import create_project
from hypertest.cloud.broker import CloudBroker
from hypertest.cloud.reporter import CloudTaskReporter
from hypertest.cloud.worker import CloudWorker
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import (
    CloudAttempt,
    CloudConfigCredential,
    CloudInputResolution,
    CloudOperationReceipt,
    CloudTask,
    CloudWorkGrant,
    CredentialVersion,
    ProjectCloudConfigRevision,
)
from hypertest.domain.models import Project
from hypertest.main import app

SHA = "1" * 40
FRAMEWORK_SHA = "2" * 40
ORIGIN = "https://git.example.invalid/sut.git"
FRAMEWORK_ORIGIN = "https://git.example.invalid/framework.git"
OPERATOR = "cloud-fixture-operator"


@pytest.fixture
async def cloud_context(monkeypatch, tmp_path):
    settings = get_settings()
    key_file = tmp_path / "wrapping-key"
    key_file.write_bytes(base64.b64encode(b"x" * 32))
    key_file.chmod(0o600)
    monkeypatch.setattr(settings, "cloud_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_enabled", False)
    monkeypatch.setattr(settings, "cloud_attempt_timeout_seconds", 60)
    monkeypatch.setattr(settings, "cloud_credential_key_file", str(key_file))
    monkeypatch.setattr(settings, "connector_operator_key", OPERATOR)
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("CLOUD"), name="Cloud synthetic acceptance",
            repository_url=ORIGIN, test_framework_repository_url=FRAMEWORK_ORIGIN))
        project_id = str(project.id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        scopes = ["cloud:configure", "credential:manage", "cloud:dispatch", "cloud:control", "cloud:read", "task:sync"]
        auth = await client.post("/api/v1/interactive/registrations", headers={"X-Hypertest-Operator-Key": OPERATOR}, json={
            "actor_ref": "cloud-fixture-" + uuid4().hex, "client_instance_id": str(uuid4()),
            "project_id": project_id, "scopes": scopes})
        assert auth.status_code == 201, auth.text
        yield {"client": client, "project_id": project_id, "grant": auth.json(),
               "headers": {"Authorization": "Bearer " + auth.json()["integration_token"]},
               "operator_headers": {"X-Hypertest-Operator-Key": OPERATOR}}


def configuration(**changes):
    return {"sut": {"url": ORIGIN, "default_selector": {"kind": "BRANCH", "value": "feature/test"}},
            "framework": {"url": FRAMEWORK_ORIGIN, "default_selector": {"kind": "BRANCH", "value": "main"}},
            "environment": {"name": "Workspace fixture", "connection": "NONE"}, **changes}


def inputs(**changes):
    return {"sut_selector": {"kind": "BRANCH", "value": "feature/test"},
            "framework_selector": {"kind": "BRANCH", "value": "main"},
            "prd_markdown": "# Fixture PRD\nSynthetic protocol acceptance only.", "prd_version": "fixture-v1",
            "objective": "Preserve a synthetic failing framework report", "basic_flow": "Read fixture, record exact result",
            "test_scope": "Control-plane fixture; no model/SUT is invoked",
            "framework_entrypoints": ["python -m pytest"],
            "expected_outputs": ["ANALYSIS", "DESIGN", "CASE", "IMPLEMENTATION", "REPORT"],
            "authorization": {"targets": [ORIGIN, FRAMEWORK_ORIGIN],
                "permitted_actions": ["git:read", "framework:execute"], "network_targets": [],
                "side_effect_limits": "Workspace fixture only; no remote writes",
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
            "budgets": {"total_seconds": 600, "total_cost_microunits": 10000}, **changes}


def new_inputs(**changes):
    """Current creation contract; historical budget fixtures use inputs()."""
    data = inputs(**changes)
    data.pop("budgets", None)
    data.setdefault("mr_url", "https://git.example.invalid/sut/-/merge_requests/1")
    data["authorization"] = changes.get("authorization")
    return data


async def post(context, operation, expected_version=0, operation_key=None, **fields):
    response = await context["client"].post("/api/v1/cloud/operations", headers=context["headers"], json={
        "project_id": context["project_id"], "operation": operation,
        "operation_key": operation_key or "fixture-" + uuid4().hex,
        "expected_version": expected_version, **fields})
    return response


async def seed_legacy_configuration(context, config=None, operation_key=None):
    """Explicit historical fixture only; retired resource writes are not API setup."""
    value = Configuration.model_validate(config or configuration()).model_dump(mode="json")
    async with AsyncSessionLocal() as db:
        await service._lock(db, f"cloud-config:{context['project_id']}")
        latest = await db.scalar(select(ProjectCloudConfigRevision).where(
            ProjectCloudConfigRevision.project_id == UUID(context["project_id"]))
            .order_by(ProjectCloudConfigRevision.revision.desc()).limit(1))
        row = ProjectCloudConfigRevision(id=uuid7(), project_id=UUID(context["project_id"]),
            revision=latest.revision + 1 if latest else 1, configuration=value,
            digest=service.canonical_json_sha256(value), created_by="legacy-fixture")
        db.add(row)
        await db.flush()
        for role, version, _ in await service._credential_versions(db, value, now=await service.clock(db)):
            db.add(CloudConfigCredential(project_id=row.project_id, config_id=row.id,
                credential_version_id=version.id, role=role))
        if operation_key:
            from hypertest.domain.interactive import InteractiveIntegrationGrant
            grant = await db.get(InteractiveIntegrationGrant, UUID(context["grant"]["grant_id"]))
            payload = CloudConfigure(project_id=row.project_id, operation_key=operation_key,
                expected_version=row.revision - 1, configuration=value)
            response = {"status": "ACCEPTED", "profile": service.PROFILE, "project_id": str(row.project_id),
                "operation_key": operation_key, "operation": "CONFIGURE", "version": row.revision,
                "config_id": str(row.id)}
            db.add(CloudOperationReceipt(id=uuid7(), project_id=row.project_id,
                operation_key=operation_key, operation="CONFIGURE",
                actor_ref="interactive:" + str(grant.actor_identity_id),
                input_digest=service.canonical_json_sha256(service._safe_payload(payload)),
                expected_version=row.revision - 1, accepted_version=row.revision, response=response))
        await db.commit()
        return row.id


async def draft(context, *, config=None, task_inputs=None):
    async with AsyncSessionLocal() as db:
        project = await db.get(Project, UUID(context["project_id"]))
        if config is not None:
            project.repository_url = config["sut"]["url"]
            project.test_framework_repository_url = config["framework"]["url"]
            await db.commit()
        project_version = project.row_version
    task_data = dict(task_inputs) if task_inputs is not None else new_inputs()
    task_data.setdefault("mr_url", "https://git.example.invalid/sut/-/merge_requests/1")
    created = await post(context, "CREATE_TASK", title="Cloud synthetic fixture", expected_project_version=project_version,
                         inputs=task_data)
    assert created.status_code == 200, created.text
    return created.json()


async def legacy_draft(context, *, task_inputs, config=None):
    """Seed an old undispatched authorization; new requests cannot configure it."""
    config_id = await seed_legacy_configuration(context, config)
    value = dict(task_inputs)
    value.pop("mr_url", None)
    value = TaskInputs.model_validate(value).model_dump(mode="json")
    async with AsyncSessionLocal() as db:
        row = CloudTask(id=uuid7(), project_id=UUID(context["project_id"]), owner_actor_ref="legacy-fixture",
            title="Legacy draft fixture", config_id=config_id, inputs=value, status="DRAFT", version=1,
            reported_result="NOT_RUN")
        db.add(row)
        await db.commit()
        return {"task_id": str(row.id), "version": 1}


async def dispatched(context, *, framework_sha=FRAMEWORK_SHA, **draft_options):
    created = await draft(context, **draft_options)
    task_id = created["task_id"]
    requested = await post(context, "RESOLVE_INPUTS", 1, task_id=task_id)
    assert requested.status_code == 200, requested.text
    async with AsyncSessionLocal() as db:
        claim = await service.claim_resolution(db, "fixture-worker", project_id=UUID(context["project_id"]))
        result = {"repositories": {
            "sut": {"url": ORIGIN, "commit_sha": SHA, "selector": claim["task"]["inputs"]["sut_selector"]},
            "framework": {"url": FRAMEWORK_ORIGIN, "commit_sha": framework_sha,
                          "selector": claim["task"]["inputs"]["framework_selector"]}},
            "environment_observation": {"deployment": "UNKNOWN", "source": "synthetic-fixture"},
            "observed_at": datetime.now(UTC).isoformat(), "source": "synthetic-fixture-no-git-executed"}
        resolved = await service.accept_resolution(db, UUID(claim["resolution"]["id"]), "fixture-worker",
            claim["lease_token"], result, work_token=claim["work_token"])
    accepted = await post(context, "DISPATCH", resolved["version"], task_id=task_id,
                          resolution_id=requested.json()["resolution_id"])
    assert accepted.status_code == 200, accepted.text
    return accepted.json()


async def legacy_dispatched(context, *, config=None, task_inputs=None, framework_sha=FRAMEWORK_SHA):
    """Seed a historical frozen budgeted attempt in the dedicated test DB.

    New CREATE/DISPATCH intentionally reject this legacy contract. The fixture
    inserts a coherent frozen manifest, original attempt and receipt explicitly;
    it does not change the current API or replay any external action.
    """
    config_id = await seed_legacy_configuration(context, config)
    project_id = UUID(context["project_id"])
    task_id, resolution_id, attempt_id = uuid7(), uuid7(), uuid7()
    task_input = TaskInputs.model_validate(task_inputs or inputs()).model_dump(mode="json")
    assert task_input["budgets"] is not None
    now = datetime.now(UTC)
    result = {"repositories": {
        "sut": {"url": ORIGIN, "commit_sha": SHA, "selector": task_input["sut_selector"]},
        "framework": {"url": FRAMEWORK_ORIGIN, "commit_sha": framework_sha,
                      "selector": task_input["framework_selector"]}},
        "environment_observation": {"deployment": "UNKNOWN", "source": "synthetic-fixture"},
        "observed_at": now.isoformat(), "source": "synthetic-fixture-no-git-executed"}
    async with AsyncSessionLocal() as db:
        revision = await db.get(ProjectCloudConfigRevision, config_id)
        manifest = {"profile": service.PROFILE, "project_id": str(project_id), "cloud_task_id": str(task_id),
            "config_id": str(config_id), "config_revision": revision.revision, "configuration": revision.configuration,
            "inputs": task_input, "resolution": result, "resolution_id": str(resolution_id),
            "prd_sha256": hashlib.sha256(task_input["prd_markdown"].encode()).hexdigest()}
        digest = service.canonical_json_sha256(manifest)
        task = CloudTask(id=task_id, project_id=project_id, owner_actor_ref="legacy-fixture",
            title="Cloud synthetic legacy fixture", config_id=config_id, inputs=task_input,
            status="QUEUED", version=4, reported_result="NOT_RUN", frozen_manifest=manifest, input_digest=digest)
        db.add(task)
        await db.flush()
        resolution = CloudInputResolution(id=resolution_id, project_id=project_id, task_id=task_id,
            operation_key="legacy-resolve-" + uuid4().hex, source_draft_version=2, accepted_task_version=3,
            source_digest=service.canonical_json_sha256({"inputs": task_input, "config_id": str(config_id), "config_digest": revision.digest}),
            status="ACCEPTED", result=result, digest=service.canonical_json_sha256(result),
            requested_by="legacy-fixture", accepted_at=now, grant_id=UUID(context["grant"]["grant_id"]))
        attempt = CloudAttempt(id=attempt_id, project_id=project_id, task_id=task_id, attempt_no=1,
            input_digest=digest, status="QUEUED", reported_result="NOT_RUN", lease_generation=0,
            checkpoint={}, runtime_metadata={}, usage_seconds=0, cost_microunits=0,
            authorization_grant_id=UUID(context["grant"]["grant_id"]))
        db.add_all([resolution, attempt])
        await db.flush()
        task.latest_attempt_id = attempt_id
        await db.flush()
        operation_key = "legacy-dispatch-" + uuid4().hex
        response = {"status": "ACCEPTED", "profile": service.PROFILE, "project_id": str(project_id),
            "operation_key": operation_key, "operation": "DISPATCH", "version": 4, "task_id": str(task_id),
            "attempt_id": str(attempt_id), "input_digest": digest}
        db.add(CloudOperationReceipt(id=uuid7(), project_id=project_id, task_id=task_id, attempt_id=attempt_id,
            operation_key=operation_key, operation="DISPATCH", actor_ref="legacy-fixture", input_digest="0" * 64,
            expected_version=3, accepted_version=4, response=response, task_snapshot=await service._snapshot(db, task)))
        await db.commit()
    return response


async def legacy_claimed(context, **draft_options):
    receipt = await legacy_dispatched(context, **draft_options)
    async with AsyncSessionLocal() as db:
        claim = await service.claim_attempt(db, "fixture-worker", project_id=UUID(context["project_id"]))
    assert type(claim["budget_remaining"]["seconds"]) is int
    assert type(claim["budget_remaining"]["cost_microunits"]) is int
    identity = service.WorkerIdentity("fixture-worker", claim["lease_token"], claim["generation"], claim["work_token"])
    return receipt, claim, identity


async def worker_submit(context, identity, receipt, operation, **fields):
    body = {"project_id": context["project_id"], "task_id": receipt["task_id"],
            "attempt_id": receipt["attempt_id"], "expected_version": receipt["version"],
            "operation_key": "worker-" + uuid4().hex, "operation": operation, **fields}
    payload = TypeAdapter(CloudMutation).validate_python(body)
    async with AsyncSessionLocal() as db:
        return await service.mutate(db, payload, "worker:" + identity.worker_id, worker=identity)


async def read_all(context, task_id, version):
    offset, parts = 0, []
    while True:
        response = await context["client"].get(f"/api/v1/cloud/tasks/{task_id}", headers=context["headers"],
            params={"project_id": context["project_id"], "version": version, "offset": offset, "limit": 1024})
        assert response.status_code == 200, response.text
        page = response.json()
        parts.append(page["content"])
        offset += len(page["content"])
        if page["complete"]:
            content = "".join(parts)
            assert len(content) == page["total_characters"]
            assert hashlib.sha256(content.encode()).hexdigest() == page["sha256"]
            return json.loads(content)
        assert page["next_offset"] == offset


def test_new_task_default_authorization_has_no_expiry():
    task_inputs = new_inputs()
    task_inputs["authorization"] = None
    now = datetime.now(UTC)
    effective = service._task_inputs_with_runtime_defaults(CloudTaskInputs.model_validate(task_inputs), configuration(), now)
    assert effective["authorization"]["expires_at"] is None
    service._authorize_input_reads(effective, configuration(), now + timedelta(days=3651))


async def test_new_task_without_expiry_can_be_claimed_and_renewed(cloud_context):
    context = cloud_context
    task_inputs = new_inputs()
    task_inputs.pop("authorization")
    queued = await dispatched(context, task_inputs=task_inputs)
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(queued["task_id"]))
        assert task.inputs["authorization"]["expires_at"] is None
        claim = await service.claim_attempt(db, "fixture-worker", project_id=UUID(context["project_id"]))
        assert claim["attempt"]["id"] == queued["attempt_id"]
    async with AsyncSessionLocal() as db:
        renewed = await service.renew_lease(db, UUID(queued["attempt_id"]), "fixture-worker",
            claim["lease_token"], claim["generation"], claim["work_token"])
        assert datetime.fromisoformat(renewed["expires_at"]) < datetime.now(UTC) + timedelta(minutes=16)


async def test_freeze_idempotency_and_fixed_version_readback(cloud_context):
    context = cloud_context
    accepted = await dispatched(context)
    task_id = accepted["task_id"]
    frozen = await read_all(context, task_id, accepted["version"])
    assert frozen["task"]["frozen_manifest"]["resolution"]["repositories"]["sut"]["commit_sha"] == SHA
    assert frozen["task"]["status"] == "QUEUED"
    assert frozen["task_kind"] == "CLOUD_TASK" and frozen["product_mode"] == "CLOUD"
    edited = await post(context, "UPDATE_TASK", accepted["version"], task_id=task_id,
                        title="Cannot change frozen input", expected_project_version=1, inputs=new_inputs())
    assert edited.status_code == 409
    stale = await post(context, "CANCEL_ATTEMPT", 1, task_id=task_id, attempt_id=accepted["attempt_id"], reason="stale")
    assert stale.status_code == 409
    receipt = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/operations/{accepted['operation_key']}",
                                         headers=context["headers"])
    assert receipt.json() == accepted
    cancelled = await post(context, "CANCEL_ATTEMPT", accepted["version"], task_id=task_id,
                            attempt_id=accepted["attempt_id"], reason="Explicit fixture cleanup")
    assert cancelled.status_code == 200
    assert (await read_all(context, task_id, accepted["version"])) == frozen


@pytest.mark.parametrize("resolution_status", [None, "PENDING", "RESOLVING"])
async def test_draft_cancel_atomically_accepts_terminal_version_and_retains_history(cloud_context, resolution_status):
    context = cloud_context
    created = await draft(context)
    task_id, version = created["task_id"], created["version"]
    if resolution_status is not None:
        requested = await post(context, "RESOLVE_INPUTS", version, task_id=task_id)
        assert requested.status_code == 200, requested.text
        version = requested.json()["version"]
        if resolution_status == "RESOLVING":
            async with AsyncSessionLocal() as db:
                claim = await service.claim_resolution(db, "fixture-resolver", project_id=UUID(context["project_id"]))
            assert claim["resolution"]["id"] == requested.json()["resolution_id"]
    original = await read_all(context, task_id, version)
    operation_key = "cancel-draft-" + uuid4().hex
    fields = {"task_id": task_id, "reason": "Synthetic undispatched cancellation"}
    cancelled = await post(context, "CANCEL_TASK", version, operation_key=operation_key, **fields)
    assert cancelled.status_code == 200, cancelled.text
    accepted = cancelled.json()
    assert accepted["version"] == version + 1
    final = await read_all(context, task_id, accepted["version"])
    assert final["task"]["status"] == "CANCELLED"
    assert final["task"]["version"] == version + 1
    assert final["task"]["reported_result"] == "NOT_RUN"
    assert final["task"]["latest_attempt_id"] is None
    assert final["task"]["frozen_manifest"] is None
    assert final["attempts"] == []
    if resolution_status is not None:
        assert final["resolutions"][0]["status"] == (
            "RECOVERY_REQUIRED" if resolution_status == "RESOLVING" else "FAILED")
    if resolution_status == "RESOLVING":
        async with AsyncSessionLocal() as db:
            grants = list(await db.scalars(select(CloudWorkGrant).where(
                CloudWorkGrant.resolution_id == UUID(requested.json()["resolution_id"]))))
            assert len(grants) == 1 and grants[0].revoked_at is not None
    replay = await post(context, "CANCEL_TASK", version, operation_key=operation_key, **fields)
    assert replay.status_code == 200 and replay.json() == accepted
    assert (await read_all(context, task_id, version)) == original
    denied = await post(context, "CANCEL_TASK", accepted["version"], **fields)
    assert denied.status_code == 409
    # Keep the database guard itself effective: even a later version-only edit
    # must not mutate the accepted cancelled draft.
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudTask, UUID(task_id))
        row.version += 1
        with pytest.raises(DBAPIError, match="cancelled draft is terminal"):
            await db.flush()
        await db.rollback()
    assert (await read_all(context, task_id, accepted["version"])) == final


async def test_secret_roundtrip_is_encrypted_scoped_and_binds_idempotency(cloud_context):
    context = cloud_context
    canary = "synthetic-cloud-secret-canary-123456"
    payload = {"kind": "GIT_TOKEN", "label": "fixture", "purpose": "read fixture repository",
               "allowed_targets": [ORIGIN], "allowed_actions": ["git:read"], "secret": canary}
    first = await post(context, "STORE_CREDENTIAL", operation_key="store-once", **payload)
    assert first.status_code == 200, first.text
    replay = await post(context, "STORE_CREDENTIAL", operation_key="store-once", **payload)
    assert replay.json() == first.json()
    conflict = await post(context, "STORE_CREDENTIAL", operation_key="store-once", **{**payload, "secret": canary + "changed"})
    assert conflict.status_code == 409
    async with AsyncSessionLocal() as db:
        row = await db.get(CredentialVersion, UUID(first.json()["credential_version_id"]))
        assert isinstance(row.encrypted_secret, dict)
        assert canary not in json.dumps(row.encrypted_secret)
    response = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/credentials", headers=context["headers"])
    assert canary not in response.text and "ciphertext" not in response.text and "encrypted_secret" not in response.text
    wrong_action = await post(context, "STORE_CREDENTIAL", **{**payload, "allowed_actions": ["git:write"]})
    config = configuration()
    config["sut"]["credential_version_id"] = wrong_action.json()["credential_version_id"]
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as denied:
            await service._credential_versions(db, config, now=await service.clock(db))
        assert denied.value.status_code == 403


async def test_running_cancel_fences_worker_and_requires_observed_reconciliation(cloud_context):
    context = cloud_context
    current, _, identity = await legacy_claimed(context)
    running = await worker_submit(context, identity, current, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 60, "request_limits": [{"scope": "ROOT", "max_requests": 1, "cost_per_request_microunits": 1}]})
    cancelled = await post(context, "CANCEL_ATTEMPT", running["version"], task_id=running["task_id"],
        attempt_id=running["attempt_id"], reason="Cancel active fixture")
    assert cancelled.status_code == 200, cancelled.text
    latest = cancelled.json()
    assert (await read_all(context, latest["task_id"], latest["version"]))["task"]["status"] == "RECOVERY_REQUIRED"
    with pytest.raises(HTTPException, match="stale"):
        await worker_submit(context, identity, latest, "SUBMIT_ASSETS", assets=[{
            "kind": "REPORT", "key": "late", "title": "Late worker", "markdown": "Cannot submit after fence"}])
    retry = await post(context, "DISPATCH", latest["version"], task_id=latest["task_id"],
        retry_of_attempt_id=latest["attempt_id"], retry_scope_confirmed=True, retry_authorization_confirmed=True, reason="Must not bypass recovery")
    assert retry.status_code == 409
    reconciled = await post(context, "RECONCILE_ATTEMPT", latest["version"], task_id=latest["task_id"],
        attempt_id=latest["attempt_id"], status="CANCELLED", reason="Observed stopped fixture", reconciliation={
            "old_owner_fenced": True, "local_processes_stopped": True, "external_operations_reconciled": True,
            "observations": "Synthetic fixture had no runtime and no external operation"})
    assert reconciled.status_code == 200, reconciled.text
    retry = await post(context, "DISPATCH", reconciled.json()["version"], task_id=latest["task_id"],
        retry_of_attempt_id=latest["attempt_id"], retry_scope_confirmed=True, retry_authorization_confirmed=True, reason="Explicit same-input fixture retry")
    assert retry.status_code == 409 and "requires new scope and authorization" in retry.text


async def test_recovery_capability_does_not_admit_legacy_budget_resume(cloud_context):
    context = cloud_context
    capabilities = (await context["client"].get("/api/v1/cloud/capabilities")).json()
    assert capabilities["supported"]["resume_attempt"] is True
    assert capabilities["recovery"]["resume_reason"] == "EXPLICIT_ORIGINAL_SESSION_CONTINUATION"
    receipt, _, identity = await legacy_claimed(context)
    recovery = await worker_submit(context, identity, receipt, "TRANSITION", status="RECOVERY_REQUIRED",
        checkpoint={"session_id": "original-session", "workspace_id": "original-workspace"})
    resumed = await post({**context, "headers": context["operator_headers"]}, "RESUME_ATTEMPT", recovery["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], reason="Legacy budget needs a separate settlement contract",
        identity_source="OPERATOR_ADOPTED",
        reconciliation={"old_owner_fenced": True, "local_processes_stopped": True,
            "external_operations_reconciled": True, "checkpoint_verified": True, "observations": "Synthetic fixture"})
    assert resumed.status_code == 409 and "NATIVE_RESUME_LEGACY_BUDGET_UNSUPPORTED" in resumed.text
    async with AsyncSessionLocal() as db:
        assert await service.claim_attempt(db, "restart-worker", project_id=UUID(context["project_id"])) is None
    assert (await read_all(context, receipt["task_id"], recovery["version"]))["attempts"][-1]["checkpoint"]["runtime_context"]["session_id"] == "original-session"


async def test_cancel_already_recovering_attempt_preserves_unknown_work_and_original_key(cloud_context):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    running = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 60, "request_limits": [
            {"scope": "ROOT", "max_requests": 1, "cost_per_request_microunits": 100}]})
    recovery = await worker_submit(context, identity, running, "TRANSITION", status="RECOVERY_REQUIRED",
        reason="Synthetic runtime failure", checkpoint={"session_id": "original-session"})
    # Represent an unresolved original external operation in the dedicated test DB.
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(receipt["attempt_id"]))
        attempt.checkpoint = {**attempt.checkpoint, "pending_operation_keys": ["original-unknown-key"],
                              "external_operations_reconciled": False}
        generation = attempt.lease_generation
        original_metadata = attempt.runtime_metadata
        assert original_metadata["budget_reservation"]["state"] == "HELD"
        await db.commit()

    fields = {"task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"],
              "reason": "OPERATOR_REQUESTED_CANCELLATION"}
    key = "cancel-recovery-" + uuid4().hex
    cancelled = await post(context, "CANCEL_ATTEMPT", recovery["version"], operation_key=key, **fields)
    assert cancelled.status_code == 200, cancelled.text
    accepted = cancelled.json()
    assert accepted["version"] == recovery["version"] + 1
    fixed = await read_all(context, receipt["task_id"], accepted["version"])
    attempt = fixed["attempts"][-1]
    assert fixed["task"]["status"] == attempt["status"] == "RECOVERY_REQUIRED"
    assert attempt["reason"] == "Synthetic runtime failure"
    assert attempt["runtime_metadata"] == original_metadata
    assert attempt["reported_result"] == fixed["task"]["reported_result"] == "NOT_RUN"
    assert attempt["checkpoint"] == {"runtime_context": {"session_id": "original-session"},
        "pending_operation_keys": ["original-unknown-key"], "external_operations_reconciled": False,
        "cancellation_requested": True, "cancellation_reason": fields["reason"]}
    assert attempt["lease_generation"] == generation + 1
    assert (await post(context, "CANCEL_ATTEMPT", recovery["version"], operation_key=key, **fields)).json() == accepted
    conflict = await post(context, "CANCEL_ATTEMPT", recovery["version"], operation_key=key,
                          **{**fields, "reason": "Different intention"})
    assert conflict.status_code == 409
    assert (await post(context, "CANCEL_ATTEMPT", recovery["version"], **fields)).status_code == 409
    assert (await post(context, "CANCEL_ATTEMPT", accepted["version"], **fields)).status_code == 409
    with pytest.raises(HTTPException, match="stale"):
        await worker_submit(context, identity, accepted, "SUBMIT_ASSETS", assets=[{
            "kind": "REPORT", "key": "late", "title": "Late worker", "markdown": "Cannot write after fence"}])
    reconciled = await post(context, "RECONCILE_ATTEMPT", accepted["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], status="CANCELLED", reason="Cannot claim completion", reconciliation={
            "old_owner_fenced": True, "local_processes_stopped": True, "external_operations_reconciled": True,
            "observations": "Synthetic unverified claim", "pending_operation_keys": []})
    assert reconciled.status_code == 409
    assert (await read_all(context, receipt["task_id"], accepted["version"])) == fixed


@pytest.mark.parametrize("delete_before_reconcile", [False, True])
async def test_lost_cancel_response_uses_original_receipt_and_attestation_keeps_hold(cloud_context, delete_before_reconcile):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    receipt = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 60, "request_limits": [
            {"scope": "ROOT", "max_requests": 1, "cost_per_request_microunits": 100}]})
    original = await read_all(context, receipt["task_id"], receipt["version"])
    key = "cancel-lost-response-" + uuid4().hex
    cancelled = await post(context, "CANCEL_ATTEMPT", receipt["version"], operation_key=key,
        task_id=receipt["task_id"], attempt_id=receipt["attempt_id"], reason="Synthetic cancellation")
    assert cancelled.status_code == 200
    restored = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/operations/{key}", headers=context["headers"])
    assert restored.status_code == 200 and restored.json() == cancelled.json()
    summary = (await context["client"].get(f"/api/v1/cloud/tasks/{receipt['task_id']}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])).json()
    assert summary["recovery"]["phase"] == "STOP_UNCONFIRMED"
    assert summary["recovery"]["old_owner_fenced"] is True
    assert summary["recovery"]["local_processes_stopped_observed"] is False
    assert summary["recovery"]["can_reconcile"] is True
    reconcile_version = cancelled.json()["version"]
    if delete_before_reconcile:
        deleted = await post(context, "DELETE_TASK", reconcile_version, task_id=receipt["task_id"])
        assert deleted.status_code == 200, deleted.text
        reconcile_version = deleted.json()["version"]
        deleted_snapshot = await read_all(context, receipt["task_id"], reconcile_version)
    fields = dict(task_id=receipt["task_id"], attempt_id=receipt["attempt_id"], status="FAILED",
        reason="Manual fixture finish", reconciliation={"old_owner_fenced": True,
            "local_processes_stopped": True, "external_operations_reconciled": True,
            "observations": "Operator checked the synthetic fixture; no model or process ran",
            "source": "INDEPENDENT_STOP_PROOF", "independent_process_stop_proof": True,
            "independent_stop_proof": True, "model_drain_observed": True,
            "reconciliation_source": "INDEPENDENT_STOP_PROOF", "arbitrary_stop_proof": "must not persist",
            "model_budget_disposition": "RELEASE"})
    finished = await post(context, "RECONCILE_ATTEMPT", reconcile_version, **fields)
    assert finished.status_code == 200, finished.text
    final = await read_all(context, receipt["task_id"], finished.json()["version"])
    attempt = final["attempts"][-1]
    assert attempt["checkpoint"]["reconciliation"]["source"] == "OPERATOR_ATTESTATION"
    assert attempt["checkpoint"]["reconciliation"]["independent_process_stop_proof"] is False
    assert attempt["checkpoint"]["reconciliation"]["independent_stop_proof"] is False
    assert attempt["checkpoint"]["reconciliation"]["model_drain_observed"] is False
    assert attempt["checkpoint"]["reconciliation"]["reconciliation_source"] == "OPERATOR_ATTESTATION"
    assert "arbitrary_stop_proof" not in attempt["checkpoint"]["reconciliation"]
    assert attempt["checkpoint"]["reconciliation"]["model_budget_disposition"] == "KEEP_HELD"
    assert attempt["runtime_metadata"] == original["attempts"][-1]["runtime_metadata"]
    assert attempt["reported_result"] == original["attempts"][-1]["reported_result"]
    assert await read_all(context, receipt["task_id"], receipt["version"]) == original
    assert bool(final["task"]["deleted_at"]) == delete_before_reconcile
    if delete_before_reconcile:
        assert await read_all(context, receipt["task_id"], reconcile_version) == deleted_snapshot


@pytest.mark.parametrize("pending_kind", ["platform_key", "delegation"])
async def test_manual_reconcile_cannot_erase_original_unknown_operations(cloud_context, pending_kind):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    if pending_kind == "delegation":
        receipt = await worker_submit(context, identity, receipt, "SUBMIT_DELEGATION",
            delegation_key="unobserved-child", provider="codex", responsibility="Synthetic work",
            status="UNKNOWN", native_ref="fixture-native-ref")
    else:
        async with AsyncSessionLocal() as db:
            attempt = await db.get(CloudAttempt, UUID(receipt["attempt_id"]))
            attempt.checkpoint = {"pending_operation_keys": ["original-unknown-operation"]}
            await db.commit()
    cancelled = await post(context, "CANCEL_ATTEMPT", receipt["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], reason="Stop fixture but preserve its original unknown")
    response = await post(context, "RECONCILE_ATTEMPT", cancelled.json()["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], status="CANCELLED", reason="Must not overwrite UNKNOWN",
        reconciliation={"old_owner_fenced": True, "local_processes_stopped": True,
            "external_operations_reconciled": True, "pending_operation_keys": [], "observations": "Operator assertion"})
    assert response.status_code == 409
    summary = (await context["client"].get(f"/api/v1/cloud/tasks/{receipt['task_id']}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])).json()
    assert summary["status"] == "RECOVERY_REQUIRED" and summary["recovery"]["can_reconcile"] is False
    reason = "DELEGATIONS_UNRECONCILED" if pending_kind == "delegation" else "PENDING_ORIGINAL_OPERATIONS"
    assert reason in summary["recovery"]["blocking_reasons"]
    if pending_kind == "platform_key":
        assert summary["recovery"]["pending_operation_keys"] == ["original-unknown-operation"]


async def test_original_worker_safety_fence_prevents_restart_and_ordinary_writes(cloud_context):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    original = await read_all(context, receipt["task_id"], receipt["version"])
    wrong_identity = service.WorkerIdentity(identity.worker_id, identity.lease_token, identity.generation + 1, identity.work_token)
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException, match="different Worker"):
            await service.fence_attempt_for_recovery(db, UUID(receipt["task_id"]), UUID(receipt["attempt_id"]), wrong_identity, "RUNTIME_TIMEOUT")
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE cloud_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"),
            {"id": UUID(receipt["attempt_id"])})
        await db.commit()
        assert await service.fence_attempt_for_recovery(db, UUID(receipt["task_id"]), UUID(receipt["attempt_id"]), identity, "RUNTIME_TIMEOUT") is True
    async with AsyncSessionLocal() as db:
        assert await service.fence_attempt_for_recovery(db, UUID(receipt["task_id"]), UUID(receipt["attempt_id"]), identity, "RUNTIME_TIMEOUT") is False
        assert await service.claim_attempt(db, "restart-worker", project_id=UUID(context["project_id"])) is None
    with pytest.raises(HTTPException, match="stale"):
        await worker_submit(context, identity, receipt, "SUBMIT_ASSETS", assets=[{
            "kind": "REPORT", "key": "late", "title": "Late report", "markdown": "Forbidden after safety fence"}])
    summary = (await context["client"].get(f"/api/v1/cloud/tasks/{receipt['task_id']}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])).json()
    assert summary["status"] == "RECOVERY_REQUIRED" and summary["current_attempt"]["reason"] == "RUNTIME_TIMEOUT"
    assert summary["current_attempt"]["runtime_metadata"]["preparation_budget_reservation"]["state"] == "HELD"
    assert await read_all(context, receipt["task_id"], receipt["version"]) == original


async def test_stage_checkpoint_raw_report_and_failure_are_preserved(cloud_context):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    receipt = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 60, "request_limits": [{"scope": "ROOT", "max_requests": 1, "cost_per_request_microunits": 1}]})
    report_bytes = b'{"fixture":true,"reported_result":"FAIL","actual":"synthetic mismatch"}'
    receipt = await worker_submit(context, identity, receipt, "UPLOAD_ARTIFACT", filename="synthetic-report.json",
        media_type="application/json", content_base64=base64.b64encode(report_bytes).decode(),
        byte_count=len(report_bytes), sha256=hashlib.sha256(report_bytes).hexdigest())
    artifact_id = receipt["artifact_id"]
    assets = [
        {"kind": "ANALYSIS", "key": "analysis", "title": "Fixture analysis", "markdown": "Synthetic risk"},
        {"kind": "DESIGN", "key": "design", "title": "Fixture design", "markdown": "Synthetic case design"},
        {"kind": "CASE", "key": "case", "title": "Fixture case", "details": {
            "steps": ["Read synthetic fixture"], "expected": "match", "actual": "mismatch"}, "reported_result": "FAIL"},
        {"kind": "IMPLEMENTATION", "key": "code", "title": "Existing fixture framework", "markdown": "No test changes", "details": {
            "framework_sha": FRAMEWORK_SHA, "cwd": "framework", "dirty_files": [], "untracked_files": [], "test_tree_digest": "3" * 64}},
        {"kind": "REPORT", "key": "progress", "title": "Fixture progress", "markdown": "# FAIL\nSynthetic fixture only", "reported_result": "FAIL"},
    ]
    receipt = await worker_submit(context, identity, receipt, "SUBMIT_ASSETS", assets=assets, checkpoint_report_key="progress")
    stage = await read_all(context, receipt["task_id"], receipt["version"])
    assert stage["task"]["reported_result"] == "NOT_RUN"  # management does not infer a result
    assert receipt["checkpoint"]["progress_report_revision"]
    asset_ids = [x["id"] for x in receipt["assets"]]
    case_id = next(x["id"] for x in receipt["assets"] if x["kind"] == "CASE")
    report_id = next(x["id"] for x in receipt["assets"] if x["kind"] == "REPORT")
    now = datetime.now(UTC).isoformat()
    receipt = await worker_submit(context, identity, receipt, "SUBMIT_RUN", run_key="synthetic-failure",
        execution={"source": "PROJECT_FRAMEWORK", "actual_sut_build": "UNKNOWN", "framework_sha": FRAMEWORK_SHA,
            "test_tree_digest": "3" * 64, "environment_observation": {"source": "synthetic-fixture"},
            "entrypoint": "python -m pytest", "cwd": "framework", "framework_version": "synthetic-fixture",
            "started_at": now, "finished_at": now, "exit_code": 1}, reported_result="FAIL",
        report_artifact_ids=[artifact_id], cases=[{"case_revision_id": case_id, "actual": "synthetic mismatch", "reported_result": "FAIL"}])
    with pytest.raises(HTTPException, match="disagree"):
        await worker_submit(context, identity, receipt, "COMPLETE_ATTEMPT", final_report_revision=report_id,
            reported_result="PASS", usage_seconds=1, cost_microunits=0, completion_manifest={"required_asset_ids": asset_ids,
                "all_local_processes_stopped": True, "external_operations_reconciled": True,
                "scope_and_gaps": "Cannot replace the raw failure with PASS"})
    receipt = await worker_submit(context, identity, receipt, "COMPLETE_ATTEMPT", final_report_revision=report_id,
        reported_result="FAIL", usage_seconds=1, cost_microunits=0, completion_manifest={"required_asset_ids": asset_ids,
            "all_local_processes_stopped": True, "external_operations_reconciled": True,
            "scope_and_gaps": "Synthetic control-plane fixture, no model or SUT execution"})
    final = await read_all(context, receipt["task_id"], receipt["version"])
    assert final["task"]["status"] == "COMPLETED" and final["task"]["reported_result"] == "FAIL"
    assert final["run_cases"][0]["reported_result"] == "FAIL"
    raw = await context["client"].get(f"/api/v1/cloud/tasks/{receipt['task_id']}/artifacts/{artifact_id}",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert base64.b64decode(raw.json()["content_base64"]) == report_bytes


@pytest.mark.parametrize("expected,reported", [(1, "PASS"), (2, "FAIL")])
async def test_framework_process_handoffs_and_report_readback(cloud_context, tmp_path, expected, reported):
    """Run a synthetic project's unittest, then exercise the real Worker handoff path.

    This fixture does not run an SDK, model, or namespace. Resolution is a
    fixture: the framework SHA is a local synthetic commit, while the SUT
    identity is synthetic and no SUT is executed.
    """
    context = cloud_context
    entrypoint = "python -m unittest -v test_fixture"
    workspace = tmp_path / "workspace"
    framework = workspace / "framework"
    ready = workspace / ".hypertest-cloud" / "ready"
    framework.mkdir(parents=True)
    ready.mkdir(parents=True)
    source = f"import unittest\nclass Fixture(unittest.TestCase):\n    def test_actual(self):\n        self.assertEqual(1, {expected})\n"
    (framework / "test_fixture.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(framework)], check=True, timeout=10)
    subprocess.run(["git", "-C", str(framework), "add", "test_fixture.py"], check=True, timeout=10)
    subprocess.run(["git", "-C", str(framework), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "Synthetic test framework"], check=True, timeout=10)
    framework_sha = subprocess.run(["git", "-C", str(framework), "rev-parse", "HEAD"], capture_output=True,
                                   text=True, check=True, timeout=10).stdout.strip()
    receipt, claim, identity = await legacy_claimed(context, framework_sha=framework_sha,
                                              task_inputs=inputs(framework_entrypoints=[entrypoint]))
    receipt = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 60, "request_limits": [{"scope": "ROOT", "max_requests": 1,
                            "cost_per_request_microunits": 1}]})
    started = datetime.now(UTC)
    process = subprocess.run([sys.executable, "-m", "unittest", "-v", "test_fixture"], cwd=framework,
                             capture_output=True, timeout=10, check=False,
                             env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    finished = datetime.now(UTC)
    assert process.returncode == (0 if reported == "PASS" else 1)
    original = process.stdout + process.stderr
    assert b"test_actual" in original
    (workspace / "framework-report.txt").write_bytes(original)

    # Transition above advances the task version before this reporter starts.
    claim["task"]["version"] = receipt["version"]
    broker = CloudBroker(AsyncSessionLocal, claim, "fixture-worker")
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=workspace)
    worker = CloudWorker(None, None, "fixture-worker")
    accepted = {}

    async def publish(key, operation, payload):
        document = {"profile": "hypertest-cloud-handoff/v1alpha1", "task_id": broker.task_id,
                    "attempt_id": broker.attempt_id, "key": key, "operation": operation, "payload": payload}
        (ready / (key + ".json")).write_text(json.dumps(document), encoding="utf-8")
        terminal = await worker.collect(reporter, workspace, accepted, stopped=False)
        if terminal:
            return terminal
        return json.loads((workspace / ".hypertest-cloud" / "receipts" / (key + ".json")).read_text())

    try:
        upload = await publish("01-report-original", "UPLOAD_ARTIFACT", {
            "path": "framework-report.txt", "filename": "framework-report.txt", "media_type": "text/plain",
            "sha256": hashlib.sha256(original).hexdigest(), "byte_count": len(original)})
        tree_digest = hashlib.sha256(source.encode()).hexdigest()
        asset_receipt = await publish("02-stage-assets", "SUBMIT_ASSETS", {"assets": [
            {"kind": "ANALYSIS", "key": "analysis", "title": "Fixture analysis", "markdown": "Synthetic case"},
            {"kind": "DESIGN", "key": "design", "title": "Fixture design", "markdown": "Run unittest"},
            {"kind": "CASE", "key": "case", "title": "Fixture case", "reported_result": reported,
             "details": {"steps": ["Run unittest"], "expected": str(expected), "actual": "1"}},
            {"kind": "IMPLEMENTATION", "key": "implementation", "title": "Synthetic framework", "markdown": "Fixture source",
             "details": {"framework_sha": framework_sha, "cwd": "framework", "dirty_files": [],
                         "untracked_files": [], "test_tree_digest": tree_digest}},
            {"kind": "REPORT", "key": "final", "title": "Fixture report", "markdown": "Actual unittest output attached",
             "artifact_id": upload["artifact_id"], "reported_result": reported},
        ]})
        case_id = next(item["id"] for item in asset_receipt["assets"] if item["kind"] == "CASE")
        final_id = next(item["id"] for item in asset_receipt["assets"] if item["kind"] == "REPORT")
        asset_ids = [item["id"] for item in asset_receipt["assets"]]
        await publish("03-framework-run", "SUBMIT_RUN", {"run_key": "fixture-run", "execution": {
            "source": "PROJECT_FRAMEWORK", "actual_sut_build": "UNKNOWN", "framework_sha": framework_sha,
            "test_tree_digest": tree_digest, "environment_observation": {"source": "synthetic-local-fixture"},
            "entrypoint": entrypoint, "cwd": "framework", "framework_version": "python-stdlib-unittest",
            "started_at": started.isoformat(), "finished_at": finished.isoformat(), "exit_code": process.returncode},
            "reported_result": reported, "report_artifact_ids": [upload["artifact_id"]],
            "cases": [{"case_revision_id": case_id, "actual": "1", "reported_result": reported}]})
        handoff, handoff_digest = await publish("04-finish", "COMPLETE_ATTEMPT", {
            "final_report_revision": final_id, "reported_result": reported, "completion_manifest": {
                "required_asset_ids": asset_ids, "scope_and_gaps": "Synthetic fixture only; no model, sandbox or real SUT"}})
        result = await reporter.submit_handoff(handoff, handoff_digest, runtime_stopped=True,
                                               external_operations_reconciled=True)
        assert result.synced
        document = await read_all(context, broker.task_id, result.receipt["version"])
        assert document["task"]["status"] == "COMPLETED"
        assert document["task"]["reported_result"] == reported
        assert document["runs"][0]["execution"]["exit_code"] == process.returncode
        assert document["run_cases"][0]["reported_result"] == reported
        assert await broker.artifact(upload["artifact_id"]) == original
    finally:
        reporter.close()


async def test_budget_hold_survives_lease_loss_and_operator_reconciliation(cloud_context):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    with pytest.raises(HTTPException, match="reservation"):
        await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING")
    receipt = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 600, "request_limits": [
            {"scope": "ROOT", "max_requests": 100, "cost_per_request_microunits": 100}]})
    accepted = await read_all(context, receipt["task_id"], receipt["version"])
    running = accepted["attempts"][-1]
    assert running["cost_microunits"] == 0
    assert running["runtime_metadata"]["budget_reservation"]["state"] == "HELD"
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE cloud_attempts SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"),
            {"id": UUID(receipt["attempt_id"])})
        await db.commit()
        await service.expire_leases(db)
    reconciled = await post(context, "RECONCILE_ATTEMPT", receipt["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], status="FAILED", reason="Fixture host stopped after lease loss",
        reconciliation={"old_owner_fenced": True, "local_processes_stopped": True,
            "external_operations_reconciled": True, "observations": "No real runtime or model; preserve the synthetic hold"})
    assert reconciled.status_code == 200, reconciled.text
    retry = await post(context, "DISPATCH", reconciled.json()["version"], task_id=receipt["task_id"],
        retry_of_attempt_id=receipt["attempt_id"], retry_scope_confirmed=True, retry_authorization_confirmed=True, reason="Must not reset uncertain usage")
    assert retry.status_code == 409 and "requires new scope and authorization" in retry.text
    with pytest.raises(HTTPException, match="stale"):
        await worker_submit(context, identity, reconciled.json(), "TRANSITION", status="FAILED",
            usage_seconds=1, cost_microunits=100, budget_settlement={"observed_seconds": 1,
                "namespace_stopped": True, "brokers_drained": True, "requests": [{"scope": "ROOT", "requests": 1}]})


async def test_stopped_broker_accounting_settles_hold_and_preserves_its_history(cloud_context):
    context = cloud_context
    task_inputs = inputs()
    task_inputs["budgets"]["accounting_unit"] = "REQUEST_CREDITS"
    receipt, _, identity = await legacy_claimed(context, task_inputs=task_inputs)
    receipt = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"accounting_unit": "REQUEST_CREDITS", "reserved_seconds": 600,
            "request_limits": [{"scope": "ROOT", "max_requests": 10, "cost_per_request_microunits": 1000}]})
    settlement = {"accounting_unit": "REQUEST_CREDITS", "observed_seconds": 2,
        "namespace_stopped": True, "brokers_drained": True, "requests": [{"scope": "ROOT", "requests": 11}]}
    with pytest.raises(HTTPException, match="counts"):
        await worker_submit(context, identity, receipt, "TRANSITION", status="FAILED", usage_seconds=2,
            cost_microunits=11000, budget_settlement=settlement)
    settlement["requests"][0]["requests"] = 1
    final = await worker_submit(context, identity, receipt, "TRANSITION", status="FAILED", usage_seconds=2,
        cost_microunits=1000, budget_settlement=settlement)
    snapshot = await read_all(context, receipt["task_id"], final["version"])
    terminal = snapshot["attempts"][-1]
    assert terminal["status"] == "FAILED" and terminal["lease_generation"] == identity.generation + 1
    assert terminal["lease_owner"] is None and terminal["lease_expires_at"] is None
    hold = terminal["runtime_metadata"]["budget_reservation"]
    assert hold["state"] == "SETTLED" and hold["reserved_cost_microunits"] == 10000
    assert hold["settlement"]["observed_cost_microunits"] == 1000
    assert hold["settlement"]["accounting_unit"] == "REQUEST_CREDITS"
    historical = await read_all(context, receipt["task_id"], receipt["version"])
    assert historical["attempts"][-1]["status"] == "RUNNING"
    assert historical["attempts"][-1]["runtime_metadata"]["budget_reservation"]["state"] == "HELD"
    retry = await post(context, "DISPATCH", final["version"], task_id=receipt["task_id"],
        retry_of_attempt_id=receipt["attempt_id"], retry_scope_confirmed=True, retry_authorization_confirmed=True, reason="Explicit remaining-credit fixture retry")
    assert retry.status_code == 409 and "requires new scope and authorization" in retry.text
    async with AsyncSessionLocal() as db:
        count, seconds, cost = await service._task_budget_usage(db, UUID(receipt["task_id"]))
    assert (count, seconds, cost) == (1, 2, 1000)


async def test_preparation_time_is_held_before_git_or_any_model_start(cloud_context):
    context = cloud_context
    receipt, claim, _ = await legacy_claimed(context)
    assert claim["attempt"]["runtime_metadata"]["preparation_budget_reservation"]["reserved_seconds"] == 60
    assert claim["attempt"]["usage_seconds"] == 0 and claim["attempt"]["cost_microunits"] == 0
    cancelled = await post(context, "CANCEL_ATTEMPT", receipt["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], reason="No real Git/model executed; fixture cancellation")
    reconciled = await post(context, "RECONCILE_ATTEMPT", cancelled.json()["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], status="CANCELLED", reason="Observed fixture stopped",
        reconciliation={"old_owner_fenced": True, "local_processes_stopped": True,
            "external_operations_reconciled": True, "observations": "Keep preparation hold; no fabricated measured usage"})
    retry = await post(context, "DISPATCH", reconciled.json()["version"], task_id=receipt["task_id"],
        retry_of_attempt_id=receipt["attempt_id"], retry_scope_confirmed=True, retry_authorization_confirmed=True, reason="Explicit new preparation fixture")
    assert retry.status_code == 409 and "requires new scope and authorization" in retry.text
    async with AsyncSessionLocal() as db:
        count, seconds, cost = await service._task_budget_usage(db, UUID(receipt["task_id"]))
    assert (count, seconds, cost) == (1, 60, 0)


async def test_local_archive_remains_independent_when_cloud_is_disabled(cloud_context, monkeypatch):
    context = cloud_context
    created = await draft(context)
    monkeypatch.setattr(get_settings(), "cloud_enabled", False)
    local = await context["client"].post("/api/v1/local-archive/tasks", headers=context["operator_headers"], json={
        "project_id": context["project_id"], "idempotency_key": "local-independent", "title": "Local fixture"})
    assert local.status_code == 200, local.text
    cloud_read = await read_all(context, created["task_id"], 1)
    assert cloud_read["task"]["status"] == "DRAFT"
    directory = await context["client"].get(f"/api/v1/projects/{context['project_id']}/task-directory", headers=context["headers"])
    assert {x["task_kind"] for x in directory.json()["items"]} == {"CLOUD_TASK"}
    assert (await post(context, "CREATE_TASK", title="Disabled", expected_project_version=1, inputs=new_inputs())).status_code == 503


async def test_scope_separation_worker_api_rejection_and_error_redaction(cloud_context):
    context = cloud_context
    registered = await context["client"].post("/api/v1/interactive/registrations", headers=context["operator_headers"], json={
        "actor_ref": "local-only-" + uuid4().hex, "client_instance_id": str(uuid4()),
        "project_id": context["project_id"], "scopes": ["task:sync"]})
    local_headers = {"Authorization": "Bearer " + registered.json()["integration_token"]}
    denied = await context["client"].post("/api/v1/cloud/operations", headers=local_headers, json={
        "operation": "CONFIGURE", "project_id": context["project_id"], "operation_key": "no-cloud-grant",
        "expected_version": 0, "configuration": configuration()})
    assert denied.status_code == 403
    assert (await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/credentials", headers=local_headers)).status_code == 403
    denied = await post(context, "TRANSITION", task_id=str(uuid4()), attempt_id=str(uuid4()), status="RUNNING")
    assert denied.status_code == 403
    canary = "synthetic-invalid-private-field"
    invalid = await post(context, "CONFIGURE", configuration=configuration(), secret=canary)
    assert invalid.status_code == 422 and canary not in invalid.text
    unknown = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/operations/not-sent", headers=context["headers"])
    assert unknown.status_code == 404 and "replay" in unknown.text


async def test_credential_revocation_stops_current_worker_even_when_cloud_disabled(cloud_context, monkeypatch):
    context = cloud_context
    stored = await post(context, "STORE_CREDENTIAL", kind="GIT_TOKEN", label="Fixture token", purpose="repository read",
        allowed_targets=[ORIGIN, FRAMEWORK_ORIGIN], allowed_actions=["git:read"], secret="synthetic-host-only-value")
    assert stored.status_code == 200, stored.text
    config = configuration()
    for role in ("sut", "framework"):
        config[role]["credential_version_id"] = stored.json()["credential_version_id"]
    receipt, _, identity = await legacy_claimed(context, config=config)
    async with AsyncSessionLocal() as db:
        material = await service.materialize_credentials(db, UUID(receipt["task_id"]), UUID(receipt["attempt_id"]), identity)
        assert material == {"SUT": b"synthetic-host-only-value", "FRAMEWORK": b"synthetic-host-only-value"}
    monkeypatch.setattr(get_settings(), "cloud_enabled", False)
    revoked = await post(context, "REVOKE_CREDENTIAL", 1, credential_id=stored.json()["credential_id"], reason="Explicit fixture revoke")
    assert revoked.status_code == 200, revoked.text
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException, match="revoked"):
            await service.renew_lease(db, UUID(receipt["attempt_id"]), identity.worker_id, identity.lease_token,
                                      identity.generation, identity.work_token)


async def test_database_keeps_frozen_input_history_and_cross_project_work_authority(cloud_context):
    context = cloud_context
    accepted = await dispatched(context)
    async with AsyncSessionLocal() as db:
        other = await create_project(db, ProjectCreate(key=public_key("OTHER"), name="Other authority boundary"))
        other_id = other.id
    statements = [
        ("DELETE FROM cloud_tasks WHERE id=:id", {"id": UUID(accepted["task_id"])}),
        ("UPDATE cloud_tasks SET inputs='{}'::jsonb WHERE id=:id", {"id": UUID(accepted["task_id"])}),
        ("UPDATE cloud_tasks SET owner_actor_ref='another-owner' WHERE id=:id", {"id": UUID(accepted["task_id"])}),
        ("UPDATE cloud_operation_receipts SET response='{}'::jsonb WHERE task_id=:id", {"id": UUID(accepted["task_id"])}),
        ("INSERT INTO cloud_work_grants (id,project_id,attempt_id,token_hash,worker_id,lease_generation,expires_at,created_at) "
         "VALUES (:id,:project,:attempt,:hash,'fixture',1,clock_timestamp()+interval '60 seconds',clock_timestamp())",
         {"id": uuid4(), "project": other_id, "attempt": UUID(accepted["attempt_id"]), "hash": "a" * 64}),
    ]
    for sql, parameters in statements:
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(sql), parameters)
                await db.commit()
            await db.rollback()


@pytest.mark.parametrize("encoded", [False, True])
@pytest.mark.parametrize("canary", ["synthetic-new-secret-in-readable-label", 'synthetic-quoted-"secret"\nnext-line'])
async def test_secret_cannot_be_pasted_into_readable_credential_metadata(cloud_context, encoded, canary):
    context = cloud_context
    label = base64.b64encode(canary.encode()).decode() if encoded else canary
    response = await post(context, "STORE_CREDENTIAL", kind="GIT_TOKEN", label=label,
        purpose="repository read", allowed_targets=[ORIGIN], allowed_actions=["git:read"], secret=canary)
    assert response.status_code == 422, response.text
    assert canary not in response.text and label not in response.text
    metadata = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/credentials", headers=context["headers"])
    assert metadata.json() == {"credentials": [], "versions": []}


async def test_existing_escaped_secret_cannot_enter_nested_testing_assets(cloud_context):
    context = cloud_context
    canary = 'synthetic-existing-"secret"\nwith-newline'
    stored = await post(context, "STORE_CREDENTIAL", kind="GIT_TOKEN", label="Fixture credential",
        purpose="repository read", allowed_targets=[ORIGIN], allowed_actions=["git:read"], secret=canary)
    assert stored.status_code == 200, stored.text
    for value in (canary, base64.b64encode(canary.encode()).decode()):
        async with AsyncSessionLocal() as db:
            with pytest.raises(HTTPException, match="Credential material"):
                await service._reject_secrets(db, UUID(context["project_id"]), {"nested": [{"original": value}]})


@pytest.mark.parametrize("scope_gap", ["missing_target", "missing_git_read", "expired"])
async def test_input_resolution_checks_original_authorization_before_any_git_access(cloud_context, scope_gap):
    context = cloud_context
    task_inputs = new_inputs(authorization=inputs()["authorization"])
    if scope_gap == "missing_target":
        task_inputs["authorization"]["targets"] = [ORIGIN]
    elif scope_gap == "missing_git_read":
        task_inputs["authorization"]["permitted_actions"] = ["framework:execute"]
    else:
        task_inputs["authorization"]["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    created = await legacy_draft(context, task_inputs=task_inputs)
    denied = await post(context, "RESOLVE_INPUTS", 1, task_id=created["task_id"])
    assert denied.status_code == 403, denied.text
    async with AsyncSessionLocal() as db:
        assert await service.claim_resolution(db, "fixture-worker", project_id=UUID(context["project_id"])) is None


async def test_resolution_rechecks_expiration_at_claim_and_materialization(cloud_context, monkeypatch):
    context = cloud_context
    now = datetime.now(UTC)
    task_inputs = new_inputs(authorization=inputs()["authorization"])
    task_inputs["authorization"]["expires_at"] = (now + timedelta(seconds=60)).isoformat()
    created = await legacy_draft(context, task_inputs=task_inputs)
    requested = await post(context, "RESOLVE_INPUTS", 1, task_id=created["task_id"])
    assert requested.status_code == 200, requested.text
    async with AsyncSessionLocal() as db:
        claim = await service.claim_resolution(db, "fixture-worker", project_id=UUID(context["project_id"]))
        assert claim is not None

    async def expired(_db):
        return now + timedelta(seconds=61)

    monkeypatch.setattr(service, "clock", expired)
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException, match="preflight"):
            await service.materialize_resolution_credentials(db, UUID(claim["resolution"]["id"]),
                "fixture-worker", claim["lease_token"], claim["work_token"])


async def test_live_summary_observes_claim_and_expiry_without_rewriting_fixed_history(cloud_context, monkeypatch):
    context = cloud_context
    receipt, _, _ = await legacy_claimed(context)
    original = await read_all(context, receipt["task_id"], receipt["version"])
    params = {"project_id": context["project_id"]}
    endpoint = f"/api/v1/cloud/tasks/{receipt['task_id']}/summary"
    live = (await context["client"].get(endpoint, params=params, headers=context["headers"])).json()
    assert live["status"] == "PREPARING"
    assert live["version"] == receipt["version"]
    assert live["current_attempt"]["id"] == receipt["attempt_id"]
    assert live["current_attempt"]["status"] == "PREPARING"
    assert original["task"]["status"] == "QUEUED"

    future = datetime.now(UTC) + timedelta(minutes=20)

    async def expired(_db):
        return future

    monkeypatch.setattr(service, "clock", expired)
    async with AsyncSessionLocal() as db:
        await service.expire_leases(db)
    live = (await context["client"].get(endpoint, params=params, headers=context["headers"])).json()
    assert live["status"] == "RECOVERY_REQUIRED"
    assert live["current_attempt"]["status"] == "RECOVERY_REQUIRED"
    assert live["version"] == receipt["version"]
    assert await read_all(context, receipt["task_id"], receipt["version"]) == original


async def test_live_summary_observes_input_resolution_claim_without_relabeling_snapshot(cloud_context):
    context = cloud_context
    created = await draft(context)
    requested = await post(context, "RESOLVE_INPUTS", 1, task_id=created["task_id"])
    original = await read_all(context, created["task_id"], requested.json()["version"])
    async with AsyncSessionLocal() as db:
        await service.claim_resolution(db, "fixture-worker", project_id=UUID(context["project_id"]))
    live = await context["client"].get(f"/api/v1/cloud/tasks/{created['task_id']}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert live.json()["resolutions"][0]["status"] == "RESOLVING"
    assert original["resolutions"][0]["status"] == "PENDING"
    assert await read_all(context, created["task_id"], requested.json()["version"]) == original


async def test_fixed_cancellation_fences_worker_when_wrapping_key_is_unavailable(cloud_context):
    context = cloud_context
    stored = await post(context, "STORE_CREDENTIAL", kind="GIT_TOKEN", label="Fixture credential",
        purpose="repository read", allowed_targets=[ORIGIN, FRAMEWORK_ORIGIN],
        allowed_actions=["git:read"], secret="synthetic-cancellation-fixture-token")
    assert stored.status_code == 200, stored.text
    config = configuration()
    for role in ("sut", "framework"):
        config[role]["credential_version_id"] = stored.json()["credential_version_id"]
    receipt, _, identity = await legacy_claimed(context, config=config)
    from pathlib import Path
    Path(get_settings().cloud_credential_key_file).unlink()
    fields = {"task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"]}
    rejected = await post(context, "CANCEL_ATTEMPT", receipt["version"], reason="Unscanned arbitrary rationale", **fields)
    assert rejected.status_code == 503, rejected.text
    safety_key = "cancel:" + str(uuid4())
    cancelled = await post(context, "CANCEL_ATTEMPT", receipt["version"], operation_key=safety_key,
        reason=service.EMERGENCY_CANCEL_REASON, **fields)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["safety_control"] == "FIXED_CANCELLATION_WITH_SECRET_SCAN_UNAVAILABLE"
    replay = await post(context, "CANCEL_ATTEMPT", receipt["version"], operation_key=safety_key,
        reason=service.EMERGENCY_CANCEL_REASON, **fields)
    assert replay.json() == cancelled.json()
    changed = await post(context, "CANCEL_ATTEMPT", receipt["version"], operation_key=safety_key,
        reason="Cannot replace the original frozen reason", **fields)
    assert changed.status_code == 409
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException, match="stale"):
            await service.renew_lease(db, UUID(receipt["attempt_id"]), identity.worker_id,
                identity.lease_token, identity.generation, identity.work_token)
    live = await context["client"].get(f"/api/v1/cloud/tasks/{receipt['task_id']}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert live.json()["current_attempt"]["status"] == "RECOVERY_REQUIRED"


async def test_cloud_task_edit_delete_readback_and_original_key(cloud_context):
    context = cloud_context
    created = await draft(context)
    task_id = created["task_id"]
    original = await read_all(context, task_id, 1)
    updated = await post(context, "UPDATE_TASK", 1, task_id=task_id, title="Edited fixture",
                         expected_project_version=1, inputs=new_inputs(objective="Edited objective"))
    assert updated.status_code == 200, updated.text
    changed = await read_all(context, task_id, updated.json()["version"])
    assert changed["task"]["title"] == "Edited fixture"
    assert changed["task"]["inputs"]["objective"] == "Edited objective"
    stale = await post(context, "DELETE_TASK", 1, task_id=task_id)
    assert stale.status_code == 409
    async with AsyncSessionLocal() as db:
        foreign = await create_project(db, ProjectCreate(key=public_key("FOREIGN"), name="Foreign fixture"))
        foreign_id = str(foreign.id)
    cross = await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"], json={
        "project_id": foreign_id, "operation": "DELETE_TASK", "task_id": task_id,
        "operation_key": "cross-" + uuid4().hex, "expected_version": updated.json()["version"]})
    assert cross.status_code == 404
    key = "delete-" + uuid4().hex
    deleted = await post(context, "DELETE_TASK", updated.json()["version"], operation_key=key, task_id=task_id)
    assert deleted.status_code == 200, deleted.text
    receipt = deleted.json()
    final = await read_all(context, task_id, receipt["version"])
    assert final["task"]["deleted_at"] and final["task"]["status"] == "DRAFT"
    assert (await read_all(context, task_id, 1)) == original
    assert (await post(context, "DELETE_TASK", updated.json()["version"], operation_key=key, task_id=task_id)).json() == receipt
    assert (await post(context, "RESOLVE_INPUTS", receipt["version"], task_id=task_id)).status_code == 409
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudTask, UUID(task_id))
        row.title = "Forbidden change"
        with pytest.raises(DBAPIError, match="deleted cloud task is immutable"):
            await db.flush()
        await db.rollback()
    directory = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/tasks", headers=context["headers"])
    assert task_id not in [item["task_id"] for item in directory.json()["items"]]


async def test_cloud_task_delete_rejects_pending_resolution(cloud_context):
    context = cloud_context
    created = await draft(context)
    task_id = created["task_id"]
    pending = await post(context, "RESOLVE_INPUTS", 1, task_id=task_id)
    assert pending.status_code == 200
    assert (await post(context, "DELETE_TASK", pending.json()["version"], task_id=task_id)).status_code == 409


async def test_cloud_task_delete_rejects_active_attempt(cloud_context):
    context = cloud_context
    running = await dispatched(context)
    assert (await post(context, "DELETE_TASK", running["version"], task_id=running["task_id"])).status_code == 409


async def test_delete_cancelled_recovery_preserves_unknown_work_and_allows_only_recovery(cloud_context):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    recovery = await worker_submit(context, identity, receipt, "TRANSITION", status="RECOVERY_REQUIRED",
        reason="Synthetic runtime failed")
    assert (await post(context, "DELETE_TASK", recovery["version"], task_id=receipt["task_id"])).status_code == 409
    cancelled = await post(context, "CANCEL_ATTEMPT", recovery["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], reason="Synthetic cancellation")
    assert cancelled.status_code == 200
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(receipt["attempt_id"]))
        attempt.lease_owner = "unfenced-fixture-owner"
        await db.commit()
    assert (await post(context, "DELETE_TASK", cancelled.json()["version"], task_id=receipt["task_id"])).status_code == 409
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(receipt["attempt_id"]))
        attempt.lease_owner = None
        attempt.checkpoint = {**attempt.checkpoint, "pending_operation_keys": ["original-unknown"],
                              "external_operations_reconciled": False}
        await db.commit()
    key = "delete-recovery-" + uuid4().hex
    deleted = await post(context, "DELETE_TASK", cancelled.json()["version"],
                         operation_key=key, task_id=receipt["task_id"])
    assert deleted.status_code == 200, deleted.text
    fixed = await read_all(context, receipt["task_id"], deleted.json()["version"])
    attempt = fixed["attempts"][-1]
    assert fixed["task"]["deleted_at"] and fixed["task"]["status"] == attempt["status"] == "RECOVERY_REQUIRED"
    assert attempt["reason"] == "Synthetic runtime failed"
    assert attempt["checkpoint"]["pending_operation_keys"] == ["original-unknown"]
    assert attempt["checkpoint"]["external_operations_reconciled"] is False
    assert attempt["runtime_metadata"]["preparation_budget_reservation"]["state"] == "HELD"
    assert fixed["task"]["reported_result"] == attempt["reported_result"] == "NOT_RUN"
    assert (await post(context, "DELETE_TASK", cancelled.json()["version"], operation_key=key,
                       task_id=receipt["task_id"])).json() == deleted.json()
    directory = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/tasks", headers=context["headers"])
    assert receipt["task_id"] not in [row["task_id"] for row in directory.json()["items"]]
    fields = dict(task_id=receipt["task_id"], attempt_id=receipt["attempt_id"], status="CANCELLED",
        reason="Cannot erase unknown work", reconciliation={"old_owner_fenced": True,
            "local_processes_stopped": True, "external_operations_reconciled": True,
            "observations": "Unverified synthetic declaration"})
    stale = await post(context, "RECONCILE_ATTEMPT", cancelled.json()["version"], **fields)
    assert stale.status_code == 409 and "version is stale" in stale.text
    denied = await post(context, "RECONCILE_ATTEMPT", deleted.json()["version"], **fields)
    assert denied.status_code == 409 and "pending operations" in denied.text
    assert (await post(context, "RESOLVE_INPUTS", deleted.json()["version"], task_id=receipt["task_id"])).status_code == 409
    with pytest.raises(HTTPException, match="deleted"):
        await worker_submit(context, identity, {**deleted.json(), "attempt_id": receipt["attempt_id"]}, "SUBMIT_ASSETS", assets=[{
            "kind": "REPORT", "key": "late", "title": "Late writer", "markdown": "Forbidden"}])
    async with AsyncSessionLocal() as db:
        assert await service.claim_attempt(db, "new-worker", project_id=UUID(context["project_id"])) is None
        task = await db.get(CloudTask, UUID(receipt["task_id"]))
        task.title = "Forbidden change"
        with pytest.raises(DBAPIError, match="deleted cloud task is immutable"):
            await db.flush()
        await db.rollback()
        task = await db.get(CloudTask, UUID(receipt["task_id"]))
        task.status = "RUNNING"
        task.version += 1
        with pytest.raises(DBAPIError, match="deleted cloud task is immutable"):
            await db.flush()
        await db.rollback()
    assert (await read_all(context, receipt["task_id"], deleted.json()["version"])) == fixed


async def test_cloud_delete_rejects_unclosed_container(cloud_context, monkeypatch):
    context = cloud_context
    running = await dispatched(context)
    cancelled = await post(context, "CANCEL_ATTEMPT", running["version"], task_id=running["task_id"],
                           attempt_id=running["attempt_id"], reason="Fixture cancellation")
    assert cancelled.status_code == 200

    async def unclosed(db, task_id):
        raise HTTPException(409, "CLOUD_CONTAINER_UNRECONCILED")

    monkeypatch.setattr(service, "_ensure_container_closed", unclosed)
    denied = await post(context, "DELETE_TASK", cancelled.json()["version"], task_id=running["task_id"])
    assert denied.status_code == 409 and denied.json()["detail"] == "CLOUD_CONTAINER_UNRECONCILED"


async def test_cloud_delete_cancelled_draft_preserves_terminal_history(cloud_context):
    context = cloud_context
    created = await draft(context)
    cancelled = await post(context, "CANCEL_TASK", 1, task_id=created["task_id"], reason="Fixture cancellation")
    assert cancelled.status_code == 200
    deleted = await post(context, "DELETE_TASK", cancelled.json()["version"], task_id=created["task_id"])
    assert deleted.status_code == 200, deleted.text
    final = await read_all(context, created["task_id"], deleted.json()["version"])
    assert final["task"]["status"] == "CANCELLED" and final["task"]["deleted_at"]


async def test_historical_retry_receipt_replays_only_the_original_request(cloud_context):
    from hypertest.api.cloud_schemas import CloudDispatch

    context = cloud_context
    first = await dispatched(context)
    stopped = await post(context, "CANCEL_ATTEMPT", first["version"], task_id=first["task_id"],
        attempt_id=first["attempt_id"], reason="Cancel synthetic queued attempt")
    assert stopped.status_code == 200, stopped.text
    key = "historical-retry-" + uuid4().hex
    fields = {"task_id": first["task_id"], "retry_of_attempt_id": first["attempt_id"],
              "reason": "Historical retry fixture"}
    payload = CloudDispatch(project_id=UUID(context["project_id"]), operation_key=key,
                            expected_version=stopped.json()["version"], **fields)
    old_request = payload.model_dump(mode="json")
    old_request.pop("retry_scope_confirmed")
    old_request.pop("retry_authorization_confirmed")
    old_request.pop("retry_inputs")
    response = {"status": "ACCEPTED", "profile": service.PROFILE, "project_id": context["project_id"],
                "task_id": first["task_id"], "attempt_id": first["attempt_id"], "operation": "DISPATCH",
                "operation_key": key, "version": stopped.json()["version"] + 1}
    async with AsyncSessionLocal() as db:
        original = await db.scalar(select(CloudOperationReceipt).where(
            CloudOperationReceipt.project_id == UUID(context["project_id"]),
            CloudOperationReceipt.task_id == UUID(first["task_id"])).limit(1))
        db.add(CloudOperationReceipt(id=uuid7(), project_id=UUID(context["project_id"]),
            task_id=UUID(first["task_id"]), operation_key=key, operation="DISPATCH",
            actor_ref=original.actor_ref, input_digest=service.canonical_json_sha256(old_request),
            expected_version=stopped.json()["version"], accepted_version=response["version"], response=response))
        await db.commit()
    replay = await post(context, "DISPATCH", stopped.json()["version"], operation_key=key, **fields)
    assert replay.status_code == 200 and replay.json() == response
    conflict = await post(context, "DISPATCH", stopped.json()["version"], operation_key=key,
                          **{**fields, "reason": "A different request"})
    assert conflict.status_code == 409
    confirmed = await post(context, "DISPATCH", stopped.json()["version"], operation_key=key, **fields,
                           retry_scope_confirmed=True, retry_authorization_confirmed=True)
    assert confirmed.status_code == 409


async def test_explicit_retry_creates_new_attempt_and_preserves_prior_version(cloud_context):
    context = cloud_context
    first = await dispatched(context)
    stopped = await post(context, "CANCEL_ATTEMPT", first["version"], task_id=first["task_id"],
        attempt_id=first["attempt_id"], reason="Cancel synthetic queued attempt")
    assert stopped.status_code == 200, stopped.text
    for scope, authorization in [(False, False), (True, False), (False, True)]:
        denied = await post(context, "DISPATCH", stopped.json()["version"], task_id=first["task_id"],
            retry_of_attempt_id=first["attempt_id"], retry_scope_confirmed=scope,
            retry_authorization_confirmed=authorization, reason="Retry synthetic task after review")
        assert denied.status_code == 422
    retry = await post(context, "DISPATCH", stopped.json()["version"], task_id=first["task_id"],
        retry_of_attempt_id=first["attempt_id"], retry_scope_confirmed=True, retry_authorization_confirmed=True,
        retry_inputs={"objective": "Synthetic retry", "test_scope": "Fixture only", "basic_flow": "Run fixture",
                      "framework_entrypoints": ["python -m pytest"], "authorization": inputs()["authorization"]},
        reason="Retry synthetic task after review")
    assert retry.status_code == 200, retry.text
    assert retry.json()["attempt_id"] != first["attempt_id"]
    assert retry.json()["retry_confirmation"] == {"scope_confirmed": True, "authorization_confirmed": True,
                                                   "retry_of_attempt_id": first["attempt_id"]}
    snapshot = await read_all(context, first["task_id"], retry.json()["version"])
    assert [row["status"] for row in snapshot["attempts"]] == ["CANCELLED", "QUEUED"]
    assert snapshot["attempts"][0]["id"] == first["attempt_id"]
    stale = await post(context, "DISPATCH", stopped.json()["version"], task_id=first["task_id"],
        retry_of_attempt_id=first["attempt_id"], retry_scope_confirmed=True, retry_authorization_confirmed=True, reason="Stale retry")
    assert stale.status_code == 409


async def test_legacy_retry_uses_independent_snapshot(cloud_context):
    context = cloud_context
    first = await legacy_dispatched(context)
    async with AsyncSessionLocal() as db:
        original = await db.get(CloudTask, UUID(first["task_id"]))
        original_manifest, original_inputs = original.frozen_manifest, original.inputs
    stopped = await post(context, "CANCEL_ATTEMPT", first["version"], task_id=first["task_id"],
        attempt_id=first["attempt_id"], reason="Cancel queued synthetic attempt")
    assert stopped.status_code == 200, stopped.text
    new_authorization = inputs()["authorization"]
    new_authorization.pop("expires_at")
    retry_inputs = {"objective": "Retest synthetic scope", "test_scope": "Synthetic only",
                    "basic_flow": "Inspect the synthetic fixture", "framework_entrypoints": ["pytest -q"],
                    "authorization": new_authorization}
    key = "retry-snapshot-" + uuid4().hex
    fields = {"task_id": first["task_id"], "retry_of_attempt_id": first["attempt_id"],
              "retry_scope_confirmed": True, "retry_authorization_confirmed": True,
              "retry_inputs": retry_inputs, "reason": "Explicit synthetic review"}
    retry = await post(context, "DISPATCH", stopped.json()["version"], operation_key=key, **fields)
    assert retry.status_code == 200, retry.text
    replay = await post(context, "DISPATCH", stopped.json()["version"], operation_key=key, **fields)
    assert replay.status_code == 200 and replay.json() == retry.json()
    conflict = await post(context, "DISPATCH", stopped.json()["version"], operation_key=key,
        **{**fields, "retry_inputs": {**retry_inputs, "test_scope": "Different scope"}})
    assert conflict.status_code == 409
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(first["task_id"]))
        attempt = await db.get(CloudAttempt, UUID(retry.json()["attempt_id"]))
        old = await db.get(CloudAttempt, UUID(first["attempt_id"]))
        assert task.frozen_manifest == original_manifest and task.inputs == original_inputs
        assert original_inputs["authorization"]["expires_at"] is not None
        assert old.status == "CANCELLED" and old.execution_manifest is None
        assert attempt.execution_manifest["inputs"]["test_scope"] == "Synthetic only"
        assert attempt.execution_manifest["inputs"]["budgets"] is None
        assert attempt.execution_manifest["inputs"]["authorization"]["expires_at"] is None
        assert attempt.execution_manifest["retry_of_attempt_id"] == first["attempt_id"]
        assert attempt.input_digest == service.canonical_json_sha256(attempt.execution_manifest)
        assert await service.claim_attempt(db, "legacy-worker", project_id=UUID(context["project_id"])) is None
        claim = await service.claim_attempt(db, "fixture-worker", project_id=UUID(context["project_id"]),
                                            supports_attempt_manifest=True)
    assert claim["attempt"]["id"] == retry.json()["attempt_id"]
    assert claim["budget_remaining"] is None
    from hypertest.cloud.native_worker import native_execution_task
    runtime_task, manifest, is_retry = native_execution_task(claim["task"], claim["attempt"])
    assert is_retry and runtime_task["inputs"]["test_scope"] == "Synthetic only"
    assert manifest["inputs"]["budgets"] is None and claim["task"]["inputs"] == original_inputs
    identity = service.WorkerIdentity("fixture-worker", claim["lease_token"], claim["generation"], claim["work_token"])
    async with AsyncSessionLocal() as db:
        renewed = await service.renew_lease(db, UUID(retry.json()["attempt_id"]), identity.worker_id,
            identity.lease_token, identity.generation, identity.work_token)
        assert datetime.fromisoformat(renewed["expires_at"]) < datetime.now(UTC) + timedelta(minutes=16)
    running = await worker_submit(context, identity, retry.json(), "TRANSITION", status="RUNNING",
        reason="Synthetic native worker", runtime_metadata={}, usage_seconds=0, cost_microunits=0)
    assert running["status"] == "ACCEPTED"
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE cloud_attempts SET execution_manifest = '{}'::jsonb WHERE id=:id"),
                             {"id": UUID(retry.json()["attempt_id"])})
        await db.rollback()
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE cloud_attempts SET input_digest = :digest WHERE id=:id"),
                             {"id": UUID(retry.json()["attempt_id"]), "digest": "a" * 64})
        await db.rollback()
