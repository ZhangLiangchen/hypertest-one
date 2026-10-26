"""Versioned Local member contributions, separated from legacy full synchronization."""
import json

from fastapi import HTTPException
from sqlalchemy import func, select, text

from hypertest.api.task_collaboration_schemas import COLLABORATION_PROFILE
from hypertest.application.management import record_change
from hypertest.application.services import canonical_json_sha256
from hypertest.application.session_tasks import project, public, version_snapshot
from hypertest.application.task_binding import creator_ref, ensure_actor
from hypertest.common.ids import uuid7
from hypertest.domain.session_tasks import (
    CollaborationReceipt,
    ContributionRevision,
    SessionTask,
    TaskPublication,
    TaskSessionParticipant,
    TaskSessionSource,
)


async def roster_snapshot(db, task):
    participants = await db.scalars(select(TaskSessionParticipant).where(
        TaskSessionParticipant.task_id == task.id).order_by(TaskSessionParticipant.created_at, TaskSessionParticipant.id))
    contributions = await db.scalars(select(ContributionRevision).where(
        ContributionRevision.task_id == task.id).order_by(ContributionRevision.task_version, ContributionRevision.id))
    publications = await db.scalars(select(TaskPublication).where(
        TaskPublication.task_id == task.id).order_by(TaskPublication.task_version))
    return {"enabled": task.collaboration_enabled, "primary_participant_id": str(task.primary_participant_id)
            if task.primary_participant_id else None, "primary_generation": task.primary_generation,
            "participants": [public(row) for row in participants],
            "contributions": [public(row) for row in contributions],
            "publications": [public(row) for row in publications]}


async def participant(db, task_id, provider, session_id):
    return await db.scalar(select(TaskSessionParticipant).where(
        TaskSessionParticipant.task_id == task_id, TaskSessionParticipant.provider == provider,
        TaskSessionParticipant.session_id == session_id).execution_options(populate_existing=True))


async def require_member(db, task, actor_ref, provider, session_id, *, joining=False):
    row = await participant(db, task.id, provider, session_id)
    if (task.owner_actor_ref != actor_ref or row is None or row.actor_ref != actor_ref
            or row.status not in ({"AUTHORIZED", "ACTIVE"} if joining else {"ACTIVE"})):
        raise HTTPException(403, "COLLABORATION_MEMBER_UNAUTHORIZED")
    return row


async def document(db, task_id, *, version=None, project_id=None, actor_ref=None,
                   provider=None, session_id=None, include_deleted=False):
    task = await db.get(SessionTask, task_id)
    if task is None or (project_id is not None and task.project_id != project_id):
        raise HTTPException(404, "Session task not found in Project")
    if task.deleted_at is not None and not include_deleted:
        raise HTTPException(404, "Session task not found in Project")
    await project(db, task.project_id, include_deleted=include_deleted)
    if actor_ref is not None:
        await require_member(db, task, actor_ref, provider, session_id, joining=True)
    selected = task.version if version is None else version
    snapshot = await version_snapshot(db, task.id, selected)
    # A collaboration snapshot is immutable at every accepted collaboration
    # version. Later Web delete/restore versions inherit its unchanged roster.
    latest = await db.scalar(select(CollaborationReceipt).where(
        CollaborationReceipt.task_id == task.id, CollaborationReceipt.task_version <= selected
    ).order_by(CollaborationReceipt.task_version.desc()).limit(1))
    collab = latest.collaboration_snapshot if latest else {
        "enabled": False, "primary_participant_id": None, "primary_generation": 0,
        "participants": [], "contributions": [], "publications": []}
    history = await db.scalars(select(CollaborationReceipt).where(
        CollaborationReceipt.task_id == task.id, CollaborationReceipt.task_version <= selected
    ).order_by(CollaborationReceipt.task_version))
    return {"profile": COLLABORATION_PROFILE, "task": snapshot, "collaboration": collab,
            "operation_history": [{k: v for k, v in public(row).items()
                if k not in {"task_snapshot", "collaboration_snapshot"}} for row in history]}


