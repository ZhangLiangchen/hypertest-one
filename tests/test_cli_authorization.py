"""Pairing boundaries and recovery using synthetic data in the dedicated test DB."""
import asyncio
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from hypertest.api.schemas import ProjectCreate
from hypertest.application import cli_authorization as service
from hypertest.application import interactive
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.connector.security import token_hash
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cli_authorization import (
    CliArchiveUploader,
    CliAuthorizationGlobalGrant,
    CliAuthorizationGrant,
)
from hypertest.domain.interactive import InteractiveActorIdentity
from hypertest.main import app

ROOT = "/api/v1/cli-authorizations"


@pytest.fixture
async def pairing(monkeypatch):
    monkeypatch.setattr(get_settings(), "connector_operator_key", "cli-operator-fixture")
    operator_ref = "cli-operator-fixture-" + uuid4().hex
    monkeypatch.setattr(get_settings(), "connector_operator_identity", operator_ref)
    async with AsyncSessionLocal() as db:
        projects = [str((await create_project(db, ProjectCreate(
            key=public_key("CLI"), name="CLI fixture"))).id) for _ in range(3)]
        actor = InteractiveActorIdentity(actor_ref="cli-fixture-" + uuid4().hex, registered_by="fixture")
        db.add(actor)
        await db.commit()
        actor_id = str(actor.id)
    secret, proof = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    body = {"request_id": str(uuid4()), "idempotency_key": "create", "client_instance_id": str(uuid4()),
            "client_name": "Fixture CLI", "server_url": "https://localhost",
            "credential_hash": token_hash(secret), "verifier_challenge": token_hash(proof), "project_id": None}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        yield {"client": client, "body": body, "secret": secret, "proof": proof,
               "projects": projects, "actor_id": actor_id, "operator_ref": operator_ref,
               "operator": {"X-Hypertest-Operator-Key": "cli-operator-fixture"},
               "headers": {"X-Hypertest-Pairing-Proof": proof}}


async def created(f):
    response = await f["client"].post(ROOT + "/requests", json=f["body"])
    assert response.status_code == 201, response.text
    return response.json()


def approval(f, pending):
    return {"idempotency_key": "approve",
            "project_ids": f["projects"][:2], "scopes": ["archive:read", "archive:write"],
            "expires_in_days": 30, "short_code": pending["short_code"]}


async def approved(f, pending):
    response = await f["client"].post(ROOT + "/requests/" + pending["request_id"] + "/approve",
                                      json=approval(f, pending), headers=f["operator"])
    assert response.status_code == 200, response.text
    return response.json()


async def bound(f):
    pending = await created(f)
    accepted = await approved(f, pending)
    return await redeemed(f, accepted)


async def redeemed(f, accepted):
    body = {"idempotency_key": "redeem", "approval_digest": accepted["approval"]["approval_digest"]}
    response = await f["client"].post(ROOT + "/requests/" + accepted["request_id"] + "/redeem",
                                      json=body, headers=f["headers"])
    assert response.status_code == 200, response.text
    return response.json(), body


def another_client(f):
    secret, proof = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    return {**f, "secret": secret, "proof": proof,
        "headers": {"X-Hypertest-Pairing-Proof": proof},
        "body": {**f["body"], "request_id": str(uuid4()), "client_instance_id": str(uuid4()),
                 "credential_hash": token_hash(secret), "verifier_challenge": token_hash(proof)}}


async def test_pairing_requires_private_proof_and_web_operator(pairing):
    f = pairing
    pending = await created(f)
    url = ROOT + "/requests/" + pending["request_id"]
    assert (await f["client"].get(url)).status_code == 403
    assert (await f["client"].get(url, headers={"X-Hypertest-Pairing-Proof": pending["short_code"]})).status_code == 403
    assert (await f["client"].get(url, headers=f["headers"])).json()["status"] == "PENDING"
    assert (await f["client"].post(url + "/approve", json=approval(f, pending))).status_code == 401
    assert (await f["client"].post(url + "/approve", headers=f["operator"],
        json={**approval(f, pending), "short_code": "0000-0000"})).status_code == 403
    assert (await f["client"].post(url + "/approve", headers=f["operator"],
        json={**approval(f, pending), "scopes": ["archive:read", "task:sync"]})).status_code == 422
    async with AsyncSessionLocal() as db:
        assert await db.get(CliArchiveUploader, f["operator_ref"]) is None
    accepted = await approved(f, pending)
    assert (await f["client"].post(url + "/redeem", json={"idempotency_key": "redeem",
        "approval_digest": accepted["approval"]["approval_digest"]})).status_code == 403
    assert f["secret"] not in str(accepted) and f["proof"] not in str(accepted)
    assert "credential_hash" not in accepted and "verifier_challenge" not in accepted


