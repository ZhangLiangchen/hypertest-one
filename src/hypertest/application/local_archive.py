"""Transactional post-test archives, immutable original requests and fixed readback."""
import copy
import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, select, text

from hypertest.api.archive_schemas import PROFILE
from hypertest.application.services import canonical_json_sha256
from hypertest.application.session_tasks import project, public
from hypertest.common.ids import uuid7
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveIntegrationGrant,
)
from hypertest.domain.local_archive import (
    LocalArchiveAssetRevision,
    LocalArchiveOperation,
    LocalArchivePublication,
    LocalArchiveSnapshot,
    LocalArchiveSubmission,
    LocalArchiveSubtask,
    LocalArchiveTask,
)
from hypertest.domain.models import AuditEvent, OutboxEvent


async def clock(db):
    return await db.scalar(select(func.clock_timestamp()))


async def key_lock(db, namespace, project_id, actor, key):
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                     {"key": f"local-archive:{namespace}:{project_id}:{actor}:{key}"})


def actor_query(project_id):
    return select(InteractiveActorIdentity).join(InteractiveIntegrationGrant,
        InteractiveIntegrationGrant.actor_identity_id == InteractiveActorIdentity.id).join(
        InteractiveClientRegistration, and_(
            InteractiveClientRegistration.actor_identity_id == InteractiveIntegrationGrant.actor_identity_id,
            InteractiveClientRegistration.client_instance_id == InteractiveIntegrationGrant.client_instance_id)).where(
        InteractiveActorIdentity.status == "ACTIVE", InteractiveClientRegistration.status == "ACTIVE",
        InteractiveIntegrationGrant.project_id == project_id, InteractiveIntegrationGrant.status == "ACTIVE",
        InteractiveIntegrationGrant.not_before <= func.clock_timestamp(),
        InteractiveIntegrationGrant.expires_at > func.clock_timestamp(),
        InteractiveIntegrationGrant.scopes.contains(["archive:read", "archive:write"]))


async def actors(db, project_id):
    await project(db, project_id)
    rows = (await db.scalars(actor_query(project_id).order_by(InteractiveActorIdentity.id))).unique().all()
    return {"items": [{"actor_ref": "interactive:" + str(row.id), "label": row.actor_ref} for row in rows], "total": len(rows)}


async def ensure_actor(db, project_id, actor_ref):
    if actor_ref is None:
        return
    try:
        prefix, raw = actor_ref.split(":", 1)
        actor_id = UUID(raw)
        if prefix != "interactive":
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(422, "ARCHIVE_UPLOADER_UNAVAILABLE") from None
    actor = await db.scalar(actor_query(project_id).where(InteractiveActorIdentity.id == actor_id)
                            .with_for_update(read=True).execution_options(populate_existing=True))
    if actor is None:
        raise HTTPException(422, "ARCHIVE_UPLOADER_UNAVAILABLE")


