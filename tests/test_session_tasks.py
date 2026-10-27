"""ADR-018 real PostgreSQL management acceptance without test execution."""
import asyncio
import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from hypertest.api.schemas import ProjectCreate
from hypertest.application import session_tasks as task_service
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.connector.security import token_hash
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.bindings import RunExecutionBinding
from hypertest.domain.interactive import InteractiveIntegrationGrant
from hypertest.domain.jobs import DurableJob
from hypertest.domain.models import AuditEvent, Evidence, OutboxEvent
from hypertest.domain.models import TestExecution as Execution
from hypertest.domain.models import TestRun as LegacyRun
from hypertest.domain.native import NativeConclusion, NativeTestRun
from hypertest.domain.session_tasks import SyncReceipt
from hypertest.main import app


@pytest.fixture
async def context(monkeypatch):
    # Historical profile fixtures opt in; deployed defaults reject new writes.
    monkeypatch.setattr(get_settings(), "local_session_writes_enabled", True)
    monkeypatch.setattr(get_settings(), "connector_operator_key", "task-sync-fixture-operator")
    async with AsyncSessionLocal() as db:
        p = await create_project(db, ProjectCreate(key=public_key("TASK"), name="Task management QA"))
        project_id = str(p.id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        actor = "session-task-fixture-" + uuid4().hex
        registration = await client.post("/api/v1/interactive/registrations", headers={
            "X-Hypertest-Operator-Key": "task-sync-fixture-operator"}, json={
                "actor_ref": actor, "client_instance_id": str(uuid4()), "project_id": project_id,
                "scopes": ["task:sync"]})
        assert registration.status_code == 201, registration.text
        yield {"c": client, "project_id": project_id, "actor": actor,
               "auth": registration.json(),
               "headers": {"Authorization": "Bearer " + registration.json()["integration_token"]}}


def body(f, **changes):
    return {"project_id": f["project_id"], "idempotency_key": "sync-first", "expected_version": 0,
        "provider": "codex", "session_id": str(uuid4()), "title": "Existing Codex testing task",
        "objective": "Manage existing cases and report", "plan_markdown": "# Original plan\nUse existing framework",
        "status": "IN_PROGRESS", "reported_result": "FAIL",
        "cases": [{"key": "UC-18", "title": "Existing test assertion", "steps": ["Read original report"],
                   "expected": "Provider error retained", "actual": "Observed mismatch", "reported_result": "FAIL"}],
        "reports": [{"key": "original", "title": "Original failure report", "markdown": "# FAIL\nExact original content\n",
                     "source_ref": "codex-session:fixture/report.md", "reported_result": "FAIL"}], **changes}


async def sync(f, payload):
    return await f["c"].post("/api/v1/interactive/tasks/sync", json=payload, headers=f["headers"])


async def counts():
    async with AsyncSessionLocal() as db:
        return [await db.scalar(select(func.count()).select_from(model)) for model in (
            LegacyRun, Execution, Evidence, DurableJob, RunExecutionBinding, NativeTestRun, NativeConclusion)]


async def test_complete_sync_roundtrip_history_no_execution(context):
    f = context
    baseline = await counts()
    payload = body(f)
    first = await sync(f, payload)
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert receipt["version"] == 1
    assert (await sync(f, payload)).json() == receipt
    task_id = receipt["task_id"]
    detail = (await f["c"].get("/api/v1/tasks/" + task_id)).json()
    assert detail["task"]["reported_result"] == "FAIL"
    assert detail["task"]["status"] == "IN_PROGRESS"
    assert detail["task"]["source"] == "AGENT_REPORTED"
    assert detail["reports"][0]["markdown"] == payload["reports"][0]["markdown"]
    assert detail["cases"][0]["reported_result"] == "FAIL"
    read_report = await f["c"].get(f"/api/v1/tasks/{task_id}/reports/{detail['reports'][0]['id']}")
    assert read_report.json() == detail["reports"][0]
    update = {**payload, "expected_version": 1, "idempotency_key": "sync-second", "status": "COMPLETED",
              "reported_result": "PASS", "cases": [],
              "reports": [{**payload["reports"][0], "markdown": "# PASS\nFollow-up result\n", "reported_result": "PASS"}]}
    assert (await sync(f, update)).json()["version"] == 2
    current = (await f["c"].get("/api/v1/tasks/" + task_id)).json()
    assert current["task"]["reported_result"] == "PASS"
    assert current["cases"][0]["reported_result"] == "FAIL"  # omission does not delete
    assert [r["reported_result"] for r in current["report_history"]] == ["FAIL", "PASS"]
    assert (await sync(f, payload)).json() == receipt  # old key remains its original receipt
    original = (await f["c"].get("/api/v1/tasks/" + task_id, params={"version": 1})).json()
    assert original["task"]["reported_result"] == "FAIL"
    assert original["reports"][0]["markdown"] == payload["reports"][0]["markdown"]
    listing = (await f["c"].get("/api/v1/tasks", params={"project_id": f["project_id"]})).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == task_id
    assert await counts() == baseline
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(SyncReceipt).where(SyncReceipt.task_id == UUID(task_id))) == 2
        assert await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == UUID(task_id))) == 2
        assert await db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == UUID(task_id))) == 2


