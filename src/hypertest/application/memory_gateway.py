"""ADR-022 optional experience Gateway, isolated from task acceptance and results.

Every external write has a committed SENT intent before the one permitted call.
Only original-key reads reconcile SENT/UNKNOWN. Nothing redispatches the outbox.
"""
import asyncio
import base64
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select

from hypertest.api.memory_schemas import PROFILE, MemoryBrowse, MemoryQuery, MemoryVisibility
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
from hypertest.memory.powercontext import MemoryUpstreamError, shared_kind

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
    if task.deleted_at is not None or task.status in cloud_tasks.TERMINAL | {"WAITING_INPUT", "RECOVERY_REQUIRED"}:
        raise HTTPException(409, "Cloud memory task is closed or fenced")
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
    """Server-generated opaque locator; no credential, private source or proof.

    Authorized readers may receive these exact accepted bytes after current
    visibility/digest verification. The marker grants no API authority.
    """
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
    # Preserve digests of existing CONFIGURE intents created before adoption
    # was supported. A supplied target is frozen, never inferred on recovery.
    if payload.operation == "CONFIGURE" and original.get("existing_scope_id") is None:
        original.pop("existing_scope_id", None)
    digest = canonical_json_sha256(original)
    if old:
        if old.actor_ref != context.actor_ref or old.input_digest != digest:
            raise HTTPException(409, "Memory operation key already belongs to a different frozen intent")
        # An accepted duplicate is a local receipt read. In-flight duplicates do
        # not cause another network call, even if the first request lost its ACK.
        return old.response
    if payload.operation == "CONFIGURE" and payload.existing_scope_id:
        # Adoption performs no upstream mutation. Reject an invalid exact target
        # before recording SENT, so a typo/cross-project target cannot freeze the
        # project into UNKNOWN. Release locks across I/O and reacquire authority
        # and the original key before committing the accepted intent.
        mapped = await mapping(db, payload.project_id)
        if (not payload.enabled or (mapped and mapped.scope_id)
                or payload.expected_version != (mapped.version if mapped else 0)):
            raise HTTPException(409, "Existing scope adoption requires an enabled, unbound project at its current version")
        await db.commit()
        try:
            async with asyncio.timeout(get_settings().memory_timeout_seconds):
                await adapter().adopt_scope(payload.existing_scope_id, "hypertest-project-" + str(payload.project_id))
        except MemoryUpstreamError as error:
            if error.code in {"MEMORY_UPSTREAM_SCOPE_MISMATCH", "MEMORY_UPSTREAM_NOT_FOUND"}:
                raise HTTPException(409, "Existing scope does not identify this project; no adoption intent was stored") from None
            raise HTTPException(503, "Existing scope verification unavailable; no adoption intent was stored") from None
        except Exception:
            raise HTTPException(503, "Existing scope verification unavailable; no adoption intent was stored") from None
        await authorize(db, context, scope, payload.project_id, lock=True)
        await cloud_tasks.project(db, payload.project_id, lock=True)
        await cloud_tasks._lock(db, "memory-key:" + str(payload.project_id) + ":" + payload.operation_key)
        old = await db.scalar(select(MemoryOperation).where(MemoryOperation.project_id == payload.project_id,
            MemoryOperation.operation_key == payload.operation_key).execution_options(populate_existing=True))
        if old:
            if old.actor_ref != context.actor_ref or old.input_digest != digest:
                raise HTTPException(409, "Memory operation key already belongs to a different frozen intent")
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
        if payload.existing_scope_id and (not payload.enabled or (mapped and mapped.scope_id)):
            raise HTTPException(409, "Existing scope adoption requires an enabled, unbound project")
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
            target = operation.request.get("existing_scope_id")
            scope_id = (await upstream.adopt_scope(target, mapped.namespace) if target
                else await upstream.create_scope(mapped.namespace, operation.marker))
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
            target = operation.request.get("existing_scope_id")
            scope_id = (await upstream.adopt_scope(target, mapped.namespace) if target
                else await upstream.find_scope(mapped.namespace))
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
    main_scope_id, namespace, mapping_version = mapped.scope_id, mapped.namespace, mapped.version
    is_history = payload.collection == "history"
    binding = history_binding(payload.project_id, main_scope_id) if is_history else None
    if is_history and not get_settings().memory_shared_knowledge_enabled:
        raise HTTPException(503, "Shared project knowledge is disabled")
    if is_history and binding is None:
        raise HTTPException(503, "Project history is not configured")
    scope_id = binding["history_scope_id"] if is_history else main_scope_id
    shared = get_settings().memory_shared_knowledge_enabled
    response = {"profile": PROFILE, "project_id": str(payload.project_id), "collection": payload.collection,
        "scope_id": scope_id, "results": [], "external_results": [], "history_results": [], "notice": NOTICE}
    await db.commit()  # Release authority/source locks before any external I/O.
    try:
        async with asyncio.timeout(getattr(get_settings(), "memory_timeout_seconds", 5.0)):
            if is_history:
                upstream = adapter()
                await upstream.adopt_scope(scope_id, namespace, reference_kind="hypertest-project-history")
                page = await upstream.browse(scope_id, history=True, query=payload.query, limit=payload.limit)
                hits, search = page["items"], {"mode": page["search_mode"]}
            elif shared:
                search = await adapter().search_project(scope_id, payload.query, min(payload.limit * 4, 50), payload.limit)
                hits = search["hits"]
            else:
                hits = await adapter().search(scope_id, payload.query, min(payload.limit * 4, 50))
                search = {"mode": "text"}
    except TimeoutError:
        return {**response, "degraded": True, "result_status": "UNAVAILABLE", "reason": "MEMORY_SEARCH_TIMEOUT"}
    except Exception as error:
        reason = error.code if isinstance(error, MemoryUpstreamError) else "MEMORY_SEARCH_UNAVAILABLE"
        return {**response, "degraded": True, "result_status": "UNAVAILABLE", "reason": reason}
    # Recheck mutable configuration/auth after network I/O. A stale index result
    # is only a locator into the *current* published PostgreSQL visibility set.
    # The session retains objects across commit; discard them so an in-flight
    # revocation/lease/generation change cannot be hidden by the identity map.
    db.expire_all()
    await authorize(db, context, "memory:read", payload.project_id, lock=True)
    await cloud_tasks.project(db, payload.project_id)
    current = await mapping(db, payload.project_id, ready=True, lock=True)
    if (current.scope_id != main_scope_id or current.namespace != namespace or current.version != mapping_version
            or (is_history and (history_binding(payload.project_id, main_scope_id) != binding
                or not get_settings().memory_shared_knowledge_enabled))):
        raise HTTPException(409, "Project knowledge configuration changed")
    enabled()
    if payload.source is not None:
        await verify_source(db, payload.project_id, payload.source, context, lock=bool(context.worker))
    if payload.context is not None:
        await verify_query_context(db, payload.project_id, payload.context, context, lock=True)
    if is_history:
        managed = await _platform_artifact_ids(db, [hit["artifact_id"] for hit in hits])
        historical, seen = [], set()
        for hit in hits:
            identity = (hit["artifact_id"], hit["revision"])
            if hit.get("kind") != "historical_technical_record" or hit["artifact_id"] in managed or identity in seen:
                continue
            seen.add(identity)
            historical.append({**hit, "result_type": "HISTORICAL_TECHNICAL_RECORD", "historical": True,
                "project_id": str(payload.project_id), "scope_id": scope_id,
                "ref": {"family": "atomic-memory", "artifact_id": hit["artifact_id"], "revision": hit["revision"]},
                "history_metadata": history_metadata(hit["content"]), "state": "active",
                "review_status": "EXTERNAL_NOT_HYPERTEST_REVIEWED",
                "notice": "Historical technical record; preserve original date, record ID, parts and known corrections. "
                    "Not current environment facts, HyperTest publication, test evidence or execution authorization. "
                    "A search is not exhaustive; retrieve any stated corrections before relying on an earlier diagnosis."})
            if len(historical) == payload.limit:
                break
        await reject_secrets(db, payload.project_id, {"history_results": historical}, context)
        return {**response, "history_results": historical, "search_mode": search["mode"], "degraded": False,
            "result_status": "OK" if historical else "EMPTY"}
    rows = list(await db.scalars(select(MemoryEntry).where(MemoryEntry.project_id == payload.project_id,
        MemoryEntry.status == "PUBLISHED").execution_options(populate_existing=True)))
    visible = {}
    for entry in rows:
        revision = await _revision(db, entry)
        if not revision.upstream_ref or (revision.expires_at and revision.expires_at <= datetime.now(UTC)):
            continue
        visible[(revision.upstream_ref["artifact_id"], revision.upstream_ref["revision"])] = (entry, revision)
    # Platform-owned artifacts never become external knowledge, even if a
    # direct service writer changes their kind after retraction or expiry.
    hit_ids = [hit.get("artifact_id") for hit in hits if shared_kind(hit.get("kind"))]
    platform_artifacts = await _platform_artifact_ids(db, hit_ids) if shared and hit_ids else set()
    result, external, seen = [], [], set()
    for hit in hits:
        identity = (hit.get("artifact_id"), hit.get("revision"))
        if identity in visible and identity not in seen:
            entry, revision = visible[identity]
            result.append({**revision_view(entry, revision, context), "upstream_ref": revision.upstream_ref,
                "matched_by": hit.get("matched_by", []), **({"score": hit["score"]} if "score" in hit else {})})
            seen.add(identity)
        elif (shared and shared_kind(hit.get("kind")) and identity not in seen
                and hit["artifact_id"] not in platform_artifacts):
            external.append({"result_type": "EXTERNAL_PROJECT_KNOWLEDGE", "project_id": str(payload.project_id),
                "scope_id": scope_id, "artifact_id": hit["artifact_id"], "revision": hit["revision"],
                "kind": hit["kind"], "content": hit["content"], "content_digest": hit["content_digest"],
                "state": "active", "state_version": hit["state_version"], "matched_by": hit["matched_by"],
                **({"score": hit["score"]} if "score" in hit else {}),
                "review_status": "EXTERNAL_NOT_HYPERTEST_REVIEWED",
                "notice": "Explicitly shared project knowledge; not HyperTest publication, test evidence or execution permission. Verify current applicability. Legacy source references in text are not native lineage."})
            seen.add(identity)
        if len(result) + len(external) == payload.limit:
            break
    # Direct service writes did not pass the platform's publication scanner.
    # Refuse the response if known credentials appear; never redact bytes while
    # retaining an immutable digest that would describe different content.
    if external:
        await reject_secrets(db, payload.project_id, {"external_results": [row["content"] for row in external]}, context)
    return {**response, "results": result,
        "external_results": external, "search_mode": search["mode"],
        "degraded": False, "result_status": "OK" if result or external else "EMPTY"}