async def target(db, project_id, task_id, subtask_id=None, *, actor=None, operator=False, lock=False):
    query = select(LocalArchiveTask).where(LocalArchiveTask.project_id == project_id, LocalArchiveTask.id == task_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    task = await db.scalar(query)
    if task is None:
        raise HTTPException(404, "ARCHIVE_TASK_NOT_FOUND")
    if not operator and (not task.owner_uploader_actor_ref or task.owner_uploader_actor_ref != actor):
        raise HTTPException(403, "ARCHIVE_TASK_OWNER_REQUIRED")
    child = None
    if subtask_id is not None:
        query = select(LocalArchiveSubtask).where(LocalArchiveSubtask.project_id == project_id,
            LocalArchiveSubtask.task_id == task_id, LocalArchiveSubtask.id == subtask_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        child = await db.scalar(query)
        if child is None:
            raise HTTPException(404, "ARCHIVE_SUBTASK_NOT_FOUND")
        if not operator and (not child.authorized_uploader_actor_ref or child.authorized_uploader_actor_ref != actor):
            raise HTTPException(403, "ARCHIVE_SUBTASK_UPLOADER_REQUIRED")
    return task, child


def scope(task, child):
    return {"project_id": str(task.project_id), "task_id": str(task.id),
            "target_kind": "SUBTASK" if child else "TASK", "subtask_id": str(child.id) if child else None}


def db_scope(task, child):
    return {"project_id": task.project_id, "task_id": task.id,
            "target_kind": "SUBTASK" if child else "TASK", "subtask_id": child.id if child else None}


async def snapshot(db, task, child, version):
    row = await db.scalar(select(LocalArchiveSnapshot).where(
        LocalArchiveSnapshot.task_id == task.id,
        LocalArchiveSnapshot.subtask_id == (child.id if child else None),
        LocalArchiveSnapshot.archive_version == version))
    if row is None:
        raise HTTPException(404, "ARCHIVE_VERSION_NOT_FOUND")
    return row


def initial_snapshot(task, child, timestamp):
    doc = {"profile": PROFILE, **scope(task, child), "archive_version": 1, "assets": []}
    if child:
        doc.update(status=child.status, reported_result=child.reported_result)
    return LocalArchiveSnapshot(id=uuid7(), **db_scope(task, child), archive_version=1, document=doc, created_at=timestamp)


def event(db, task, actor, action, entity_id, data, *, operator=False):
    db.add(AuditEvent(project_id=task.project_id, actor_type="OPERATOR" if operator else "USER",
        actor_ref=actor, action="local_archive." + action.lower(), entity_type="LocalArchiveTask",
        entity_id=entity_id, event_metadata=data))
    db.add(OutboxEvent(aggregate_type="LocalArchiveTask", aggregate_id=task.id,
        event_type="local_archive." + action.lower(), payload=data))


async def children(db, task_id):
    return list(await db.scalars(select(LocalArchiveSubtask).where(LocalArchiveSubtask.task_id == task_id)
                                .order_by(LocalArchiveSubtask.created_at, LocalArchiveSubtask.id)))


async def manage(db, payload, actor, operation, task_id=None):
    await project(db, payload.project_id, lock=True)
    await key_lock(db, "management", payload.project_id, actor, payload.idempotency_key)
    frozen = {"operation": operation, "task_id": str(task_id) if task_id else None,
              "request": payload.model_dump(mode="json", exclude_unset=True)}
    digest = canonical_json_sha256(frozen)
    old = await db.scalar(select(LocalArchiveOperation).where(LocalArchiveOperation.project_id == payload.project_id,
        LocalArchiveOperation.actor_ref == actor, LocalArchiveOperation.idempotency_key == payload.idempotency_key))
    if old:
        if old.request_digest != digest:
            raise HTTPException(409, "ARCHIVE_OPERATION_KEY_CONFLICT")
        return old.response
    timestamp = await clock(db)
    publication = None
    if operation == "CREATE":
        owner = payload.owner_uploader_actor_ref
        if "owner_uploader_actor_ref" not in payload.model_fields_set:
            available = await actors(db, payload.project_id)
            if available["total"] == 1:
                owner = available["items"][0]["actor_ref"]
        await ensure_actor(db, payload.project_id, owner)
        task = LocalArchiveTask(id=uuid7(), project_id=payload.project_id, creator_actor_ref=actor,
            owner_uploader_actor_ref=owner, title=payload.title, objective=payload.objective,
            version=1, archive_version=1, status="DRAFT", reported_result="NOT_RUN", created_at=timestamp, updated_at=timestamp)
        db.add(task)
        await db.flush()
        db.add(initial_snapshot(task, None, timestamp))
    else:
        task, _ = await target(db, payload.project_id, task_id, operator=True, lock=True)
        if task.version != payload.expected_task_version:
            raise HTTPException(409, "ARCHIVE_TASK_VERSION_CONFLICT")
        if operation == "SUBTASK_CREATE":
            child = LocalArchiveSubtask(id=uuid7(), project_id=task.project_id, task_id=task.id,
                authorized_uploader_actor_ref=task.owner_uploader_actor_ref, title=payload.title, objective=payload.objective,
                archive_version=1, status="DRAFT", reported_result="NOT_RUN", created_at=timestamp, updated_at=timestamp)
            db.add(child)
            await db.flush()
            db.add(initial_snapshot(task, child, timestamp))
        elif operation == "AUTHORIZE":
            await ensure_actor(db, task.project_id, payload.uploader_actor_ref)
            if payload.subtask_id is not None:
                _, child = await target(db, task.project_id, task.id, payload.subtask_id, operator=True, lock=True)
                if payload.uploader_actor_ref is not None and payload.uploader_actor_ref != task.owner_uploader_actor_ref:
                    raise HTTPException(422, "ARCHIVE_SUBTASK_OWNER_MISMATCH")
                child.authorized_uploader_actor_ref = payload.uploader_actor_ref
                child.updated_at = timestamp
            else:
                if task.owner_uploader_actor_ref != payload.uploader_actor_ref:
                    accepted = await db.scalar(select(LocalArchiveSubmission.id).where(LocalArchiveSubmission.task_id == task.id).limit(1))
                    if accepted:
                        raise HTTPException(409, "ARCHIVE_ACCEPTED_OWNER_IMMUTABLE")
                    # Existing child authorization may only follow an explicit owner
                    # change while no accepted upload exists; revocations stay revoked.
                    old_owner = task.owner_uploader_actor_ref
                    for child in await children(db, task.id):
                        if child.authorized_uploader_actor_ref == old_owner:
                            child.authorized_uploader_actor_ref = payload.uploader_actor_ref
                            child.updated_at = timestamp
                task.owner_uploader_actor_ref = payload.uploader_actor_ref
        elif operation == "UPDATE":
            for field in payload.model_fields_set & {"title", "objective"}:
                setattr(task, field, getattr(payload, field))
        elif operation == "PUBLISH":
            publication = await prepare_publication(db, task, payload, actor, timestamp)
            task.status, task.reported_result = payload.status, payload.reported_result
        else:
            raise HTTPException(422, "ARCHIVE_OPERATION_UNSUPPORTED")
        task.version += 1
        task.updated_at = timestamp
    await db.flush()
    operation_id = uuid7()
    receipt = {"operation_id": str(operation_id), "operation": operation,
        "idempotency_key": payload.idempotency_key, "project_id": str(task.project_id), "task_id": str(task.id),
        "task_version": task.version, "request_digest": digest, "request_payload": frozen}
    response = {"task": public(task), "subtasks": [public(row) for row in await children(db, task.id)], "receipt": receipt}
    if publication:
        response["publication"] = public(publication)
    db.add(LocalArchiveOperation(id=operation_id, project_id=task.project_id, task_id=task.id,
        actor_ref=actor, operation=operation, idempotency_key=payload.idempotency_key, request_digest=digest,
        request_payload=frozen, task_version=task.version, response=response, created_at=timestamp))
    event(db, task, actor, operation, task.id, receipt, operator=True)
    await db.commit()
    return response


async def prepare_publication(db, task, payload, actor, timestamp):
    if task.archive_version != payload.root_archive_version:
        raise HTTPException(409, "ARCHIVE_ROOT_VERSION_CONFLICT")
    await ensure_actor(db, task.project_id, task.owner_uploader_actor_ref)
    if not task.owner_uploader_actor_ref:
        raise HTTPException(409, "ARCHIVE_TASK_OWNER_REQUIRED")
    all_children = {row.id: row for row in await children(db, task.id)}
    documents = [(await snapshot(db, task, None, payload.root_archive_version)).document]
    selected, incomplete = set(), []
    for ref in payload.subtask_versions:
        child = all_children.get(ref.subtask_id)
        if child is None or child.authorized_uploader_actor_ref != task.owner_uploader_actor_ref:
            raise HTTPException(409, "ARCHIVE_PUBLICATION_SUBTASK_UNAVAILABLE")
        if child.archive_version != ref.archive_version:
            raise HTTPException(409, "ARCHIVE_SUBTASK_VERSION_CONFLICT")
        selected.add(child.id)
        if child.status != "COMPLETED":
            incomplete.append(str(child.id))
        documents.append((await snapshot(db, task, child, ref.archive_version)).document)
    allowed_ids = {asset["id"] for document in documents for asset in document["assets"]}
    if any(str(item) not in allowed_ids for item in payload.asset_revision_ids):
        raise HTTPException(422, "ARCHIVE_PUBLICATION_ASSET_OUTSIDE_VERSION_VECTOR")
    publication = LocalArchivePublication(id=uuid7(), project_id=task.project_id, task_id=task.id,
        task_version=task.version + 1, root_archive_version=payload.root_archive_version,
        subtask_versions=[item.model_dump(mode="json") for item in payload.subtask_versions],
        asset_revision_ids=[str(item) for item in payload.asset_revision_ids],
        omitted_subtask_ids=sorted(str(item) for item in set(all_children) - selected),
        incomplete_subtask_ids=sorted(incomplete), summary=payload.summary, status=payload.status,
        reported_result=payload.reported_result, actor_ref=actor, created_at=timestamp)
    db.add(publication)
    return publication


async def operation_by_key(db, project_id, actor, key):
    await project(db, project_id)
    row = await db.scalar(select(LocalArchiveOperation).where(LocalArchiveOperation.project_id == project_id,
        LocalArchiveOperation.actor_ref == actor, LocalArchiveOperation.idempotency_key == key))
    if row is None:
        raise HTTPException(404, "ARCHIVE_OPERATION_NOT_FOUND; this does not authorize replay")
    return row.response


async def submit(db, payload, actor, client_instance_id, *, authorization_check):
    await project(db, payload.project_id, lock=True)
    await key_lock(db, "submission", payload.project_id, actor, payload.idempotency_key)
    task, child = await target(db, payload.project_id, payload.task_id, payload.subtask_id, actor=actor, lock=True)
    await authorization_check()
    original = payload.wire()
    digest = canonical_json_sha256(original)
    old = await db.scalar(select(LocalArchiveSubmission).where(LocalArchiveSubmission.project_id == payload.project_id,
        LocalArchiveSubmission.uploader_actor_ref == actor, LocalArchiveSubmission.operation == "ARCHIVE",
        LocalArchiveSubmission.idempotency_key == payload.idempotency_key))
    if old:
        if old.request_digest != digest or old.client_instance_id != client_instance_id:
            raise HTTPException(409, "ARCHIVE_SUBMISSION_KEY_CONFLICT")
        return old.response
    destination = child or task
    if destination.archive_version != payload.expected_archive_version:
        raise HTTPException(409, "ARCHIVE_VERSION_CONFLICT")
    previous = await snapshot(db, task, child, destination.archive_version)
    document = copy.deepcopy(previous.document)
    existing = {(item["kind"], item["stable_key"]): item for item in document["assets"]}
    changed = []
    timestamp, submission_id = await clock(db), uuid7()
    for asset in payload.assets:
        value = asset.model_dump(mode="json")
        old_asset = existing.get((asset.kind, asset.stable_key))
        if old_asset and all(old_asset.get(key) == val for key, val in value.items()):
            continue
        revision = LocalArchiveAssetRevision(id=uuid7(), **db_scope(task, child), submission_id=submission_id,
            kind=asset.kind, stable_key=asset.stable_key, revision=old_asset["revision"] + 1 if old_asset else 1,
            archive_version=destination.archive_version + 1, uploader_actor_ref=actor, content=value, created_at=timestamp)
        changed.append(revision)
        existing[(asset.kind, asset.stable_key)] = {**value, "id": str(revision.id), "revision": revision.revision,
            "submission_id": str(submission_id), "accepted_at": timestamp.isoformat(), "uploader_actor_ref": actor}
    status_changed = False
    if payload.subtask_update:
        for name, value in payload.subtask_update.model_dump(exclude_unset=True).items():
            if getattr(child, name) != value:
                status_changed = True
            setattr(child, name, value)
            document[name] = value
    if changed or status_changed:
        destination.archive_version += 1
        destination.updated_at = timestamp
        document["archive_version"] = destination.archive_version
        document["assets"] = [existing[key] for key in sorted(existing)]
        selected = LocalArchiveSnapshot(id=uuid7(), **db_scope(task, child), archive_version=destination.archive_version,
            document=document, created_at=timestamp)
        db.add(selected)
        outcome = "ACCEPTED"
    else:
        selected, outcome = previous, "UNCHANGED"
    response = {"profile": PROFILE, "submission_id": str(submission_id), **scope(task, child),
        "uploader_actor_ref": actor, "idempotency_key": payload.idempotency_key, "request_digest": digest,
        "outcome": outcome, "accepted_version": destination.archive_version}
    # Persist the immutable snapshot before its receipt, then receipt before
    # asset rows; database guards validate these exact references on INSERT.
    await db.flush()
    db.add(LocalArchiveSubmission(id=submission_id, **db_scope(task, child), profile=PROFILE, operation="ARCHIVE",
        uploader_actor_ref=actor, client_instance_id=client_instance_id, idempotency_key=payload.idempotency_key,
        request_payload=original, request_digest=digest, expected_archive_version=payload.expected_archive_version,
        outcome=outcome, accepted_version=destination.archive_version, snapshot_id=selected.id, response=response, created_at=timestamp))
    await db.flush()
    db.add_all(changed)
    event(db, task, actor, "SUBMISSION", submission_id, response)
    await db.flush()
    await authorization_check()
    await db.commit()
    return response


async def submission_by_key(db, project_id, actor, key):
    await project(db, project_id)
    row = await db.scalar(select(LocalArchiveSubmission).where(LocalArchiveSubmission.project_id == project_id,
        LocalArchiveSubmission.uploader_actor_ref == actor, LocalArchiveSubmission.idempotency_key == key))
    if row is None:
        raise HTTPException(404, "ARCHIVE_SUBMISSION_NOT_FOUND; this does not authorize replay")
    await target(db, project_id, row.task_id, row.subtask_id, actor=actor)
    return row.response


def page(row, *, submission_id=None, offset=0, limit=24000):
    content = json.dumps(row.document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if offset > len(content):
        raise HTTPException(422, "ARCHIVE_OFFSET_OUT_OF_BOUNDS")
    next_offset = min(offset + limit, len(content))
    return {"profile": PROFILE, "submission_id": str(submission_id) if submission_id else None,
        "project_id": str(row.project_id), "task_id": str(row.task_id), "target_kind": row.target_kind,
        "subtask_id": str(row.subtask_id) if row.subtask_id else None, "archive_version": row.archive_version,
        "offset": offset, "total_chars": len(content), "next_offset": next_offset if next_offset < len(content) else None,
        "content": content[offset:next_offset], "complete": next_offset == len(content)}


async def read_archive(db, project_id, task_id, subtask_id, actor, operator, version, offset, limit):
    await project(db, project_id)
    task, child = await target(db, project_id, task_id, subtask_id, actor=actor, operator=operator)
    if offset and version is None:
        raise HTTPException(422, "ARCHIVE_CONTINUATION_REQUIRES_VERSION")
    selected = version if version is not None else (child or task).archive_version
    row = await snapshot(db, task, child, selected)
    return page(row, offset=offset, limit=limit)


async def read_submission(db, project_id, submission_id, actor, operator, offset, limit):
    await project(db, project_id)
    row = await db.get(LocalArchiveSubmission, submission_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "ARCHIVE_SUBMISSION_NOT_FOUND")
    await target(db, project_id, row.task_id, row.subtask_id, actor=actor, operator=operator)
    selected = await db.get(LocalArchiveSnapshot, row.snapshot_id)
    return page(selected, submission_id=row.id, offset=offset, limit=limit)


async def list_tasks(db, project_id, actor, operator, limit, offset):
    await project(db, project_id)
    where = [LocalArchiveTask.project_id == project_id]
    if not operator:
        where.append(LocalArchiveTask.owner_uploader_actor_ref == actor)
    total = await db.scalar(select(func.count()).select_from(LocalArchiveTask).where(*where))
    rows = await db.scalars(select(LocalArchiveTask).where(*where).order_by(LocalArchiveTask.updated_at.desc(),
        LocalArchiveTask.id).offset(offset).limit(limit))
    return {"items": [public(row) for row in rows], "total": total, "offset": offset, "limit": limit}


async def detail(db, project_id, task_id, actor, operator):
    await project(db, project_id)
    task, _ = await target(db, project_id, task_id, actor=actor, operator=operator)
    members = await children(db, task_id)
    if not operator:
        members = [row for row in members if row.authorized_uploader_actor_ref == actor]
    allowed = [None, *(row.id for row in members)]
    submissions = list(await db.scalars(select(LocalArchiveSubmission).where(LocalArchiveSubmission.task_id == task_id)
        .order_by(LocalArchiveSubmission.created_at, LocalArchiveSubmission.id)))
    publications = list(await db.scalars(select(LocalArchivePublication).where(LocalArchivePublication.task_id == task_id)
        .order_by(LocalArchivePublication.task_version)))
    management = list(await db.scalars(select(LocalArchiveOperation).where(LocalArchiveOperation.task_id == task_id)
        .order_by(LocalArchiveOperation.task_version))) if operator else []
    return {"task": public(task), "subtasks": [public(row) for row in members],
        "publications": [public(row) for row in publications],
        "management_history": [row.response["receipt"] for row in management],
        "submission_history": [row.response for row in submissions if row.subtask_id in allowed]}