async def test_conflicting_key_stale_version_and_duplicate_case_are_atomic(context):
    f = context
    payload = body(f)
    first = (await sync(f, payload)).json()
    assert (await sync(f, {**payload, "title": "Different"})).status_code == 409
    assert (await sync(f, {**payload, "idempotency_key": "stale", "expected_version": 0})).status_code == 409
    assert (await sync(f, {**payload, "idempotency_key": "duplicate", "expected_version": 1,
                          "cases": payload["cases"] * 2})).status_code == 422
    detail = (await f["c"].get("/api/v1/tasks/" + first["task_id"])).json()
    assert detail["task"]["version"] == 1 and len(detail["sync_history"]) == 1


async def test_same_session_unique_concurrent_updates_and_case_revisions(context):
    f = context
    payload = body(f)
    initial = await asyncio.gather(sync(f, payload), sync(f, payload))
    assert initial[0].json() == initial[1].json()
    task_id = initial[0].json()["task_id"]
    update = {**payload, "expected_version": 1, "idempotency_key": "update-case",
              "cases": [{**payload["cases"][0], "actual": "Additional exact observed details"}]}
    results = await asyncio.gather(sync(f, update), sync(f, {**update, "idempotency_key": "other-update"}))
    assert sorted(r.status_code for r in results) == [200, 409]
    detail = (await f["c"].get("/api/v1/tasks/" + task_id)).json()
    assert len(detail["case_history"]) == 2 and detail["cases"][0]["revision"] == 2
    assert len(detail["report_history"]) == 1  # identical report is not re-versioned


async def test_scope_project_actor_and_revocation(context):
    f = context
    payload = body(f)
    assert (await f["c"].post("/api/v1/interactive/tasks/sync", json=payload)).status_code == 401
    accepted = (await sync(f, payload)).json()
    async with AsyncSessionLocal() as db:
        other = await create_project(db, ProjectCreate(key=public_key("OTHER"), name="Other Project"))
        other_project_id = str(other.id)
    assert (await sync(f, {**payload, "project_id": other_project_id})).status_code == 403
    # The operator can manage multiple Projects, but cannot relocate a session.
    different_project = await f["c"].post("/api/v1/interactive/tasks/sync", json={**payload,
        "project_id": other_project_id, "idempotency_key": "cross-project"},
        headers={"X-Hypertest-Operator-Key": "task-sync-fixture-operator"})
    assert different_project.status_code == 409
    for actor, scopes, expected in [("other-" + uuid4().hex, ["task:sync"], 403),
                                    (f["actor"], ["task:submit"], 403)]:
        registered = await f["c"].post("/api/v1/interactive/registrations", headers={
            "X-Hypertest-Operator-Key": "task-sync-fixture-operator"}, json={"actor_ref": actor,
            "client_instance_id": str(uuid4()), "project_id": f["project_id"], "scopes": scopes})
        token = registered.json()["integration_token"]
        denied = await f["c"].post("/api/v1/interactive/tasks/sync", json={**payload,
            "expected_version": 1, "idempotency_key": "unauthorized"}, headers={"Authorization": "Bearer " + token})
        assert denied.status_code == expected
    revoked = await f["c"].post(f"/api/v1/interactive/grants/{f['auth']['grant_id']}/revoke", headers={
        "X-Hypertest-Operator-Key": "task-sync-fixture-operator"})
    assert revoked.status_code == 200
    assert (await sync(f, {**payload, "expected_version": 1, "idempotency_key": "revoked"})).status_code == 403
    assert (await f["c"].get("/api/v1/interactive/tasks/syncs/by-key", params={
        "project_id": f["project_id"], "idempotency_key": payload["idempotency_key"]}, headers=f["headers"])).status_code == 403
    assert (await f["c"].get("/api/v1/tasks/" + accepted["task_id"])).json()["task"]["version"] == 1


