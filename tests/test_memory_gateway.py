"""ADR-022 isolated PostgreSQL/API regressions; upstream is an inert fixture.

No real model, SUT, PowerContext mutation, production Task or credential is used.
"""
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_cloud_tasks import claimed, worker_submit
from test_cloud_tasks import cloud_context as _cloud_context
from test_cloud_tasks import post as cloud_post

from hypertest.api.schemas import ProjectCreate
from hypertest.application import memory_gateway as service
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.interactive import InteractiveIntegrationGrant
from hypertest.domain.memory import MemoryOperation
from hypertest.main import app

OPERATOR = "synthetic-memory-operator"


class InertPowerContext:
    def __init__(self):
        self.scopes = {}
        self.records = []
        self.creates = self.writes = self.reads = 0
        self.lose_scope_ack = self.lose_write_ack = False
        self.mismatch_read = self.fail_search = False
        self.on_remember = self.on_search = None

    async def create_scope(self, namespace, operation_key):
        self.creates += 1
        scope_id = "fixture-scope-" + uuid4().hex
        self.scopes[namespace] = scope_id
        if self.lose_scope_ack:
            raise OSError("synthetic lost response")
        return scope_id

    async def find_scope(self, namespace):
        self.reads += 1
        return self.scopes.get(namespace)

    async def remember(self, scope_id, content, metadata=None):
        self.writes += 1
        row = {"scope_id": scope_id, "artifact_id": "fixture-art-" + uuid4().hex,
               "revision": 1, "content": content, "content_digest": "sha256:" + "a" * 64}
        self.records.append(row)
        if self.on_remember:
            await self.on_remember(row)
        if self.lose_write_ack:
            raise OSError("synthetic lost response")
        return {key: row[key] for key in ("artifact_id", "revision", "content_digest")}

    async def get(self, scope_id, artifact_id, revision):
        self.reads += 1
        row = next(row for row in self.records if row["scope_id"] == scope_id
                   and row["artifact_id"] == artifact_id and row["revision"] == revision)
        return {**row, "content": "wrong fixed body" if self.mismatch_read else row["content"]}

    async def search(self, scope_id, query, limit):
        self.reads += 1
        if self.on_search:
            await self.on_search()
        if self.fail_search:
            raise OSError("synthetic unavailable")
        # Deliberately stale: returns all retained index rows, including old,
        # retracted and expired revisions. Gateway visibility must filter them.
        return [row for row in self.records if row["scope_id"] == scope_id][:limit]

    async def find_operation(self, scope_id, marker):
        self.reads += 1
        return [row for row in self.records if row["scope_id"] == scope_id and marker in row["content"]]


async def register(f, scopes, *, project_id=None):
    response = await f["client"].post("/api/v1/interactive/registrations", headers=f["operator"], json={
        "actor_ref": "memory-fixture-" + uuid4().hex, "client_instance_id": str(uuid4()),
        "project_id": project_id or f["project_id"], "scopes": scopes})
    assert response.status_code == 201, response.text
    auth = response.json()
    return {"Authorization": "Bearer " + auth["integration_token"]}, auth


