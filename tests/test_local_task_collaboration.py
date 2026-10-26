"""Local collaboration regression with synthetic data in the dedicated test DB."""
import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_session_tasks import body, counts, sync
from test_session_tasks import context as context

from hypertest.api.task_collaboration_schemas import COLLABORATION_PROFILE
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.session_tasks import CollaborationReceipt, ContributionRevision, SessionTask


async def setup(f):
    original = body(f)
    response = await sync(f, original)
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    enable = await op(f, task_id, "ENABLE", 1, "enable")
    assert enable.status_code == 200, enable.text
    detail = (await f["c"].get(f"/api/v1/tasks/{task_id}/collaboration")).json()
    return task_id, original, detail


async def op(f, task, operation, version, key, **fields):
    return await f["c"].post(f"/api/v1/tasks/{task}/collaboration", json={
        "profile": COLLABORATION_PROFILE, "operation": operation, "expected_version": version,
        "idempotency_key": key, **fields})


def member_body(f, source, operation, version, key, **fields):
    return {"profile": COLLABORATION_PROFILE, "project_id": f["project_id"], "provider": "codex",
            "session_id": source, "operation": operation, "expected_version": version,
            "idempotency_key": key, **fields}


async def member(f, task, source, operation, version, key, **fields):
    return await f["c"].post(f"/api/v1/interactive/tasks/{task}/collaboration", headers=f["headers"],
        json=member_body(f, source, operation, version, key, **fields))


async def read(f, task, source, **params):
    return await f["c"].get(f"/api/v1/interactive/tasks/{task}/collaboration", headers=f["headers"],
        params={"project_id": f["project_id"], "provider": "codex", "session_id": source, **params})


async def add(f, task, actor, version=2, key="authorize", source=None):
    source = source or "other-root-" + uuid4().hex
    response = await op(f, task, "AUTHORIZE", version, key, actor_ref=actor,
                        provider="codex", session_id=source, assignment="API checks")
    assert response.status_code == 200, response.text
    return source


def report(result="FAIL", expected=0):
    return [{"kind": "REPORT", "stable_key": "same-key", "expected_revision": expected,
             "content": {"title": "Independent report", "markdown": f"# {result}\nExact raw report", "reported_result": result}}]


def summary(**changes):
    return {"title": "Explicit aggregate", "objective": "Keep all sources", "status": "IN_PROGRESS",
            "plan_markdown": "# Aggregate", "reported_result": "FAIL", "contribution_refs": [],
            "completion_basis": "", "unresolved_items": ["Retained failure"], **changes}