async def test_receipt_original_key_lookup_and_task_by_session(context):
    f = context
    payload = body(f)
    accepted = (await sync(f, payload)).json()
    receipt = await f["c"].get("/api/v1/interactive/tasks/syncs/by-key", params={
        "project_id": f["project_id"], "idempotency_key": payload["idempotency_key"]}, headers=f["headers"])
    assert receipt.json() == accepted
    missing = await f["c"].get("/api/v1/interactive/tasks/syncs/by-key", params={
        "project_id": f["project_id"], "idempotency_key": "unknown-write"}, headers=f["headers"])
    assert missing.status_code == 404 and "does not authorize replay" in missing.text
    read = await f["c"].get("/api/v1/interactive/tasks/by-session", params={
        "project_id": f["project_id"], "provider": "codex", "session_id": payload["session_id"]}, headers=f["headers"])
    assert json.loads(read.json()["content"])["task"]["id"] == accepted["task_id"]


async def test_sync_waiting_for_aggregate_lock_cannot_commit_after_revocation(context, monkeypatch):
    f = context
    payload = body(f)
    accepted = (await sync(f, payload)).json()
    entered = asyncio.Event()
    original = task_service.sync_task

    async def observed(*args, **kwargs):
        # The route has already authenticated before entering the aggregate.
        entered.set()
        return await original(*args, **kwargs)

    monkeypatch.setattr(task_service, "sync_task", observed)
    async with AsyncSessionLocal() as blocker:
        await blocker.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                              {"identity": f"session-task:codex:{payload['session_id']}"})
        pending = asyncio.create_task(sync(f, {**payload, "expected_version": 1,
            "idempotency_key": "queued-before-revoke", "title": "Must never commit"}))
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            revoked = await asyncio.wait_for(f["c"].post(
                f"/api/v1/interactive/grants/{f['auth']['grant_id']}/revoke",
                headers={"X-Hypertest-Operator-Key": "task-sync-fixture-operator"}), timeout=10)
            assert revoked.status_code == 200 and revoked.json()["status"] == "REVOKED"
        finally:
            await blocker.rollback()
        denied = await asyncio.wait_for(pending, timeout=10)
    assert denied.status_code == 403
    detail = (await f["c"].get("/api/v1/tasks/" + accepted["task_id"])).json()
    assert detail["task"]["version"] == 1 and detail["task"]["title"] == payload["title"]
    assert len(detail["sync_history"]) == 1


async def test_sync_rechecks_real_grant_expiry_before_commit_and_rolls_back_history(context, monkeypatch):
    f = context
    payload = body(f)
    accepted = (await sync(f, payload)).json()
    secret = "task-expiry-" + uuid4().hex
    async with AsyncSessionLocal() as db:
        original_grant = await db.get(InteractiveIntegrationGrant, UUID(f["auth"]["grant_id"]))
        clock = await db.scalar(select(func.clock_timestamp()))
        expiry = clock + timedelta(seconds=2)
        db.add(InteractiveIntegrationGrant(actor_identity_id=original_grant.actor_identity_id,
            client_instance_id=original_grant.client_instance_id, project_id=original_grant.project_id,
            scopes=["task:sync"], token_hash=token_hash(secret), registered_by="task-expiry-fixture",
            not_before=clock, expires_at=expiry))
        await db.commit()
    checks = 0
    original = task_service.sync_task

    async def crosses_expiry(db, *args, authorization_check, **kwargs):
        async def delayed_check():
            nonlocal checks
            checks += 1
            if checks == 2:
                # Expire after admission and history writes, before the final
                # authorization check. Use the database clock, not host skew.
                current = await db.scalar(select(func.clock_timestamp()))
                await asyncio.sleep(max(0, (expiry - current).total_seconds()) + 0.05)
            await authorization_check()
        return await original(db, *args, authorization_check=delayed_check, **kwargs)

    monkeypatch.setattr(task_service, "sync_task", crosses_expiry)
    denied = await f["c"].post("/api/v1/interactive/tasks/sync",
        headers={"Authorization": "Bearer " + secret},
        json={**payload, "expected_version": 1, "idempotency_key": "expires-before-commit",
              "reports": [{**payload["reports"][0], "markdown": "Must be rolled back"}]})
    assert checks == 2 and denied.status_code == 403
    detail = (await f["c"].get("/api/v1/tasks/" + accepted["task_id"])).json()
    assert detail["task"]["version"] == 1 and len(detail["sync_history"]) == 1
    assert len(detail["report_history"]) == 1
    assert detail["reports"][0]["markdown"] == payload["reports"][0]["markdown"]


