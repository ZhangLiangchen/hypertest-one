"""ADR-027 PostgreSQL regression: scopes, exact targets and preserved accepted history."""
import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from hypertest.api.archive_schemas import ArchiveSubmit
from hypertest.api.schemas import ProjectCreate
from hypertest.application import local_archive as service
from hypertest.application.services import canonical_json_sha256, create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.local_archive import (
    LocalArchiveAssetRevision,
    LocalArchiveSnapshot,
    LocalArchiveSubmission,
    LocalArchiveTask,
)
from hypertest.domain.models import AuditEvent, OutboxEvent
from hypertest.main import app

PREFIX = "/api/v1/local-archive"


@pytest.fixture
async def archive_context(monkeypatch):
    monkeypatch.setattr(get_settings(), "connector_operator_key", "archive-fixture-operator")
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("ARCHIVE"), name="Synthetic archive regression"))
    operator = {"X-Hypertest-Operator-Key": "archive-fixture-operator"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        registration = await client.post("/api/v1/interactive/registrations", headers=operator, json={
            "actor_ref": "archive-fixture-" + uuid4().hex, "client_instance_id": str(uuid4()),
            "project_id": str(project.id), "scopes": ["archive:read", "archive:write"]})
        assert registration.status_code == 201, registration.text
        grant = registration.json()
        created = await client.post(PREFIX + "/tasks", headers=operator, json={
            "project_id": str(project.id), "idempotency_key": "create", "title": "Post-test archive"})
        assert created.status_code == 200, created.text
        yield {"client": client, "project_id": str(project.id), "operator": operator,
            "auth": {"Authorization": "Bearer " + grant["integration_token"]}, "grant": grant,
            "task_id": created.json()["task"]["id"], "created": created.json()}


def payload(f, **changes):
    return {"profile": "local-artifact-archive/v1alpha1", "project_id": f["project_id"], "task_id": f["task_id"],
        "idempotency_key": "first", "expected_archive_version": 1,
        "assets": [{"kind": "REPORT", "stable_key": "original", "title": "Original failure", "markdown": "# FAIL\n原文\r\nExact bytes\n",
            "reported_result": "FAIL", "origin": {"origin_provider": "codex", "origin_session_ref": "declared-original"}}], **changes}


async def upload(f, body):
    return await f["client"].post(PREFIX + "/tasks/" + f["task_id"] + "/submissions", headers=f["auth"], json=body)


async def detail(f):
    r = await f["client"].get(PREFIX + "/tasks/" + f["task_id"], headers=f["operator"], params={"project_id": f["project_id"]})
    assert r.status_code == 200, r.text
    return r.json()


async def read_submission(f, receipt, *, limit=24000):
    parts, offset = [], 0
    while True:
        read = await f["client"].get(PREFIX + "/submissions/" + receipt["submission_id"], headers=f["auth"],
            params={"project_id": f["project_id"], "offset": offset, "limit": limit})
        assert read.status_code == 200, read.text
        page = read.json()
        assert page["archive_version"] == receipt["accepted_version"]
        assert page["submission_id"] == receipt["submission_id"]
        assert page["offset"] == offset
        parts.append(page["content"])
        if page["complete"]:
            assert page["next_offset"] is None
            assert len("".join(parts)) == page["total_chars"]
            return json.loads("".join(parts))
        offset = page["next_offset"]


async def add_child(f, key="child", expected=1):
    response = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/subtasks", headers=f["operator"], json={
        "project_id": f["project_id"], "idempotency_key": key, "expected_task_version": expected, "title": key})
    assert response.status_code == 200, response.text
    return response.json()["subtasks"][-1]["id"]