@pytest.fixture
async def memory_context(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "memory_enabled", True)
    monkeypatch.setattr(settings, "connector_operator_key", OPERATOR)
    admin_file = tmp_path / "synthetic-powercontext-token"
    admin_file.write_text("synthetic-powercontext-private-token")
    admin_file.chmod(0o600)
    monkeypatch.setattr(settings, "memory_powercontext_token_file", str(admin_file))
    upstream = InertPowerContext()
    monkeypatch.setattr(service, "adapter", lambda: upstream)
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("MEMORY"), name="Isolated memory regression"))
        project_id = str(project.id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        f = {"client": client, "project_id": project_id, "operator": {"X-Hypertest-Operator-Key": OPERATOR},
             "upstream": upstream}
        headers, auth = await register(f, ["task:sync", "memory:read", "memory:propose"])
        f.update(headers=headers, auth=auth)
        archive_headers, _ = await register(f, ["archive:read", "archive:write"])
        created = await client.post("/api/v1/local-archive/tasks", headers=f["operator"], json={
            "project_id": project_id, "idempotency_key": "memory-source-task", "title": "Private source title"})
        assert created.status_code == 200, created.text
        task_id = created.json()["task"]["id"]
        response = await client.post(f"/api/v1/local-archive/tasks/{task_id}/submissions", headers=archive_headers, json={
            "profile": "local-artifact-archive/v1alpha1", "project_id": project_id, "task_id": task_id,
            "idempotency_key": "memory-source", "expected_archive_version": 1,
            "assets": [{"kind": "REPORT", "stable_key": "original", "title": "Private report title",
                "markdown": "# FAIL\nSynthetic preservation fixture", "reported_result": "FAIL"}]})
        assert response.status_code == 200, response.text
        receipt = response.json()
        read = await client.get(f"/api/v1/local-archive/submissions/{receipt['submission_id']}",
            headers=f["operator"], params={"project_id": project_id})
        import json
        report = json.loads(read.json()["content"])["assets"][0]
        f["source"] = {"mode": "LOCAL_ARCHIVE", "task_id": task_id, "submission_id": receipt["submission_id"],
            "archive_version": receipt["accepted_version"], "asset_revision_id": report["id"]}
        f["task_snapshot"] = (await client.get(f"/api/v1/local-archive/tasks/{task_id}",
            headers=f["operator"], params={"project_id": project_id})).json()
        configured = await mutate(f, "CONFIGURE", 0, enabled=True)
        assert configured.status_code == 200 and configured.json()["status"] == "ACCEPTED", configured.text
        yield f


async def mutate(f, operation, expected_version=0, *, headers=None, key=None, **fields):
    return await f["client"].post("/api/v1/memory/operations", headers=headers or f["operator"], json={
        "project_id": f["project_id"], "operation_key": key or "fixture-" + uuid4().hex,
        "operation": operation, "expected_version": expected_version, **fields})


async def candidate(f, **changes):
    fields = {"title": "Approved candidate summary", "content": "Synthetic historical method; verify current inputs",
              "source": f["source"], **changes}
    response = await mutate(f, "CREATE_CANDIDATE", headers=f["operator"], **fields)
    assert response.status_code == 200 and response.json()["status"] == "ACCEPTED", response.text
    return response.json()


async def publish(f, receipt, *, operation="PUBLISH", version=1, **changes):
    return await mutate(f, operation, version, entry_id=receipt["entry_id"], title="Shared redacted method",
        content="Synthetic shareable method", publication_note="Human reviewed scope and removed private source text", **changes)


async def query(f, *, headers=None):
    return await f["client"].post("/api/v1/memory/query", headers=headers or f["headers"], json={
        "project_id": f["project_id"], "query": "synthetic", "limit": 20})


async def test_retired_session_task_cannot_be_used_as_a_new_memory_source(memory_context):
    f = memory_context
    response = await mutate(f, "CREATE_CANDIDATE", title="retired source", content="synthetic",
        source={"mode": "LOCAL", "task_id": str(uuid4()), "task_version": 1, "report_id": str(uuid4())})
    assert response.status_code == 410 and "retired" in response.text
    assert f["upstream"].writes == 0


async def test_archive_source_requires_operator_and_fixed_accepted_report(memory_context):
    f = memory_context
    archive_auth, archive_grant = await register(f, ["archive:read", "archive:write"])
    task = await f["client"].post("/api/v1/local-archive/tasks", headers=f["operator"], json={
        "project_id": f["project_id"], "idempotency_key": "archive-memory-task", "title": "Archive source",
        "owner_uploader_actor_ref": "interactive:" + archive_grant["actor_identity_id"]})
    assert task.status_code == 200, task.text
    task_id = task.json()["task"]["id"]
    uploaded = await f["client"].post(f"/api/v1/local-archive/tasks/{task_id}/submissions", headers=archive_auth, json={
        "profile": "local-artifact-archive/v1alpha1", "project_id": f["project_id"], "task_id": task_id,
        "idempotency_key": "archive-memory-report", "expected_archive_version": 1,
        "assets": [{"kind": "REPORT", "stable_key": "report", "title": "Report", "markdown": "Fixed report",
                    "reported_result": "PASS", "origin": {"origin_provider": "codex"}},
                   {"kind": "PLAN", "stable_key": "plan", "title": "Plan", "markdown": "Fixed plan",
                    "origin": {"origin_provider": "codex"}}]})
    assert uploaded.status_code == 200, uploaded.text
    receipt = uploaded.json()
    read = await f["client"].get(f"/api/v1/local-archive/submissions/{receipt['submission_id']}", headers=f["operator"],
        params={"project_id": f["project_id"]})
    assert read.status_code == 200, read.text
    import json
    document = json.loads(read.json()["content"])
    report = next(item for item in document["assets"] if item["kind"] == "REPORT")
    plan = next(item for item in document["assets"] if item["kind"] == "PLAN")
    source = {"mode": "LOCAL_ARCHIVE", "task_id": task_id, "submission_id": receipt["submission_id"],
              "archive_version": receipt["accepted_version"], "asset_revision_id": report["id"]}
    fields = {"title": "Reviewed lesson", "content": "Use the native command", "source": source}
    denied = await mutate(f, "CREATE_CANDIDATE", headers=f["headers"], **fields)
    assert denied.status_code == 403
    bad_version = await mutate(f, "CREATE_CANDIDATE", **{**fields, "source": {**source, "archive_version": 99}})
    assert bad_version.status_code == 409
    bad_kind = await mutate(f, "CREATE_CANDIDATE", **{**fields, "source": {**source, "asset_revision_id": plan["id"]}})
    assert bad_kind.status_code == 409
    async with AsyncSessionLocal() as db:
        other = await create_project(db, ProjectCreate(key=public_key("MEMORY"), name="Other project"))
    other_f = {**f, "project_id": str(other.id)}
    assert (await mutate(other_f, "CONFIGURE", enabled=True)).status_code == 200
    assert (await mutate(other_f, "CREATE_CANDIDATE", **fields)).status_code == 404
    accepted = await mutate(f, "CREATE_CANDIDATE", **fields)
    assert accepted.status_code == 200, accepted.text
    fixed = await f["client"].get(f"/api/v1/memory/entries/{accepted.json()['entry_id']}", headers=f["operator"],
        params={"project_id": f["project_id"], "version": 1})
    assert fixed.status_code == 200 and fixed.json()["source"]["asset_revision_id"] == report["id"]
    unchanged = await f["client"].post(f"/api/v1/local-archive/tasks/{task_id}/submissions", headers=archive_auth, json={
        "profile": "local-artifact-archive/v1alpha1", "project_id": f["project_id"], "task_id": task_id,
        "idempotency_key": "archive-memory-unchanged", "expected_archive_version": receipt["accepted_version"],
        "assets": []})
    assert unchanged.status_code == 200 and unchanged.json()["outcome"] == "UNCHANGED", unchanged.text
    reused_source = {**source, "submission_id": unchanged.json()["submission_id"]}
    reused = await mutate(f, "CREATE_CANDIDATE", **{**fields, "source": reused_source})
    assert reused.status_code == 200, reused.text
    published = await publish(f, accepted.json())
    assert published.status_code == 200 and published.json()["status"] == "ACCEPTED", published.text
    results = await query(f)
    assert results.status_code == 200 and results.json()["degraded"] is False
    assert set(results.json()["results"][0]["source"]) == {"mode", "provenance_id"}


async def test_candidate_private_fixed_readback_and_task_history_unchanged(memory_context):
    f = memory_context
    receipt = await candidate(f)
    assert receipt["accepted_version"] == 1 and receipt["expected_version"] == 0
    assert f["upstream"].writes == 0
    response = await f["client"].get("/api/v1/memory/entries/" + receipt["entry_id"], headers=f["operator"],
        params={"project_id": f["project_id"], "version": 1})
    assert response.status_code == 200
    entry = response.json()
    assert entry["source"]["mode"] == "LOCAL_ARCHIVE"
    assert entry["source"]["asset_revision_id"] == f["source"]["asset_revision_id"]
    stranger, _ = await register(f, ["memory:read"])
    denied = await f["client"].get("/api/v1/memory/entries/" + receipt["entry_id"], headers=stranger,
        params={"project_id": f["project_id"], "version": 1})
    assert denied.status_code == 404
    assert (await query(f)).json()["results"] == []
    assert (await f["client"].get("/api/v1/local-archive/tasks/" + f["source"]["task_id"], headers=f["operator"], params={"project_id": f["project_id"]})).json() == f["task_snapshot"]


async def test_independent_permissions_owner_source_and_operator_publication(memory_context):
    f = memory_context
    sync_only, _ = await register(f, ["task:sync", "cloud:read"])
    assert (await query(f, headers=sync_only)).status_code == 403
    no_owner, _ = await register(f, ["memory:read", "memory:propose", "memory:publish"])
    denied = await mutate(f, "CREATE_CANDIDATE", headers=no_owner,
        title="No privilege transfer", content="Cannot claim source", source=f["source"])
    assert denied.status_code == 403
    receipt = await candidate(f)
    denied = await mutate(f, "PUBLISH", 1, headers=no_owner, entry_id=receipt["entry_id"],
        title="No self promotion", content="Not approved", publication_note="Bearer is not human Operator")
    assert denied.status_code == 403
    bad = {**f["source"], "archive_version": 999}
    assert (await mutate(f, "CREATE_CANDIDATE", headers=f["operator"], title="bad", content="bad", source=bad)).status_code == 409
    cross_project = {**f["source"], "task_id": str(uuid4())}
    assert (await mutate(f, "CREATE_CANDIDATE", headers=f["operator"], title="bad", content="bad", source=cross_project)).status_code == 404


async def test_publish_fixed_get_revise_retract_stale_index_and_opaque_source(memory_context):
    f = memory_context
    receipt = await candidate(f)
    response = await publish(f, receipt)
    assert response.status_code == 200 and response.json()["status"] == "ACCEPTED", response.text
    assert response.json()["accepted_version"] == 2 and f["upstream"].writes == 1
    stranger, _ = await register(f, ["memory:read"])
    hits = (await query(f, headers=stranger)).json()["results"]
    assert len(hits) == 1 and hits[0]["version"] == 2
    assert set(hits[0]["source"]) == {"mode", "provenance_id"}
    assert "Private report title" not in str(hits)
    revised = await publish(f, receipt, operation="REVISE", version=2)
    assert revised.json()["accepted_version"] == 3
    hits = (await query(f)).json()["results"]
    assert len(hits) == 1 and hits[0]["version"] == 3  # old upstream row retained
    withdrawn = await mutate(f, "RETRACT", 3, entry_id=receipt["entry_id"], publication_note="Counterexample invalidates method")
    assert withdrawn.json()["accepted_version"] == 4
    assert (await query(f)).json()["results"] == []
    old = await f["client"].get("/api/v1/memory/entries/" + receipt["entry_id"], headers=f["operator"],
        params={"project_id": f["project_id"], "version": 2})
    assert old.json()["version"] == 2 and old.json()["status"] == "SUPERSEDED"
    assert len(f["upstream"].records) == 2


async def test_lost_ack_original_key_reconciles_readonly_no_second_remember(memory_context):
    f = memory_context
    receipt = await candidate(f)
    f["upstream"].lose_write_ack = True
    response = await publish(f, receipt)
    assert response.json()["status"] == "UNKNOWN", response.text
    key = response.json()["operation_key"]
    assert f["upstream"].writes == 1
    assert (await query(f)).json()["results"] == []
    # Lost tab/process recovery needs only metadata and the original key.
    recovered = await f["client"].get("/api/v1/memory/operations/by-key", headers=f["operator"],
        params={"project_id": f["project_id"], "operation_key": key})
    assert recovered.json()["status"] == "ACCEPTED" and recovered.json()["accepted_version"] == 2, recovered.text
    assert f["upstream"].writes == 1
    unknown = await f["client"].get("/api/v1/memory/operations/by-key", headers=f["operator"],
        params={"project_id": f["project_id"], "operation_key": "not-found"})
    assert unknown.status_code == 404 and "does not authorize replay" in unknown.text
    assert f["upstream"].writes == 1


async def test_fixed_readback_mismatch_keeps_unknown_and_exact_original_id(memory_context):
    f = memory_context
    receipt = await candidate(f)
    f["upstream"].mismatch_read = True
    response = await publish(f, receipt)
    assert response.json()["status"] == "UNKNOWN"
    key = response.json()["operation_key"]
    first_id = f["upstream"].records[0]["artifact_id"]
    async with AsyncSessionLocal() as db:
        operation = await db.scalar(select(MemoryOperation).where(MemoryOperation.project_id == UUID(f["project_id"]), MemoryOperation.operation_key == key))
        assert operation.upstream_ref["artifact_id"] == first_id
    unresolved = await f["client"].get("/api/v1/memory/operations/by-key", headers=f["operator"],
        params={"project_id": f["project_id"], "operation_key": key})
    assert unresolved.json()["status"] == "UNKNOWN" and f["upstream"].writes == 1
    f["upstream"].mismatch_read = False
    resolved = await f["client"].get("/api/v1/memory/operations/by-key", headers=f["operator"],
        params={"project_id": f["project_id"], "operation_key": key})
    assert resolved.json()["status"] == "ACCEPTED" and f["upstream"].writes == 1


async def test_concurrent_original_key_and_versions_only_one_external_write(memory_context):
    f = memory_context
    receipt = await candidate(f)
    async def one(key):
        return await mutate(f, "PUBLISH", 1, key=key, entry_id=receipt["entry_id"], title="Shared",
            content="Synthetic content", publication_note="Human approved")
    key = "concurrent-original"
    responses = await asyncio.gather(one(key), one(key))
    assert all(row.status_code == 200 for row in responses)
    assert f["upstream"].writes == 1
    assert any(row.json()["status"] == "ACCEPTED" for row in responses)
    reused = await mutate(f, "PUBLISH", 1, key=key, entry_id=receipt["entry_id"], title="Different request",
        content="Synthetic content", publication_note="Human approved")
    assert reused.status_code == 409


async def test_retract_during_upstream_write_never_reactivates_old_response(memory_context):
    f = memory_context
    receipt = await candidate(f)
    async def retract_in_flight(_row):
        response = await mutate(f, "RETRACT", 1, entry_id=receipt["entry_id"], publication_note="Withdraw in-flight publication")
        assert response.status_code == 200 and response.json()["accepted_version"] == 2, response.text
    f["upstream"].on_remember = retract_in_flight
    response = await publish(f, receipt)
    assert response.json()["status"] == "UNKNOWN"
    assert response.json()["reason"] == "PUBLICATION_SUPERSEDED_OR_DISABLED"
    assert (await query(f)).json()["results"] == []
    assert f["upstream"].writes == 1


async def test_disable_revoke_during_search_and_expired_visibility(memory_context):
    f = memory_context
    receipt = await candidate(f)
    expiry = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert (await publish(f, receipt, expires_at=expiry)).json()["status"] == "ACCEPTED"
    assert (await query(f)).json()["results"] == []
    async def disable_during_search():
        response = await mutate(f, "CONFIGURE", 1, enabled=False)
        assert response.json()["status"] == "ACCEPTED"
    f["upstream"].on_search = disable_during_search
    assert (await query(f)).status_code == 503
    assert f["upstream"].creates == 1
    old = await f["client"].get(f"/api/v1/memory/projects/{f['project_id']}/configuration", headers=f["operator"], params={"version": 1})
    assert old.json()["enabled"] is True and old.json()["version"] == 1


async def test_no_external_io_under_task_lock_and_revoke_race(memory_context):
    f = memory_context
    async def revoke_during_search():
        async with AsyncSessionLocal() as db:
            await db.execute(text("SET LOCAL lock_timeout='1s'"))
            grant = await db.get(InteractiveIntegrationGrant, UUID(f["auth"]["grant_id"]))
            grant.status = "REVOKED"
            grant.row_version += 1
            grant.revoked_at = datetime.now(UTC)
            await db.commit()
    f["upstream"].on_search = revoke_during_search
    response = await query(f)
    assert response.status_code == 403


async def test_byte_limit_secret_scan_and_generation_never_invoked(memory_context):
    f = memory_context
    receipt = await candidate(f, content="Long private candidate: " + "界" * 4000)
    assert f["upstream"].writes == 0
    denied = await mutate(f, "PUBLISH", 1, entry_id=receipt["entry_id"], title="too long", content="界" * 4000,
        publication_note="Needs shortening")
    assert denied.status_code == 422 and f["upstream"].writes == 0
    secret = await mutate(f, "CREATE_CANDIDATE", headers=f["headers"], title="Unsafe",
        content="-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----", source=f["source"])
    assert secret.status_code == 422
    f["upstream"].fail_search = True
    degraded = await query(f)
    assert degraded.status_code == 200 and degraded.json()["degraded"] is True
    # Optional memory failure never rewrites the existing task's FAIL or history.
    assert (await f["client"].get("/api/v1/local-archive/tasks/" + f["source"]["task_id"], headers=f["operator"], params={"project_id": f["project_id"]})).json() == f["task_snapshot"]


async def test_memory_history_database_guards_and_scope_mapping_immutable(memory_context):
    f = memory_context
    receipt = await candidate(f)
    for statement in (
        "DELETE FROM memory_entries WHERE id=:entry",
        "UPDATE memory_revisions SET content='rewrite history' WHERE entry_id=:entry",
        "UPDATE memory_entries SET source='{}'::jsonb WHERE id=:entry",
        "UPDATE memory_project_mappings SET scope_id='cross-project' WHERE project_id=:project",
    ):
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(statement), {"entry": UUID(receipt["entry_id"]), "project": UUID(f["project_id"])})
                await db.commit()
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE memory_operations SET response='{}'::jsonb WHERE project_id=:project AND state='ACCEPTED'"),
                {"project": UUID(f["project_id"])})
            await db.commit()


