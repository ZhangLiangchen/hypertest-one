"""ADR-018 scoped sync API plus read-only management views for the existing Web boundary."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.interactive_routes import bearer, controlled_errors
from hypertest.api.schemas import ManagementVersion
from hypertest.api.task_schemas import (
    LocalTaskCreate,
    SessionTaskSync,
    SessionTaskUpdate,
    TaskBind,
    TaskBindingAuthorization,
)
from hypertest.application import interactive
from hypertest.application import session_tasks as service
from hypertest.application import task_binding
from hypertest.connector.security import require_operator
from hypertest.db.session import get_db
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveIntegrationGrant,
)

router = APIRouter(tags=["session-task-management"])


async def identity(request, db, project_id, authorization, operator_key, *, lock_authority=False):
    if operator_key is not None:
        actor = await require_operator(operator_key)
        return "operator:" + actor, True
    token = bearer(request, authorization)
    grant = await interactive.authenticate(db, token, "task:sync", project_id=project_id)
    if lock_authority:
        # Match the existing authority lock order. Hold shared locks through the
        # write transaction so revoke cannot complete ahead of a later commit.
        for model, predicates in (
            (InteractiveActorIdentity, [InteractiveActorIdentity.id == grant.actor_identity_id]),
            (InteractiveClientRegistration, [
                InteractiveClientRegistration.actor_identity_id == grant.actor_identity_id,
                InteractiveClientRegistration.client_instance_id == grant.client_instance_id,
            ]),
            (InteractiveIntegrationGrant, [InteractiveIntegrationGrant.id == grant.id]),
        ):
            await db.scalar(select(model).where(*predicates).with_for_update(read=True)
                            .execution_options(populate_existing=True))
        grant = await interactive.authenticate(db, token, "task:sync", project_id=project_id)
    return "interactive:" + str(grant.actor_identity_id), False


@router.post("/interactive/tasks/sync")
@controlled_errors
async def sync(payload: SessionTaskSync, request: Request,
               authorization: str | None = Header(default=None),
               x_hypertest_operator_key: str | None = Header(default=None),
               db: AsyncSession = Depends(get_db)):
    actor, operator = await identity(request, db, payload.project_id, authorization, x_hypertest_operator_key)
    authority_locked = False

    async def recheck_authority():
        nonlocal authority_locked
        current = await identity(request, db, payload.project_id, authorization,
                                 x_hypertest_operator_key, lock_authority=not authority_locked)
        if current != (actor, operator):
            raise HTTPException(403, "Task synchronization authorization changed")
        authority_locked = True

    return await service.sync_task(db, payload, actor, operator=operator,
                                   authorization_check=recheck_authority)


@router.get("/interactive/tasks/by-session")
@controlled_errors
async def by_session(request: Request, project_id: UUID, provider: str, session_id: str,
                     version: int | None = Query(default=None, ge=1),
                     offset: int = Query(default=0, ge=0),
                     limit: int = Query(default=24_000, ge=1, le=24_000),
                     authorization: str | None = Header(default=None),
                     x_hypertest_operator_key: str | None = Header(default=None),
                     db: AsyncSession = Depends(get_db)):
    actor, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await service.by_session(db, project_id, provider, session_id, actor, operator=operator,
                                    version=version, offset=offset, limit=limit)


@router.get("/interactive/tasks/syncs/by-key")
@controlled_errors
async def receipt(request: Request, project_id: UUID, idempotency_key: str,
                  authorization: str | None = Header(default=None),
                  x_hypertest_operator_key: str | None = Header(default=None),
                  db: AsyncSession = Depends(get_db)):
    actor, _ = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await service.receipt_view(db, project_id, actor, idempotency_key)


@router.post("/interactive/tasks/bind")
@controlled_errors
async def bind(payload: TaskBind, request: Request,
               authorization: str | None = Header(default=None),
               x_hypertest_operator_key: str | None = Header(default=None),
               db: AsyncSession = Depends(get_db)):
    actor, operator = await identity(request, db, payload.project_id, authorization, x_hypertest_operator_key)
    if operator:
        raise HTTPException(403, "TASK_BINDING_REQUIRES_INTEGRATION_ACTOR")
    locked = False

    async def recheck():
        nonlocal locked
        current = await identity(request, db, payload.project_id, authorization,
                                 x_hypertest_operator_key, lock_authority=not locked)
        if current != (actor, False):
            raise HTTPException(403, "Task binding authorization changed")
        locked = True

    return await task_binding.bind_task(db, payload, actor, authorization_check=recheck)


@router.get("/interactive/tasks/bindings/by-key")
@controlled_errors
async def bind_receipt(request: Request, project_id: UUID, idempotency_key: str,
                       authorization: str | None = Header(default=None),
                       x_hypertest_operator_key: str | None = Header(default=None),
                       db: AsyncSession = Depends(get_db)):
    actor, _ = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await task_binding.binding_receipt(db, project_id, actor, idempotency_key)


@router.get("/interactive/tasks/{task_id}")
@controlled_errors
async def binding_target(task_id: UUID, request: Request, project_id: UUID,
                         version: int | None = Query(default=None, ge=1),
                         offset: int = Query(default=0, ge=0), limit: int = Query(default=24000, ge=1, le=24000),
                         authorization: str | None = Header(default=None),
                         x_hypertest_operator_key: str | None = Header(default=None),
                         db: AsyncSession = Depends(get_db)):
    actor, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await service.by_task_id(db, project_id, task_id, actor, operator=operator,
                                    version=version, offset=offset, limit=limit)


# Operator Web intents share the established trusted management boundary.
@router.post("/projects/{project_id}/local-tasks")
async def create_local_task(project_id: UUID, payload: LocalTaskCreate,
                            db: AsyncSession = Depends(get_db)):
    return await task_binding.create_task(db, project_id, payload)


@router.get("/projects/{project_id}/local-tasks/by-key")
async def created_task_receipt(project_id: UUID, idempotency_key: str, db: AsyncSession = Depends(get_db)):
    return await task_binding.creation_view(db, project_id, idempotency_key)


@router.get("/projects/{project_id}/local-task-actors")
async def local_task_actors(project_id: UUID, db: AsyncSession = Depends(get_db)):
    return await task_binding.local_actors(db, project_id)


@router.patch("/tasks/{task_id}/binding-authorization")
async def authorize_task(task_id: UUID, payload: TaskBindingAuthorization,
                          db: AsyncSession = Depends(get_db)):
    return await service.manage_task(db, task_id, payload.expected_version,
        changes={"intended_actor_ref": payload.intended_actor_ref}, action="AUTHORIZE")


# These read routes deliberately follow existing /projects and /test-runs Web
# deployment access controls. They never expose the Operator or grant token.
@router.get("/tasks")
async def tasks(project_id: UUID, limit: int = Query(default=50, ge=1, le=100),
                offset: int = Query(default=0, ge=0), include_deleted: bool = False,
                db: AsyncSession = Depends(get_db)):
    return await service.list_tasks(db, project_id, limit=limit, offset=offset,
                                    include_deleted=include_deleted)


@router.get("/tasks/{task_id}")
async def detail(task_id: UUID, version: int | None = Query(default=None, ge=1),
                 include_deleted: bool = False,
                 db: AsyncSession = Depends(get_db)):
    return await service.get_task(db, task_id, version=version, include_deleted=include_deleted)


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: UUID, payload: SessionTaskUpdate, db: AsyncSession = Depends(get_db)):
    return await service.manage_task(db, task_id, payload.expected_version,
        changes=payload.model_dump(exclude_unset=True, exclude={"expected_version"}))


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: UUID, expected_version: int = Query(ge=1),
                      db: AsyncSession = Depends(get_db)):
    return await service.manage_task(db, task_id, expected_version, action="DELETE")


@router.post("/tasks/{task_id}/restore")
async def restore_task(task_id: UUID, payload: ManagementVersion, db: AsyncSession = Depends(get_db)):
    return await service.manage_task(db, task_id, payload.expected_version, action="RESTORE")


@router.get("/tasks/{task_id}/reports/{report_id}")
async def report(task_id: UUID, report_id: UUID, db: AsyncSession = Depends(get_db)):
    return await service.read_report(db, task_id, report_id)