async def test_fixed_keys_restore_lost_responses_without_new_grants(pairing):
    f = pairing
    pending = await created(f)
    assert (await f["client"].post(ROOT + "/requests", json=f["body"])).json() == pending
    assert (await f["client"].post(ROOT + "/requests", json={**f["body"], "client_name": "changed"})).status_code == 409
    accepted = await approved(f, pending)
    url = ROOT + "/requests/" + pending["request_id"]
    assert (await f["client"].post(url + "/approve", headers=f["operator"],
        json=approval(f, pending))).json() == accepted
    assert (await f["client"].post(url + "/approve", headers=f["operator"],
        json={**approval(f, pending), "project_ids": f["projects"]})).status_code == 409
    body = {"idempotency_key": "redeem", "approval_digest": accepted["approval"]["approval_digest"]}
    first = await f["client"].post(url + "/redeem", headers=f["headers"], json=body)
    assert first.status_code == 200, first.text
    assert (await f["client"].post(url + "/redeem", headers=f["headers"], json=body)).json() == first.json()
    recovery = await f["client"].get(ROOT + "/requests/by-key", headers=f["headers"], params={
        "request_id": pending["request_id"], "operation": "REDEEM", "idempotency_key": "redeem"})
    assert recovery.json() == first.json()
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CliAuthorizationGrant).where(
            CliAuthorizationGrant.request_id == UUID(pending["request_id"]))) == 2
    assert (await f["client"].get(ROOT + "/requests/by-key", headers=f["headers"], params={
        "request_id": pending["request_id"], "operation": "REDEEM", "idempotency_key": "unknown"})).status_code == 404


async def test_global_credential_keeps_project_scopes_and_independent_revocation(pairing):
    f = pairing
    accepted, _ = await bound(f)
    async with AsyncSessionLocal() as db:
        for project in f["projects"][:2]:
            grant = await interactive.authenticate(db, f["secret"], "archive:write", project_id=UUID(project))
            assert str(grant.project_id) == project
        for scope, project in (("archive:write", f["projects"][2]), ("task:sync", f["projects"][0]), ("memory:read", f["projects"][0])):
            with pytest.raises(HTTPException):
                await interactive.authenticate(db, f["secret"], scope, project_id=UUID(project))
    grant = next(g for g in accepted["grants"] if g["project_id"] == f["projects"][0])
    url = ROOT + "/grants/" + grant["grant_id"]
    revoked = await f["client"].post(url + "/revoke", headers=f["operator"], json={"idempotency_key": "revoke"})
    assert revoked.status_code == 200, revoked.text
    assert (await f["client"].get(url + "/operations/by-key", headers=f["operator"],
        params={"idempotency_key": "revoke"})).json() == revoked.json()
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException):
            await interactive.authenticate(db, f["secret"], "archive:read", project_id=UUID(f["projects"][0]))
        assert await interactive.authenticate(db, f["secret"], "archive:read", project_id=UUID(f["projects"][1]))
    current = (await f["client"].get(ROOT + "/requests/" + accepted["request_id"], headers=f["headers"])).json()
    assert {g["status"] for g in current["grants"]} == {"ACTIVE", "REVOKED"}
    assert (await f["client"].get(ROOT + "/grants")).status_code == 401


async def test_expired_pairing_cannot_be_approved_or_renewed(pairing, monkeypatch):
    f = pairing
    real_now = interactive.now
    async def past_clock(db):
        return await real_now(db) - timedelta(minutes=11)
    with monkeypatch.context() as clock_patch:
        clock_patch.setattr(interactive, "now", past_clock)
        pending = await created(f)
    url = ROOT + "/requests/" + pending["request_id"]
    assert (await f["client"].get(url, headers=f["headers"])).json()["status"] == "EXPIRED"
    assert (await f["client"].post(url + "/approve", headers=f["operator"], json=approval(f, pending))).status_code == 409
    replay = await f["client"].post(ROOT + "/requests", json=f["body"])
    assert replay.json()["expires_at"] == pending["expires_at"]


