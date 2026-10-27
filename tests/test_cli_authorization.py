"""Pairing boundaries and recovery using synthetic data in the dedicated test DB."""
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from hypertest.api.schemas import ProjectCreate
from hypertest.application import interactive
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.connector.security import token_hash
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cli_authorization import CliAuthorizationGrant
from hypertest.domain.interactive import InteractiveActorIdentity
from hypertest.main import app

ROOT = "/api/v1/cli-authorizations"


@pytest.fixture
async def pairing(monkeypatch):
    monkeypatch.setattr(get_settings(), "connector_operator_key", "cli-operator-fixture")
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
               "projects": projects, "actor_id": actor_id,
               "operator": {"X-Hypertest-Operator-Key": "cli-operator-fixture"},
               "headers": {"X-Hypertest-Pairing-Proof": proof}}


async def created(f):
    response = await f["client"].post(ROOT + "/requests", json=f["body"])
    assert response.status_code == 201, response.text
    return response.json()


def approval(f, pending):
    return {"idempotency_key": "approve", "actor_identity_id": f["actor_id"],
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
    body = {"idempotency_key": "redeem", "approval_digest": accepted["approval"]["approval_digest"]}
    response = await f["client"].post(ROOT + "/requests/" + pending["request_id"] + "/redeem",
                                      json=body, headers=f["headers"])
    assert response.status_code == 200, response.text
    return response.json(), body


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
        row = await db.get(InteractiveActorIdentity, UUID(f["actor_id"]))
        clock = await interactive.now(db)
        row.status = "REVOKED"
        row.row_version += 1
        row.revoked_at = clock
        await db.commit()
    response = await f["client"].post(ROOT + "/requests/" + accepted["request_id"] + "/redeem",
        headers=f["headers"], json={"idempotency_key": "redeem", "approval_digest": accepted["approval"]["approval_digest"]})
    assert response.status_code == 403


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
