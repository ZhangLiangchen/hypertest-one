"""Atomic task/plan/case/report synchronization. Contains no execution dispatch."""
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text

from hypertest.api.task_schemas import PROFILE
from hypertest.application.services import canonical_json_sha256
from hypertest.common.ids import uuid7
from hypertest.domain.models import AuditEvent, OutboxEvent, Project
from hypertest.domain.session_tasks import (
    CaseRevision,
    ReportRevision,
    SessionTask,
    SyncReceipt,
    TaskManagementRevision,
)


def public(row):
    def convert(value):
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value
    return {column.name: convert(getattr(row, column.name)) for column in row.__table__.columns}


async def project(db, project_id, *, include_deleted=False, lock=False):
    query = select(Project).where(Project.id == project_id)
    if lock:
        query = query.with_for_update(read=True).execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None or (row.deleted_at is not None and not include_deleted):
        raise HTTPException(404, "Project not found")
    return row


async def prior_receipt(db, project_id, actor_ref, key):
    return await db.scalar(select(SyncReceipt).where(
        SyncReceipt.project_id == project_id, SyncReceipt.actor_ref == actor_ref,
        SyncReceipt.idempotency_key == key))


def receipt_projection(row):
    """Expose correlation fields without copying a stored snapshot or history."""
    return {
        "status": row.response["status"], "profile": row.response["profile"],
        "task_id": str(row.task_id), "project_id": str(row.project_id),
        "provider": row.task_snapshot["provider"], "session_id": row.task_snapshot["session_id"],
        "version": row.task_version, "idempotency_key": row.idempotency_key,
        "source": "AGENT_REPORTED",
    }


async def receipt_view(db, project_id, actor_ref, key):
    # Original accepted receipts remain queryable for UNKNOWN reconciliation,
    # including after a task or its Project was soft deleted.
    await project(db, project_id, include_deleted=True)
    row = await prior_receipt(db, project_id, actor_ref, key)
    if row is None:
        raise HTTPException(404, "Sync receipt not found; this does not authorize replay")
    return receipt_projection(row)


async def sync_task(db, payload, actor_ref, *, operator=False,
                    authorization_check: Callable[[], Awaitable[None]] | None = None):
    parent = await project(db, payload.project_id, include_deleted=True, lock=True)
    original = payload.model_dump(mode="json")
    digest = canonical_json_sha256(original)
    # The provider/session identity is global. This transaction-scoped DB lock
    # serializes even first admission, including competing Project assignments.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                     {"identity": f"session-task:{payload.provider}:{payload.session_id}"})
    # A distinct session using the same actor/Project/key must also serialize.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                     {"identity": f"session-sync:{actor_ref}:{payload.project_id}:{payload.idempotency_key}"})
    if authorization_check is not None:
        # Initial request authentication can become stale while waiting for the
        # aggregate locks. Recheck only after those waits, retaining authority
        # locks until this transaction finishes.
        await authorization_check()
    old = await prior_receipt(db, payload.project_id, actor_ref, payload.idempotency_key)
    if old:
        if old.input_digest != digest:
            raise HTTPException(409, "Sync idempotency key conflicts with original input")
        return receipt_projection(old)
    if parent.deleted_at is not None:
        raise HTTPException(404, "Project not found")
    task = await db.scalar(select(SessionTask).where(
        SessionTask.provider == payload.provider, SessionTask.session_id == payload.session_id
    ).with_for_update().execution_options(populate_existing=True))
    clock = await db.scalar(select(func.clock_timestamp()))
    if task:
        if task.deleted_at is not None:
            raise HTTPException(409, "Session task is deleted; restore it explicitly before synchronization")
        if task.project_id != payload.project_id:
            raise HTTPException(409, "Session is already assigned to another Project")
        if not operator and task.owner_actor_ref != actor_ref:
            raise HTTPException(403, "Session task belongs to another actor")
        if payload.expected_version != task.version:
            raise HTTPException(409, "Task version is stale; read current task before a new explicit sync")
        task.version += 1
    else:
        if payload.expected_version != 0:
            raise HTTPException(409, "New session task requires expected_version=0")
        task = SessionTask(id=uuid7(), project_id=payload.project_id, provider=payload.provider,
            session_id=payload.session_id, owner_actor_ref=actor_ref, version=1, created_at=clock)
        db.add(task)
    for field in ("title", "objective", "status", "plan_markdown", "reported_result"):
        setattr(task, field, getattr(payload, field))
    task.source = "AGENT_REPORTED"
    task.last_synced_at = clock
    await db.flush()
    changed_cases, changed_reports = 0, 0
    for model, submitted in ((CaseRevision, payload.cases), (ReportRevision, payload.reports)):
        for item in submitted:
            latest = await db.scalar(select(model).where(
                model.task_id == task.id, model.key == item.key).order_by(model.revision.desc()).limit(1))
            data = item.model_dump(mode="json")
            # Unchanged payloads retain the original revision; omitted keys also
            # remain present. Nothing here deletes a prior failure or report.
            if latest and all(getattr(latest, key) == value for key, value in data.items()):
                continue
            db.add(model(task_id=task.id, task_version=task.version,
                         revision=latest.revision + 1 if latest else 1, **data))
            if model is CaseRevision:
                changed_cases += 1
            else:
                changed_reports += 1
    response = {"status": "ACCEPTED", "profile": PROFILE, "task_id": str(task.id),
        "project_id": str(task.project_id), "provider": task.provider, "session_id": task.session_id,
        "version": task.version, "idempotency_key": payload.idempotency_key,
        "source": "AGENT_REPORTED"}
    db.add(SyncReceipt(task_id=task.id, project_id=task.project_id, actor_ref=actor_ref,
        idempotency_key=payload.idempotency_key, input_digest=digest, task_version=task.version,
        request_payload=original, task_snapshot=public(task), response=response))
    metadata = {"task_id": str(task.id), "version": task.version,
        "idempotency_key": payload.idempotency_key, "source": "AGENT_REPORTED",
        "changed_cases": changed_cases, "changed_reports": changed_reports}
    db.add(AuditEvent(project_id=task.project_id, actor_type="OPERATOR" if operator else "USER",
        actor_ref=actor_ref, action="session_task.synced", entity_type="SessionTask", entity_id=task.id,
        event_metadata=metadata))
    db.add(OutboxEvent(aggregate_type="SessionTask", aggregate_id=task.id,
        event_type="session_task.synced", payload=metadata))
    if authorization_check is not None:
        # Row locks fence revocation; a fresh clock also fences time-based expiry
        # during a large sync. Failure rolls back records, history and audit.
        await authorization_check()
    await db.commit()
    return response


