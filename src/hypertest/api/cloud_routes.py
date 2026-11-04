"""ADR-019 typed Cloud operations; API processes never start SDK or test commands."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.cloud_schemas import PROFILE, CloudMutation
from hypertest.api.interactive_routes import bearer, controlled_errors
from hypertest.application import cloud_agent_auth, interactive
from hypertest.application import cloud_tasks as service
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
            "recovery": {"resume_supported": True, "resume_reason": "EXPLICIT_ORIGINAL_SESSION_CONTINUATION",
                         "native_session_inspection_supported": False,
                         "native_session_inspection_reason": "NATIVE_SESSION_INSPECTION_UNSAFE_DISABLED",
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
                          "resume_attempt": True, "conversation": True, "reconcile_attempt": True},
            "not_proven": ["provider_authentication", "model_execution", "delegation", "production_acceptance"]}


@router.get("/cloud/agent-auth-status")
async def agent_auth_status(request: Request, response: Response,
                            x_hypertest_operator_key: str | None = Header(default=None),
                            db: AsyncSession = Depends(get_db)):
    """Global runtime observations are only visible at the operator boundary."""
    secure_transport(request)
    await require_operator(x_hypertest_operator_key)
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    return await cloud_agent_auth.read_auth_status(
        db, enabled=settings.cloud_enabled and settings.cloud_worker_enabled)


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


@router.get("/cloud/native-session-inspections/by-key")
@controlled_errors
async def native_session_inspection_by_key(project_id: UUID, operation_key: str, request: Request,
                                           authorization: str | None = Header(default=None),
                                           x_hypertest_operator_key: str | None = Header(default=None),
                                           db: AsyncSession = Depends(get_db)):
    actor, operator, _ = await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    from hypertest.application import cloud_native_session_restore
    return await cloud_native_session_restore.read_by_key(db, project_id=project_id, request_key=operation_key,
                                                          actor_ref=actor, operator=operator)


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
                    task_kind: str | None = Query(default=None, pattern=r"^CLOUD_TASK$"),
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


class LiveAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    project_id: UUID
    operation_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    answers: list[dict] = Field(default_factory=list, max_length=20)
    cancelled: bool = False


@router.get("/cloud/tasks/{task_id}/live-questions")
@controlled_errors
async def list_live_questions(task_id: UUID, project_id: UUID, request: Request, response: Response,
    authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)):
    from hypertest.application import cloud_live_questions as live_questions
    from hypertest.domain.cloud_tasks import CloudLiveQuestion
    await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    task = await service._task(db, task_id, project_id)
    rows = (await db.scalars(select(CloudLiveQuestion).where(CloudLiveQuestion.project_id == project_id,
        CloudLiveQuestion.task_id == task_id).order_by(CloudLiveQuestion.created_at, CloudLiveQuestion.id))).all()
    attempt = await service._attempt(db, task, task.latest_attempt_id) if task.latest_attempt_id else None
    result = [live_questions.projected(row, bool(attempt and await live_questions.live(db, task, attempt, row))) for row in rows]
    response.headers["Cache-Control"] = "no-store"
    return {"items": result}


@router.post("/cloud/tasks/{task_id}/live-questions/{question_id}/answer")
@controlled_errors
async def answer_live_question(task_id: UUID, question_id: UUID, body: LiveAnswer, request: Request,
    authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)):
    from hypertest.application import cloud_live_questions as live_questions
    from hypertest.domain.cloud_tasks import CloudLiveQuestion
    actor, _, _ = await identity(request, db, body.project_id, "cloud:control", authorization, x_hypertest_operator_key, lock=True)
    task, attempt = await live_questions.task_attempt(db, body.project_id, task_id)
    row = await live_questions.fetch_row(db, task, attempt, question_id)
    answer = {"answers": body.answers, "cancelled": body.cancelled}
    digest = service.canonical_json_sha256(answer)
    if row.answer_operation_key is not None:
        if row.answer_operation_key != body.operation_key or row.answer_digest != digest or row.answered_by != actor:
            raise HTTPException(409, "Live question already answered")
        return live_questions.projected(row, await live_questions.live(db, task, attempt, row))
    other = await db.scalar(select(CloudLiveQuestion.id).where(CloudLiveQuestion.project_id == body.project_id,
        CloudLiveQuestion.answer_operation_key == body.operation_key, CloudLiveQuestion.id != row.id))
    if other is not None:
        raise HTTPException(409, "Live answer operation key conflicts")
    if row.status != "OPEN" or not await live_questions.live(db, task, attempt, row):
        raise HTTPException(409, "Live question expired or fenced")
    live_questions.validate_answer(row.questions, answer)
    await service._reject_secrets(db, task.project_id, answer)
    if not await live_questions.live(db, task, attempt, row):
        raise HTTPException(409, "Live question expired or fenced")
    row.answer, row.answer_operation_key, row.answer_digest, row.answered_by = answer, body.operation_key, digest, actor
    row.status = "ANSWERED"
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Live answer operation key conflicts") from None
    result = live_questions.projected(row, True)
    await db.commit()
    return result
