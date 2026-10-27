"""One-command CLI enrollment with explicit Web consent and original-key recovery."""
import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text

from hypertest.application import interactive
from hypertest.application.services import ConflictError, NotFoundError
from hypertest.common.ids import uuid7
from hypertest.connector.security import token_hash
from hypertest.domain.cli_authorization import (
    CliArchiveUploader,
    CliAuthorizationGrant,
    CliAuthorizationReceipt,
    CliAuthorizationRequest,
)
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveIntegrationGrant,
)
from hypertest.domain.models import AuditEvent, OutboxEvent, Project


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def audit(db, row, action, operator=None):
    metadata = {"request_id": str(row.id), "client_instance_id": str(row.client_instance_id)}
    # The pre-consent request has no authorized Project. Its immutable receipt
    # and outbox record are the audit; do not invent a Project for AuditEvent.
    db.add(OutboxEvent(aggregate_type="CliAuthorizationRequest", aggregate_id=row.id,
                       event_type=action, payload=metadata))
    for project_id in (row.approval or {}).get("project_ids", []):
        db.add(AuditEvent(project_id=UUID(project_id), actor_type="USER",
            actor_ref=operator or "cli-pairing", action=action,
            entity_type="CliAuthorizationRequest", entity_id=row.id, event_metadata=metadata))


async def request_record(db, request_id, *, lock=False):
    query = select(CliAuthorizationRequest).where(CliAuthorizationRequest.id == request_id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query.execution_options(populate_existing=True))
    if row is None:
        raise NotFoundError("CLI_PAIRING_NOT_FOUND")
    return row


def check_proof(row, proof):
    if not proof or len(proof) < 32 or len(proof) > 512 or not hmac.compare_digest(token_hash(proof), row.verifier_challenge):
        raise HTTPException(403, "CLI_PAIRING_PROOF_REQUIRED")


async def grant_view(db, mapping, row=None):
    row = row or await request_record(db, mapping.request_id)
    grant = await db.get(InteractiveIntegrationGrant, mapping.grant_id, populate_existing=True)
    actor = await db.get(InteractiveActorIdentity, grant.actor_identity_id, populate_existing=True)
    client = await db.get(InteractiveClientRegistration, (grant.actor_identity_id, grant.client_instance_id), populate_existing=True)
    clock = await interactive.now(db)
    status = grant.status
    if status == "ACTIVE":
        if actor.status != "ACTIVE" or client.status != "ACTIVE":
            status = "REVOKED"
        elif not grant.not_before <= clock < grant.expires_at:
            status = "EXPIRED"
    return {"grant_id": str(grant.id), "request_id": str(row.id),
            "client_instance_id": str(row.client_instance_id), "client_name": row.client_name,
            "actor_identity_id": str(actor.id), "actor_ref": "interactive:" + str(actor.id),
            "actor_label": actor.actor_ref, "project_id": str(grant.project_id),
            "scopes": grant.scopes, "expires_at": grant.expires_at.isoformat(), "status": status,
            "credential_fingerprint": row.credential_hash[:16]}


async def view(db, row):
    clock = await interactive.now(db)
    status = row.status
    if status in {"PENDING", "APPROVED"} and row.expires_at <= clock:
        status = "EXPIRED"
    mappings = (await db.scalars(select(CliAuthorizationGrant).where(
        CliAuthorizationGrant.request_id == row.id).order_by(CliAuthorizationGrant.project_id))).all()
    return {"request_id": str(row.id), "status": status, "client_instance_id": str(row.client_instance_id),
            "client_name": row.client_name, "server_url": row.server_url, "short_code": row.short_code,
            "expires_at": row.expires_at.isoformat(), "created_at": row.created_at.isoformat(),
            "verification_url": row.server_url + "/cli-authorizations?request_id=" + str(row.id),
            "credential_fingerprint": row.credential_hash[:16],
            "requested_project_id": str(row.requested_project_id) if row.requested_project_id else None,
            "approval": row.approval, "grants": [await grant_view(db, item, row) for item in mappings]}


async def prior(db, row, operation, key, payload=None):
    receipt = await db.scalar(select(CliAuthorizationReceipt).where(
        CliAuthorizationReceipt.request_id == row.id,
        CliAuthorizationReceipt.operation == operation,
        CliAuthorizationReceipt.idempotency_key == key))
    if receipt and payload is not None and receipt.request_digest != digest(payload):
        raise ConflictError("CLI_AUTHORIZATION_KEY_CONFLICT")
    return receipt.response if receipt else None


async def save_receipt(db, row, operation, key, payload, response=None):
    response = dict(response if response is not None else await view(db, row))
    response.update(operation=operation, idempotency_key=key, request_digest=digest(payload))
    db.add(CliAuthorizationReceipt(request_id=row.id, operation=operation,
        idempotency_key=key, request_digest=digest(payload), response=response))
    await db.flush()
    return response