async def test_same_actor_new_client_continues_task_without_execution_scope(context):
    f = context
    payload = body(f)
    accepted = (await sync(f, payload)).json()
    registered = await f["c"].post("/api/v1/interactive/registrations", headers={
        "X-Hypertest-Operator-Key": "task-sync-fixture-operator"}, json={
        "actor_ref": f["actor"], "client_instance_id": str(uuid4()), "project_id": f["project_id"],
        "scopes": ["task:sync"]})
    headers = {"Authorization": "Bearer " + registered.json()["integration_token"]}
    continued = await f["c"].post("/api/v1/interactive/tasks/sync", headers=headers,
        json={**payload, "idempotency_key": "new-client", "expected_version": 1})
    assert continued.json()["task_id"] == accepted["task_id"] and continued.json()["version"] == 2
    # A management-only grant cannot submit a legacy execution task.
    denied = await f["c"].post("/api/v1/interactive/submissions", headers=headers, json={
        "project_id": f["project_id"], "submission_key": "not-authorized",
        "bootstrap": {"repository_url": "https://example.invalid/repo", "commit_sha": "a" * 40,
                      "prd_text": "Existing managed route remains scoped"}})
    assert denied.status_code == 403


async def test_database_retains_history_and_identity(context):
    f = context
    receipt = (await sync(f, body(f))).json()
    task_id = UUID(receipt["task_id"])
    statements = [
        ("UPDATE session_tasks SET project_id=:other, version=version+1 WHERE id=:id", {"other": uuid4()}),
        ("UPDATE session_tasks SET version=version+2 WHERE id=:id", {}),
        ("DELETE FROM session_tasks WHERE id=:id", {}),
        ("UPDATE session_case_revisions SET actual='rewritten' WHERE task_id=:id", {}),
        ("DELETE FROM session_report_revisions WHERE task_id=:id", {}),
        ("UPDATE session_sync_receipts SET response='{}'::jsonb WHERE task_id=:id", {}),
    ]
    for statement, params in statements:
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(statement), {"id": task_id, **params})
                await db.commit()
            await db.rollback()


async def test_report_task_isolation_and_strict_unsupported_inputs(context):
    f = context
    first = (await sync(f, body(f))).json()
    first_detail = (await f["c"].get("/api/v1/tasks/" + first["task_id"])).json()
    second = (await sync(f, body(f, idempotency_key="second-task"))).json()
    wrong_report = await f["c"].get(f"/api/v1/tasks/{second['task_id']}/reports/{first_detail['reports'][0]['id']}")
    assert wrong_report.status_code == 404
    for changes in ({"execute": True}, {"expected_version": -1}, {"provider": "CODEX"}, {"idempotency_key": "../unsafe"}):
        assert (await sync(f, body(f, idempotency_key="invalid", **changes) if "idempotency_key" not in changes else body(f, **changes))).status_code == 422


async def test_capabilities_exposes_management_tools_without_execution_binding(context):
    result = (await context["c"].get("/api/v1/interactive/capabilities")).json()
    tools = {tool["name"]: tool for tool in result["tools"]}
    assert "hypertest_sync_task" in tools and "hypertest_get_task" in tools
    assert "host_proof" not in tools["hypertest_sync_task"]["inputSchema"]["properties"]