async def list_tasks(db, project_id, *, limit=50, offset=0, include_deleted=False):
    await project(db, project_id, include_deleted=include_deleted)
    where = [SessionTask.project_id == project_id]
    if not include_deleted:
        where.append(SessionTask.deleted_at.is_(None))
    total = await db.scalar(select(func.count()).select_from(SessionTask).where(*where))
    rows = await db.scalars(select(SessionTask).where(*where).order_by(
        func.greatest(SessionTask.last_synced_at, SessionTask.last_managed_at).desc(),
        SessionTask.id).limit(limit).offset(offset))
    return {"items": [public(row) for row in rows], "total": total, "limit": limit, "offset": offset}


async def version_snapshot(db, task_id, version):
    for model in (SyncReceipt, TaskManagementRevision):
        row = await db.scalar(select(model).where(model.task_id == task_id, model.task_version == version))
        if row is not None:
            return row.task_snapshot
    raise HTTPException(404, "Task version not found")


async def get_task(db, task_id, *, version=None, project_id=None, actor_ref=None, operator=False,
                   include_deleted=False):
    task = await db.get(SessionTask, task_id)
    if (task is None or (task.deleted_at is not None and not include_deleted)
            or (project_id is not None and task.project_id != project_id)):
        raise HTTPException(404, "Session task not found in Project")
    await project(db, task.project_id, include_deleted=include_deleted)
    if actor_ref is not None and not operator and task.owner_actor_ref != actor_ref:
        raise HTTPException(403, "Session task belongs to another actor")
    selected = task.version if version is None else version
    receipts = list(await db.scalars(select(SyncReceipt).where(
        SyncReceipt.task_id == task.id, SyncReceipt.task_version <= selected
    ).order_by(SyncReceipt.task_version)))
    snapshot = await version_snapshot(db, task.id, selected)
    management = list(await db.scalars(select(TaskManagementRevision).where(
        TaskManagementRevision.task_id == task.id, TaskManagementRevision.task_version <= selected
    ).order_by(TaskManagementRevision.task_version)))
    histories = []
    currents = []
    for model in (CaseRevision, ReportRevision):
        rows = list(await db.scalars(select(model).where(
            model.task_id == task.id, model.task_version <= selected
        ).order_by(model.key, model.revision)))
        latest = {row.key: public(row) for row in rows}
        histories.append([public(row) for row in rows])
        currents.append(list(latest.values()))
    return {"task": snapshot, "cases": currents[0], "reports": currents[1],
        "case_history": histories[0], "report_history": histories[1],
        "management_history": [public(row) for row in management],
        "sync_history": [{key: value for key, value in public(row).items()
                          if key not in {"request_payload", "response", "input_digest"}} for row in receipts]}