async def document_page(db, task_id, *, version=None, offset=0, limit=24000, **kwargs):
    if offset < 0 or not 1 <= limit <= 24000 or (offset and version is None):
        raise HTTPException(422, "Continuation requires a fixed version and bounded offset/limit")
    result = await document(db, task_id, version=version, **kwargs)
    content = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if offset >= len(content):
        raise HTTPException(422, "Page offset is outside the fixed task version")
    end = min(offset + limit, len(content))
    return {"task_id": str(task_id), "version": result["task"]["version"],
            "profile": COLLABORATION_PROFILE, "format": "application/json",
            "offset": offset, "total_chars": len(content), "next_offset": end if end < len(content) else None,
            "complete": end == len(content), "content": content[offset:end]}


async def prior(db, project_id, actor_ref, key):
    return await db.scalar(select(CollaborationReceipt).where(
        CollaborationReceipt.project_id == project_id, CollaborationReceipt.actor_ref == actor_ref,
        CollaborationReceipt.idempotency_key == key))


async def receipt(db, task_id, actor_ref, key, *, project_id=None, provider=None, session_id=None):
    task = await db.get(SessionTask, task_id)
    if task is None or (project_id is not None and task.project_id != project_id):
        raise HTTPException(404, "Session task not found in Project")
    await project(db, task.project_id, include_deleted=True)
    if provider is not None:
        await require_member(db, task, actor_ref, provider, session_id, joining=True)
    row = await prior(db, task.project_id, actor_ref, key)
    if row is None or row.task_id != task.id:
        raise HTTPException(404, "COLLABORATION_RECEIPT_NOT_FOUND_NO_REPLAY")
    if row.provider != provider or row.session_id != session_id:
        raise HTTPException(403, "COLLABORATION_RECEIPT_SOURCE_MISMATCH")
    return row.response


async def check_source(db, task, provider, session_id):
    reservation = await db.get(TaskSessionSource, (provider, session_id))
    if reservation is not None and reservation.task_id != task.id:
        raise HTTPException(409, "SESSION_ALREADY_HAS_TASK")


async def change(db, task_id, payload, *, actor_ref=None, authorization_check=None):
    with db.no_autoflush:
        return await _change(db, task_id, payload, actor_ref=actor_ref,
                             authorization_check=authorization_check)