async def test_root_archive_exact_text_fixed_readback_and_unchanged_receipt(archive_context):
    f = archive_context
    body = payload(f)
    accepted = await upload(f, body)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()
    assert receipt["outcome"] == "ACCEPTED" and receipt["accepted_version"] == 2
    assert receipt["target_kind"] == "TASK" and receipt["subtask_id"] is None
    assert receipt["request_digest"] == canonical_json_sha256(ArchiveSubmit.model_validate(body).wire())
    original = await read_submission(f, receipt, limit=73)
    assert original["assets"][0]["markdown"] == body["assets"][0]["markdown"]
    assert original["assets"][0]["reported_result"] == "FAIL"
    assert "status" not in original and "reported_result" not in original
    current = await detail(f)
    assert current["task"]["status"] == "DRAFT" and current["task"]["reported_result"] == "NOT_RUN"
    assert current["task"]["version"] == 1 and current["task"]["archive_version"] == 2
    assert current["subtasks"] == []
    unchanged = await upload(f, {**body, "expected_archive_version": 2, "idempotency_key": "same-content"})
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["outcome"] == "UNCHANGED" and unchanged.json()["accepted_version"] == 2
    assert await read_submission(f, unchanged.json()) == original
    next_body = {**body, "expected_archive_version": 2, "idempotency_key": "later",
        "assets": [{**body["assets"][0], "markdown": "# PASS\nNew observation", "reported_result": "PASS"}]}
    later = await upload(f, next_body)
    assert later.status_code == 200 and later.json()["accepted_version"] == 3
    assert (await upload(f, body)).json() == receipt
    assert await read_submission(f, receipt) == original
    lookup = await f["client"].get(PREFIX + "/submissions/by-key", headers=f["auth"],
        params={"project_id": f["project_id"], "idempotency_key": "same-content"})
    assert lookup.json() == unchanged.json()
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(LocalArchiveAssetRevision).where(LocalArchiveAssetRevision.task_id == UUID(f["task_id"]))) == 2
        assert await db.scalar(select(func.count()).select_from(LocalArchiveSubmission).where(LocalArchiveSubmission.task_id == UUID(f["task_id"]))) == 3


async def test_independent_root_child_spaces_omission_and_publication_vector(archive_context):
    f = archive_context
    child = await add_child(f)
    root = await upload(f, payload(f))
    sub = await upload(f, payload(f, subtask_id=child, idempotency_key="child-upload",
        subtask_update={"status": "COMPLETED", "reported_result": "FAIL"}))
    assert root.status_code == sub.status_code == 200, (root.text, sub.text)
    current = await detail(f)
    assert current["task"]["version"] == 2
    assert current["task"]["archive_version"] == current["subtasks"][0]["archive_version"] == 2
    assert current["task"]["reported_result"] == "NOT_RUN" and current["subtasks"][0]["reported_result"] == "FAIL"
    assert (await read_submission(f, root.json()))["assets"][0]["revision"] == 1
    child_doc = await read_submission(f, sub.json())
    assert child_doc["assets"][0]["revision"] == 1 and child_doc["status"] == "COMPLETED"
    publication = {"project_id": f["project_id"], "idempotency_key": "summary", "expected_task_version": 2,
        "root_archive_version": 2, "subtask_versions": [{"subtask_id": child, "archive_version": 2}],
        "asset_revision_ids": [child_doc["assets"][0]["id"]], "summary": "Explicit failed overall result",
        "status": "COMPLETED", "reported_result": "FAIL"}
    published = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/publications", headers=f["operator"], json=publication)
    assert published.status_code == 200, published.text
    assert published.json()["task"]["reported_result"] == "FAIL"
    more = await upload(f, payload(f, subtask_id=child, expected_archive_version=2, idempotency_key="more", assets=[
        {"kind": "CASE", "stable_key": "new-case", "title": "More testing", "reported_result": "PASS"}]))
    assert more.status_code == 200, more.text
    document = await read_submission(f, more.json())
    assert len(document["assets"]) == 2 and document["reported_result"] == "FAIL"
    current = await detail(f)
    assert current["task"]["version"] == 3 and current["publications"][0]["subtask_versions"][0]["archive_version"] == 2
    assert (await f["client"].get(PREFIX + "/operations/by-key", headers=f["operator"], params={
        "project_id": f["project_id"], "idempotency_key": "summary"})).json() == published.json()
    stale = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/publications", headers=f["operator"],
        json={**publication, "idempotency_key": "stale-vector", "expected_task_version": 3})
    assert stale.status_code == 409


