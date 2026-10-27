"""Scoped archive HTTPS API; management uses the explicit trusted Operator boundary."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.archive_schemas import (
    MAX_BYTES,
    PROFILE,
    ArchiveAuthorize,
    ArchivePublish,
    ArchiveSubmit,
    ArchiveSubtaskCreate,
    ArchiveTaskCreate,
    ArchiveTaskUpdate,
)
from hypertest.api.interactive_routes import bearer, controlled_errors
from hypertest.application import interactive
from hypertest.application import local_archive as service
from hypertest.connector.security import require_operator
from hypertest.db.session import get_db
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveIntegrationGrant,
)

router = APIRouter(prefix="/local-archive", tags=["local-archive"])


async def identity(request, db, project_id, authorization, operator_key, *, write=False, lock=False):
    if operator_key is not None and not write:
        return "operator:" + await require_operator(operator_key), None, True
    token = bearer(request, authorization)
    grant = await interactive.authenticate(db, token, "archive:write" if write else "archive:read", project_id=project_id)
    if write:
        await interactive.authenticate(db, token, "archive:read", project_id=project_id)
    if lock:
        for model, predicates in (
            (InteractiveActorIdentity, [InteractiveActorIdentity.id == grant.actor_identity_id]),
            (InteractiveClientRegistration, [InteractiveClientRegistration.actor_identity_id == grant.actor_identity_id,
                InteractiveClientRegistration.client_instance_id == grant.client_instance_id]),
            (InteractiveIntegrationGrant, [InteractiveIntegrationGrant.id == grant.id]),
        ):
            await db.scalar(select(model).where(*predicates).with_for_update(read=True).execution_options(populate_existing=True))
        grant = await interactive.authenticate(db, token, "archive:write" if write else "archive:read", project_id=project_id)
        if write:
            await interactive.authenticate(db, token, "archive:read", project_id=project_id)
    return "interactive:" + str(grant.actor_identity_id), grant.client_instance_id, False


@router.get("/capabilities")
@controlled_errors
async def capabilities(request: Request, project_id: UUID,
                       authorization: str | None = Header(default=None),
                       x_hypertest_operator_key: str | None = Header(default=None),
                       db: AsyncSession = Depends(get_db)):
    await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    await service.project(db, project_id)
    return {"profile": PROFILE, "implemented": True, "configured": True,
        "asset_kinds": ["PLAN", "CASE", "REPORT"], "max_request_bytes": MAX_BYTES,
        "max_text_chars": 262144, "max_plans": 16, "max_cases": 200, "max_reports": 16,
        "max_case_steps": 100, "max_page_chars": 24000, "optional_subtask": True,
        "legacy_local_new_writes": False}


@router.get("/actors")
async def actors(project_id: UUID, operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.actors(db, project_id)


@router.post("/tasks")
async def create(payload: ArchiveTaskCreate, operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.manage(db, payload, "operator:" + operator, "CREATE")


@router.post("/tasks/{task_id}/update")
async def update(task_id: UUID, payload: ArchiveTaskUpdate, operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.manage(db, payload, "operator:" + operator, "UPDATE", task_id)


@router.post("/tasks/{task_id}/subtasks")
async def create_subtask(task_id: UUID, payload: ArchiveSubtaskCreate, operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.manage(db, payload, "operator:" + operator, "SUBTASK_CREATE", task_id)


@router.post("/tasks/{task_id}/authorize")
async def authorize(task_id: UUID, payload: ArchiveAuthorize, operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.manage(db, payload, "operator:" + operator, "AUTHORIZE", task_id)


@router.post("/tasks/{task_id}/publications")
async def publish(task_id: UUID, payload: ArchivePublish, operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.manage(db, payload, "operator:" + operator, "PUBLISH", task_id)


@router.get("/operations/by-key")
async def operation(project_id: UUID, idempotency_key: str = Query(min_length=1, max_length=128),
                    operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.operation_by_key(db, project_id, "operator:" + operator, idempotency_key)


@router.get("/tasks")
@controlled_errors
async def listing(request: Request, project_id: UUID, limit: int = Query(default=50, ge=1, le=100),
                  offset: int = Query(default=0, ge=0), authorization: str | None = Header(default=None),
                  x_hypertest_operator_key: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    actor, _, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await service.list_tasks(db, project_id, actor, operator, limit, offset)


@router.get("/tasks/{task_id}")
@controlled_errors
async def detail(task_id: UUID, request: Request, project_id: UUID,
                 authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
                 db: AsyncSession = Depends(get_db)):
    actor, _, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await service.detail(db, project_id, task_id, actor, operator)


@router.post("/tasks/{task_id}/submissions")
@controlled_errors
async def submit(task_id: UUID, payload: ArchiveSubmit, request: Request,
                 authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    if len(await request.body()) > MAX_BYTES:
        raise HTTPException(413, "ARCHIVE_BODY_EXCEEDS_2_MIB")
    if task_id != payload.task_id:
        raise HTTPException(422, "ARCHIVE_TASK_ID_MISMATCH")
    actor, client, _ = await identity(request, db, payload.project_id, authorization, None, write=True)
    locked = False

    async def recheck():
        nonlocal locked
        current = await identity(request, db, payload.project_id, authorization, None, write=True, lock=not locked)
        if current != (actor, client, False):
            raise HTTPException(403, "ARCHIVE_AUTHORIZATION_CHANGED")
        locked = True

    return await service.submit(db, payload, actor, client, authorization_check=recheck)


@router.get("/submissions/by-key")
@controlled_errors
async def receipt(request: Request, project_id: UUID, idempotency_key: str = Query(min_length=1, max_length=128),
                  authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    actor, _, _ = await identity(request, db, project_id, authorization, None)
    return await service.submission_by_key(db, project_id, actor, idempotency_key)


@router.get("/submissions/{submission_id}")
@controlled_errors
async def submission(submission_id: UUID, request: Request, project_id: UUID,
                     offset: int = Query(default=0, ge=0), limit: int = Query(default=24000, ge=1, le=24000),
                     authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
                     db: AsyncSession = Depends(get_db)):
    actor, _, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await service.read_submission(db, project_id, submission_id, actor, operator, offset, limit)


@router.get("/tasks/{task_id}/archive")
@controlled_errors
async def root_archive(task_id: UUID, request: Request, project_id: UUID,
                       archive_version: int | None = Query(default=None, ge=1),
                       offset: int = Query(default=0, ge=0), limit: int = Query(default=24000, ge=1, le=24000),
                       authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
                       db: AsyncSession = Depends(get_db)):
    actor, _, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await service.read_archive(db, project_id, task_id, None, actor, operator, archive_version, offset, limit)


@router.get("/tasks/{task_id}/subtasks/{subtask_id}/archive")
@controlled_errors
async def child_archive(task_id: UUID, subtask_id: UUID, request: Request, project_id: UUID,
                        archive_version: int | None = Query(default=None, ge=1),
                        offset: int = Query(default=0, ge=0), limit: int = Query(default=24000, ge=1, le=24000),
                        authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
                        db: AsyncSession = Depends(get_db)):
    actor, _, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    return await service.read_archive(db, project_id, task_id, subtask_id, actor, operator, archive_version, offset, limit)