async def test_initial_local_query_does_not_require_task_or_report(memory_context):
    f = memory_context
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("MEMORY"), name="Initial query without a task"))
    initial = {**f, "project_id": str(project.id)}
    headers, _ = await register(initial, ["memory:read"])
    assert (await mutate(initial, "CONFIGURE", enabled=True)).json()["status"] == "ACCEPTED"
    response = await query(initial, headers=headers)
    assert response.status_code == 200 and response.json()["results"] == []


async def test_scope_lost_ack_reads_original_namespace_and_keeps_disable(memory_context):
    f = memory_context
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("MEMORY"), name="Scope lost ACK fixture"))
    initial = {**f, "project_id": str(project.id)}
    f["upstream"].lose_scope_ack = True
    created = await mutate(initial, "CONFIGURE", key="scope-original", enabled=True)
    assert created.json()["status"] == "UNKNOWN"
    count = f["upstream"].creates
    duplicate = await mutate(initial, "CONFIGURE", key="scope-original", enabled=True)
    assert duplicate.json() == created.json() and f["upstream"].creates == count
    assert (await mutate(initial, "CONFIGURE", 1, enabled=False)).json()["status"] == "ACCEPTED"
    recovered = await f["client"].get("/api/v1/memory/operations/by-key", headers=f["operator"],
        params={"project_id": initial["project_id"], "operation_key": "scope-original"})
    assert recovered.json()["status"] == "ACCEPTED" and f["upstream"].creates == count
    current = await f["client"].get(f"/api/v1/memory/projects/{initial['project_id']}/configuration", headers=f["operator"])
    assert current.json()["enabled"] is False and current.json()["version"] == 2
    fixed = await f["client"].get(f"/api/v1/memory/projects/{initial['project_id']}/configuration", headers=f["operator"], params={"version": 1})
    assert fixed.json()["enabled"] is True and fixed.json()["version"] == 1