async def test_revoked_actor_rejected_after_approval(pairing):
    f = pairing
    accepted = await approved(f, await created(f))
    async with AsyncSessionLocal() as db:
        row = await db.get(InteractiveActorIdentity, UUID(accepted["approval"]["actor_identity_id"]))
        clock = await interactive.now(db)
        row.status = "REVOKED"
        row.row_version += 1
        row.revoked_at = clock
        await db.commit()
    response = await f["client"].post(ROOT + "/requests/" + accepted["request_id"] + "/redeem",
        headers=f["headers"], json={"idempotency_key": "redeem", "approval_digest": accepted["approval"]["approval_digest"]})
    assert response.status_code == 403
    other = another_client(f)
    pending = await created(other)
    denied = await other["client"].post(ROOT + "/requests/" + pending["request_id"] + "/approve",
        headers=other["operator"], json=approval(other, pending))
    assert denied.status_code == 403 and denied.json()["detail"] == "CLI_UPLOADER_NOT_ACTIVE"
    async with AsyncSessionLocal() as db:
        mapping = await db.get(CliArchiveUploader, f["operator_ref"])
        assert str(mapping.actor_identity_id) == accepted["approval"]["actor_identity_id"]


async def test_bound_identity_approval_and_receipts_cannot_be_rewritten(pairing):
    accepted, _ = await bound(pairing)
    for sql in (
        "UPDATE cli_authorization_requests SET credential_hash=repeat('f',64) WHERE id=:id",
        "UPDATE cli_authorization_requests SET approval='{}'::jsonb WHERE id=:id",
        "DELETE FROM cli_authorization_receipts WHERE request_id=:id",
        "DELETE FROM cli_authorization_grants WHERE request_id=:id",
    ):
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(sql), {"id": UUID(accepted["request_id"])})
    for sql in (
        "UPDATE cli_archive_uploaders SET operator_ref='changed' WHERE actor_identity_id=:id",
        "DELETE FROM cli_archive_uploaders WHERE actor_identity_id=:id",
    ):
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(sql), {"id": UUID(accepted["approval"]["actor_identity_id"])})


async def test_historical_actor_selection_is_retired_without_mutating_actors(pairing):
    f = pairing
    assert (await f["client"].get(ROOT + "/actors")).status_code == 401
    retired = await f["client"].get(ROOT + "/actors", headers=f["operator"])
    assert retired.status_code == 410 and retired.json()["detail"] == "CLI_UPLOADER_SELECTION_RETIRED"
    pending = await created(f)
    url = ROOT + "/requests/" + pending["request_id"] + "/approve"
    for value in (f["actor_id"], None):
        denied = await f["client"].post(url, headers=f["operator"],
            json={**approval(f, pending), "actor_identity_id": value})
        assert denied.status_code == 422 and denied.json()["detail"] == "CLI_UPLOADER_SELECTION_RETIRED"
    async with AsyncSessionLocal() as db:
        assert await db.get(CliArchiveUploader, f["operator_ref"]) is None
    accepted = await approved(f, pending)
    assert accepted["approval"]["actor_identity_id"] != f["actor_id"]
    async with AsyncSessionLocal() as db:
        old_actor = await db.get(InteractiveActorIdentity, UUID(f["actor_id"]))
        assert old_actor.status == "ACTIVE" and old_actor.row_version == 1