async def test_two_roots_preserve_contribution_namespaces_and_all_fixed_versions(context):
    f = context
    baseline = await counts()
    task, original, enabled = await setup(f)
    initial = enabled["collaboration"]["participants"][0]
    assert initial["initial_binding"] and initial["joined_at"] is None
    assert initial["role"] == "PRIMARY" and initial["status"] == "ACTIVE"
    second = await add(f, task, initial["actor_ref"])
    before_join = await read(f, task, second)
    assert before_join.status_code == 200, before_join.text
    authorized = json.loads(before_join.json()["content"])
    assert authorized["collaboration"]["participants"][1]["status"] == "AUTHORIZED"
    assert authorized["collaboration"]["participants"][1]["joined_at"] is None
    assert (await member(f, task, second, "CONTRIBUTE", 3, "no-prejoin-write", contributions=report())).status_code == 403
    missing = await f["c"].get(f"/api/v1/interactive/tasks/{task}/collaboration/receipts/by-key", headers=f["headers"],
        params={"project_id": f["project_id"], "provider": "codex", "session_id": second, "idempotency_key": "not-sent"})
    assert missing.status_code == 404
    joined = await member(f, task, second, "JOIN", 3, "join")
    assert joined.status_code == 200, joined.text
    first_contribution = await member(f, task, original["session_id"], "CONTRIBUTE", 4, "root-report", contributions=report())
    assert first_contribution.status_code == 200, first_contribution.text
    second_contribution = await member(f, task, second, "CONTRIBUTE", 5, "second-report", contributions=report("PASS"))
    assert second_contribution.status_code == 200, second_contribution.text
    current = (await f["c"].get(f"/api/v1/tasks/{task}")).json()
    assert [x["content"]["reported_result"] for x in current["collaboration"]["contributions"]] == ["FAIL", "PASS"]
    assert len({x["participant_id"] for x in current["collaboration"]["contributions"]}) == 2
    assert current["task"]["reported_result"] == "FAIL"  # contribution is not publication
    assert current["task"]["last_synced_at"] == enabled["task"]["last_synced_at"]
    refs = [{**x, "disposition": "DIVERGENCE", "shared_key": "shared-report"}
            for x in first_contribution.json()["contribution_refs"] + second_contribution.json()["contribution_refs"]]
    publication = await member(f, task, original["session_id"], "PUBLISH", 6, "publish",
        primary_generation=1, summary=summary(contribution_refs=refs))
    assert publication.status_code == 200, publication.text
    for version, members, contributions in ((1, 0, 0), (2, 1, 0), (3, 2, 0), (4, 2, 0), (5, 2, 1), (6, 2, 2), (7, 2, 2)):
        pinned = await f["c"].get(f"/api/v1/tasks/{task}/collaboration", params={"version": version})
        assert pinned.status_code == 200, pinned.text
        fixed = pinned.json()
        assert fixed["task"]["version"] == version
        assert len(fixed["collaboration"]["participants"]) == members
        assert len(fixed["collaboration"]["contributions"]) == contributions
        assert fixed["task"]["provider"] == original["provider"]
        assert fixed["task"]["session_id"] == original["session_id"]
        assert len(fixed["collaboration"]["publications"]) == (1 if version == 7 else 0)
    final = (await read(f, task, second)).json()
    assert json.loads(final["content"])["task"]["version"] == 7
    assert await counts() == baseline


async def test_legacy_write_block_original_receipts_and_exact_source_reconciliation(context):
    f = context
    task, original, enabled = await setup(f)
    assert (await sync(f, original)).status_code == 200  # original key precedes profile rejection
    assert (await sync(f, {**original, "idempotency_key": "new-fullsync", "expected_version": 2})).status_code == 409
    assert (await f["c"].patch(f"/api/v1/tasks/{task}", json={"expected_version": 2, "title": "Bypass"})).status_code == 409
    assert (await f["c"].get(f"/api/v1/interactive/tasks/{task}", headers=f["headers"], params={
        "project_id": f["project_id"]})).json()["detail"] == "COLLABORATION_PROFILE_REQUIRED"
    assert (await f["c"].get(f"/api/v1/interactive/tasks/{task}", headers=f["headers"], params={
        "project_id": f["project_id"], "version": 1})).status_code == 200
    first = enabled["collaboration"]["participants"][0]
    second = await add(f, task, first["actor_ref"])
    assert (await member(f, task, second, "JOIN", 3, "join")).status_code == 200
    accepted = await member(f, task, second, "CONTRIBUTE", 4, "reconcile", contributions=report())
    assert accepted.status_code == 200, accepted.text
    assert (await member(f, task, second, "CONTRIBUTE", 4, "reconcile", contributions=report())).json() == accepted.json()
    assert (await member(f, task, second, "CONTRIBUTE", 5, "reconcile", contributions=report())).status_code == 409
    assert (await member(f, task, original["session_id"], "CONTRIBUTE", 5, "reconcile", contributions=report())).status_code == 409
    for source, expected in ((second, 200), (original["session_id"], 403)):
        response = await f["c"].get(f"/api/v1/interactive/tasks/{task}/collaboration/receipts/by-key", headers=f["headers"],
            params={"project_id": f["project_id"], "provider": "codex", "session_id": source, "idempotency_key": "reconcile"})
        assert response.status_code == expected, response.text
    detail = (await f["c"].get(f"/api/v1/tasks/{task}/collaboration")).json()
    other = detail["collaboration"]["participants"][1]
    assert (await op(f, task, "REVOKE", 5, "revoke", participant_id=other["id"])).status_code == 200
    assert (await read(f, task, second)).status_code == 403
    assert (await member(f, task, second, "CONTRIBUTE", 4, "reconcile", contributions=report())).status_code == 403
    denied_receipt = await f["c"].get(f"/api/v1/interactive/tasks/{task}/collaboration/receipts/by-key", headers=f["headers"],
        params={"project_id": f["project_id"], "provider": "codex", "session_id": second, "idempotency_key": "reconcile"})
    assert denied_receipt.status_code == 403
    assert (await f["c"].get(f"/api/v1/tasks/{task}/collaboration", params={"version": 5})).json()["collaboration"]["participants"][1]["status"] == "ACTIVE"