async def by_session(db, project_id, provider, session_id, actor_ref, *, operator=False,
                     version=None, offset=0, limit=24_000):
    if offset < 0 or not 1 <= limit <= 24_000 or (offset > 0 and version is None):
        raise HTTPException(422, "Continuation requires a fixed version and bounded offset/limit")
    await project(db, project_id)
    task = await db.scalar(select(SessionTask).where(
        SessionTask.project_id == project_id, SessionTask.provider == provider, SessionTask.session_id == session_id))
    if task is None:
        raise HTTPException(404, "Session task not found in Project")
    if task.deleted_at is not None:
        raise HTTPException(404, "Session task not found in Project")
    if not operator and task.owner_actor_ref != actor_ref:
        raise HTTPException(403, "Session task belongs to another actor")
    selected = task.version if version is None else version
    document = {"task": await version_snapshot(db, task.id, selected)}
    # Select one latest revision per key at the pinned version. Do not assemble
    # the unbounded Web history (or duplicate current reports) for MCP transport.
    for model, key in ((CaseRevision, "cases"), (ReportRevision, "reports")):
        rows = await db.scalars(select(model).where(
            model.task_id == task.id, model.task_version <= selected
        ).distinct(model.key).order_by(model.key, model.revision.desc()))
        document[key] = [public(row) for row in rows]
    content = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if offset >= len(content):
        raise HTTPException(422, "Page offset is outside the fixed task version")
    end = min(offset + limit, len(content))
    return {"task_id": str(task.id), "version": selected, "format": "application/json",
            "source": "AGENT_REPORTED", "offset": offset, "total_chars": len(content),
            "next_offset": end if end < len(content) else None,
            "complete": end == len(content), "content": content[offset:end]}


async def read_report(db, task_id, report_id):
    task = await db.get(SessionTask, task_id)
    if task is None or task.deleted_at is not None:
        raise HTTPException(404, "Session task not found in Project")
    await project(db, task.project_id)
    report = await db.get(ReportRevision, report_id)
    if report is None or report.task_id != task_id:
        raise HTTPException(404, "Report revision not found in task")
    return public(report)


async def manage_task(db, task_id, expected_version, *, changes=None, action="UPDATE"):
    from hypertest.application.management import record_change

    candidate = await db.get(SessionTask, task_id)
    if candidate is None:
        raise HTTPException(404, "Session task not found in Project")
    # Project -> task is also the synchronization lock order. The shared parent
    # lock prevents restore/new writes racing a Project deletion.
    await project(db, candidate.project_id, lock=True)
    task = await db.scalar(select(SessionTask).where(SessionTask.id == task_id)
                           .with_for_update().execution_options(populate_existing=True))
    if task.deleted_at is not None and action != "RESTORE":
        raise HTTPException(404, "Session task not found in Project")
    if task.version != expected_version:
        raise HTTPException(409, "Task version is stale; refresh before changing it")
    if action == "RESTORE" and task.deleted_at is None:
        raise HTTPException(409, "Session task is not deleted")
    before = public(task)
    clock = await db.scalar(select(func.clock_timestamp()))
    if action == "UPDATE":
        changes = changes or {}
        if all(getattr(task, key) == value for key, value in changes.items()):
            return await get_task(db, task.id)
        for key, value in changes.items():
            setattr(task, key, value)
    if action in {"DELETE", "RESTORE"}:
        task.deleted_at = clock if action == "DELETE" else None
    task.version += 1
    task.last_managed_at = clock
    await db.flush()
    actor = record_change(db, task, before, action, version=task.version)
    db.add(TaskManagementRevision(task_id=task.id, task_version=task.version,
        action=action, actor_ref=actor, task_snapshot=public(task), created_at=clock))
    await db.commit()
    return await get_task(db, task.id, include_deleted=action == "DELETE")