async def _platform_artifact_ids(db, artifact_ids):
    refs = await db.scalars(select(MemoryRevision.upstream_ref).where(
        MemoryRevision.upstream_ref["artifact_id"].astext.in_(artifact_ids)).union_all(
            select(MemoryOperation.upstream_ref).where(
                MemoryOperation.upstream_ref["artifact_id"].astext.in_(artifact_ids))))
    return {ref["artifact_id"] for ref in refs if isinstance(ref, dict) and ref.get("artifact_id")}


def history_binding(project_id, main_scope_id):
    binding = get_settings().memory_history_bindings.get(str(project_id))
    if not binding:
        return None
    if (set(binding) != {"main_scope_id", "history_scope_id"}
            or binding.get("main_scope_id") != main_scope_id
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", binding.get("history_scope_id", ""))
            or binding["history_scope_id"] == main_scope_id):
        raise HTTPException(503, "Project history binding requires Operator reconciliation")
    return dict(binding)


def history_metadata(content):
    """Literal migration-header claims only; never infer review or current validity."""
    header = content.partition("\n---\n")[0]
    origin = re.search(r"^原日期：([^；\n]+)；原项目：[^；\n]+；原记录ID：(\d+)。$", header, re.MULTILINE)
    part = re.search(r"^分块：(\d+)/(\d+)；", header, re.MULTILINE)
    correction = next((line for line in header.splitlines() if line.startswith("已知后续更正/补充")), None)
    return {"original_date": origin[1] if origin else None, "legacy_record_id": origin[2] if origin else None,
        "part_index": int(part[1]) if part else None, "part_count": int(part[2]) if part else None,
        "correction_notice": correction}