async def test_concurrent_pairings_share_owner_across_clients_but_not_operators(pairing, monkeypatch):
    first, second = pairing, another_client(pairing)
    pending = [await created(first), await created(second)]
    accepted = await asyncio.gather(approved(first, pending[0]), approved(second, pending[1]))
    actor_id = accepted[0]["approval"]["actor_identity_id"]
    assert accepted[1]["approval"]["actor_identity_id"] == actor_id
    await redeemed(first, accepted[0])
    await redeemed(second, accepted[1])
    async with AsyncSessionLocal() as db:
        mapping = await db.get(CliArchiveUploader, first["operator_ref"])
        assert str(mapping.actor_identity_id) == actor_id
        assert await db.scalar(select(func.count()).select_from(InteractiveActorIdentity).where(
            InteractiveActorIdentity.registered_by == first["operator_ref"])) == 1
    project_id = first["projects"][0]
    task_response = await first["client"].post("/api/v1/local-archive/tasks", headers=first["operator"], json={
        "project_id": project_id, "idempotency_key": "task", "title": "Shared archive owner",
        "owner_uploader_actor_ref": "interactive:" + actor_id})
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()["task"]
    assert task["owner_uploader_actor_ref"] == "interactive:" + actor_id
    url = "/api/v1/local-archive/tasks/" + task["id"]
    for client in (first, second):
        response = await client["client"].get(url, params={"project_id": project_id},
            headers={"Authorization": "Bearer " + client["secret"]})
        assert response.status_code == 200, response.text
    other = another_client(first)
    monkeypatch.setattr(get_settings(), "connector_operator_identity", "other-" + uuid4().hex)
    other_bound, _ = await bound(other)
    assert other_bound["approval"]["actor_identity_id"] != actor_id
    denied = await other["client"].get(url, params={"project_id": project_id},
        headers={"Authorization": "Bearer " + other["secret"]})
    assert denied.status_code == 403 and denied.json()["detail"] == "ARCHIVE_TASK_OWNER_REQUIRED"


async def test_historical_approval_receipt_and_pending_redemption_keep_original_actor(pairing):
    f = pairing
    pending = await created(f)
    legacy_body = {**approval(f, pending), "actor_identity_id": f["actor_id"]}
    # A pre-retirement accepted approval fixture. Its actor and receipt must
    # remain exact even though new approvals no longer accept actor selection.
    async with AsyncSessionLocal() as db:
        row = await service.request_record(db, UUID(pending["request_id"]), lock=True)
        actor = await db.get(InteractiveActorIdentity, UUID(f["actor_id"]))
        row.approval = {**legacy_body, "actor_ref": "interactive:" + f["actor_id"],
            "actor_label": actor.actor_ref, "operator": f["operator_ref"],
            "expires_at": ((await interactive.now(db)) + timedelta(days=30)).isoformat(),
            "credential_fingerprint": f["body"]["credential_hash"][:16], "approval_digest": "a" * 64}
        row.status = "APPROVED"
        original = await service.save_receipt(db, row, "APPROVE", "approve",
            {**legacy_body, "operator": f["operator_ref"]})
        await db.commit()
    url = ROOT + "/requests/" + pending["request_id"]
    replay = await f["client"].post(url + "/approve", json=legacy_body, headers=f["operator"])
    assert replay.status_code == 200 and replay.json() == original
    receipt = await f["client"].get(ROOT + "/requests/by-key", headers=f["operator"], params={
        "request_id": pending["request_id"], "operation": "APPROVE", "idempotency_key": "approve"})
    assert receipt.json() == original
    for changed in ({**legacy_body, "project_ids": f["projects"]}, approval(f, pending)):
        conflict = await f["client"].post(url + "/approve", json=changed, headers=f["operator"])
        assert conflict.status_code == 409
    accepted, _ = await redeemed(f, original)
    assert {g["actor_identity_id"] for g in accepted["grants"]} == {f["actor_id"]}
    async with AsyncSessionLocal() as db:
        assert await db.get(CliArchiveUploader, f["operator_ref"]) is None