async def create(db, payload):
    data = payload.model_dump(mode="json")
    row = await db.scalar(select(CliAuthorizationRequest).where(
        CliAuthorizationRequest.client_instance_id == payload.client_instance_id,
        CliAuthorizationRequest.create_key == payload.idempotency_key).with_for_update())
    if row:
        if row.create_digest != digest(data):
            raise ConflictError("CLI_AUTHORIZATION_KEY_CONFLICT")
        return await prior(db, row, "CREATE", payload.idempotency_key, data)
    if await db.get(CliAuthorizationRequest, payload.request_id):
        raise ConflictError("CLI_PAIRING_ID_CONFLICT")
    if payload.project_id and not await db.get(Project, payload.project_id):
        raise NotFoundError("CLI_PROJECT_NOT_FOUND")
    clock = await interactive.now(db)
    code = secrets.token_hex(4).upper()
    row = CliAuthorizationRequest(id=payload.request_id, client_instance_id=payload.client_instance_id,
        client_name=payload.client_name, server_url=payload.server_url,
        create_key=payload.idempotency_key, create_digest=digest(data),
        credential_hash=payload.credential_hash, verifier_challenge=payload.verifier_challenge,
        requested_project_id=payload.project_id, short_code=code[:4] + "-" + code[4:],
        status="PENDING", created_at=clock, expires_at=clock + timedelta(minutes=10))
    db.add(row)
    await db.flush()
    audit(db, row, "cli.pairing.created")
    response = await save_receipt(db, row, "CREATE", payload.idempotency_key, data)
    await db.commit()
    return response


async def archive_uploader(db, operator):
    # Serializes the first approval across distinct pairing requests. The
    # mapping is permanent: a revoked actor cannot be bypassed by re-pairing.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                     {"key": "cli-archive-uploader:" + operator})
    mapping = await db.get(CliArchiveUploader, operator)
    if mapping is None:
        actor_id = uuid7()
        actor = InteractiveActorIdentity(id=actor_id,
            actor_ref="cli-archive:" + str(actor_id), registered_by=operator)
        db.add(actor)
        await db.flush()
        db.add(CliArchiveUploader(operator_ref=operator, actor_identity_id=actor_id))
        await db.flush()
    else:
        actor = await db.get(InteractiveActorIdentity, mapping.actor_identity_id,
                             with_for_update={"read": True}, populate_existing=True)
    if actor is None or actor.status != "ACTIVE":
        raise HTTPException(403, "CLI_UPLOADER_NOT_ACTIVE")
    return actor


async def approve(db, request_id, payload, operator):
    row = await request_record(db, request_id, lock=True)
    data = {**payload.model_dump(mode="json"), "operator": operator}
    if "actor_identity_id" not in payload.model_fields_set:
        data.pop("actor_identity_id")
    old = await prior(db, row, "APPROVE", payload.idempotency_key, data)
    if old:
        return old
    if "actor_identity_id" in payload.model_fields_set:
        raise HTTPException(422, "CLI_UPLOADER_SELECTION_RETIRED")
    clock = await interactive.now(db)
    if row.status != "PENDING" or row.expires_at <= clock:
        raise ConflictError("CLI_PAIRING_NOT_PENDING_OR_EXPIRED")
    if not hmac.compare_digest(payload.short_code, row.short_code):
        raise HTTPException(403, "CLI_PAIRING_CODE_MISMATCH")
    for project_id in payload.project_ids:
        if not await db.get(Project, project_id):
            raise NotFoundError("CLI_PROJECT_NOT_FOUND")
    actor = await archive_uploader(db, operator)
    existing = await db.get(InteractiveClientRegistration, (actor.id, row.client_instance_id))
    if existing and existing.status != "ACTIVE":
        raise HTTPException(403, "CLI_CLIENT_REVOKED")
    approval = {"idempotency_key": payload.idempotency_key, "actor_identity_id": str(actor.id),
        "actor_ref": "interactive:" + str(actor.id), "actor_label": actor.actor_ref,
        "project_ids": [str(item) for item in payload.project_ids], "scopes": payload.scopes,
        "expires_in_days": payload.expires_in_days,
        "expires_at": (clock + timedelta(days=payload.expires_in_days)).isoformat(),
        "credential_fingerprint": row.credential_hash[:16], "operator": operator}
    approval["approval_digest"] = digest({**approval, "request_id": str(row.id),
        "client_instance_id": str(row.client_instance_id), "credential_hash": row.credential_hash,
        "verifier_challenge": row.verifier_challenge})
    row.approval, row.status = approval, "APPROVED"
    audit(db, row, "cli.pairing.approved", operator)
    response = await save_receipt(db, row, "APPROVE", payload.idempotency_key, data)
    await db.commit()
    return response