def browse_cursor(payload, scope_id, cursor, *, encode=False):
    binding = {"project_id": str(payload.project_id), "scope_id": scope_id, "collection": payload.collection}
    if cursor is None:
        return None
    if encode:
        return base64.urlsafe_b64encode(json.dumps({**binding, "cursor": cursor}, separators=(",", ":")).encode()).decode()
    try:
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (not isinstance(value, dict) or set(value) != {*binding, "cursor"}
                or any(value[key] != expected for key, expected in binding.items())
                or not isinstance(value["cursor"], str) or not 1 <= len(value["cursor"]) <= 4096):
            raise ValueError
        return value["cursor"]
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Inventory cursor belongs to another project or collection; restart browsing") from None


async def browse(db, payload: MemoryBrowse, context):
    """Human-requested external inventory. Default query/Worker recall is unchanged."""
    enabled()
    if context.worker:
        raise HTTPException(403, "Worker memory reads require the fenced query endpoint")
    await authorize(db, context, "memory:read", payload.project_id, lock=True)
    await cloud_tasks.project(db, payload.project_id)
    mapped = await mapping(db, payload.project_id, ready=True)
    main_scope_id, namespace = mapped.scope_id, mapped.namespace
    binding = history_binding(payload.project_id, main_scope_id)
    if not get_settings().memory_shared_knowledge_enabled:
        raise HTTPException(503, "Shared project knowledge is disabled")
    if payload.query is not None and (not payload.query.strip() or payload.cursor is not None):
        raise HTTPException(422, "Search needs nonblank text and does not accept an inventory cursor")
    response = {"profile": PROFILE, "project_id": str(payload.project_id), "collection": payload.collection,
        "history_available": binding is not None, "items": [], "next_cursor": None, "configured": True,
        "notice": ("SELECTED_TECHNICAL_HISTORY_CHUNKS_NOT_ALL_LEGACY_RECORDS_OR_CURRENT_FACTS"
                   if payload.collection == "history" else "SHARED_PROJECT_KNOWLEDGE_NOT_PLATFORM_REVIEWED")}
    if payload.collection == "history" and binding is None:
        return {**response, "configured": False}
    scope_id = binding["history_scope_id"] if payload.collection == "history" else main_scope_id
    cursor = browse_cursor(payload, scope_id, payload.cursor)
    await reject_secrets(db, payload.project_id, {"query": payload.query}, context)
    await db.commit()
    try:
        upstream = adapter()
        if payload.collection == "history":
            await upstream.adopt_scope(scope_id, namespace, reference_kind="hypertest-project-history")
        page = await upstream.browse(scope_id, history=payload.collection == "history",
            query=payload.query, cursor=cursor, limit=payload.limit)
    except MemoryUpstreamError:
        raise HTTPException(503, "Project knowledge inventory is unavailable") from None
    # Recheck grant/configuration after all external I/O, before disclosing text.
    await authorize(db, context, "memory:read", payload.project_id, lock=True)
    await cloud_tasks.project(db, payload.project_id)
    current = await mapping(db, payload.project_id, ready=True, lock=True)
    if (current.scope_id != main_scope_id or history_binding(payload.project_id, main_scope_id) != binding
            or not get_settings().memory_shared_knowledge_enabled):
        raise HTTPException(409, "Project knowledge configuration changed; refresh the page")
    enabled()
    managed = await _platform_artifact_ids(db, [row["artifact_id"] for row in page["items"]])
    items = [{"project_id": str(payload.project_id), "scope_id": scope_id, **row,
        "review_status": "EXTERNAL_NOT_HYPERTEST_REVIEWED", "historical": payload.collection == "history",
        "history_metadata": history_metadata(row["content"]) if payload.collection == "history" else None}
        for row in page["items"] if row["artifact_id"] not in managed and (
            row.get("kind") == "historical_technical_record" if payload.collection == "history" else shared_kind(row.get("kind")))]
    await reject_secrets(db, payload.project_id, {"knowledge": items}, context)
    return {**response, "items": items, "next_cursor": browse_cursor(payload, scope_id, page["next_cursor"], encode=True),
            "search_mode": page["search_mode"]}