async def test_conflicting_keys_versions_and_invalid_targets_reject_atomically(archive_context):
    f = archive_context
    first = await upload(f, payload(f))
    assert first.status_code == 200, first.text
    assert (await upload(f, payload(f, assets=[]))).status_code == 409
    assert (await upload(f, payload(f, idempotency_key="stale"))).status_code == 409
    assert (await upload(f, payload(f, subtask_id=str(uuid4()), idempotency_key="bad-child"))).status_code == 404
    assert (await upload(f, payload(f, expected_archive_version=2, subtask_update={"reported_result": "PASS"}))).status_code == 422
    assert (await upload(f, payload(f, assets=payload(f)["assets"] * 2))).status_code == 422
    other_task = await f["client"].post(PREFIX + "/tasks", headers=f["operator"], json={
        "project_id": f["project_id"], "idempotency_key": "other", "title": "Other"})
    other_id = other_task.json()["task"]["id"]
    child = await f["client"].post(PREFIX + f"/tasks/{other_id}/subtasks", headers=f["operator"], json={
        "project_id": f["project_id"], "idempotency_key": "other-child", "expected_task_version": 1, "title": "Other child"})
    assert (await upload(f, payload(f, subtask_id=child.json()["subtasks"][0]["id"], idempotency_key="cross-child"))).status_code == 404
    current = await detail(f)
    assert len(current["submission_history"]) == 1 and current["task"]["archive_version"] == 2
    absent = await f["client"].get(PREFIX + "/submissions/by-key", headers=f["auth"], params={
        "project_id": f["project_id"], "idempotency_key": "not-found"})
    assert absent.status_code == 404 and "does not authorize replay" in absent.text


async def test_scopes_operator_and_revocation_guard_reads_and_writes(archive_context):
    f = archive_context
    assert (await f["client"].get(PREFIX + "/tasks", params={"project_id": f["project_id"]})).status_code == 401
    assert (await f["client"].post(PREFIX + "/tasks", json={"project_id": f["project_id"], "idempotency_key": "unauth", "title": "No"})).status_code == 401
    assert (await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/submissions", headers=f["operator"], json=payload(f))).status_code == 401
    for scopes in (["task:sync"], ["archive:write"], ["archive:read"]):
        registered = await f["client"].post("/api/v1/interactive/registrations", headers=f["operator"], json={
            "actor_ref": "different-" + uuid4().hex, "client_instance_id": str(uuid4()), "project_id": f["project_id"], "scopes": scopes})
        denied = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/submissions", json=payload(f),
            headers={"Authorization": "Bearer " + registered.json()["integration_token"]})
        assert denied.status_code == 403
    accepted = await upload(f, payload(f))
    assert accepted.status_code == 200
    revoked = await f["client"].post(f"/api/v1/interactive/grants/{f['grant']['grant_id']}/revoke", headers=f["operator"])
    assert revoked.status_code == 200
    assert (await upload(f, payload(f))).status_code == 403
    assert (await f["client"].get(PREFIX + "/submissions/by-key", headers=f["auth"], params={
        "project_id": f["project_id"], "idempotency_key": "first"})).status_code == 403
    assert (await detail(f))["task"]["archive_version"] == 2


async def test_subtask_revoke_and_accepted_owner_are_preserved(archive_context):
    f = archive_context
    child = await add_child(f)
    body = payload(f, subtask_id=child)
    accepted = await upload(f, body)
    assert accepted.status_code == 200, accepted.text
    revoke = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/authorize", headers=f["operator"], json={
        "project_id": f["project_id"], "idempotency_key": "revoke-child", "expected_task_version": 2,
        "subtask_id": child, "uploader_actor_ref": None})
    assert revoke.status_code == 200, revoke.text
    assert (await upload(f, body)).status_code == 403
    assert (await f["client"].get(PREFIX + "/submissions/" + accepted.json()["submission_id"], headers=f["auth"],
        params={"project_id": f["project_id"]})).status_code == 403
    owner_change = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/authorize", headers=f["operator"], json={
        "project_id": f["project_id"], "idempotency_key": "change-owner", "expected_task_version": 3,
        "uploader_actor_ref": None})
    assert owner_change.status_code == 409
    restore = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/authorize", headers=f["operator"], json={
        "project_id": f["project_id"], "idempotency_key": "restore-child", "expected_task_version": 3,
        "subtask_id": child, "uploader_actor_ref": f["created"]["task"]["owner_uploader_actor_ref"]})
    assert restore.status_code == 200, restore.text
    assert (await upload(f, body)).json() == accepted.json()


