"""ADR-019 typed Cloud operations; API processes never start SDK or test commands."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.cloud_schemas import PROFILE, CloudMutation
from hypertest.api.interactive_routes import bearer, controlled_errors
from hypertest.application import cloud_tasks as service
from hypertest.application import interactive
from hypertest.cloud.errors import CloudBlocked
from hypertest.config import get_settings
from hypertest.connector.security import require_operator
from hypertest.db.session import get_db
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveIntegrationGrant,
)

router = APIRouter(tags=["cloud-task-management"])


def secure_transport(request: Request):
    settings = get_settings()
    if request.url.scheme != "https" and not (
        settings.connector_allow_insecure_loopback and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "Cloud credentials require HTTPS")


async def identity(request, db, project_id, scope, authorization, operator_key, *, lock=False):
    secure_transport(request)
    if operator_key is not None:
        return "operator:" + await require_operator(operator_key), True, None
    token = bearer(request, authorization)
    grant = await interactive.authenticate(db, token, scope, project_id=project_id)
    if lock:
        for model, predicates in (
            (InteractiveActorIdentity, [InteractiveActorIdentity.id == grant.actor_identity_id]),
            (InteractiveClientRegistration, [InteractiveClientRegistration.actor_identity_id == grant.actor_identity_id,
                                            InteractiveClientRegistration.client_instance_id == grant.client_instance_id]),
            (InteractiveIntegrationGrant, [InteractiveIntegrationGrant.id == grant.id]),
        ):
            await db.scalar(select(model).where(*predicates).with_for_update(read=True)
                            .execution_options(populate_existing=True))
        grant = await interactive.authenticate(db, token, scope, project_id=project_id)
    return "interactive:" + str(grant.actor_identity_id), False, grant


@router.get("/cloud/capabilities")
async def capabilities():
    settings = get_settings()
    return {"profile": PROFILE, "enabled": settings.cloud_enabled,
            "worker_enabled": settings.cloud_worker_enabled, "sdk_package_version": "0.2.1rc2",
            "support_semantics": "IMPLEMENTATION_NOT_ADMISSION",
            "configuration": {"cloud_enabled": settings.cloud_enabled,
                              "worker_enabled": settings.cloud_worker_enabled,
                              "codex_enabled": settings.cloud_codex_enabled,
                              "ssh_fixed_diagnostics_enabled": settings.cloud_ssh_enabled,
                              "https_controlled_api_enabled": settings.cloud_https_enabled},
            "admission": {"state": "NOT_CHECKED", "scope": "PER_ATTEMPT", "checked_by": "WORKER"},
            "recovery": {"resume_supported": False, "resume_reason": "SDK_RESUME_UNSUPPORTED",
                         "reconcile_supported": True, "reconciliation_source": "OPERATOR_ATTESTATION",
                         "independent_stop_proof": False, "budget_disposition": "KEEP_HELD"},
            "supported": {"repositories": ["HTTPS"], "environment_connections": ["NONE"],
                          "execution": "WORKSPACE_LOCAL", "root_agent": True,
                          "codex_delegation": True, "claude_code_delegation": False,
                          "ssh": False, "ssh_fixed_diagnostics": True,
                          "ssh_profile": "SSH_FIXED_DIAGNOSTICS_V1",
                          "https_controlled_api": True, "https_profile": "HTTPS_CONTROLLED_API_V1",
                          "https_methods": ["GET", "HEAD"], "framework_runtime_freeze": True,
                          "remote_ci": False, "project_framework": True,
                          "resume_attempt": False, "reconcile_attempt": True},
            "not_proven": ["provider_authentication", "model_execution", "delegation", "production_acceptance"]}


@router.post("/cloud/operations")
@controlled_errors
async def mutate(payload: CloudMutation, request: Request,
                 authorization: str | None = Header(default=None),
                 x_hypertest_operator_key: str | None = Header(default=None),
                 db: AsyncSession = Depends(get_db)):
    scope = service.SCOPES[payload.operation]
    if scope == "cloud:work":
        raise HTTPException(403, "Worker operations require the private fenced Worker broker")
    actor, operator, grant = await identity(request, db, payload.project_id, scope, authorization, x_hypertest_operator_key)
    locked = False

    async def recheck():
        nonlocal locked
        current, current_operator, current_grant = await identity(
            request, db, payload.project_id, scope, authorization, x_hypertest_operator_key, lock=not locked)
        if (current, current_operator) != (actor, operator) or (grant and current_grant.id != grant.id):
            raise HTTPException(403, "Cloud authorization changed")
        locked = True

    try:
        return await service.mutate(db, payload, actor, authorization_check=recheck,
                                    grant_id=grant.id if grant else None)
    except CloudBlocked as error:
        raise HTTPException(503, error.code) from None


@router.get("/cloud/projects/{project_id}/configuration")
@controlled_errors
async def configuration(project_id: UUID, request: Request,
                        authorization: str | None = Header(default=None),
                        x_hypertest_operator_key: str | None = Header(default=None),
                        db: AsyncSession = Depends(get_db)):
    await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    return await service.configuration(db, project_id)


@router.get("/cloud/projects/{project_id}/credentials")
@controlled_errors
async def credentials(project_id: UUID, request: Request,
                      authorization: str | None = Header(default=None),
                      x_hypertest_operator_key: str | None = Header(default=None),
                      db: AsyncSession = Depends(get_db)):
    await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    return await service.credentials(db, project_id)


@router.get("/cloud/operations/by-key")
@router.get("/cloud/projects/{project_id}/operations/{operation_key}")
@controlled_errors
async def receipt(project_id: UUID, operation_key: str, request: Request,
                  authorization: str | None = Header(default=None),
                  x_hypertest_operator_key: str | None = Header(default=None),
                  db: AsyncSession = Depends(get_db)):
    actor, operator, grant = await identity(request, db, project_id, None, authorization, x_hypertest_operator_key)
    if grant and not set(grant.scopes) & {"cloud:read", "cloud:configure", "credential:manage", "cloud:dispatch", "cloud:control"}:
        raise HTTPException(403, "Cloud receipt permission required")
    return await service.receipt_view(db, project_id, operation_key, actor, operator=operator)


@router.get("/cloud/tasks/{task_id}")
@controlled_errors
async def detail(task_id: UUID, project_id: UUID, request: Request,
                 version: int | None = Query(default=None, ge=1),
                 offset: int = Query(default=0, ge=0), limit: int = Query(default=24000, ge=1, le=24000),
                 authorization: str | None = Header(default=None),
                 x_hypertest_operator_key: str | None = Header(default=None),
                 db: AsyncSession = Depends(get_db)):
    await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    return await service.read_task(db, task_id, project_id=project_id, version=version, offset=offset, limit=limit)


@router.get("/cloud/tasks/{task_id}/summary")
@controlled_errors
async def summary(task_id: UUID, project_id: UUID, request: Request,
                  authorization: str | None = Header(default=None),
                  x_hypertest_operator_key: str | None = Header(default=None),
                  db: AsyncSession = Depends(get_db)):
    await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    return await service.task_summary(db, task_id, project_id=project_id)


@router.get("/cloud/tasks/{task_id}/artifacts/{artifact_id}")
@controlled_errors
async def artifact(task_id: UUID, artifact_id: UUID, project_id: UUID, request: Request,
                   offset: int = Query(default=0, ge=0), length: int = Query(default=65536, ge=1, le=65536),
                   authorization: str | None = Header(default=None),
                   x_hypertest_operator_key: str | None = Header(default=None),
                   db: AsyncSession = Depends(get_db)):
    await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    return await service.artifact_bytes(db, project_id, task_id, artifact_id, offset=offset, length=length)


@router.get("/cloud/projects/{project_id}/tasks")
@router.get("/projects/{project_id}/task-directory")
@controlled_errors
async def directory(project_id: UUID, request: Request,
                    task_kind: str | None = Query(default=None, pattern=r"^(CLOUD_TASK|SESSION_TASK)$"),
                    product_mode: str | None = Query(default=None, pattern=r"^(CLOUD|LOCAL)$"),
                    provider: str | None = Query(default=None, max_length=64),
                    offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
                    authorization: str | None = Header(default=None),
                    x_hypertest_operator_key: str | None = Header(default=None),
                    db: AsyncSession = Depends(get_db)):
    actor, operator, grant = await identity(request, db, project_id, None, authorization, x_hypertest_operator_key)
    cloud_allowed = operator or "cloud:read" in grant.scopes
    local_allowed = operator or "task:sync" in grant.scopes
    if not cloud_allowed and not local_allowed:
        raise HTTPException(403, "Task directory permission required")
    if request.url.path.endswith("/tasks"):
        task_kind = "CLOUD_TASK"
        if not cloud_allowed:
            raise HTTPException(403, "Cloud read permission required")
    result = await service.directory(db, project_id, actor_ref=actor, local_allowed=local_allowed,
        cloud_allowed=cloud_allowed, operator=operator, task_kind=task_kind, product_mode=product_mode,
        provider=provider, offset=offset, limit=limit)
    for item in result["items"]:
        item["id"] = item["task_id"]
    return result