async def test_timeout_preserves_sent_outbox_and_never_reposts(memory_context, monkeypatch):
    f = memory_context
    receipt = await candidate(f)
    monkeypatch.setattr(get_settings(), "memory_timeout_seconds", 0.1)
    async def wait_after_write(_row):
        async with AsyncSessionLocal() as db:
            persisted = await db.scalar(select(MemoryOperation).where(MemoryOperation.entry_id == UUID(receipt["entry_id"]),
                MemoryOperation.operation == "PUBLISH"))
            assert persisted.state == "SENT"  # Persisted before the external write.
        await asyncio.sleep(1)
    f["upstream"].on_remember = wait_after_write
    response = await publish(f, receipt)
    assert response.json()["status"] == "UNKNOWN"
    assert f["upstream"].writes == 1
    f["upstream"].on_remember = None
    recovered = await f["client"].get("/api/v1/memory/operations/by-key", headers=f["operator"],
        params={"project_id": f["project_id"], "operation_key": response.json()["operation_key"]})
    assert recovered.json()["status"] == "ACCEPTED" and f["upstream"].writes == 1


async def test_pagination_filters_before_limit_and_project_index_injection_rejected(memory_context):
    f = memory_context
    for n in range(3):
        await candidate(f, title="candidate-" + str(n))
    first = await f["client"].get(f"/api/v1/memory/projects/{f['project_id']}", headers=f["operator"],
        params={"status": "CANDIDATE", "limit": 2, "offset": 0})
    second = await f["client"].get(f"/api/v1/memory/projects/{f['project_id']}", headers=f["operator"],
        params={"status": "CANDIDATE", "limit": 2, "offset": 2})
    assert len(first.json()["entries"]) == 2 and first.json()["has_more"] is True
    assert len(second.json()["entries"]) == 1 and second.json()["has_more"] is False
    foreign = {"scope_id": next(iter(f["upstream"].scopes.values())), "artifact_id": "foreign-project-row", "revision": 1,
        "content": "This upstream row is outside the PostgreSQL authorized set"}
    f["upstream"].records.append(foreign)
    assert (await query(f)).json()["results"] == []


