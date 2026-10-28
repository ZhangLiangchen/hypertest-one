"""ADR-022 optional experience Gateway, isolated from task acceptance and results.

Every external write has a committed SENT intent before the one permitted call.
Only original-key reads reconcile SENT/UNKNOWN. Nothing redispatches the outbox.
"""
import asyncio
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select

from hypertest.api.memory_schemas import PROFILE, MemoryQuery
from hypertest.application import cloud_tasks, interactive
from hypertest.application.services import canonical_json_sha256
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.private_file import read_private_file
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.connector.security import token_hash
from hypertest.domain.cloud_tasks import CloudAssetRevision, CloudOperationReceipt
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveIntegrationGrant,
)
from hypertest.domain.local_archive import (
    LocalArchiveAssetRevision,
    LocalArchiveSnapshot,
    LocalArchiveSubmission,
    LocalArchiveTask,
)
from hypertest.domain.memory import (
    MemoryEntry,
    MemoryOperation,
    MemoryProjectMapping,
    MemoryRevision,
)
from hypertest.domain.models import AuditEvent, OutboxEvent

SCOPES = {"CONFIGURE": "memory:publish", "CREATE_CANDIDATE": "memory:propose",
          "PUBLISH": "memory:publish", "REVISE": "memory:publish", "RETRACT": "memory:publish"}
NOTICE = "UNTRUSTED_HISTORICAL_CONTEXT_NOT_EXECUTION_EVIDENCE_OR_AUTHORIZATION"


@dataclass(frozen=True)
class ActorContext:
    actor_ref: str
    operator: bool = False
    grant_id: UUID | None = None
    worker: cloud_tasks.WorkerIdentity | None = None


async def authenticate(db, token, scope, project_id, *, worker=None):
    grant = await interactive.authenticate(db, token, scope, project_id=project_id)
    return ActorContext("interactive:" + str(grant.actor_identity_id), grant_id=grant.id, worker=worker)


async def authorize(db, context, scope, project_id, *, lock=False):
    if context.operator:
        return
    grant = await db.get(InteractiveIntegrationGrant, context.grant_id, populate_existing=True)
    if lock and grant:
        for model, predicates in (
            (InteractiveActorIdentity, [InteractiveActorIdentity.id == grant.actor_identity_id]),
            (InteractiveClientRegistration, [InteractiveClientRegistration.actor_identity_id == grant.actor_identity_id,
                InteractiveClientRegistration.client_instance_id == grant.client_instance_id]),
            (InteractiveIntegrationGrant, [InteractiveIntegrationGrant.id == grant.id]),
        ):
            await db.scalar(select(model).where(*predicates).with_for_update(read=True)
                            .execution_options(populate_existing=True))
    grant = await interactive.authenticate_integration_record(db, grant, scope, project_id=project_id)
    if context.actor_ref != "interactive:" + str(grant.actor_identity_id):
        raise HTTPException(403, "Memory actor mismatch")


def adapter():
    # Only the API Gateway process has the PowerContext secret file. Local and
    # Cloud agents use the authenticated HTTPS surface and cannot load this key.
    from hypertest.memory.powercontext import PowerContextAdapter
    return PowerContextAdapter()


def enabled():
    if not getattr(get_settings(), "memory_enabled", False):
        raise HTTPException(503, "Memory Gateway is disabled; task synchronization remains available")


async def reject_secrets(db, project_id, values, context):
    """Known credentials never enter candidate storage or explicit upstream text.

    Private files are read only inside the Gateway process. Failure closes only
    this optional memory operation and never changes task/report transactions.
    """
    try:
        await cloud_tasks._reject_secrets(db, project_id, values)
        settings = get_settings()
        upstream_secret = read_private_file(settings.memory_powercontext_token_file, max_bytes=8192).strip()
        if not upstream_secret or any(byte in upstream_secret for byte in (b" ", b"\t", b"\r", b"\n")):
            raise HTTPException(503, "Memory secret scanning is unavailable")
    except CloudBlocked:
        raise HTTPException(503, "Memory secret scanning is unavailable") from None
    secrets = [upstream_secret, settings.connector_operator_key.encode()]
    if context.worker:
        secrets += [context.worker.lease_token.encode(), context.worker.work_token.encode()]
    if any(secret and cloud_tasks._contains_secret(values, secret) for secret in secrets):
        raise HTTPException(422, "Credential material is not accepted experience input")
    # Integration bearer secrets are not recoverable from the database. Match
    # bounded opaque token candidates against their existing one-way hashes so
    # an Operator cannot accidentally publish another registered client's key.
    candidates = re.findall(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{64}(?![A-Za-z0-9_-])",
                            json.dumps(values, ensure_ascii=False))
    fingerprints = {token_hash(value) for value in candidates}
    if fingerprints and await db.scalar(select(InteractiveIntegrationGrant.id).where(
            InteractiveIntegrationGrant.token_hash.in_(fingerprints)).limit(1)):
        raise HTTPException(422, "Credential material is not accepted experience input")