async def test_handoff_generation_late_publication_and_revoked_primary(context):
    f = context
    task, original, enabled = await setup(f)
    primary = enabled["collaboration"]["participants"][0]
    second = await add(f, task, primary["actor_ref"])
    assert (await member(f, task, second, "JOIN", 3, "join")).status_code == 200
    detail = (await f["c"].get(f"/api/v1/tasks/{task}/collaboration")).json()
    target = detail["collaboration"]["participants"][1]
    assert (await member(f, task, second, "PUBLISH", 4, "not-primary", primary_generation=1, summary=summary())).status_code == 403
    accepted = await member(f, task, original["session_id"], "PUBLISH", 4, "first-publish", primary_generation=1, summary=summary())
    assert accepted.status_code == 200, accepted.text
    handoff_fields = {"participant_id": target["id"], "expected_primary_generation": 1,
                      "handoff": {"materials": ["Current accepted reports"], "unresolved_items": ["Old root private ledger unobserved"], "private_journals_observed": False}}
    handoff = await op(f, task, "HANDOFF", 5, "handoff", **handoff_fields)
    assert handoff.status_code == 200, handoff.text
    assert handoff.json()["primary_generation"] == 2
    assert (await op(f, task, "HANDOFF", 5, "handoff", **handoff_fields)).json() == handoff.json()
    assert (await member(f, task, original["session_id"], "PUBLISH", 4, "first-publish", primary_generation=1, summary=summary())).json() == accepted.json()
    assert (await member(f, task, original["session_id"], "PUBLISH", 6, "late", primary_generation=1, summary=summary())).status_code == 403
    assert (await member(f, task, second, "PUBLISH", 6, "wrong-generation", primary_generation=1, summary=summary())).status_code == 403
    assert (await member(f, task, second, "PUBLISH", 6, "new-publish", primary_generation=2,
        summary=summary(status="COMPLETED", reported_result="PASS", completion_basis="Explicit reported aggregate; original failure retained", unresolved_items=[]))).status_code == 200
    assert (await op(f, task, "REVOKE", 7, "revoke-primary", participant_id=target["id"])).status_code == 200
    final = (await f["c"].get(f"/api/v1/tasks/{task}/collaboration")).json()
    assert final["task"]["primary_participant_id"] is None and final["task"]["primary_generation"] == 3
    assert (await member(f, task, original["session_id"], "CONTRIBUTE", 8, "still-contribute", contributions=report())).status_code == 200