cloud_context = _cloud_context


@pytest.fixture
async def cloud_memory_context(cloud_context, monkeypatch, tmp_path):
    f = cloud_context
    admin_file = tmp_path / "synthetic-powercontext-token"
    admin_file.write_text("synthetic-powercontext-private-token")
    admin_file.chmod(0o600)
    monkeypatch.setattr(get_settings(), "memory_powercontext_token_file", str(admin_file))
    upstream = InertPowerContext()
    monkeypatch.setattr(service, "adapter", lambda: upstream)
    monkeypatch.setattr(get_settings(), "memory_enabled", True)
    configured = await f["client"].post("/api/v1/memory/operations", headers=f["operator_headers"], json={
        "project_id": f["project_id"], "operation_key": "cloud-memory-config", "operation": "CONFIGURE",
        "expected_version": 0, "enabled": True})
    assert configured.json()["status"] == "ACCEPTED", configured.text
    registration = await f["client"].post("/api/v1/interactive/registrations", headers=f["operator_headers"], json={
        "actor_ref": "dedicated-memory-worker-" + uuid4().hex, "client_instance_id": str(uuid4()),
        "project_id": f["project_id"], "scopes": ["memory:read", "memory:propose"]})
    assert registration.status_code == 201
    receipt, claim, identity = await claimed(f)
    headers = {"Authorization": "Bearer " + registration.json()["integration_token"],
        "X-Hypertest-Memory-Worker-Id": identity.worker_id,
        "X-Hypertest-Memory-Lease-Token": identity.lease_token,
        "X-Hypertest-Memory-Generation": str(identity.generation),
        "X-Hypertest-Memory-Work-Token": identity.work_token}
    return {**f, "upstream": upstream, "identity": identity, "receipt": receipt, "claim": claim,
        "memory_headers": headers, "memory_auth": registration.json()}


