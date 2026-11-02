"""Dedicated host Worker API; per-attempt capabilities remain fenced by the service."""

from __future__ import annotations

import base64
import hmac
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.cloud_routes import secure_transport
from hypertest.api.cloud_schemas import CloudMutation
from hypertest.api.interactive_routes import controlled_errors
from hypertest.application import cloud_tasks as service
from hypertest.cloud.errors import REPORT_CONTENT_REJECTED, CloudBlocked
from hypertest.cloud.private_file import read_private_file
from hypertest.config import get_settings
from hypertest.connector.security import token_hash
from hypertest.db.session import get_db
from hypertest.domain.cloud_tasks import (
    CloudArtifact,
    CloudInputResolution,
    CloudOperationReceipt,
    CloudWorkGrant,
)

router = APIRouter(prefix="/cloud/worker", tags=["cloud-worker"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Identity(Input):
    worker_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    lease_token: str = Field(min_length=16, max_length=512)
    generation: int = Field(ge=1)
    work_token: str = Field(min_length=16, max_length=512)

    def service_identity(self):
        return service.WorkerIdentity(self.worker_id, self.lease_token, self.generation, self.work_token)


class Claim(Input):
    worker_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    lease_seconds: int = Field(default=90, ge=15, le=300)
    supports_attempt_manifest: bool = Field(default=False, strict=True)


class AuthObservation(Input):
    status: Literal["VALID", "INVALID", "UNKNOWN"]


class Attempt(Input):
    identity: Identity
    project_id: UUID
    task_id: UUID
    attempt_id: UUID


class Renew(Attempt):
    lease_seconds: int = Field(default=90, ge=15, le=300)


class Fence(Attempt):
    reason: Literal["WORKER_INTERRUPTED", "WORKER_LEASE_UNCONFIRMED", "RUNTIME_TIMEOUT",
                    "REPORT_RECONCILIATION_PENDING", "ATTEMPT_RECOVERY_REQUIRED", "WORKER_RUNTIME_FAILED",
                    "REPORT_CONTENT_REJECTED"]


class Resolution(Input):
    identity: Identity
    project_id: UUID
    task_id: UUID
    resolution_id: UUID


class ResolutionAccept(Resolution):
    result: dict


class Submit(Attempt):
    payload: dict


class Receipt(Attempt):
    operation_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class Page(Attempt):
    version: int = Field(ge=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=24000, ge=1, le=24000)


class Artifact(Attempt):
    artifact_id: UUID


def authenticate_worker(request: Request, authorization: str | None = Header(default=None)) -> str:
    secure_transport(request)
    settings = get_settings()
    if not settings.cloud_enabled or not settings.cloud_worker_enabled or not settings.cloud_worker_api_worker_id:
        raise HTTPException(503, "Host Worker API is unavailable")
    if not settings.cloud_worker_api_token_file:
        raise HTTPException(503, "Host Worker API is unavailable")
    try:
        expected = read_private_file(settings.cloud_worker_api_token_file, max_bytes=512).strip()
    except CloudBlocked:
        raise HTTPException(503, "Host Worker API is unavailable") from None
    supplied = authorization[7:].encode() if authorization and authorization.startswith("Bearer ") else b""
    if len(expected) < 32 or len(supplied) > 512 or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Worker authentication required")
    return settings.cloud_worker_api_worker_id


def check_identity(worker_id: str, identity: Identity):
    if not hmac.compare_digest(worker_id, identity.worker_id):
        raise HTTPException(403, "Worker identity mismatch")


async def active(db, body: Attempt):
    task = await service._task(db, body.task_id, body.project_id)
    attempt = await service._attempt(db, task, body.attempt_id)
    await service.worker_authority(db, task, attempt, body.identity.service_identity())
    return task, attempt


async def original_read(db, body: Attempt):
    """The original work token can read only its own accepted records after fence."""
    task = await service._task(db, body.task_id, body.project_id)
    attempt = await service._attempt(db, task, body.attempt_id)
    grant = await db.scalar(select(CloudWorkGrant).where(
        CloudWorkGrant.token_hash == token_hash(body.identity.work_token),
        CloudWorkGrant.worker_id == body.identity.worker_id,
        CloudWorkGrant.lease_generation == body.identity.generation,
        CloudWorkGrant.project_id == body.project_id,
        CloudWorkGrant.attempt_id == body.attempt_id))
    if not grant:
        raise HTTPException(403, "Original Worker capability required")
    await service._current_grant(db, attempt.authorization_grant_id, task.project_id)


@router.post("/auth-observation")
@controlled_errors
async def auth_observation(body: AuthObservation, worker_id: str = Depends(authenticate_worker),
                           db: AsyncSession = Depends(get_db)):
    from hypertest.application.cloud_agent_auth import store_worker_auth_status
    await store_worker_auth_status(db, worker_id, body.status)
    await db.commit()
    return {"recorded": True}


@router.post("/claim")
@controlled_errors
async def claim(body: Claim, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    if not hmac.compare_digest(body.worker_id, worker_id):
        raise HTTPException(403, "Worker identity mismatch")
    await service.expire_leases(db)
    result = await service.claim_resolution(db, worker_id, body.lease_seconds)
    if result:
        return {"kind": "RESOLUTION", "claim": result}
    result = await service.claim_attempt(db, worker_id, body.lease_seconds,
                                         supports_attempt_manifest=body.supports_attempt_manifest)
    return {"kind": "ATTEMPT" if result else "EMPTY", "claim": result}


@router.post("/renew")
@controlled_errors
async def renew(body: Renew, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await active(db, body)
    i = body.identity
    return await service.renew_lease(db, body.attempt_id, i.worker_id, i.lease_token, i.generation, i.work_token, body.lease_seconds)


@router.post("/assert")
@controlled_errors
async def assert_authority(body: Attempt, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await active(db, body)
    return {"current": True}


@router.post("/fence")
@controlled_errors
async def fence(body: Fence, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    # Fence is narrowly scoped and idempotent; verify the original work token
    # even if the owner has already been fenced before this response is read.
    await original_read(db, body)
    fenced = await service.fence_attempt_for_recovery(db, body.task_id, body.attempt_id, body.identity.service_identity(), body.reason)
    return {"fenced": fenced}


@router.post("/resolution/accept")
@controlled_errors
async def accept_resolution(body: ResolutionAccept, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    i = body.identity
    row = await db.get(CloudInputResolution, body.resolution_id)
    if not row or row.project_id != body.project_id or row.task_id != body.task_id:
        raise HTTPException(404, "Original resolution not found")
    # Even the already-accepted readback path must present the original work token.
    grant = await db.scalar(select(CloudWorkGrant).where(CloudWorkGrant.resolution_id == body.resolution_id,
        CloudWorkGrant.worker_id == worker_id, CloudWorkGrant.lease_generation == i.generation,
        CloudWorkGrant.token_hash == token_hash(i.work_token)))
    if not grant:
        raise HTTPException(403, "Original resolution capability required")
    return await service.accept_resolution(db, body.resolution_id, worker_id, i.lease_token, body.result, work_token=i.work_token)


@router.post("/resolution/assert")
@controlled_errors
async def assert_resolution(body: Resolution, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    row = await db.get(CloudInputResolution, body.resolution_id)
    if not row or row.project_id != body.project_id or row.task_id != body.task_id or body.identity.generation != 1:
        raise HTTPException(404, "Original resolution not found")
    await service.resolution_authority(db, row, worker_id, body.identity.lease_token, body.identity.work_token)
    return {"current": True}


@router.post("/submit")
@controlled_errors
async def submit(body: Submit, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    try:
        payload = TypeAdapter(CloudMutation).validate_python(body.payload)
    except ValidationError:
        raise HTTPException(422, "Invalid Worker operation") from None
    if (service.SCOPES.get(payload.operation) != "cloud:work"
            or payload.operation in {"PREPARE_CONTAINER_CREATE", "CONFIRM_CONTAINER_ID", "PREPARE_CONTAINER_START", "OBSERVE_CONTAINER_STOP", "OBSERVE_CONTAINER_NEVER_STARTED"}
            or payload.project_id != body.project_id or payload.task_id != body.task_id or payload.attempt_id != body.attempt_id):
        raise HTTPException(403, "Worker operation is outside its Attempt")
    await active(db, body)
    return await service.mutate(db, payload, "worker:" + worker_id, worker=body.identity.service_identity(), native_worker=True)


@router.post("/validate-payload")
@controlled_errors
async def validate_payload(body: Submit, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await active(db, body)
    values = [body.payload]
    if body.payload.get("operation") == "UPLOAD_ARTIFACT":
        try:
            values.append(base64.b64decode(body.payload["content_base64"], validate=True).decode("utf-8", errors="replace"))
        except (KeyError, ValueError, TypeError):
            raise HTTPException(422, "Invalid artifact payload") from None
    try:
        await service._reject_secrets(db, body.project_id, values)
    except HTTPException as error:
        # Project only the fixed admission outcome. Never return content, a
        # matched secret, or arbitrary server errors to the host Worker.
        if error.status_code == 422 and isinstance(error.detail, str) and error.detail in {
            "Potential secret material is not an accepted testing artifact",
            "Credential material is not an accepted testing artifact",
        }:
            raise HTTPException(422, REPORT_CONTENT_REJECTED) from None
        raise
    return {"valid": True}


@router.post("/receipt")
@controlled_errors
async def receipt(body: Receipt, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await original_read(db, body)
    row = await db.scalar(select(CloudOperationReceipt).where(CloudOperationReceipt.project_id == body.project_id,
        CloudOperationReceipt.task_id == body.task_id, CloudOperationReceipt.operation_key == body.operation_key,
        CloudOperationReceipt.actor_ref == "worker:" + worker_id))
    if not row or row.response.get("attempt_id") != str(body.attempt_id):
        raise HTTPException(404, "Original Worker receipt not found")
    return row.response


@router.post("/page")
@controlled_errors
async def page(body: Page, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await original_read(db, body)
    row = await db.scalar(select(CloudOperationReceipt).where(CloudOperationReceipt.project_id == body.project_id,
        CloudOperationReceipt.task_id == body.task_id, CloudOperationReceipt.accepted_version == body.version,
        CloudOperationReceipt.actor_ref == "worker:" + worker_id))
    if not row or row.response.get("attempt_id") != str(body.attempt_id):
        raise HTTPException(404, "Original Worker version not found")
    return await service.read_task(db, body.task_id, project_id=body.project_id, version=body.version, offset=body.offset, limit=body.limit)


@router.post("/artifact")
@controlled_errors
async def artifact(body: Artifact, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await original_read(db, body)
    row = await db.get(CloudArtifact, body.artifact_id)
    if not row or row.project_id != body.project_id or row.task_id != body.task_id or row.attempt_id != body.attempt_id or not row.verified_at or row.byte_count > 8 * 1024 * 1024:
        raise HTTPException(404, "Original Worker artifact not found")
    return {"content_base64": base64.b64encode(row.content).decode("ascii")}


class LiveOpen(Attempt):
    request_id: str = Field(min_length=1, max_length=255)
    session_id: str = Field(min_length=1, max_length=255)
    questions: list[dict] = Field(min_length=1, max_length=20)
    timeout_seconds: int = Field(default=600, ge=1, le=3600)


class LiveLookup(Attempt):
    request_id: str = Field(min_length=1, max_length=255)
    session_id: str = Field(min_length=1, max_length=255)


class LiveQuestion(Attempt):
    question_id: UUID


class LiveFinish(LiveQuestion):
    outcome: Literal["DELIVERED", "CANCELLED", "UNKNOWN"]


@router.post("/live-question/open")
@controlled_errors
async def live_open(body: LiveOpen, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    from hypertest.application import cloud_live_questions as live_questions
    check_identity(worker_id, body.identity)
    task, attempt = await live_questions.task_attempt(db, body.project_id, body.task_id, body.attempt_id)
    return await live_questions.open_question(db, task, attempt, body.identity.service_identity(), body.request_id, body.session_id, body.questions, body.timeout_seconds)


@router.post("/live-question/lookup")
@controlled_errors
async def live_lookup(body: LiveLookup, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    from hypertest.application import cloud_live_questions as live_questions
    check_identity(worker_id, body.identity)
    task, attempt = await live_questions.task_attempt(db, body.project_id, body.task_id, body.attempt_id)
    return await live_questions.worker_lookup(db, task, attempt, body.identity.service_identity(), body.request_id, body.session_id)


@router.post("/live-question/poll")
@controlled_errors
async def live_poll(body: LiveQuestion, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    from hypertest.application import cloud_live_questions as live_questions
    check_identity(worker_id, body.identity)
    task, attempt = await live_questions.task_attempt(db, body.project_id, body.task_id, body.attempt_id)
    return await live_questions.worker_poll(db, task, attempt, body.identity.service_identity(), body.question_id)


@router.post("/live-question/finish")
@controlled_errors
async def live_finish(body: LiveFinish, worker_id: str = Depends(authenticate_worker), db: AsyncSession = Depends(get_db)):
    from hypertest.application import cloud_live_questions as live_questions
    check_identity(worker_id, body.identity)
    task, attempt = await live_questions.task_attempt(db, body.project_id, body.task_id, body.attempt_id)
    return await live_questions.worker_finish(db, task, attempt, body.identity.service_identity(), body.question_id, body.outcome)