async def test_concurrent_contributions_revision_conflicts_and_softdelete_versions(context):
    f = context
    task, original, enabled = await setup(f)
    one = enabled["collaboration"]["participants"][0]
    second = await add(f, task, one["actor_ref"])
    assert (await member(f, task, second, "JOIN", 3, "join")).status_code == 200
    results = await asyncio.gather(member(f, task, original["session_id"], "CONTRIBUTE", 4, "one", contributions=report()),
                                   member(f, task, second, "CONTRIBUTE", 4, "two", contributions=report("PASS")))
    assert sorted(x.status_code for x in results) == [200, 409]
    accepted_source = original["session_id"] if results[0].status_code == 200 else second
    assert (await member(f, task, accepted_source, "CONTRIBUTE", 5, "revision-stale", contributions=report())).status_code == 409
    updated = await member(f, task, accepted_source, "CONTRIBUTE", 5, "revision-two", contributions=report("PASS", expected=1))
    assert updated.status_code == 200, updated.text
    assert (await f["c"].delete(f"/api/v1/tasks/{task}", params={"expected_version": 6})).status_code == 200
    deleted = (await f["c"].get(f"/api/v1/tasks/{task}/collaboration", params={"include_deleted": True})).json()
    assert deleted["task"]["version"] == 7 and len(deleted["collaboration"]["contributions"]) == 2
    assert (await member(f, task, accepted_source, "CONTRIBUTE", 7, "deleted-write", contributions=report(expected=2))).status_code == 409
    assert (await f["c"].post(f"/api/v1/tasks/{task}/restore", json={"expected_version": 7})).status_code == 200
    restored = (await f["c"].get(f"/api/v1/tasks/{task}/collaboration")).json()
    assert restored["task"]["version"] == 8 and len(restored["collaboration"]["contributions"]) == 2
    assert (await member(f, task, accepted_source, "CONTRIBUTE", 8, "revision-three", contributions=report(expected=2))).status_code == 200


async def test_source_reservation_covers_join_bind_fullsync_and_immutable_history(context):
    f = context
    task, original, enabled = await setup(f)
    actor = enabled["collaboration"]["participants"][0]["actor_ref"]
    second = await add(f, task, actor)
    assert (await member(f, task, second, "JOIN", 3, "join")).status_code == 200
    # A source that joined a task cannot create a second task through legacy sync.
    assert (await sync(f, body(f, session_id=second, idempotency_key="cannot-auto-create"))).status_code == 409
    candidate = await f["c"].post(f"/api/v1/projects/{f['project_id']}/local-tasks", json={"idempotency_key": "new-unbound", "title": "Candidate"})
    candidate_id = candidate.json()["task"]["id"]
    denied = await f["c"].post("/api/v1/interactive/tasks/bind", headers=f["headers"], json={
        "project_id": f["project_id"], "task_id": candidate_id, "provider": "codex", "session_id": second,
        "expected_version": 1, "idempotency_key": "cannot-bind"})
    assert denied.status_code == 409, denied.text
    accepted = await member(f, task, second, "CONTRIBUTE", 4, "retained-report", contributions=report())
    assert accepted.status_code == 200, accepted.text
    current = (await f["c"].get(f"/api/v1/tasks/{task}/collaboration")).json()
    target = current["collaboration"]["participants"][1]
    assert (await op(f, task, "REVOKE", 5, "revoke-source", participant_id=target["id"])).status_code == 200
    assert (await sync(f, body(f, session_id=second, idempotency_key="still-cannot-auto-create"))).status_code == 409
    async with AsyncSessionLocal() as db:
        receipt = await db.scalar(select(CollaborationReceipt).where(CollaborationReceipt.task_id == UUID(task)))
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE session_collaboration_receipts SET response='{}' WHERE id=:id"), {"id": receipt.id})
        await db.rollback()
        with pytest.raises(DBAPIError):
            await db.execute(text("DELETE FROM session_task_sources WHERE task_id=:id"), {"id": UUID(task)})
        await db.rollback()
        assert (await db.get(SessionTask, UUID(task))).session_id == original["session_id"]
        contribution = await db.scalar(select(ContributionRevision).where(ContributionRevision.task_id == UUID(task)))
        assert contribution.content["reported_result"] == "FAIL"
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE session_contribution_revisions SET content='{}' WHERE id=:id"), {"id": contribution.id})
        await db.rollback()