async def _change(db, task_id, payload, *, actor_ref=None, authorization_check=None):
    operator = actor_ref is None
    actor_ref = creator_ref() if operator else actor_ref
    candidate = await db.get(SessionTask, task_id)
    if candidate is None or (not operator and candidate.project_id != payload.project_id):
        raise HTTPException(404, "Session task not found in Project")
    parent = await project(db, candidate.project_id, include_deleted=True, lock=True)
    # Source lock order agrees with BIND/full-sync, before key and aggregate.
    source_provider = getattr(payload, "provider", None)
    source_session = getattr(payload, "session_id", None)
    if source_provider is not None:
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                         {"key": f"session-task:{source_provider}:{source_session}"})
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                     {"key": f"collaboration:{actor_ref}:{candidate.project_id}:{payload.idempotency_key}"})
    if authorization_check:
        await authorization_check()
    task = await db.scalar(select(SessionTask).where(SessionTask.id == task_id).with_for_update()
                           .execution_options(populate_existing=True))
    provider = None if operator else payload.provider
    session_id = None if operator else payload.session_id
    # Current reconciliation authority and exact submitting source remain
    # necessary, while accepted original keys precede version/role checks.
    member = None
    if not operator:
        member = await require_member(db, task, actor_ref, provider, session_id, joining=payload.operation == "JOIN")
    original = payload.model_dump(mode="json")
    digest = canonical_json_sha256(original)
    old = await prior(db, task.project_id, actor_ref, payload.idempotency_key)
    if old is not None:
        if (old.task_id != task.id or old.provider != provider or old.session_id != session_id
                or old.input_digest != digest or old.operation != payload.operation):
            raise HTTPException(409, "COLLABORATION_KEY_CONFLICT")
        return old.response
    if parent.deleted_at is not None or task.deleted_at is not None:
        raise HTTPException(409, "COLLABORATION_TASK_DELETED")
    if task.version != payload.expected_version:
        raise HTTPException(409, "TASK_VERSION_CONFLICT")
    if payload.operation != "ENABLE" and not task.collaboration_enabled:
        raise HTTPException(409, "COLLABORATION_NOT_ENABLED")
    if payload.operation == "ENABLE" and task.collaboration_enabled:
        raise HTTPException(409, "COLLABORATION_ALREADY_ENABLED")
    before = public(task)
    clock = await db.scalar(select(func.clock_timestamp()))
    version = task.version + 1
    accepted_contributions = []
    operation = payload.operation
    if operation == "ENABLE":
        if task.binding_state != "BOUND":
            raise HTTPException(409, "TASK_BINDING_REQUIRED")
        await ensure_actor(db, task.project_id, task.owner_actor_ref)
        member = TaskSessionParticipant(id=uuid7(), task_id=task.id, project_id=task.project_id,
            provider=task.provider, session_id=task.session_id, actor_ref=task.owner_actor_ref,
            status="ACTIVE", role="PRIMARY", assignment="", initial_binding=True,
            task_version=version, authorized_at=clock, joined_at=None, created_at=clock)
        task.collaboration_enabled = True
        task.primary_participant_id = member.id
        task.primary_generation = 1
        db.add(member)
    elif operation == "AUTHORIZE":
        if payload.actor_ref != task.owner_actor_ref:
            raise HTTPException(403, "COLLABORATION_ACTOR_MISMATCH")
        await ensure_actor(db, task.project_id, payload.actor_ref)
        await check_source(db, task, payload.provider, payload.session_id)
        target = await participant(db, task.id, payload.provider, payload.session_id)
        if target is not None and target.status != "REVOKED":
            raise HTTPException(409, "COLLABORATION_PARTICIPANT_EXISTS")
        if target is None:
            target = TaskSessionParticipant(id=uuid7(), task_id=task.id, project_id=task.project_id,
                provider=payload.provider, session_id=payload.session_id, actor_ref=payload.actor_ref,
                role="CONTRIBUTOR", status="AUTHORIZED", assignment=payload.assignment,
                initial_binding=False, task_version=version, authorized_at=clock, created_at=clock)
            db.add(target)
        else:
            target.status, target.role = "AUTHORIZED", "CONTRIBUTOR"
            target.assignment, target.authorized_at = payload.assignment, clock
            target.task_version = version
    elif operation == "JOIN":
        if member.status != "AUTHORIZED":
            raise HTTPException(409, "COLLABORATION_ALREADY_JOINED")
        await check_source(db, task, provider, session_id)
        member.status, member.joined_at, member.revoked_at = "ACTIVE", clock, None
        member.task_version = version
    elif operation in {"REVOKE", "HANDOFF"}:
        target = await db.get(TaskSessionParticipant, payload.participant_id)
        if target is None or target.task_id != task.id:
            raise HTTPException(404, "COLLABORATION_PARTICIPANT_NOT_FOUND")
        if operation == "REVOKE":
            if target.status == "REVOKED":
                raise HTTPException(409, "COLLABORATION_ALREADY_REVOKED")
            if task.primary_participant_id == target.id:
                task.primary_participant_id = None
                task.primary_generation += 1
            target.status, target.role, target.revoked_at = "REVOKED", "CONTRIBUTOR", clock
            target.task_version = version
        else:
            if payload.expected_primary_generation != task.primary_generation:
                raise HTTPException(409, "COLLABORATION_PRIMARY_GENERATION_CONFLICT")
            if target.status != "ACTIVE":
                raise HTTPException(409, "COLLABORATION_HANDOFF_REQUIRES_ACTIVE_MEMBER")
            if target.id == task.primary_participant_id:
                raise HTTPException(409, "COLLABORATION_ALREADY_PRIMARY")
            if task.primary_participant_id is not None:
                previous = await db.get(TaskSessionParticipant, task.primary_participant_id)
                previous.role, previous.task_version = "CONTRIBUTOR", version
                # Flush the former role before the partial unique index admits
                # its successor. Task version is advanced below first.
            target.role, target.task_version = "PRIMARY", version
            task.primary_participant_id = target.id
            task.primary_generation += 1
    elif operation == "CONTRIBUTE":
        for item in payload.contributions:
            latest = await db.scalar(select(ContributionRevision).where(
                ContributionRevision.task_id == task.id, ContributionRevision.participant_id == member.id,
                ContributionRevision.kind == item.kind, ContributionRevision.stable_key == item.stable_key
            ).order_by(ContributionRevision.revision.desc()).limit(1))
            if item.expected_revision != (latest.revision if latest else 0):
                raise HTTPException(409, "COLLABORATION_REVISION_CONFLICT")
            row = ContributionRevision(id=uuid7(), task_id=task.id, participant_id=member.id,
                kind=item.kind, stable_key=item.stable_key, revision=item.expected_revision + 1,
                task_version=version, content=item.content, actor_ref=actor_ref,
                provider=provider, session_id=session_id, created_at=clock)
            db.add(row)
            accepted_contributions.append({"contribution_id": str(row.id), "revision": row.revision})
    elif operation == "PUBLISH":
        if (task.primary_participant_id != member.id or member.role != "PRIMARY"
                or payload.primary_generation != task.primary_generation):
            raise HTTPException(403, "COLLABORATION_PRIMARY_REQUIRED")
        for ref in payload.summary.contribution_refs:
            accepted = await db.get(ContributionRevision, ref.contribution_id)
            if accepted is None or accepted.task_id != task.id or accepted.revision != ref.revision:
                raise HTTPException(409, "COLLABORATION_CONTRIBUTION_REFERENCE_MISMATCH")
        for field in ("title", "objective", "status", "plan_markdown", "reported_result"):
            setattr(task, field, getattr(payload.summary, field))
        task.source, task.last_synced_at = "AGENT_REPORTED", clock
        db.add(TaskPublication(id=uuid7(), task_id=task.id, participant_id=member.id,
            task_version=version, primary_generation=task.primary_generation,
            summary=payload.summary.model_dump(mode="json"), created_at=clock))
    task.version = version
    if operator:
        task.last_managed_at = clock
    # Disable autoflush while operation branches build aggregate changes. The
    # parent must reach its new version before any child acceptance is flushed.
    await db.flush([task])
    if operation == "HANDOFF" and before["primary_participant_id"]:
        await db.flush([previous])
    await db.flush()
    state = await roster_snapshot(db, task)
    response = {"status": "ACCEPTED", "profile": COLLABORATION_PROFILE, "operation": operation,
        "task_id": str(task.id), "project_id": str(task.project_id), "actor_ref": actor_ref,
        "provider": provider, "session_id": session_id, "participant_id": str(member.id) if not operator else None,
        "version": version, "idempotency_key": payload.idempotency_key, "request_digest": digest,
        "primary_generation": task.primary_generation, "contribution_refs": accepted_contributions}
    db.add(CollaborationReceipt(id=uuid7(), task_id=task.id, project_id=task.project_id,
        actor_ref=actor_ref, operation=operation, idempotency_key=payload.idempotency_key,
        input_digest=digest, task_version=version, provider=provider, session_id=session_id,
        participant_id=member.id if not operator else None, request_payload=original,
        task_snapshot=public(task), collaboration_snapshot=state, response=response, created_at=clock))
    record_change(db, task, before, "COLLABORATION_" + operation, version=version, actor_ref=actor_ref)
    if authorization_check:
        await authorization_check()
    await db.commit()
    return response