async def test_global_authorization_new_projects_no_expiry_and_revoke(pairing):
    from hypertest.application import local_archive

    f = pairing
    pending = await created(f)
    url = ROOT + "/requests/" + pending["request_id"]
    response = await f["client"].post(url + "/approve", headers=f["operator"], json={
        "idempotency_key": "approve-global", "short_code": pending["short_code"]})
    assert response.status_code == 200, response.text
    approved_view = response.json()
    assert approved_view["approval"]["all_projects"] is True
    assert approved_view["approval"]["expires_at"] is None
    accepted, _ = await redeemed(f, approved_view)
    assert accepted["grants"] == []
    assert accepted["authorization"]["status"] == "ACTIVE"
    headers = {"Authorization": "Bearer " + f["secret"]}
    doctor = await f["client"].get("/api/v1/local-archive/capabilities", headers=headers)
    assert doctor.status_code == 200, doctor.text
    assert doctor.json()["all_projects"] is True
    async with AsyncSessionLocal() as db:
        new_project = (await create_project(db, ProjectCreate(key=public_key("CLI"), name="New fixture"))).id
        items = (await local_archive.actors(db, new_project))["items"]
        assert accepted["authorization"]["actor_ref"] in [x["actor_ref"] for x in items]
        grant = await interactive.authenticate(db, f["secret"], "archive:write", project_id=new_project)
        assert grant.expires_at is None
        grant_id = str(grant.id)
        await db.commit()
    partial = await f["client"].post(ROOT + "/grants/" + grant_id + "/revoke",
        headers=f["operator"], json={"idempotency_key": "partial"})
    assert partial.status_code == 409
    async with AsyncSessionLocal() as db:
        assert await interactive.authenticate(db, f["secret"], "archive:read", project_id=new_project)
        for scope in ("memory:read", "task:sync"):
            with pytest.raises(HTTPException):
                await interactive.authenticate(db, f["secret"], scope, project_id=new_project)
    revoke = await f["client"].post(url + "/revoke", headers=f["operator"], json={"idempotency_key": "global-revoke"})
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "REVOKED"
    assert (await f["client"].post(url + "/revoke", headers=f["operator"], json={"idempotency_key": "global-revoke"})).json() == revoke.json()
    receipt = await f["client"].get(ROOT + "/requests/by-key", headers=f["operator"], params={
        "request_id": pending["request_id"], "operation": "REVOKE", "idempotency_key": "global-revoke"})
    assert receipt.json() == revoke.json()
    async with AsyncSessionLocal() as db:
        assert accepted["authorization"]["actor_ref"] not in [x["actor_ref"] for x in (await local_archive.actors(db, new_project))["items"]]
        with pytest.raises(HTTPException):
            await interactive.authenticate(db, f["secret"], "archive:read", project_id=new_project)
    assert (await f["client"].get("/api/v1/local-archive/capabilities", headers=headers)).status_code == 401


async def test_concurrent_global_project_grant_creation_is_serialized(pairing):
    f = pairing
    pending = await created(f)
    response = await f["client"].post(ROOT + "/requests/" + pending["request_id"] + "/approve",
        headers=f["operator"], json={"idempotency_key": "global", "short_code": pending["short_code"]})
    assert response.status_code == 200, response.text
    await redeemed(f, response.json())
    project = UUID(f["projects"][0])

    async def authenticate_and_commit():
        async with AsyncSessionLocal() as db:
            grant = await interactive.authenticate(db, f["secret"], "archive:read", project_id=project)
            grant_id = grant.id
            await db.commit()
            return grant_id

    first, second = await asyncio.gather(authenticate_and_commit(), authenticate_and_commit())
    assert first == second
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CliAuthorizationGlobalGrant).where(
            CliAuthorizationGlobalGrant.request_id == UUID(pending["request_id"]),
            CliAuthorizationGlobalGrant.project_id == project)) == 1