async def test_authority_project_source_and_pagination_are_fenced(context):
    f = context
    task, original, enabled = await setup(f)
    primary = enabled["collaboration"]["participants"][0]
    assert (await read(f, task, "invented-source")).status_code == 403
    unauthorized = await op(f, task, "AUTHORIZE", 2, "wrong-actor", actor_ref="interactive:" + str(uuid4()),
                           provider="codex", session_id="wrong-actor-root")
    assert unauthorized.status_code == 403
    second = await add(f, task, primary["actor_ref"])
    assert (await member(f, task, second, "JOIN", 2, "stale-join")).status_code == 409
    assert (await member(f, task, second, "JOIN", 3, "join")).status_code == 200
    wrong_project = await f["c"].post(f"/api/v1/interactive/tasks/{task}/collaboration", headers=f["headers"],
        json={**member_body(f, second, "CONTRIBUTE", 4, "wrong-project", contributions=report()), "project_id": str(uuid4())})
    assert wrong_project.status_code in {403, 404}
    operator_write = await f["c"].post(f"/api/v1/interactive/tasks/{task}/collaboration",
        headers={"X-Hypertest-Operator-Key": "task-sync-fixture-operator"},
        json=member_body(f, second, "CONTRIBUTE", 4, "operator-bypass", contributions=report()))
    assert operator_write.status_code == 403
    cursor, collected, fixed = 0, [], 4
    while cursor is not None:
        response = await read(f, task, second, version=fixed, offset=cursor, limit=1500)
        assert response.status_code == 200, response.text
        envelope = response.json()
        assert envelope["version"] == fixed
        collected.append(envelope["content"])
        cursor = envelope["next_offset"]
    assert json.loads("".join(collected))["task"]["version"] == fixed
    assert (await read(f, task, second, offset=1)).status_code == 422
    # Revoking the actual integration grant also denies new operations and
    # original-key reads even while the roster still lists this member ACTIVE.
    revoked = await f["c"].post(f"/api/v1/interactive/grants/{f['auth']['grant_id']}/revoke",
        headers={"X-Hypertest-Operator-Key": "task-sync-fixture-operator"})
    assert revoked.status_code == 200, revoked.text
    assert (await read(f, task, second)).status_code == 403
    assert (await member(f, task, second, "JOIN", 3, "join")).status_code == 403


async def test_join_and_legacy_creation_race_share_one_global_source_reservation(context):
    f = context
    task, original, enabled = await setup(f)
    actor = enabled["collaboration"]["participants"][0]["actor_ref"]
    source = await add(f, task, actor)
    joined, legacy = await asyncio.gather(
        member(f, task, source, "JOIN", 3, "racing-join"),
        sync(f, body(f, session_id=source, idempotency_key="racing-legacy")))
    assert sorted(x.status_code for x in (joined, legacy)) == [200, 409]
    async with AsyncSessionLocal() as db:
        owner = await db.scalar(text("SELECT task_id FROM session_task_sources WHERE provider='codex' AND session_id=:source"), {"source": source})
        assert str(owner) == (task if joined.status_code == 200 else legacy.json()["task_id"])
        accepted = await db.scalar(select(SessionTask).where(SessionTask.id == UUID(task)))
        assert accepted.version == (4 if joined.status_code == 200 else 3)


