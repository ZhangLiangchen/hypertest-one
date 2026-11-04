"""Public task conversation and the private fenced SDK bridge."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.cloud_routes import identity
from hypertest.api.cloud_worker_routes import (
    Attempt,
    Input,
    authenticate_worker,
    check_identity,
    original_read,
)
from hypertest.api.interactive_routes import controlled_errors
from hypertest.application import cloud_conversation as conversation
from hypertest.application import cloud_tasks as service
from hypertest.db.session import get_db
from hypertest.domain.cloud_tasks import CloudWorkGrant

router = APIRouter(tags=["cloud-conversation"])
KEY = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"


class UserMessage(Input):
    project_id: UUID
    attempt_id: UUID
    # Retained only to recognize an already-saved legacy request by its key.
    # New message routing generations are assigned by the server.
    generation: int | None = Field(default=None, ge=1, strict=True)
    operation_key: str = Field(min_length=1, max_length=128, pattern=KEY)
    text: str = Field(min_length=1, max_length=16000)


class ConversationObservation(Input):
    event_key: str = Field(min_length=1, max_length=128, pattern=KEY)
    session_id: str = Field(min_length=1, max_length=128)
    role: Literal["ASSISTANT", "SYSTEM"]
    text: str = Field(default="", max_length=65536)
    event_seq: int | None = Field(default=None, ge=0)
    state: Literal["RUNNING", "AWAITING_REPLY", "INTERRUPTED", "CLOSED"] | None = None
    reason_code: Literal["SDK_RUN_FAILED", "WORKER_INTERRUPTED", "CONTENT_REJECTED", "MESSAGE_TOO_LARGE", "CONVERSATION_GAP",
                         "TURN_BLOCKED", "TURN_COMPLETED", "TURN_ABORTED", "TURN_ERROR",
                         "ARTIFACT_REJECTED", "ARTIFACT_CONTENT_REJECTED"] | None = None
    observed_at: datetime | None = None


class ConversationEvent(Attempt, ConversationObservation):
    pass


class HistoricalTarget(Input):
    project_id: UUID
    task_id: UUID
    attempt_id: UUID
    worker_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(ge=1, strict=True)


class RecoveredConversationEvent(HistoricalTarget, ConversationObservation):
    pass


class RecoveredConversationAck(HistoricalTarget):
    session_id: str = Field(min_length=1, max_length=128)
    message_id: UUID
    status: Literal["DELIVERED", "UNKNOWN"]
    sdk_message_id: str | None = Field(default=None, min_length=1, max_length=255)


class ConversationLookup(Attempt):
    event_key: str = Field(min_length=1, max_length=128, pattern=KEY)


class ConversationPoll(Attempt):
    session_id: str = Field(min_length=1, max_length=128)


class ConversationAck(ConversationPoll):
    message_id: UUID
    status: Literal["DELIVERED", "UNKNOWN"]
    sdk_message_id: str | None = Field(default=None, min_length=1, max_length=255)


class ConversationValidate(Attempt):
    text: str = Field(max_length=65536)


@router.get("/cloud/tasks/{task_id}/conversation")
@controlled_errors
async def get_conversation(task_id: UUID, project_id: UUID, request: Request, response: Response,
    attempt_id: UUID | None = None, after: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200),
    authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)):
    await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    task = await service._task(db, task_id, project_id)
    chosen = attempt_id or task.latest_attempt_id
    attempt = await service._attempt(db, task, chosen) if chosen else None
    response.headers["Cache-Control"] = "no-store"
    return await conversation.read(db, task, attempt, after, limit)


@router.post("/cloud/tasks/{task_id}/conversation")
@controlled_errors
async def send_message(task_id: UUID, body: UserMessage, request: Request,
    authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)):
    actor, _, _ = await identity(request, db, body.project_id, "cloud:control", authorization, x_hypertest_operator_key, lock=True)
    task, attempt = await conversation.context(db, body.project_id, task_id, body.attempt_id, lock=True)
    return await conversation.send(db, task, attempt, actor, body)


@router.get("/cloud/tasks/{task_id}/conversation/messages/by-key")
@controlled_errors
async def lookup_message(task_id: UUID, project_id: UUID, operation_key: str, request: Request, response: Response,
    authorization: str | None = Header(default=None), x_hypertest_operator_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)):
    await identity(request, db, project_id, "cloud:read", authorization, x_hypertest_operator_key)
    task = await service._task(db, task_id, project_id)
    response.headers["Cache-Control"] = "no-store"
    return await conversation.lookup_user(db, task, operation_key)


@router.post("/cloud/worker/conversation/validate")
@controlled_errors
async def validate_output(body: ConversationValidate, worker_id: str = Depends(authenticate_worker),
                          db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await original_read(db, body)
    try:
        await service._reject_secrets(db, body.project_id, {"text": body.text})
    except HTTPException as error:
        if error.status_code != 422:
            raise
        return {"accepted": False, "reason_code": "CONTENT_REJECTED"}
    return {"accepted": True}


@router.post("/cloud/worker/conversation/append")
@controlled_errors
async def append_output(body: ConversationEvent, worker_id: str = Depends(authenticate_worker),
                        db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await original_read(db, body)
    task, attempt = await conversation.context(db, body.project_id, body.task_id, body.attempt_id, lock=True)
    return await conversation.append(db, task, attempt, body.identity.generation, "worker:" + worker_id, body)


@router.post("/cloud/worker/conversation/lookup")
@controlled_errors
async def lookup_output(body: ConversationLookup, worker_id: str = Depends(authenticate_worker),
                        db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await original_read(db, body)
    task, attempt = await conversation.context(db, body.project_id, body.task_id, body.attempt_id)
    return await conversation.lookup_event(db, attempt, body.identity.generation, body.event_key)


@router.post("/cloud/worker/conversation/poll")
@controlled_errors
async def poll_message(body: ConversationPoll, worker_id: str = Depends(authenticate_worker),
                       db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    task, attempt = await conversation.context(db, body.project_id, body.task_id, body.attempt_id, lock=True)
    return await conversation.poll(db, task, attempt, body.identity.service_identity(), body.session_id)


@router.post("/cloud/worker/conversation/ack")
@controlled_errors
async def ack_message(body: ConversationAck, worker_id: str = Depends(authenticate_worker),
                      db: AsyncSession = Depends(get_db)):
    check_identity(worker_id, body.identity)
    await original_read(db, body)
    task, attempt = await conversation.context(db, body.project_id, body.task_id, body.attempt_id, lock=True)
    return await conversation.ack(db, task, attempt, body.identity.generation, body)


async def historical_target(db, body, worker_id):
    # Recovery of observations needs no persisted execution token. The host's
    # existing credential and an actual historical grant bind the exact target.
    if worker_id != body.worker_id:
        raise HTTPException(403, "CONVERSATION_WORKER_MISMATCH")
    task, attempt = await conversation.context(db, body.project_id, body.task_id, body.attempt_id, lock=True)
    original = await db.scalar(select(CloudWorkGrant.id).where(
        CloudWorkGrant.project_id == task.project_id,
        CloudWorkGrant.attempt_id == attempt.id, CloudWorkGrant.worker_id == worker_id,
        CloudWorkGrant.lease_generation == body.generation).limit(1))
    if original is None:
        raise HTTPException(403, "CONVERSATION_ORIGINAL_GRANT_REQUIRED")
    return task, attempt


@router.post("/cloud/worker/conversation/recover-append")
@controlled_errors
async def recover_output(body: RecoveredConversationEvent, worker_id: str = Depends(authenticate_worker),
                         db: AsyncSession = Depends(get_db)):
    task, attempt = await historical_target(db, body, worker_id)
    # Identical digest to the original live append, independent of transport.
    observation = ConversationObservation.model_validate(body.model_dump(exclude={
        "project_id", "task_id", "attempt_id", "worker_id", "generation"}))
    return await conversation.append(db, task, attempt, body.generation, "worker:" + worker_id, observation)


@router.post("/cloud/worker/conversation/recover-ack")
@controlled_errors
async def recover_ack(body: RecoveredConversationAck, worker_id: str = Depends(authenticate_worker),
                      db: AsyncSession = Depends(get_db)):
    task, attempt = await historical_target(db, body, worker_id)
    return await conversation.ack(db, task, attempt, body.generation, body)