async def test_concurrent_same_key_and_new_versions_serialize(archive_context):
    f = archive_context
    same = await asyncio.gather(upload(f, payload(f)), upload(f, payload(f)))
    assert same[0].status_code == same[1].status_code == 200
    assert same[0].json() == same[1].json()
    next_body = payload(f, expected_archive_version=2, idempotency_key="update", assets=[
        {"kind": "PLAN", "stable_key": "plan", "title": "Next", "markdown": "Exact plan"}])
    different = await asyncio.gather(upload(f, next_body), upload(f, {**next_body, "idempotency_key": "competing"}))
    assert sorted(item.status_code for item in different) == [200, 409]


async def test_revocation_while_waiting_for_target_lock_prevents_acceptance(archive_context, monkeypatch):
    f = archive_context
    entered = asyncio.Event()
    original = service.submit

    async def observed(*args, **kwargs):
        entered.set()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "submit", observed)
    async with AsyncSessionLocal() as blocker:
        await blocker.scalar(select(LocalArchiveTask).where(LocalArchiveTask.id == UUID(f["task_id"])).with_for_update())
        pending = asyncio.create_task(upload(f, payload(f)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            revoked = await asyncio.wait_for(f["client"].post(
                f"/api/v1/interactive/grants/{f['grant']['grant_id']}/revoke", headers=f["operator"]), timeout=10)
            assert revoked.status_code == 200
        finally:
            await blocker.rollback()
        assert (await asyncio.wait_for(pending, timeout=10)).status_code == 403
    assert (await detail(f))["task"]["archive_version"] == 1


async def test_database_history_guards_and_atomic_rejection(archive_context):
    f = archive_context
    accepted = await upload(f, payload(f))
    assert accepted.status_code == 200, accepted.text
    async with AsyncSessionLocal() as db:
        count_before = await db.scalar(select(func.count()).select_from(OutboxEvent))
        for sql in (
            "UPDATE local_archive_submissions SET outcome='UNCHANGED' WHERE task_id=:id",
            "DELETE FROM local_archive_asset_revisions WHERE task_id=:id",
            "UPDATE local_archive_tasks SET owner_uploader_actor_ref=NULL, version=version+1 WHERE id=:id",
            "UPDATE local_archive_tasks SET archive_version=archive_version+1, status='COMPLETED' WHERE id=:id",
        ):
            with pytest.raises(DBAPIError):
                await db.execute(text(sql), {"id": UUID(f["task_id"])})
                await db.commit()
            await db.rollback()
        assert await db.scalar(select(func.count()).select_from(OutboxEvent)) == count_before
        assert await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == UUID(accepted.json()["submission_id"]))) == 1
        assert await db.scalar(select(func.count()).select_from(LocalArchiveSnapshot).where(LocalArchiveSnapshot.task_id == UUID(f["task_id"]))) == 2


async def test_project_owner_and_original_client_are_separate_boundaries(archive_context):
    from hypertest.domain.interactive import InteractiveActorIdentity
    f = archive_context
    async with AsyncSessionLocal() as db:
        other = await create_project(db, ProjectCreate(key=public_key("OTHER"), name="Other synthetic project"))
        actor_id = UUID(f["created"]["task"]["owner_uploader_actor_ref"].split(":", 1)[1])
        actor = await db.get(InteractiveActorIdentity, actor_id)
        actor_label = actor.actor_ref
    assert (await upload(f, payload(f, project_id=str(other.id)))).status_code == 403
    for label, expected in (("other-owner-" + uuid4().hex, 403), (actor_label, 409)):
        registration = await f["client"].post("/api/v1/interactive/registrations", headers=f["operator"], json={
            "actor_ref": label, "client_instance_id": str(uuid4()), "project_id": f["project_id"],
            "scopes": ["archive:read", "archive:write"]})
        assert registration.status_code == 201
        if expected == 409:
            assert (await upload(f, payload(f))).status_code == 200
        response = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/submissions", json=payload(f),
            headers={"Authorization": "Bearer " + registration.json()["integration_token"]})
        assert response.status_code == expected
    current = await detail(f)
    assert len(current["submission_history"]) == 1