async def test_global_authorization_archives_any_task_without_rewriting_ownership(pairing):
    f = pairing
    project_id = f["projects"][0]
    archive = "/api/v1/local-archive"
    pending = await created(f)
    url = ROOT + "/requests/" + pending["request_id"]
    approved_view = (await f["client"].post(url + "/approve", headers=f["operator"], json={
        "idempotency_key": "approve-all", "short_code": pending["short_code"]})).json()
    accepted, _ = await redeemed(f, approved_view)
    global_actor = accepted["authorization"]["actor_ref"]
    global_headers = {"Authorization": "Bearer " + f["secret"]}

    registered = await f["client"].post("/api/v1/interactive/registrations", headers=f["operator"], json={
        "actor_ref": "other-" + uuid4().hex, "client_instance_id": str(uuid4()), "project_id": project_id,
        "scopes": ["archive:read", "archive:write"]})
    assert registered.status_code == 201, registered.text
    old = registered.json()
    old_actor = "interactive:" + old["actor_identity_id"]
    old_headers = {"Authorization": "Bearer " + old["integration_token"]}
    old_capabilities = await f["client"].get(archive + "/capabilities", headers=old_headers,
                                              params={"project_id": project_id})
    assert old_capabilities.status_code == 200
    assert old_capabilities.json()["all_projects"] is False
    global_capabilities = await f["client"].get(archive + "/capabilities", headers=global_headers,
                                                 params={"project_id": project_id})
    assert global_capabilities.status_code == 200
    assert global_capabilities.json()["all_projects"] is True

    for owner in (old_actor, None):
        created_task = await f["client"].post(archive + "/tasks", headers=f["operator"], json={
            "project_id": project_id, "idempotency_key": "create-" + str(owner),
            "title": "Prior task", "owner_uploader_actor_ref": owner})
        assert created_task.status_code == 200, created_task.text
        task_id = created_task.json()["task"]["id"]
        child_resp = await f["client"].post(archive + f"/tasks/{task_id}/subtasks", headers=f["operator"], json={
            "project_id": project_id, "idempotency_key": "child-" + str(owner),
            "expected_task_version": 1, "title": "Prior subtask"})
        assert child_resp.status_code == 200, child_resp.text
        child = child_resp.json()["subtasks"][0]["id"]
        target = archive + f"/tasks/{task_id}/submissions"
        body = {"project_id": project_id, "task_id": task_id, "expected_archive_version": 1,
                "idempotency_key": "root-" + str(owner), "assets": [
                    {"kind": "REPORT", "stable_key": "report", "title": "Prior result",
                     "markdown": "failure", "reported_result": "FAIL"}]}
        if owner is None:
            assert (await f["client"].post(target, headers=old_headers, json=body)).status_code == 403
        root = await f["client"].post(target, headers=global_headers, json=body)
        assert root.status_code == 200, root.text
        assert root.json()["uploader_actor_ref"] == global_actor
        child_body = {**body, "idempotency_key": "child-upload-" + str(owner), "subtask_id": child,
                      "subtask_update": {"status": "COMPLETED", "reported_result": "FAIL"}}
        child_upload = await f["client"].post(target, headers=global_headers, json=child_body)
        assert child_upload.status_code == 200, child_upload.text
        assert child_upload.json()["uploader_actor_ref"] == global_actor
        listing = await f["client"].get(archive + "/tasks", headers=global_headers, params={"project_id": project_id})
        assert task_id in {row["id"] for row in listing.json()["items"]}
        detail = await f["client"].get(archive + f"/tasks/{task_id}", headers=global_headers, params={"project_id": project_id})
        assert detail.status_code == 200, detail.text
        assert detail.json()["task"]["owner_uploader_actor_ref"] == owner
        assert detail.json()["subtasks"][0]["authorized_uploader_actor_ref"] == owner
        assert detail.json()["subtasks"][0]["reported_result"] == "FAIL"
        assert detail.json()["management_history"] == []
        read = await f["client"].get(archive + f"/tasks/{task_id}/subtasks/{child}/archive", headers=global_headers,
                                      params={"project_id": project_id})
        assert read.status_code == 200, read.text
        lookup = await f["client"].get(archive + "/submissions/by-key", headers=global_headers,
                                        params={"project_id": project_id, "idempotency_key": body["idempotency_key"]})
        assert lookup.json() == root.json()
        foreign_key = await f["client"].get(archive + "/submissions/by-key", headers=old_headers,
                                             params={"project_id": project_id, "idempotency_key": body["idempotency_key"]})
        assert foreign_key.status_code == 404
        published = await f["client"].post(archive + f"/tasks/{task_id}/publications", headers=f["operator"], json={
            "project_id": project_id, "idempotency_key": "publish-" + str(owner), "expected_task_version": 2,
            "root_archive_version": 2, "subtask_versions": [{"subtask_id": child, "archive_version": 2}],
            "asset_revision_ids": [], "summary": "Failure reported", "status": "COMPLETED", "reported_result": "FAIL"})
        assert published.status_code == 200, published.text
        assert published.json()["task"]["owner_uploader_actor_ref"] == owner

    revoke = await f["client"].post(url + "/revoke", headers=f["operator"], json={"idempotency_key": "revoke-all"})
    assert revoke.status_code == 200, revoke.text
    assert (await f["client"].get(archive + f"/tasks/{task_id}", headers=global_headers,
                                   params={"project_id": project_id})).status_code == 401
    listed_actors = await f["client"].get(archive + "/actors", headers=f["operator"], params={"project_id": project_id})
    assert listed_actors.status_code == 200
    assert global_actor not in {item["actor_ref"] for item in listed_actors.json()["items"]}