async def mapping(db, project_id, *, ready=False, lock=False):
    query = select(MemoryProjectMapping).where(MemoryProjectMapping.project_id == project_id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query.execution_options(populate_existing=True))
    if ready and (not row or not row.enabled or row.status != "READY" or not row.scope_id):
        raise HTTPException(503, "Project memory is disabled or awaiting reconciliation")
    return row


def configuration_view(row, project_id):
    return {"project_id": str(project_id), "enabled": row.enabled if row else False,
        "version": row.version if row else 0, "scope_id": row.scope_id if row else None,
        "status": row.status if row else "UNCONFIGURED"}


async def verify_source(db, project_id, source, context, *, lock=False):
    """Resolve only fixed, accepted materials. Never trust caller provenance labels."""
    source = source.model_dump(mode="json") if hasattr(source, "model_dump") else dict(source)
    task_id = UUID(source["task_id"])
    if source["mode"] == "LOCAL_ARCHIVE":
        # Archive permissions and Memory grants are independent. Until an
        # explicit cross-scope authorization contract exists, only the human
        # Operator may select an accepted archive as a memory source.
        if not context.operator or context.worker:
            raise HTTPException(403, "Local archive memory source requires an authorized Operator")
        query = select(LocalArchiveTask).where(LocalArchiveTask.id == task_id)
        if lock:
            query = query.with_for_update(read=True)
        task = await db.scalar(query.execution_options(populate_existing=True))
        if not task or task.project_id != project_id:
            raise HTTPException(404, "Local archive memory source not found in Project")
        submission = await db.get(LocalArchiveSubmission, UUID(source["submission_id"]))
        asset = await db.get(LocalArchiveAssetRevision, UUID(source["asset_revision_id"]))
        if (not submission or submission.project_id != project_id or submission.task_id != task_id
                or submission.accepted_version != source["archive_version"] or not asset
                or asset.project_id != project_id or asset.task_id != task_id
                or asset.target_kind != submission.target_kind or asset.subtask_id != submission.subtask_id
                or asset.kind != "REPORT"):
            raise HTTPException(409, "Local archive source requires a fixed accepted report in the same target")
        snapshot = await db.get(LocalArchiveSnapshot, submission.snapshot_id)
        if (not snapshot or snapshot.project_id != project_id or snapshot.task_id != task_id
                or snapshot.target_kind != submission.target_kind or snapshot.subtask_id != submission.subtask_id
                or snapshot.archive_version != submission.accepted_version):
            raise HTTPException(409, "Local archive accepted snapshot mismatch")
        items = [item for item in snapshot.document.get("assets", []) if item.get("id") == str(asset.id)]
        if len(items) != 1 or any(items[0].get(key) != value for key, value in asset.content.items()):
            raise HTTPException(409, "Local archive report is absent from the accepted snapshot")
        return {**source, "target_kind": submission.target_kind,
            "subtask_id": str(submission.subtask_id) if submission.subtask_id else None,
            "uploader_actor_ref": asset.uploader_actor_ref, "report_key": asset.stable_key,
            "report_revision": asset.revision, "source_digest": canonical_json_sha256(asset.content)}
    version = source["task_version"]
    if source["mode"] == "LOCAL":
        raise HTTPException(410, "Legacy SessionTask memory source has been retired")
    task = await cloud_tasks._task(db, task_id, project_id, lock=lock)
    attempt_id = UUID(source["attempt_id"])
    if context.worker:
        attempt = await cloud_tasks._attempt(db, task, attempt_id)
        await cloud_tasks.worker_authority(db, task, attempt, context.worker)
    elif not context.operator:
        raise HTTPException(403, "Cloud memory submission requires the current fenced Worker broker")
    receipt = await db.scalar(select(CloudOperationReceipt).where(CloudOperationReceipt.task_id == task_id,
        CloudOperationReceipt.accepted_version == version))
    asset = await db.get(CloudAssetRevision, UUID(source["asset_revision_id"]))
    if (not receipt or not asset or asset.task_id != task_id or asset.attempt_id != attempt_id
            or asset.task_version > version):
        raise HTTPException(409, "Cloud source requires an accepted fixed task version and same-Attempt asset")
    # The fixed snapshot must actually contain the supplied Attempt and asset.
    snapshot = receipt.task_snapshot or {}
    if (not any(str(row.get("id")) == str(attempt_id) for row in snapshot.get("attempts", []))
            or not any(str(row.get("id")) == str(asset.id) for row in snapshot.get("assets", []))):
        raise HTTPException(409, "Cloud source refs are absent from the fixed accepted version")
    return {**source, "asset_kind": asset.kind, "asset_key": asset.key,
        "asset_revision": asset.revision, "source_digest": asset.content_digest}