async def visibility(db, payload: MemoryVisibility, context):
    """Current PG visibility for exact PC bytes; never grants upstream access.

    Standalone readers only. Cloud uses query with its original claim fence.
    Unknown upstream artifacts still require the client's PC lifecycle/digest
    check; this endpoint does not turn absence from PG into a trusted fact.
    """
    if context.worker:
        raise HTTPException(403, "Worker memory reads require the fenced query endpoint")
    enabled()
    await authorize(db, context, "memory:read", payload.project_id, lock=True)
    await cloud_tasks.project(db, payload.project_id, lock=True)
    mapped = await mapping(db, payload.project_id, ready=True, lock=True)
    if mapped.scope_id != payload.scope_id:
        raise HTTPException(409, "Visibility scope must match the current project binding")
    artifact_ids = {ref.artifact_id for ref in payload.artifacts}
    managed = await _platform_artifact_ids(db, artifact_ids)
    rows = await db.execute(select(MemoryEntry, MemoryRevision).join(MemoryRevision,
        (MemoryRevision.entry_id == MemoryEntry.id) & (MemoryRevision.version == MemoryEntry.version)).where(
            MemoryEntry.project_id == payload.project_id, MemoryEntry.status == "PUBLISHED",
            MemoryRevision.status == "PUBLISHED", MemoryRevision.upstream_ref["artifact_id"].astext.in_(artifact_ids)))
    current = {}
    now = datetime.now(UTC)
    for entry, revision in rows:
        ref = revision.upstream_ref
        if revision.expires_at is None or revision.expires_at > now:
            current[(ref["artifact_id"], ref["revision"], ref.get("content_digest"))] = (entry, revision)
    items = []
    for ref in payload.artifacts:
        item = {"artifact_id": ref.artifact_id, "revision": ref.revision}
        accepted = current.get((ref.artifact_id, ref.revision, ref.content_digest))
        if accepted:
            entry, revision = accepted
            item.update(disposition="PLATFORM_CURRENT", content_digest=ref.content_digest,
                entry_id=str(entry.id), version=revision.version,
                publication=revision_view(entry, revision, context))
        else:
            item["disposition"] = "PLATFORM_NOT_CURRENT" if ref.artifact_id in managed else "EXTERNAL_UNMANAGED"
        items.append(item)
    # Same output boundary as query; absence from the ledger never returns
    # candidate/operation content or identifies another owning project.
    publications = [row["publication"] for row in items if "publication" in row]
    if publications:
        await reject_secrets(db, payload.project_id, {"publications": publications}, context)
    return {"profile": PROFILE, "project_id": str(payload.project_id), "scope_id": mapped.scope_id,
        "configuration_version": mapped.version, "items": items, "notice": NOTICE}