async def test_initial_cloud_query_fixed_attempt_without_asset_and_lease_fence(cloud_memory_context):
    f = cloud_memory_context
    receipt = f["receipt"]
    body = {"project_id": f["project_id"], "query": "previous method", "limit": 10,
        "context": {"task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"], "task_version": receipt["version"]}}
    response = await f["client"].post("/api/v1/memory/query", headers=f["memory_headers"], json=body)
    assert response.status_code == 200 and response.json()["results"] == [], response.text
    forged = {**body, "context": {**body["context"], "task_version": 1}}
    assert (await f["client"].post("/api/v1/memory/query", headers=f["memory_headers"], json=forged)).status_code == 409
    cancelled = await cloud_post(f, "CANCEL_ATTEMPT", receipt["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], reason="Synthetic lease fence")
    assert cancelled.status_code == 200
    assert (await f["client"].post("/api/v1/memory/query", headers=f["memory_headers"], json=body)).status_code == 409


async def test_cloud_fixed_asset_candidate_authority_and_original_key_survive_fence(cloud_memory_context):
    f = cloud_memory_context
    receipt = await worker_submit(f, f["identity"], f["receipt"], "SUBMIT_ASSETS", assets=[{
        "kind": "REPORT", "key": "progress", "title": "Synthetic failure source", "markdown": "FAIL fixture",
        "reported_result": "FAIL"}])
    source = {"mode": "CLOUD", "task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"],
        "task_version": receipt["version"], "asset_revision_id": receipt["assets"][0]["id"]}
    payload = {"project_id": f["project_id"], "operation": "CREATE_CANDIDATE", "operation_key": "cloud-candidate-original",
        "expected_version": 0, "source": source, "title": "Synthetic Cloud method", "content": "Keep original failure"}
    response = await f["client"].post("/api/v1/memory/operations", headers=f["memory_headers"], json=payload)
    assert response.status_code == 200 and response.json()["status"] == "ACCEPTED", response.text
    assert f["upstream"].writes == 0
    # A project memory grant is insufficient without the private current proof.
    bearer_only = {"Authorization": f["memory_headers"]["Authorization"]}
    assert (await f["client"].post("/api/v1/memory/operations", headers=bearer_only,
        json={**payload, "operation_key": "unfenced-spoof"})).status_code == 403
    cancelled = await cloud_post(f, "CANCEL_ATTEMPT", receipt["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], reason="Synthetic cancellation; no process exists")
    assert cancelled.status_code == 200
    rejected = await f["client"].post("/api/v1/memory/operations", headers=f["memory_headers"],
        json={**payload, "operation_key": "late-worker"})
    assert rejected.status_code == 409
    recovered = await f["client"].get("/api/v1/memory/operations/by-key", headers=f["memory_headers"],
        params={"project_id": f["project_id"], "operation_key": payload["operation_key"]})
    assert recovered.status_code == 200 and recovered.json() == response.json()
    async with AsyncSessionLocal() as db:
        operation = await db.scalar(select(MemoryOperation).where(MemoryOperation.project_id == UUID(f["project_id"]),
            MemoryOperation.operation_key == payload["operation_key"]))
        assert "lease" not in str(operation.request) and "token" not in str(operation.request)


async def test_operation_entry_composite_fk_rejects_cross_project_persistence(memory_context):
    f = memory_context
    receipt = await candidate(f)
    async with AsyncSessionLocal() as db:
        other = await create_project(db, ProjectCreate(key=public_key("MEMORY"), name="Different Project tenant"))
    async with AsyncSessionLocal() as db:
        original = await db.scalar(select(MemoryOperation).where(MemoryOperation.entry_id == UUID(receipt["entry_id"])))
        copy = {column.name: getattr(original, column.name) for column in original.__table__.columns}
        copy.update(id=uuid4(), project_id=other.id, operation_key="cross-project-durable-guard")
        db.add(MemoryOperation(**copy))
        with pytest.raises(DBAPIError):
            await db.commit()


@pytest.mark.parametrize("secret_kind", ["admin", "operator", "bearer"])
async def test_known_gateway_and_request_tokens_never_enter_candidate_publication_or_query(memory_context, secret_kind):
    f = memory_context
    secret = {"admin": "synthetic-powercontext-private-token", "operator": OPERATOR,
        "bearer": f["headers"]["Authorization"][7:]}[secret_kind]
    denied = await mutate(f, "CREATE_CANDIDATE", headers=f["headers"], title="Unsafe input",
        content="Accidental credential: " + secret, source=f["source"])
    assert denied.status_code == 422 and secret not in denied.text
    receipt = await candidate(f)
    denied = await mutate(f, "PUBLISH", 1, entry_id=receipt["entry_id"], title="Unsafe publication",
        content="Accidental credential: " + secret, publication_note="Reject known secret before SENT")
    assert denied.status_code == 422 and secret not in denied.text
    denied = await f["client"].post("/api/v1/memory/query", headers=f["headers"], json={
        "project_id": f["project_id"], "query": "Accidental credential: " + secret})
    assert denied.status_code == 422 and secret not in denied.text
    assert f["upstream"].writes == 0


async def test_gateway_secret_unavailable_only_closes_memory_and_task_sync_still_works(memory_context, monkeypatch, tmp_path):
    f = memory_context
    monkeypatch.setattr(get_settings(), "memory_powercontext_token_file", str(tmp_path / "missing-key"))
    denied = await mutate(f, "CREATE_CANDIDATE", headers=f["headers"], title="Cannot scan safely",
        content="Synthetic new candidate", source=f["source"])
    assert denied.status_code == 503 and "missing-key" not in denied.text
    denied_query = await query(f)
    assert denied_query.status_code == 503
    read = await f["client"].get("/api/v1/local-archive/tasks/" + f["source"]["task_id"],
        headers=f["operator"], params={"project_id": f["project_id"]})
    assert read.status_code == 200 and read.json() == f["task_snapshot"]
    assert f["upstream"].writes == 0