async def verify_query_context(db, project_id, supplied, context, *, lock=False):
    if context.worker is None:
        raise HTTPException(403, "Cloud query context requires the current fenced Worker broker")
    task = await cloud_tasks._task(db, supplied.task_id, project_id, lock=lock)
    attempt = await cloud_tasks._attempt(db, task, supplied.attempt_id)
    await cloud_tasks.worker_authority(db, task, attempt, context.worker)
    receipt = await db.scalar(select(CloudOperationReceipt).where(CloudOperationReceipt.task_id == task.id,
        CloudOperationReceipt.accepted_version == supplied.task_version))
    snapshot = receipt.task_snapshot if receipt else None
    if not snapshot or not any(str(row.get("id")) == str(attempt.id) for row in snapshot.get("attempts", [])):
        raise HTTPException(409, "Cloud memory query requires the original accepted Task/Attempt context")


async def _entry(db, project_id, entry_id, *, lock=False):
    query = select(MemoryEntry).where(MemoryEntry.project_id == project_id, MemoryEntry.id == entry_id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query.execution_options(populate_existing=True))
    if not row:
        raise HTTPException(404, "Memory entry not found in Project")
    return row


async def _revision(db, entry, version=None):
    row = await db.scalar(select(MemoryRevision).where(MemoryRevision.entry_id == entry.id,
        MemoryRevision.version == (entry.version if version is None else version)))
    if row is None:
        raise HTTPException(404, "Memory revision not found")
    return row


def _can_private(entry, context):
    return context.operator or entry.owner_actor_ref == context.actor_ref


def revision_view(entry, revision, context):
    private = _can_private(entry, context)
    # An old PUBLISHED revision does not become current merely because its
    # upstream index is stale. Historical reads explicitly label its disposition.
    disposition = revision.status
    if revision.version != entry.version:
        disposition = "SUPERSEDED"
    elif entry.status == "PENDING":
        disposition = "PENDING"
    elif revision.expires_at is not None and revision.expires_at <= datetime.now(UTC):
        disposition = "EXPIRED"
    source = entry.source if private else {"mode": entry.source["mode"],
        "provenance_id": canonical_json_sha256({"entry_id": str(entry.id), "source": entry.source})}
    return {"profile": PROFILE, "id": str(entry.id), "entry_id": str(entry.id),
        "project_id": str(entry.project_id), "version": revision.version,
        "status": disposition, "revision_status": revision.status, "current_version": entry.version,
        "title": revision.title, "content": revision.content, "applicability": revision.applicability,
        "observed_at": revision.observed_at.isoformat() if revision.observed_at else None,
        "expires_at": revision.expires_at.isoformat() if revision.expires_at else None,
        "publication_note": revision.publication_note, "content_digest": revision.content_digest,
        "source": source, "created_by": entry.owner_actor_ref if private else None,
        "confirmed_by": revision.confirmed_by if private else None,
        "created_at": revision.created_at.isoformat(), "notice": NOTICE}


