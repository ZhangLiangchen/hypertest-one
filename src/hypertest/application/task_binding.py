"""Operator-created Local tasks and one-time, explicitly authorized source binding."""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, select, text

from hypertest.api.task_schemas import PROFILE
from hypertest.application.management import record_change
from hypertest.application.services import canonical_json_sha256
from hypertest.application.session_tasks import get_task, project, public
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveIntegrationGrant,
)
from hypertest.domain.session_tasks import SessionTask, TaskManagementRevision, TaskOperationReceipt


def creator_ref():
    return "web:" + get_settings().connector_operator_identity


def actor_query(project_id):
    return select(InteractiveActorIdentity).join(InteractiveIntegrationGrant,
        InteractiveIntegrationGrant.actor_identity_id == InteractiveActorIdentity.id).join(
        InteractiveClientRegistration, and_(
            InteractiveClientRegistration.actor_identity_id == InteractiveIntegrationGrant.actor_identity_id,
            InteractiveClientRegistration.client_instance_id == InteractiveIntegrationGrant.client_instance_id)).where(
        InteractiveActorIdentity.status == "ACTIVE", InteractiveClientRegistration.status == "ACTIVE",
        InteractiveIntegrationGrant.project_id == project_id,
        InteractiveIntegrationGrant.status == "ACTIVE",
        InteractiveIntegrationGrant.not_before <= func.clock_timestamp(),
        InteractiveIntegrationGrant.expires_at > func.clock_timestamp(),
        InteractiveIntegrationGrant.scopes.contains(["task:sync"]))


async def local_actors(db, project_id):
    await project(db, project_id)
    rows = (await db.scalars(actor_query(project_id).order_by(InteractiveActorIdentity.id))).unique().all()
    return {"items": [{"actor_ref": "interactive:" + str(row.id), "label": row.actor_ref}
                      for row in rows], "total": len(rows)}


async def ensure_actor(db, project_id, actor_ref):
    if actor_ref is None:
        return
    try:
        prefix, value = actor_ref.split(":", 1)
        if prefix != "interactive":
            raise ValueError
        actor_id = UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(422, "TASK_BINDING_ACTOR_UNAVAILABLE") from None
    row = await db.scalar(actor_query(project_id).where(InteractiveActorIdentity.id == actor_id)
                          .with_for_update(read=True).execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(422, "TASK_BINDING_ACTOR_UNAVAILABLE")


async def operation(db, project_id, actor_ref, key):
    return await db.scalar(select(TaskOperationReceipt).where(
        TaskOperationReceipt.project_id == project_id, TaskOperationReceipt.actor_ref == actor_ref,
        TaskOperationReceipt.idempotency_key == key))


async def creation_view(db, project_id, key):
    await project(db, project_id, include_deleted=True)
    row = await operation(db, project_id, creator_ref(), key)
    if row is None or row.operation != "CREATE":
        raise HTTPException(404, "TASK_CREATION_RECEIPT_NOT_FOUND")
    detail = await get_task(db, row.task_id, version=row.task_version, include_deleted=True)
    return {**detail, "creation_receipt": row.response}


async def create_task(db, project_id, payload):
    parent = await project(db, project_id, include_deleted=True, lock=True)
    actor = creator_ref()
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                     {"key": f"task-operation:{actor}:{project_id}:{payload.idempotency_key}"})
    digest = canonical_json_sha256(payload.model_dump(mode="json", exclude_unset=True))
    old = await operation(db, project_id, actor, payload.idempotency_key)
    if old is not None:
        if old.operation != "CREATE" or old.input_digest != digest:
            raise HTTPException(409, "TASK_OPERATION_KEY_CONFLICT")
        return await creation_view(db, project_id, payload.idempotency_key)
    if parent.deleted_at is not None:
        raise HTTPException(404, "Project not found")
    intended = payload.intended_actor_ref
    if "intended_actor_ref" not in payload.model_fields_set:
        available = await local_actors(db, project_id)
        if available["total"] == 1:
            intended = available["items"][0]["actor_ref"]
    await ensure_actor(db, project_id, intended)
    clock = await db.scalar(select(func.clock_timestamp()))
    task = SessionTask(id=uuid7(), project_id=project_id, title=payload.title,
        objective=payload.objective, plan_markdown=payload.plan_markdown,
        status="DRAFT", reported_result="NOT_RUN", version=1, created_at=clock,
        binding_state="UNBOUND", binding_required=True, creator_actor_ref=actor,
        intended_actor_ref=intended, provider=None, session_id=None, owner_actor_ref=None,
        source=None, last_synced_at=None, last_managed_at=clock)
    db.add(task)
    await db.flush()
    snapshot = public(task)
    response = {"status": "ACCEPTED", "operation": "CREATE", "project_id": str(project_id),
                "task_id": str(task.id), "version": 1, "idempotency_key": payload.idempotency_key}
    record_change(db, task, None, "CREATE", version=1)
    db.add(TaskManagementRevision(task_id=task.id, task_version=1, action="CREATE", actor_ref=actor,
                                 task_snapshot=snapshot, created_at=clock))
    db.add(TaskOperationReceipt(task_id=task.id, project_id=project_id, actor_ref=actor,
        operation="CREATE", idempotency_key=payload.idempotency_key, input_digest=digest,
        task_version=1, task_snapshot=snapshot, response=response, created_at=clock))
    await ensure_actor(db, project_id, intended)
    await db.commit()
    return await creation_view(db, project_id, payload.idempotency_key)


