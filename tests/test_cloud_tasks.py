"""ADR-019 PostgreSQL/API acceptance with synthetic framework reports, no Agent execution."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from hypertest.api.cloud_schemas import CloudMutation
from hypertest.api.schemas import ProjectCreate
from hypertest.application import cloud_tasks as service
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudTask, CloudWorkGrant, CredentialVersion
from hypertest.domain.session_tasks import SessionTask
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
        project = await create_project(db, ProjectCreate(key=public_key("CLOUD"), name="Cloud synthetic acceptance"))
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


async def post(context, operation, expected_version=0, operation_key=None, **fields):
    response = await context["client"].post("/api/v1/cloud/operations", headers=context["headers"], json={
        "project_id": context["project_id"], "operation": operation,
        "operation_key": operation_key or "fixture-" + uuid4().hex,
        "expected_version": expected_version, **fields})
    return response


async def draft(context, *, config=None, task_inputs=None):
    configured = await post(context, "CONFIGURE", configuration=config or configuration())
    assert configured.status_code == 200, configured.text
    created = await post(context, "CREATE_TASK", title="Cloud synthetic fixture", config_id=configured.json()["config_id"],
                         inputs=task_inputs or inputs())
    assert created.status_code == 200, created.text
    return created.json()


async def dispatched(context, **draft_options):
    created = await draft(context, **draft_options)
    task_id = created["task_id"]
    requested = await post(context, "RESOLVE_INPUTS", 1, task_id=task_id)
    assert requested.status_code == 200, requested.text
    async with AsyncSessionLocal() as db:
        claim = await service.claim_resolution(db, "fixture-worker", project_id=UUID(context["project_id"]))
        result = {"repositories": {
            "sut": {"url": ORIGIN, "commit_sha": SHA, "selector": claim["task"]["inputs"]["sut_selector"]},
            "framework": {"url": FRAMEWORK_ORIGIN, "commit_sha": FRAMEWORK_SHA,
                          "selector": claim["task"]["inputs"]["framework_selector"]}},
            "environment_observation": {"deployment": "UNKNOWN", "source": "synthetic-fixture"},
            "observed_at": datetime.now(UTC).isoformat(), "source": "synthetic-fixture-no-git-executed"}
        resolved = await service.accept_resolution(db, UUID(claim["resolution"]["id"]), "fixture-worker",
            claim["lease_token"], result, work_token=claim["work_token"])
    accepted = await post(context, "DISPATCH", resolved["version"], task_id=task_id,
                          resolution_id=requested.json()["resolution_id"])
    assert accepted.status_code == 200, accepted.text
    return accepted.json()


async def claimed(context, **draft_options):
    dispatched_task = await dispatched(context, **draft_options)
    async with AsyncSessionLocal() as db:
        claim = await service.claim_attempt(db, "fixture-worker", project_id=UUID(context["project_id"]))
    assert type(claim["budget_remaining"]["seconds"]) is int
    assert type(claim["budget_remaining"]["cost_microunits"]) is int
    identity = service.WorkerIdentity("fixture-worker", claim["lease_token"], claim["generation"], claim["work_token"])
    return dispatched_task, claim, identity


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


async def test_freeze_idempotency_and_fixed_version_readback(cloud_context):
    context = cloud_context
    accepted = await dispatched(context)
    task_id = accepted["task_id"]
    frozen = await read_all(context, task_id, accepted["version"])
    assert frozen["task"]["frozen_manifest"]["resolution"]["repositories"]["sut"]["commit_sha"] == SHA
    assert frozen["task"]["status"] == "QUEUED"
    assert frozen["task_kind"] == "CLOUD_TASK" and frozen["product_mode"] == "CLOUD"
    edited = await post(context, "UPDATE_TASK", accepted["version"], task_id=task_id,
                        title="Cannot change frozen input", config_id=frozen["task"]["config_id"], inputs=inputs())
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
    assert (await post(context, "CONFIGURE", configuration=config)).status_code == 403


async def test_running_cancel_fences_worker_and_requires_observed_reconciliation(cloud_context):
    context = cloud_context
    current, _, identity = await claimed(context)
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
        retry_of_attempt_id=latest["attempt_id"], reason="Must not bypass recovery")
    assert retry.status_code == 409
    reconciled = await post(context, "RECONCILE_ATTEMPT", latest["version"], task_id=latest["task_id"],
        attempt_id=latest["attempt_id"], status="CANCELLED", reason="Observed stopped fixture", reconciliation={
            "old_owner_fenced": True, "local_processes_stopped": True, "external_operations_reconciled": True,
            "observations": "Synthetic fixture had no runtime and no external operation"})
    assert reconciled.status_code == 200, reconciled.text
    retry = await post(context, "DISPATCH", reconciled.json()["version"], task_id=latest["task_id"],
        retry_of_attempt_id=latest["attempt_id"], reason="Explicit same-input fixture retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["attempt_id"] != latest["attempt_id"]


async def test_stage_checkpoint_raw_report_and_failure_are_preserved(cloud_context):
    context = cloud_context
    receipt, _, identity = await claimed(context)
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


async def test_budget_hold_survives_lease_loss_and_operator_reconciliation(cloud_context):
    context = cloud_context
    receipt, _, identity = await claimed(context)
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
        retry_of_attempt_id=receipt["attempt_id"], reason="Must not reset uncertain usage")
    assert retry.status_code == 409 and "budget" in retry.text
    with pytest.raises(HTTPException, match="stale"):
        await worker_submit(context, identity, reconciled.json(), "TRANSITION", status="FAILED",
            usage_seconds=1, cost_microunits=100, budget_settlement={"observed_seconds": 1,
                "namespace_stopped": True, "brokers_drained": True, "requests": [{"scope": "ROOT", "requests": 1}]})


async def test_stopped_broker_accounting_settles_hold_and_preserves_its_history(cloud_context):
    context = cloud_context
    task_inputs = inputs()
    task_inputs["budgets"]["accounting_unit"] = "REQUEST_CREDITS"
    receipt, _, identity = await claimed(context, task_inputs=task_inputs)
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
        retry_of_attempt_id=receipt["attempt_id"], reason="Explicit remaining-credit fixture retry")
    assert retry.status_code == 200, retry.text
    async with AsyncSessionLocal() as db:
        next_claim = await service.claim_attempt(db, "next-budget-worker", project_id=UUID(context["project_id"]))
    assert next_claim["budget_remaining"] == {"seconds": 598, "cost_microunits": 9000}


async def test_preparation_time_is_held_before_git_or_any_model_start(cloud_context):
    context = cloud_context
    receipt, claim, _ = await claimed(context)
    assert claim["attempt"]["runtime_metadata"]["preparation_budget_reservation"]["reserved_seconds"] == 60
    assert claim["attempt"]["usage_seconds"] == 0 and claim["attempt"]["cost_microunits"] == 0
    cancelled = await post(context, "CANCEL_ATTEMPT", receipt["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], reason="No real Git/model executed; fixture cancellation")
    reconciled = await post(context, "RECONCILE_ATTEMPT", cancelled.json()["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], status="CANCELLED", reason="Observed fixture stopped",
        reconciliation={"old_owner_fenced": True, "local_processes_stopped": True,
            "external_operations_reconciled": True, "observations": "Keep preparation hold; no fabricated measured usage"})
    retry = await post(context, "DISPATCH", reconciled.json()["version"], task_id=receipt["task_id"],
        retry_of_attempt_id=receipt["attempt_id"], reason="Explicit new preparation fixture")
    assert retry.status_code == 200, retry.text
    async with AsyncSessionLocal() as db:
        next_claim = await service.claim_attempt(db, "next-preparation-worker", project_id=UUID(context["project_id"]))
    assert next_claim["budget_remaining"]["seconds"] == 540


async def test_local_sync_remains_independent_when_cloud_is_disabled(cloud_context, monkeypatch):
    context = cloud_context
    created = await draft(context)
    monkeypatch.setattr(get_settings(), "cloud_enabled", False)
    local = await context["client"].post("/api/v1/interactive/tasks/sync", headers=context["headers"], json={
        "project_id": context["project_id"], "provider": "codex", "session_id": str(uuid4()),
        "idempotency_key": "local-still-independent", "expected_version": 0, "title": "Local fixture",
        "objective": "Existing local synchronization", "status": "IN_PROGRESS", "reported_result": "FAIL",
        "plan_markdown": "Retain local test result", "cases": [], "reports": []})
    assert local.status_code == 200, local.text
    cloud_read = await read_all(context, created["task_id"], 1)
    assert cloud_read["task"]["status"] == "DRAFT"
    directory = await context["client"].get(f"/api/v1/projects/{context['project_id']}/task-directory", headers=context["headers"])
    assert {x["task_kind"] for x in directory.json()["items"]} == {"CLOUD_TASK", "SESSION_TASK"}
    assert (await post(context, "CREATE_TASK", title="Disabled", config_id=cloud_read["task"]["config_id"], inputs=inputs())).status_code == 503
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(SessionTask).where(SessionTask.project_id == UUID(context["project_id"]))) == 1


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
    receipt, _, identity = await claimed(context, config=config)
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
    task_inputs = inputs()
    if scope_gap == "missing_target":
        task_inputs["authorization"]["targets"] = [ORIGIN]
    elif scope_gap == "missing_git_read":
        task_inputs["authorization"]["permitted_actions"] = ["framework:execute"]
    else:
        task_inputs["authorization"]["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    created = await draft(context, task_inputs=task_inputs)
    denied = await post(context, "RESOLVE_INPUTS", 1, task_id=created["task_id"])
    assert denied.status_code == 403, denied.text
    async with AsyncSessionLocal() as db:
        assert await service.claim_resolution(db, "fixture-worker", project_id=UUID(context["project_id"])) is None


async def test_resolution_rechecks_expiration_at_claim_and_materialization(cloud_context, monkeypatch):
    context = cloud_context
    now = datetime.now(UTC)
    task_inputs = inputs()
    task_inputs["authorization"]["expires_at"] = (now + timedelta(seconds=60)).isoformat()
    created = await draft(context, task_inputs=task_inputs)
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
    receipt, _, _ = await claimed(context)
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
    receipt, _, identity = await claimed(context, config=config)
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
