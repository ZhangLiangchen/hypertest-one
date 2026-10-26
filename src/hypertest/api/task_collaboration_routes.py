"""Versioned Local collaboration, with the existing management and grant boundaries."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.interactive_routes import controlled_errors
from hypertest.api.task_collaboration_schemas import (
    CollaborationMemberOperation,
    CollaborationOperatorOperation,
)
from hypertest.api.task_routes import identity
from hypertest.application import task_collaboration as service
from hypertest.application.task_binding import creator_ref
from hypertest.db.session import get_db

router = APIRouter(tags=["local-task-collaboration"])


@router.get("/tasks/{task_id}/collaboration")
async def operator_document(task_id: UUID, version: int | None = Query(default=None, ge=1),
                            include_deleted: bool = False, db: AsyncSession = Depends(get_db)):
    return await service.document(db, task_id, version=version, include_deleted=include_deleted)


@router.post("/tasks/{task_id}/collaboration")
@controlled_errors
async def operator_change(task_id: UUID, payload: CollaborationOperatorOperation,
                          db: AsyncSession = Depends(get_db)):
    return await service.change(db, task_id, payload)


@router.get("/tasks/{task_id}/collaboration/receipts/by-key")
async def operator_receipt(task_id: UUID, idempotency_key: str, db: AsyncSession = Depends(get_db)):
    return await service.receipt(db, task_id, creator_ref(), idempotency_key)


@router.get("/interactive/tasks/{task_id}/collaboration")
@controlled_errors
async def member_document(task_id: UUID, request: Request, project_id: UUID, provider: str, session_id: str,
                          version: int | None = Query(default=None, ge=1),
                          offset: int = Query(default=0, ge=0), limit: int = Query(default=24000, ge=1, le=24000),
                          authorization: str | None = Header(default=None),
                          x_hypertest_operator_key: str | None = Header(default=None),
                          db: AsyncSession = Depends(get_db)):
    actor, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    if operator:
        raise HTTPException(403, "COLLABORATION_REQUIRES_INTEGRATION_ACTOR")
    return await service.document_page(db, task_id, project_id=project_id, actor_ref=actor,
        provider=provider, session_id=session_id, version=version, offset=offset, limit=limit)


@router.get("/interactive/tasks/{task_id}/collaboration/receipts/by-key")
@controlled_errors
async def member_receipt(task_id: UUID, request: Request, project_id: UUID, provider: str,
                         session_id: str, idempotency_key: str,
                         authorization: str | None = Header(default=None),
                         x_hypertest_operator_key: str | None = Header(default=None),
                         db: AsyncSession = Depends(get_db)):
    actor, operator = await identity(request, db, project_id, authorization, x_hypertest_operator_key)
    if operator:
        raise HTTPException(403, "COLLABORATION_REQUIRES_INTEGRATION_ACTOR")
    return await service.receipt(db, task_id, actor, idempotency_key, project_id=project_id,
                                 provider=provider, session_id=session_id)


@router.post("/interactive/tasks/{task_id}/collaboration")
@controlled_errors
async def member_change(task_id: UUID, payload: CollaborationMemberOperation, request: Request,
                        authorization: str | None = Header(default=None),
                        x_hypertest_operator_key: str | None = Header(default=None),
                        db: AsyncSession = Depends(get_db)):
    actor, operator = await identity(request, db, payload.project_id, authorization, x_hypertest_operator_key)
    if operator:
        raise HTTPException(403, "COLLABORATION_REQUIRES_INTEGRATION_ACTOR")
    locked = False

    async def recheck():
        nonlocal locked
        current = await identity(request, db, payload.project_id, authorization,
                                 x_hypertest_operator_key, lock_authority=not locked)
        if current != (actor, False):
            raise HTTPException(403, "Collaboration authorization changed")
        locked = True

    return await service.change(db, task_id, payload, actor_ref=actor, authorization_check=recheck)


@router.get("/tasks/{task_id}/collaboration/capabilities")
async def collaboration_capabilities(task_id: UUID, db: AsyncSession = Depends(get_db)):
    await service.document(db, task_id)
    from hypertest.api.task_collaboration_schemas import COLLABORATION_PROFILE
    return {"profile": COLLABORATION_PROFILE, "operations": [
        "ENABLE", "AUTHORIZE", "JOIN", "REVOKE", "CONTRIBUTE", "PUBLISH", "HANDOFF"],
        "source_fence": "LOCAL_SUPPORTED_HOST_CALLER", "same_actor_only": True,
        "legacy_full_sync_after_enable": False, "receipt_not_found_authorizes_replay": False}