async def read_entry(db, project_id, entry_id, version, context):
    await authorize(db, context, "memory:read", project_id)
    await cloud_tasks.project(db, project_id)
    entry = await _entry(db, project_id, entry_id)
    revision = await _revision(db, entry, version)
    if not _can_private(entry, context) and revision.status != "PUBLISHED":
        raise HTTPException(404, "Memory revision not available")
    return revision_view(entry, revision, context)


async def configuration(db, project_id, context, *, version=None):
    await authorize(db, context, "memory:read", project_id)
    await cloud_tasks.project(db, project_id)
    row = await mapping(db, project_id)
    if version is None:
        return configuration_view(row, project_id)
    records = await db.scalars(select(MemoryOperation).where(MemoryOperation.project_id == project_id,
        MemoryOperation.operation == "CONFIGURE", MemoryOperation.target_version == version,
        MemoryOperation.state == "ACCEPTED"))
    for record in records:
        return record.response["configuration"]
    raise HTTPException(404, "Accepted memory configuration version not found")


async def overview(db, project_id, context, *, offset=0, limit=50, status=None):
    await authorize(db, context, "memory:read", project_id)
    await cloud_tasks.project(db, project_id)
    where = [MemoryEntry.project_id == project_id]
    if status:
        where.append(MemoryEntry.status.in_(["CANDIDATE", "PENDING"] if status == "CANDIDATE" else [status]))
    if not context.operator:
        where.append(or_(MemoryEntry.owner_actor_ref == context.actor_ref, MemoryEntry.status == "PUBLISHED"))
    entries = list(await db.scalars(select(MemoryEntry).where(*where).order_by(MemoryEntry.updated_at.desc(),
        MemoryEntry.id).offset(offset).limit(limit + 1)))
    views = [revision_view(row, await _revision(db, row), context) for row in entries[:limit]]
    query = select(MemoryOperation).where(MemoryOperation.project_id == project_id,
        MemoryOperation.state.in_(["SENT", "UNKNOWN"]))
    if not context.operator:
        query = query.where(MemoryOperation.actor_ref == context.actor_ref)
    operations = list(await db.scalars(query.order_by(MemoryOperation.created_at).limit(100)))
    return {"profile": PROFILE, "enabled": bool(getattr(get_settings(), "memory_enabled", False)),
        "configuration": configuration_view(await mapping(db, project_id), project_id),
        "entries": views, "operations": [row.response for row in operations],
        "offset": offset, "limit": limit, "has_more": len(entries) > limit, "notice": NOTICE}


def _event(db, operation, action):
    metadata = {"operation_id": str(operation.id), "operation_key": operation.operation_key,
        "operation": operation.operation, "state": operation.state,
        "entry_id": str(operation.entry_id) if operation.entry_id else None,
        "target_version": operation.target_version}
    db.add(AuditEvent(project_id=operation.project_id, actor_type="OPERATOR" if operation.actor_ref.startswith("operator:") else "USER",
        actor_ref=operation.actor_ref, action="memory." + action, entity_type="MemoryOperation",
        entity_id=operation.id, event_metadata=metadata))
    db.add(OutboxEvent(aggregate_type="MemoryOperation", aggregate_id=operation.id,
        event_type="memory." + action, payload=metadata))


def _response(operation):
    return {"profile": PROFILE, "project_id": str(operation.project_id), "operation_id": str(operation.id),
        "operation_key": operation.operation_key, "operation": operation.operation,
        "status": operation.state, "expected_version": operation.expected_version,
        "request_digest": operation.input_digest,
        "entry_id": str(operation.entry_id) if operation.entry_id else None,
        "accepted_version": operation.target_version if operation.state == "ACCEPTED" else None}


def _new_revision(entry, request, actor, *, status, upstream_ref=None):
    data = {key: request.get(key) for key in ("title", "content", "applicability", "publication_note")}
    data["applicability"] = data["applicability"] or ""
    data["publication_note"] = data["publication_note"] or ""
    for key in ("observed_at", "expires_at"):
        data[key] = datetime.fromisoformat(request[key]) if request.get(key) else None
    return MemoryRevision(id=uuid7(), entry_id=entry.id, version=entry.version, status=status,
        **data, confirmed_by=actor if status != "CANDIDATE" else None,
        content_digest=canonical_json_sha256({key: value for key, value in data.items()
            if key not in {"observed_at", "expires_at"}}), upstream_ref=upstream_ref,
        created_at=datetime.now(UTC))