async def test_real_local_adapter_asgi_roundtrip_defaults_unicode_and_fixed_pages(context, tmp_path):
    """Exercise real HTTP client, adapter, server digests and full fixed readback."""
    from httpx import ASGITransport

    from hypertest.api.task_collaboration_schemas import CollaborationMemberOperation
    from hypertest.interactive_client.api_client import ApiClient
    from hypertest.interactive_client.config import ClientConfig
    from hypertest.interactive_client.security import private_create
    from hypertest.local_sync.collaboration import LocalCollaborationAdapter, namespace
    from hypertest.main import app
    from hypertest.sync_core import FrozenIntent, digest

    f = context
    task, original, enabled = await setup(f)
    initial = enabled["collaboration"]["participants"][0]
    source = await add(f, task, initial["actor_ref"])
    token_file = tmp_path / "synthetic-integration-token"
    private_create(token_file, f["auth"]["integration_token"].encode())
    api = ApiClient(ClientConfig(api_url="https://localhost/api/v1", state_dir=tmp_path,
        integration_token_file=token_file), transport=ASGITransport(app=app))
    adapter = LocalCollaborationAdapter(api)
    target = {"project_id": f["project_id"], "task_id": task, "provider": "codex", "session_id": source}
    calls = []

    async def record(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))

    api.client.event_hooks["request"] = [record]

    async def roundtrip(operation, version, key, **fields):
        wire = CollaborationMemberOperation.model_validate(
            member_body(f, source, operation, version, key, **fields)).model_dump(mode="json")
        payload = {**wire, "task_id": task}
        intent = FrozenIntent(namespace(payload), key, target, payload, version)
        accepted = await adapter.submit(intent)
        adapter.validate_receipt(intent, accepted)
        assert accepted["request_digest"] == digest(wire)
        assert await adapter.reconcile(intent) == accepted
        document = await adapter.readback(intent, accepted)
        assert document["task"]["version"] == accepted["version"]
        return accepted, document

    try:
        prejoin = await adapter.baseline(target)
        assert prejoin["task"]["version"] == 3
        assert prejoin["collaboration"]["participants"][1]["status"] == "AUTHORIZED"
        joined, joined_document = await roundtrip("JOIN", 3, "asgi-join")
        assert joined_document["collaboration"]["participants"][1]["status"] == "ACTIVE"
        raw_report = "原始失败 Δ 引号“证据”\n" * 2000
        submitted = [{"kind": "CASE", "stable_key": "unicode-case", "expected_revision": 0,
                      "content": {"title": "接口失败保全"}},
                     {"kind": "REPORT", "stable_key": "unicode-report", "expected_revision": 0,
                      "content": {"title": "原始报告", "markdown": raw_report}}]
        contributed, contributed_document = await roundtrip("CONTRIBUTE", 4, "asgi-contribute", contributions=submitted)
        cases, reports = contributed_document["collaboration"]["contributions"]
        assert cases["content"]["steps"] == [] and cases["content"]["reported_result"] == "NOT_RUN"
        assert reports["content"]["reported_result"] == "UNKNOWN"
        assert reports["content"]["markdown"] == raw_report
        assert reports["actor_ref"] == joined["actor_ref"]
        assert reports["participant_id"] == joined["participant_id"]
        assert (await op(f, task, "HANDOFF", 5, "asgi-handoff", participant_id=joined["participant_id"],
            expected_primary_generation=1, handoff={"materials": ["固定v5原文"], "unresolved_items": [],
                                                   "private_journals_observed": False})).status_code == 200
        refs = [{**ref, "disposition": "ADOPTED", "shared_key": f"shared-{index}"}
                for index, ref in enumerate(contributed["contribution_refs"])]
        published, document = await roundtrip("PUBLISH", 6, "asgi-publish", primary_generation=2,
            summary=summary(title="多会话真实接口适配回归", contribution_refs=refs))
        assert document["task"]["session_id"] == original["session_id"]
        assert document["task"]["primary_participant_id"] == joined["participant_id"]
        assert document["collaboration"]["publications"][0]["summary"]["contribution_refs"] == refs
        assert document["collaboration"]["contributions"][1]["content"]["markdown"] == raw_report
        assert published["request_digest"] == document["operation_history"][-1]["input_digest"]
        fixed_reads = [params for method, path, params in calls if method == "GET"
                       and path.endswith("/collaboration") and params.get("version") == "7"]
        assert len(fixed_reads) > 1 and any(int(params.get("offset", "0")) > 0 for params in fixed_reads)
        assert sum(method == "POST" for method, _, _ in calls) == 3
    finally:
        await api.close()