async def redeem(db, request_id, payload, proof):
    from datetime import datetime

    row = await request_record(db, request_id, lock=True)
    check_proof(row, proof)
    data = payload.model_dump(mode="json")
    old = await prior(db, row, "REDEEM", payload.idempotency_key, data)
    if old:
        return old
    clock = await interactive.now(db)
    if row.status != "APPROVED" or row.expires_at <= clock:
        raise ConflictError("CLI_PAIRING_NOT_APPROVED_OR_EXPIRED")
    if not hmac.compare_digest(payload.approval_digest, row.approval["approval_digest"]):
        raise ConflictError("CLI_APPROVAL_CHANGED")
    actor_id = UUID(row.approval["actor_identity_id"])
    actor = await db.get(InteractiveActorIdentity, actor_id, with_for_update={"read": True})
    if actor.status != "ACTIVE":
        raise HTTPException(403, "CLI_UPLOADER_NOT_ACTIVE")
    client = await db.get(InteractiveClientRegistration, (actor_id, row.client_instance_id), with_for_update={"read": True})
    if client is None:
        client = InteractiveClientRegistration(actor_identity_id=actor_id,
            client_instance_id=row.client_instance_id, registered_by=row.approval["operator"])
        db.add(client)
        await db.flush()
    if client.status != "ACTIVE":
        raise HTTPException(403, "CLI_CLIENT_REVOKED")
    for project_id in row.approval["project_ids"]:
        # Existing project grants have globally unique token hashes. They remain
        # separate, independently revocable authorities; the CLI credential maps
        # to them through this explicit binding, never through an all-project grant.
        grant = InteractiveIntegrationGrant(actor_identity_id=actor_id,
            client_instance_id=row.client_instance_id, project_id=UUID(project_id),
            scopes=row.approval["scopes"], token_hash=token_hash(secrets.token_urlsafe(48)),
            registered_by=row.approval["operator"], policy_version="cli-archive-v1",
            not_before=clock, expires_at=datetime.fromisoformat(row.approval["expires_at"]))
        db.add(grant)
        await db.flush()
        db.add(CliAuthorizationGrant(request_id=row.id, project_id=grant.project_id, grant_id=grant.id))
        interactive.event(db, grant, "cli.integration.registered", "InteractiveIntegrationGrant", grant.id)
    row.status, row.bound_at = "BOUND", clock
    await db.flush()
    audit(db, row, "cli.pairing.bound")
    response = await save_receipt(db, row, "REDEEM", payload.idempotency_key, data)
    await db.commit()
    return response


async def authenticate_credential(db, credential_hash, scope, project_id):
    """Resolve only archive grants. Authentication/revocation reuses the old grant fence."""
    query = (select(InteractiveIntegrationGrant)
        .join(CliAuthorizationGrant, CliAuthorizationGrant.grant_id == InteractiveIntegrationGrant.id)
        .join(CliAuthorizationRequest, CliAuthorizationRequest.id == CliAuthorizationGrant.request_id)
        .where(CliAuthorizationRequest.credential_hash == credential_hash,
               CliAuthorizationRequest.status == "BOUND"))
    if project_id:
        query = query.where(CliAuthorizationGrant.project_id == project_id)
    else:
        query = query.where(InteractiveIntegrationGrant.status == "ACTIVE",
                            InteractiveIntegrationGrant.expires_at > await interactive.now(db))
    return await db.scalar(query.order_by(InteractiveIntegrationGrant.project_id)
                           .execution_options(populate_existing=True))


async def list_grants(db):
    mappings = (await db.scalars(select(CliAuthorizationGrant).order_by(CliAuthorizationGrant.request_id))).all()
    return {"items": [await grant_view(db, mapping) for mapping in mappings]}


async def revoke(db, grant_id, payload, operator):
    mapping = await db.scalar(select(CliAuthorizationGrant).where(CliAuthorizationGrant.grant_id == grant_id))
    if not mapping:
        raise NotFoundError("CLI_GRANT_NOT_FOUND")
    row = await request_record(db, mapping.request_id, lock=True)
    data = {"grant_id": str(grant_id), "operator": operator, **payload.model_dump(mode="json")}
    old = await prior(db, row, "REVOKE", payload.idempotency_key, data)
    if old:
        return old
    grant = await db.get(InteractiveIntegrationGrant, grant_id, with_for_update=True)
    if grant.status == "ACTIVE":
        grant.status, grant.revoked_at = "REVOKED", await interactive.now(db)
        grant.row_version += 1
        interactive.event(db, grant, "cli.integration.revoked", "InteractiveIntegrationGrant", grant.id,
                          extra={"operator": operator})
    await db.flush()
    response = await save_receipt(db, row, "REVOKE", payload.idempotency_key, data,
                                  await grant_view(db, mapping, row))
    await db.commit()
    return response