def upstream_content(operation):
    """The server-only marker is a locator, not upstream idempotency or proof."""
    request = operation.request
    text = (f"# {request['title']}\n\n{request['content']}\n\n"
        f"Applicability: {request.get('applicability', '')}\n\n"
        f"Historical context; not execution evidence or authorization.\n"
        f"HyperTest operation: {operation.marker}")
    return unicodedata.normalize("NFC", text).strip()


async def operate(db, payload, context, authorization_check=None):
    enabled()
    scope = SCOPES[payload.operation]
    await authorize(db, context, scope, payload.project_id, lock=True)
    if payload.operation != "CREATE_CANDIDATE" and not context.operator:
        raise HTTPException(403, "Memory publication and configuration require an authorized human Operator")
    await cloud_tasks.project(db, payload.project_id, lock=True)
    await cloud_tasks._lock(db, "memory-key:" + str(payload.project_id) + ":" + payload.operation_key)
    old = await db.scalar(select(MemoryOperation).where(MemoryOperation.project_id == payload.project_id,
        MemoryOperation.operation_key == payload.operation_key))
    original = payload.model_dump(mode="json")
    digest = canonical_json_sha256(original)
    if old:
        if old.actor_ref != context.actor_ref or old.input_digest != digest:
            raise HTTPException(409, "Memory operation key already belongs to a different frozen intent")
        # An accepted duplicate is a local receipt read. In-flight duplicates do
        # not cause another network call, even if the first request lost its ACK.
        return old.response
    await cloud_tasks._lock(db, "memory-project:" + str(payload.project_id))
    if payload.operation in {"CREATE_CANDIDATE", "PUBLISH", "REVISE"}:
        await reject_secrets(db, payload.project_id, original, context)
    operation = MemoryOperation(id=uuid7(), project_id=payload.project_id,
        operation_key=payload.operation_key, operation=payload.operation, actor_ref=context.actor_ref,
        grant_id=context.grant_id, expected_version=payload.expected_version, input_digest=digest,
        request=original, target_version=payload.expected_version + 1, state="SENT", marker="",
        response={}, created_at=datetime.now(UTC))
    operation.marker = "htmemory" + operation.id.hex
    if payload.operation == "CONFIGURE":
        mapped = await mapping(db, payload.project_id, lock=True)
        current_version = mapped.version if mapped else 0
        if payload.expected_version != current_version:
            raise HTTPException(409, "Memory configuration version conflict")
        if not mapped:
            mapped = MemoryProjectMapping(id=uuid7(), project_id=payload.project_id,
                namespace="hypertest-project-" + str(payload.project_id), enabled=payload.enabled,
                version=1, status="PENDING" if payload.enabled else "READY")
            db.add(mapped)
        else:
            if payload.enabled and mapped.status in {"PENDING", "UNKNOWN"}:
                raise HTTPException(409, "Original scope creation is unresolved; query its original operation key")
            mapped.version += 1
            mapped.enabled = payload.enabled
        if not payload.enabled or mapped.scope_id:
            operation.state = "ACCEPTED"
            operation.response = {**_response(operation), "configuration": configuration_view(mapped, payload.project_id)}
        else:
            mapped.status = "PENDING"
    elif payload.operation == "CREATE_CANDIDATE":
        if payload.expected_version != 0:
            raise HTTPException(409, "A new memory candidate requires expected_version 0")
        await mapping(db, payload.project_id, ready=True)
        source = await verify_source(db, payload.project_id, payload.source, context, lock=True)
        entry = MemoryEntry(id=uuid7(), project_id=payload.project_id, owner_actor_ref=context.actor_ref,
            source=source, version=1, status="CANDIDATE", created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        db.add(entry)
        await db.flush()
        operation.entry_id = entry.id
        operation.state = "ACCEPTED"
        db.add(_new_revision(entry, original, context.actor_ref, status="CANDIDATE"))
    else:
        entry = await _entry(db, payload.project_id, payload.entry_id, lock=True)
        if entry.version != payload.expected_version:
            raise HTTPException(409, "Memory entry version conflict")
        previous = await _revision(db, entry)
        if entry.pending_operation_id is not None and payload.operation != "RETRACT":
            raise HTTPException(409, "Memory publication is unresolved; query the original operation key")
        operation.entry_id = entry.id
        if payload.operation == "RETRACT":
            # Immediate local exclusion; stale upstream artifacts never qualify
            # again. Retraction never deletes task history, prior content or keys.
            entry.version += 1
            entry.status = "RETRACTED"
            entry.pending_operation_id = None
            preserved = {"title": previous.title, "content": previous.content,
                "applicability": previous.applicability, "observed_at": previous.observed_at.isoformat() if previous.observed_at else None,
                "expires_at": previous.expires_at.isoformat() if previous.expires_at else None,
                "publication_note": payload.publication_note}
            db.add(_new_revision(entry, preserved, context.actor_ref, status="RETRACTED"))
            operation.state = "ACCEPTED"
        else:
            await mapping(db, payload.project_id, ready=True)
            if (payload.operation == "PUBLISH" and entry.status != "CANDIDATE") or (
                    payload.operation == "REVISE" and entry.status != "PUBLISHED"):
                raise HTTPException(409, "Memory publication precondition failed")
            # A human confirms the exact redacted body and applicability. Sources
            # are checked again; this does not upgrade reported testing results.
            await verify_source(db, payload.project_id, entry.source, context)
            if len(upstream_content(operation).encode("utf-8")) > 8192:
                raise HTTPException(422, "Approved publication including title and applicability exceeds PowerContext 8192 UTF-8 bytes")
            entry.status = "PENDING"
            entry.pending_operation_id = operation.id
        entry.updated_at = datetime.now(UTC)
    db.add(operation)
    if not operation.response:
        operation.response = _response(operation)
    _event(db, operation, "accepted" if operation.state == "ACCEPTED" else "sent")
    if authorization_check:
        await authorization_check()
    await authorize(db, context, scope, payload.project_id)
    if context.worker and payload.operation == "CREATE_CANDIDATE":
        await verify_source(db, payload.project_id, payload.source, context, lock=True)
    await db.commit()
    if operation.state == "ACCEPTED":
        return operation.response
    # The committed outbox is deliberately not retry-dispatched. This call is
    # the sole permitted upstream POST for this frozen operation.
    return await _dispatch_once(db, operation.id, context)


async def _unknown(db, operation_id, error_code="UPSTREAM_OUTCOME_UNKNOWN"):
    operation = await db.scalar(select(MemoryOperation).where(MemoryOperation.id == operation_id)
        .with_for_update().execution_options(populate_existing=True))
    if operation.state == "ACCEPTED":
        return operation.response
    operation.state = "UNKNOWN"
    operation.response = {**_response(operation), "reason": error_code,
        "recovery": "QUERY_ORIGINAL_KEY_ONLY_NO_REPOST"}
    if operation.operation == "CONFIGURE":
        row = await mapping(db, operation.project_id, lock=True)
        row.status = "UNKNOWN"
    _event(db, operation, "unknown")
    await db.commit()
    return operation.response


async def _dispatch_once(db, operation_id, context):
    try:
        async with asyncio.timeout(getattr(get_settings(), "memory_timeout_seconds", 5.0)):
            return await _dispatch_bounded(db, operation_id, context)
    except Exception:
        await db.rollback()
        return await _unknown(db, operation_id)


async def _dispatch_bounded(db, operation_id, context):
    operation = await db.get(MemoryOperation, operation_id)
    mapped = await mapping(db, operation.project_id)
    try:
        upstream = adapter()
        if operation.operation == "CONFIGURE":
            scope_id = await upstream.create_scope(mapped.namespace, operation.marker)
            return await _accept_scope(db, operation_id, scope_id, context)
        await reject_secrets(db, operation.project_id, operation.request, context)
        result = await upstream.remember(mapped.scope_id, upstream_content(operation),
            {"operation_id": str(operation.id), "entry_id": str(operation.entry_id)})
        # Persist a returned ID before the fixed revision read, so a read timeout
        # retains the exact upstream identity rather than searching fresh data.
        operation.upstream_ref = {key: result[key] for key in ("artifact_id", "revision", "content_digest") if key in result}
        await db.commit()
        material = await upstream.get(mapped.scope_id, result["artifact_id"], result["revision"])
        return await _accept_publication(db, operation_id, material, context)
    except Exception:
        # Neither raw upstream failures nor secret-bearing HTTP objects enter
        # logs, responses, audit or the durable ledger.
        await db.rollback()
        return await _unknown(db, operation_id)


async def _accept_scope(db, operation_id, scope_id, context):
    operation = await db.scalar(select(MemoryOperation).where(MemoryOperation.id == operation_id)
        .with_for_update().execution_options(populate_existing=True))
    if operation.state == "ACCEPTED":
        return operation.response
    await authorize(db, context, "memory:publish", operation.project_id, lock=True)
    await cloud_tasks.project(db, operation.project_id, lock=True)
    mapped = await mapping(db, operation.project_id, lock=True)
    mapped.scope_id = scope_id
    mapped.status = "READY"
    operation.upstream_ref = {"scope_id": scope_id}
    operation.state = "ACCEPTED"
    frozen = {"project_id": str(operation.project_id), "enabled": operation.request["enabled"],
        "version": operation.target_version, "scope_id": scope_id, "status": "READY"}
    operation.response = {**_response(operation), "configuration": frozen}
    _event(db, operation, "accepted")
    await db.commit()
    return operation.response


async def _accept_publication(db, operation_id, material, context):
    operation = await db.scalar(select(MemoryOperation).where(MemoryOperation.id == operation_id)
        .with_for_update().execution_options(populate_existing=True))
    if operation.state == "ACCEPTED":
        return operation.response
    await reject_secrets(db, operation.project_id, operation.request, context)
    expected = upstream_content(operation)
    if material.get("content") != expected or not material.get("artifact_id") or not material.get("revision"):
        raise HTTPException(409, "PowerContext fixed readback does not match frozen approved content")
    if operation.upstream_ref and any(material.get(key) != operation.upstream_ref.get(key)
            for key in ("artifact_id", "revision")):
        raise HTTPException(409, "PowerContext fixed readback identity mismatch")
    await authorize(db, context, "memory:publish", operation.project_id, lock=True)
    await cloud_tasks.project(db, operation.project_id, lock=True)
    entry = await _entry(db, operation.project_id, operation.entry_id, lock=True)
    ref = {key: material[key] for key in ("artifact_id", "revision", "content_digest") if key in material}
    operation.upstream_ref = ref
    # A concurrent retract/disable cannot be undone by an earlier HTTP response.
    mapped = await mapping(db, operation.project_id)
    if (entry.pending_operation_id != operation.id or entry.version != operation.expected_version
            or not mapped.enabled or mapped.status != "READY"
            or not getattr(get_settings(), "memory_enabled", False)):
        operation.state = "UNKNOWN"
        operation.response = {**_response(operation), "reason": "PUBLICATION_SUPERSEDED_OR_DISABLED",
            "recovery": "UPSTREAM_MATERIAL_RETAINED_NOT_PROJECT_VISIBLE"}
        _event(db, operation, "unknown")
        await db.commit()
        return operation.response
    entry.version = operation.target_version
    entry.status = "PUBLISHED"
    entry.pending_operation_id = None
    entry.updated_at = datetime.now(UTC)
    db.add(_new_revision(entry, operation.request, operation.actor_ref, status="PUBLISHED", upstream_ref=ref))
    operation.state = "ACCEPTED"
    operation.response = _response(operation)
    _event(db, operation, "accepted")
    await db.commit()
    return operation.response


async def read_receipt(db, project_id, key, context):
    # Current independent memory permission and original submitter protect the
    # intent. Project tombstones do not destroy original-key reconciliation.
    await authorize(db, context, None, project_id)
    if not context.operator:
        grant = await db.get(InteractiveIntegrationGrant, context.grant_id)
        if not set(grant.scopes) & {"memory:read", "memory:propose", "memory:publish"}:
            raise HTTPException(403, "Independent memory permission required")
    await cloud_tasks.project(db, project_id, include_deleted=True)
    operation = await db.scalar(select(MemoryOperation).where(MemoryOperation.project_id == project_id,
        MemoryOperation.operation_key == key))
    if operation is None:
        raise HTTPException(404, "Memory operation not found; NOT_FOUND does not authorize replay")
    if not context.operator and operation.actor_ref != context.actor_ref:
        raise HTTPException(403, "Memory operation belongs to another submitter")
    if (operation.state == "ACCEPTED" or not context.operator
            or operation.response.get("reason") == "PUBLICATION_SUPERSEDED_OR_DISABLED"):
        return operation.response
    # Read-only upstream reconciliation. Missing/ambiguous results never cause a
    # mutation POST, key replacement, activation or pretend confirmation.
    operation_id = operation.id
    try:
        async with asyncio.timeout(getattr(get_settings(), "memory_timeout_seconds", 5.0)):
            return await _reconcile_bounded(db, operation, context)
    except Exception:
        await db.rollback()
    fresh = await db.get(MemoryOperation, operation_id, populate_existing=True)
    return fresh.response


async def _reconcile_bounded(db, operation, context):
    operation_id = operation.id
    project_id = operation.project_id
    try:
        upstream = adapter()
        mapped = await mapping(db, project_id)
        if operation.operation == "CONFIGURE":
            scope_id = await upstream.find_scope(mapped.namespace)
            if scope_id:
                return await _accept_scope(db, operation.id, scope_id, context)
        elif operation.operation in {"PUBLISH", "REVISE"} and mapped and mapped.scope_id:
            if operation.upstream_ref:
                ref = operation.upstream_ref
                result = await upstream.get(mapped.scope_id, ref["artifact_id"], ref["revision"])
                return await _accept_publication(db, operation.id, result, context)
            matches = await upstream.find_operation(mapped.scope_id, operation.marker)
            exact = [row for row in matches if row.get("content") == upstream_content(operation)]
            if len(exact) == 1:
                return await _accept_publication(db, operation.id, exact[0], context)
    except Exception:
        await db.rollback()
    fresh = await db.get(MemoryOperation, operation_id, populate_existing=True)
    return fresh.response


async def query(db, payload: MemoryQuery, context):
    await authorize(db, context, "memory:read", payload.project_id, lock=True)
    await cloud_tasks.project(db, payload.project_id)
    if context.worker and payload.source is None and payload.context is None:
        raise HTTPException(403, "Cloud memory query requires fixed source context")
    if payload.context is not None:
        if payload.source is not None:
            raise HTTPException(422, "Choose a fixed Cloud query context or a full source reference")
        await verify_query_context(db, payload.project_id, payload.context, context, lock=True)
    if payload.source is not None:
        await verify_source(db, payload.project_id, payload.source, context, lock=bool(context.worker))
    enabled()
    mapped = await mapping(db, payload.project_id, ready=True)
    await reject_secrets(db, payload.project_id, {"query": payload.query}, context)
    scope_id = mapped.scope_id
    await db.commit()  # Release authority/source locks before any external I/O.
    try:
        async with asyncio.timeout(getattr(get_settings(), "memory_timeout_seconds", 5.0)):
            hits = await adapter().search(scope_id, payload.query, min(payload.limit * 4, 50))
    except Exception:
        return {"profile": PROFILE, "project_id": str(payload.project_id), "results": [],
            "degraded": True, "reason": "MEMORY_SEARCH_UNAVAILABLE", "notice": NOTICE}
    # Recheck mutable configuration/auth after network I/O. A stale index result
    # is only a locator into the *current* published PostgreSQL visibility set.
    await authorize(db, context, "memory:read", payload.project_id)
    await cloud_tasks.project(db, payload.project_id)
    await mapping(db, payload.project_id, ready=True)
    if payload.source is not None:
        await verify_source(db, payload.project_id, payload.source, context, lock=bool(context.worker))
    if payload.context is not None:
        await verify_query_context(db, payload.project_id, payload.context, context, lock=True)
    rows = list(await db.scalars(select(MemoryEntry).where(MemoryEntry.project_id == payload.project_id,
        MemoryEntry.status == "PUBLISHED").execution_options(populate_existing=True)))
    visible = {}
    for entry in rows:
        revision = await _revision(db, entry)
        if not revision.upstream_ref or (revision.expires_at and revision.expires_at <= datetime.now(UTC)):
            continue
        visible[(revision.upstream_ref["artifact_id"], revision.upstream_ref["revision"])] = (entry, revision)
    result, seen = [], set()
    for hit in hits:
        identity = (hit.get("artifact_id"), hit.get("revision"))
        if identity in visible and identity not in seen:
            entry, revision = visible[identity]
            result.append(revision_view(entry, revision, context))
            seen.add(identity)
            if len(result) == payload.limit:
                break
    return {"profile": PROFILE, "project_id": str(payload.project_id), "results": result,
        "degraded": False, "notice": NOTICE}