async def test_existing_binding_upgrade_preserves_receipts_and_revoked_grants(pairing):
    from hypertest.domain.cli_authorization import CliAuthorizationGlobalUpgrade

    f = pairing
    old, redeem_body = await bound(f)
    old_grant = old["grants"][0]
    old_request = old["request_id"]
    response = await f["client"].post(ROOT + "/grants/" + old_grant["grant_id"] + "/revoke",
        headers=f["operator"], json={"idempotency_key": "old-revoke"})
    assert response.status_code == 200
    async with AsyncSessionLocal() as db:
        db.add(CliAuthorizationGlobalUpgrade(request_id=UUID(old_request),
            actor_identity_id=UUID(old["approval"]["actor_identity_id"])))
        await db.commit()
    current = await f["client"].get(ROOT + "/requests/" + old_request, headers=f["headers"])
    assert current.json()["authorization"]["source"] == "migration"
    assert current.json()["authorization"]["expires_at"] is None
    assert current.json()["approval"] == old["approval"]
    assert next(g for g in current.json()["grants"] if g["grant_id"] == old_grant["grant_id"])["status"] == "REVOKED"
    replay = await f["client"].post(ROOT + "/requests/" + old_request + "/redeem", headers=f["headers"], json=redeem_body)
    assert replay.json() == old
    async with AsyncSessionLocal() as db:
        for project in f["projects"]:
            grant = await interactive.authenticate(db, f["secret"], "archive:write", project_id=UUID(project))
            assert grant.expires_at is None and grant.policy_version == "cli-archive-global-v1"
        await db.commit()
    revoked = await f["client"].post(ROOT + "/requests/" + old_request + "/revoke",
        headers=f["operator"], json={"idempotency_key": "global-revoke"})
    assert revoked.status_code == 200 and revoked.json()["status"] == "REVOKED"
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException):
            await interactive.authenticate(db, f["secret"], "archive:read", project_id=UUID(f["projects"][0]))


async def test_upgraded_cli_global_revocation_blocks_token_and_actor_listing(pairing):
    from hypertest.domain.cli_authorization import CliAuthorizationGlobalUpgrade

    f = pairing
    original, _ = await bound(f)
    request_id = UUID(original["request_id"])
    actor_id = UUID(original["approval"]["actor_identity_id"])
    actor_ref = original["approval"]["actor_ref"]
    async with AsyncSessionLocal() as db:
        db.add(CliAuthorizationGlobalUpgrade(request_id=request_id, actor_identity_id=actor_id))
        await db.commit()
    project_id = f["projects"][2]
    headers = {"Authorization": "Bearer " + f["secret"]}
    archive = "/api/v1/local-archive"
    task = await f["client"].post(archive + "/tasks", headers=f["operator"], json={
        "project_id": project_id, "idempotency_key": "upgraded-task", "title": "Upgrade task",
        "owner_uploader_actor_ref": None})
    assert task.status_code == 200, task.text
    task_id = task.json()["task"]["id"]
    uploaded = await f["client"].post(archive + f"/tasks/{task_id}/submissions", headers=headers, json={
        "project_id": project_id, "task_id": task_id, "idempotency_key": "upgraded-upload",
        "expected_archive_version": 1, "assets": [{"kind": "REPORT", "stable_key": "one", "title": "Result",
                                                   "markdown": "failure", "reported_result": "FAIL"}]})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["uploader_actor_ref"] == actor_ref
    listed = await f["client"].get(archive + "/actors", headers=f["operator"], params={"project_id": project_id})
    assert actor_ref in {item["actor_ref"] for item in listed.json()["items"]}
    revoked = await f["client"].post(ROOT + f"/requests/{request_id}/revoke", headers=f["operator"],
                                      json={"idempotency_key": "upgraded-revoke"})
    assert revoked.status_code == 200, revoked.text
    listed = await f["client"].get(archive + "/actors", headers=f["operator"], params={"project_id": project_id})
    assert actor_ref not in {item["actor_ref"] for item in listed.json()["items"]}
    assert (await f["client"].get(archive + f"/tasks/{task_id}", headers=headers,
                                  params={"project_id": project_id})).status_code == 401
    historical = await f["client"].get(ROOT + f"/requests/{request_id}", headers=f["headers"])
    assert historical.json()["approval"] == original["approval"]
    assert historical.json()["authorization"]["status"] == "REVOKED"