async def binding_receipt(db, project_id, actor_ref, key):
    await project(db, project_id, include_deleted=True)
    row = await operation(db, project_id, actor_ref, key)
    if row is None or row.operation != "BIND":
        raise HTTPException(404, "TASK_BINDING_RECEIPT_NOT_FOUND")
    return row.response


async def bind_task(db, payload, actor_ref, *, authorization_check):
    parent = await project(db, payload.project_id, include_deleted=True, lock=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))"),
                     {"identity": f"session-task:{payload.provider}:{payload.session_id}"})
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))"),
                     {"identity": f"task-operation:{actor_ref}:{payload.project_id}:{payload.idempotency_key}"})
    await authorization_check()
    digest = canonical_json_sha256(payload.model_dump(mode="json"))
    old = await operation(db, payload.project_id, actor_ref, payload.idempotency_key)
    if old is not None:
        if old.operation != "BIND" or old.input_digest != digest:
            raise HTTPException(409, "TASK_OPERATION_KEY_CONFLICT")
        return old.response
    if parent.deleted_at is not None:
        raise HTTPException(404, "Project not found")
    task = await db.scalar(select(SessionTask).where(SessionTask.id == payload.task_id,
        SessionTask.project_id == payload.project_id).with_for_update().execution_options(populate_existing=True))
    if task is None:
        raise HTTPException(404, "Session task not found in Project")
    if task.deleted_at is not None:
        raise HTTPException(409, "TASK_BINDING_DELETED")
    if task.intended_actor_ref is None:
        raise HTTPException(403, "TASK_BINDING_ACTOR_REQUIRED")
    if task.intended_actor_ref != actor_ref:
        raise HTTPException(403, "TASK_BINDING_ACTOR_MISMATCH")
    if task.binding_state != "UNBOUND":
        raise HTTPException(409, "TASK_ALREADY_BOUND")
    if task.version != payload.expected_version:
        raise HTTPException(409, "TASK_VERSION_CONFLICT")
    existing = await db.scalar(select(SessionTask).where(SessionTask.provider == payload.provider,
                                                        SessionTask.session_id == payload.session_id))
    if existing is not None:
        detail = {"code": "SESSION_ALREADY_HAS_TASK"}
        if existing.project_id == task.project_id and existing.owner_actor_ref == actor_ref:
            detail["existing_task_id"] = str(existing.id)
        raise HTTPException(409, detail)
    before = public(task)
    clock = await db.scalar(select(func.clock_timestamp()))
    task.binding_state, task.provider, task.session_id = "BOUND", payload.provider, payload.session_id
    task.owner_actor_ref, task.bound_at = actor_ref, clock
    task.version += 1
    await db.flush()
    snapshot = public(task)
    response = {"status": "ACCEPTED", "operation": "BIND", "profile": PROFILE,
        "task_id": str(task.id), "project_id": str(task.project_id), "provider": task.provider,
        "session_id": task.session_id, "actor_ref": actor_ref, "binding_state": "BOUND",
        "source": None, "version": task.version, "idempotency_key": payload.idempotency_key}
    # Bind ownership is recorded separately from Agent-produced sync history.
    record_change(db, task, before, "BIND", version=task.version, actor_ref=actor_ref)
    db.add(TaskOperationReceipt(task_id=task.id, project_id=task.project_id, actor_ref=actor_ref,
        operation="BIND", idempotency_key=payload.idempotency_key, input_digest=digest,
        task_version=task.version, task_snapshot=snapshot, response=response, created_at=clock))
    await authorization_check()
    await db.commit()
    return response
