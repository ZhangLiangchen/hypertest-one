"""Authenticated, optional project experience Gateway. No model or test execution."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.cloud_routes import secure_transport
from hypertest.api.interactive_routes import bearer, controlled_errors
from hypertest.api.memory_schemas import MemoryMutation, MemoryQuery
from hypertest.application import memory_gateway as service
from hypertest.application.cloud_tasks import WorkerIdentity, _contains_secret
from hypertest.connector.security import require_operator
from hypertest.db.session import get_db

router = APIRouter(tags=["project-memory"])


def worker_identity(request):
    names = ["x-hypertest-memory-worker-id", "x-hypertest-memory-lease-token",
             "x-hypertest-memory-generation", "x-hypertest-memory-work-token"]
    values = [request.headers.get(name) for name in names]
    if not any(value is not None for value in values):
        return None
    if any(not value or len(value) > 512 for value in values):
        raise HTTPException(403, "Complete private Worker memory proof required")
    try:
        generation = int(values[2])
    except ValueError:
        raise HTTPException(403, "Worker memory generation invalid") from None
    if generation < 1:
        raise HTTPException(403, "Worker memory generation invalid")
    return WorkerIdentity(values[0], values[1], generation, values[3])


def reject_transport_secrets(payload, authorization, operator_key):
    # Request-only bearer/header values are never added to ActorContext, the
    # approved body, a receipt, a persistent journal or upstream metadata.
    secrets = [operator_key] if operator_key else []
    if authorization and authorization.lower().startswith("bearer "):
        secrets.append(authorization[7:])
    values = payload.model_dump(mode="json")
    if any(secret and _contains_secret(values, secret.encode()) for secret in secrets):
        raise HTTPException(422, "Credential material is not accepted experience input")


async def identity(request, db, project_id, scope, authorization, operator_key):
    secure_transport(request)
    worker = worker_identity(request)
    if operator_key is not None:
        if worker is not None:
            raise HTTPException(403, "Worker memory requires an independent integration grant")
        return service.ActorContext("operator:" + await require_operator(operator_key), operator=True)
    return await service.authenticate(db, bearer(request, authorization), scope, project_id, worker=worker)


@router.post("/memory/operations")
@controlled_errors
async def operate(payload: MemoryMutation, request: Request,
                  authorization: str | None = Header(default=None),
                  x_hypertest_operator_key: str | None = Header(default=None),
                  db: AsyncSession = Depends(get_db)):
    context = await identity(request, db, payload.project_id, service.SCOPES[payload.operation],
                             authorization, x_hypertest_operator_key)
    reject_transport_secrets(payload, authorization, x_hypertest_operator_key)
    return await service.operate(db, payload, context)


@router.post("/memory/query")
@controlled_errors
async def query(payload: MemoryQuery, request: Request,
                authorization: str | None = Header(default=None),
                x_hypertest_operator_key: str | None = Header(default=None),
                db: AsyncSession = Depends(get_db)):
    context = await identity(request, db, payload.project_id, "memory:read", authorization, x_hypertest_operator_key)
    reject_transport_secrets(payload, authorization, x_hypertest_operator_key)
    return await service.query(db, payload, context)


@router.get("/memory/operations/by-key")
@controlled_errors
async def receipt(project_id: UUID, operation_key: str, request: Request,
                  authorization: str | None = Header(default=None),
                  x_hypertest_operator_key: str | None = Header(default=None),
                  db: AsyncSession = Depends(get_db)):
    context = await identity(request, db, project_id, None, authorization, x_hypertest_operator_key)
    return await service.read_receipt(db, project_id, operation_key, context)


@router.get("/memory/entries/{entry_id}")
@controlled_errors
async def entry(entry_id: UUID, project_id: UUID, request: Request,
                version: int | None = Query(default=None, ge=1),
                authorization: str | None = Header(default=None),
                x_hypertest_operator_key: str | None = Header(default=None),
                db: AsyncSession = Depends(get_db)):
    context = await identity(request, db, project_id, "memory:read", authorization, x_hypertest_operator_key)
    return await service.read_entry(db, project_id, entry_id, version, context)


@router.get("/memory/projects/{project_id}/configuration")
@controlled_errors
async def configuration(project_id: UUID, request: Request,
                        version: int | None = Query(default=None, ge=1),
                        authorization: str | None = Header(default=None),
                        x_hypertest_operator_key: str | None = Header(default=None),
                        db: AsyncSession = Depends(get_db)):
    context = await identity(request, db, project_id, "memory:read", authorization, x_hypertest_operator_key)
    return await service.configuration(db, project_id, context, version=version)


@router.get("/memory/projects/{project_id}")
@controlled_errors
async def overview(project_id: UUID, request: Request,
                   offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
                   status: str | None = Query(default=None, pattern=r"^(CANDIDATE|PUBLISHED|RETRACTED)$"),
                   authorization: str | None = Header(default=None),
                   x_hypertest_operator_key: str | None = Header(default=None),
                   db: AsyncSession = Depends(get_db)):
    context = await identity(request, db, project_id, "memory:read", authorization, x_hypertest_operator_key)
    return await service.overview(db, project_id, context, offset=offset, limit=limit, status=status)