async def test_management_key_recovery_and_draft_admission(archive_context):
    f = archive_context
    create = {"project_id": f["project_id"], "idempotency_key": "create", "title": "Post-test archive"}
    same = await f["client"].post(PREFIX + "/tasks", headers=f["operator"], json=create)
    assert same.json() == f["created"]
    conflict = await f["client"].post(PREFIX + "/tasks", headers=f["operator"], json={**create, "title": "different"})
    assert conflict.status_code == 409
    draft = await f["client"].post(PREFIX + "/tasks", headers=f["operator"], json={
        **create, "idempotency_key": "draft", "owner_uploader_actor_ref": None})
    assert draft.status_code == 200 and draft.json()["task"]["owner_uploader_actor_ref"] is None
    task_id = draft.json()["task"]["id"]
    denied = await f["client"].post(PREFIX + f"/tasks/{task_id}/submissions", headers=f["auth"],
        json=payload(f, task_id=task_id))
    assert denied.status_code == 403
    await add_child(f)
    frozen = await f["client"].get(PREFIX + "/operations/by-key", headers=f["operator"], params={
        "project_id": f["project_id"], "idempotency_key": "create"})
    assert frozen.json() == f["created"]
    stale = await f["client"].post(PREFIX + f"/tasks/{f['task_id']}/update", headers=f["operator"], json={
        "project_id": f["project_id"], "idempotency_key": "stale", "expected_task_version": 1, "title": "Rejected"})
    assert stale.status_code == 409


async def test_final_authority_check_rolls_back_entire_submission(archive_context, monkeypatch):
    from fastapi import HTTPException
    f = archive_context
    original = service.submit

    async def reject_after_flush(db, body, actor, client, *, authorization_check):
        checks = 0

        async def recheck():
            nonlocal checks
            checks += 1
            await authorization_check()
            if checks == 2:
                raise HTTPException(403, "authorization expired before acceptance")

        return await original(db, body, actor, client, authorization_check=recheck)

    monkeypatch.setattr(service, "submit", reject_after_flush)
    denied = await upload(f, payload(f))
    assert denied.status_code == 403
    assert (await detail(f))["task"]["archive_version"] == 1
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(LocalArchiveSubmission).where(LocalArchiveSubmission.task_id == UUID(f["task_id"]))) == 0
        assert await db.scalar(select(func.count()).select_from(LocalArchiveAssetRevision).where(LocalArchiveAssetRevision.task_id == UUID(f["task_id"]))) == 0
        assert await db.scalar(select(func.count()).select_from(LocalArchiveSnapshot).where(LocalArchiveSnapshot.task_id == UUID(f["task_id"]))) == 1


async def test_database_rejects_cross_target_asset_insertion(archive_context):
    f = archive_context
    child = await add_child(f)
    accepted = await upload(f, payload(f))
    assert accepted.status_code == 200, accepted.text
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("""INSERT INTO local_archive_asset_revisions
                (id,project_id,task_id,target_kind,subtask_id,submission_id,kind,stable_key,revision,archive_version,uploader_actor_ref,content,created_at)
                SELECT :id,project_id,task_id,'SUBTASK',:child,submission_id,kind,'cross-target',1,archive_version,uploader_actor_ref,
                       jsonb_set(content,'{stable_key}','"cross-target"'::jsonb),created_at
                FROM local_archive_asset_revisions WHERE task_id=:task LIMIT 1"""),
                {"id": uuid4(), "child": UUID(child), "task": UUID(f["task_id"])})
            await db.commit()
        await db.rollback()
