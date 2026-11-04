"""Worker-owned delivery scheduling for durable, unattempted user messages."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.application import cloud_tasks as service
from hypertest.domain.cloud_tasks import (
    CloudAttempt,
    CloudConversationMessage,
    CloudTask,
    CloudTaskDeletion,
    CloudWorkGrant,
)

# These require a changed configuration/identity, never a repeated connection.
PERMANENT_CONNECTION_ERRORS = frozenset({
    "NATIVE_SESSION_IDENTITY_UNAVAILABLE", "NATIVE_SESSION_TARGET_MISMATCH",
    "NATIVE_RESUME_IDENTITY_TARGET_MISMATCH", "HARNESS_CONFIGURATION_INVALID",
    "HARNESS_CORDIS_UNAVAILABLE", "GIT_AUTH_FAILED", "GIT_HOST_KEY_FAILED",
    "GIT_TLS_VERIFICATION_FAILED", "ATTEMPT_SNAPSHOT_MISMATCH", "SDK_SESSION_UNAVAILABLE",
})


async def original_worker(db, attempt):
    return await db.scalar(select(CloudWorkGrant.worker_id).where(
        CloudWorkGrant.attempt_id == attempt.id).order_by(CloudWorkGrant.lease_generation.desc()).limit(1))


async def enqueue_connection(db, *, task, attempt, operation_key, actor_ref):
    """Caller holds the Task lock; schedule an already-persisted USER message.

    This acquires delivery ownership only. The Worker opens the actual original
    SDK session and its native lock; Harness owns its inbox, policy and work.
    """
    if (task.latest_attempt_id != attempt.id or task.status != "RECOVERY_REQUIRED"
            or attempt.status != "RECOVERY_REQUIRED" or not await service._owner_fenced(db, attempt)
            or attempt.checkpoint.get("cancellation_requested")):
        raise HTTPException(409, "CONVERSATION_SESSION_UNAVAILABLE")
    await service._current_grant(db, attempt.authorization_grant_id, task.project_id)
    if await db.scalar(select(CloudConversationMessage.id).where(
            CloudConversationMessage.attempt_id == attempt.id,
            CloudConversationMessage.role == "USER",
            CloudConversationMessage.status.in_(("DELIVERING", "UNKNOWN"))).limit(1)):
        raise HTTPException(409, "CONVERSATION_MESSAGE_DELIVERY_UNKNOWN")
    worker_id = await original_worker(db, attempt)
    if worker_id is None or service.attempt_inputs(task, attempt).get("budgets") is not None:
        raise HTTPException(409, "CONVERSATION_ORIGINAL_SESSION_UNAVAILABLE")
    now = await service.clock(db)
    generation = attempt.lease_generation + 1
    intent = {"profile": "hypertest-native-connection/v1", "mode": "RESTORE_ONLY",
        "operation_key": operation_key, "worker_id": worker_id,
        "target_generation": generation, "session_id": "cloud-" + str(attempt.id),
        "input_digest": attempt.input_digest, "requested_by": actor_ref,
        "requested_at": now.isoformat(), "next_retry_at": (now + timedelta(seconds=30)).isoformat()}
    checkpoint = {**attempt.checkpoint, "native_resume": intent}
    attempt.checkpoint = checkpoint
    service._state(task, attempt, "PREPARING", "Reconnecting the original Harness session", now)
    service._events(db, task.project_id, actor_ref, "CONVERSATION_CONNECT_REQUESTED", task.id,
        {"attempt_id": str(attempt.id), "generation": generation, "operation_key": operation_key})
    return generation


async def bind_queued_messages(db, task, attempt, generation):
    """A claim binds only unattempted input, preserving every original receipt."""
    from .cloud_conversation import next_cursor

    legacy_generations = dict(attempt.checkpoint.get("conversation_request_generations", {}))
    for row in await db.scalars(select(CloudConversationMessage).where(
            CloudConversationMessage.attempt_id == attempt.id,
            CloudConversationMessage.role == "USER", CloudConversationMessage.status == "QUEUED")):
        if row.generation == generation:
            continue
        current_digest = service.canonical_json_sha256({"project_id": str(row.project_id),
            "task_id": str(row.task_id), "attempt_id": str(row.attempt_id), "text": row.text})
        if row.request_digest != current_digest:
            legacy_generations.setdefault(str(row.id), row.generation)
        row.generation, row.cursor = generation, await next_cursor(db, task.id)
    if legacy_generations:
        attempt.checkpoint = {**attempt.checkpoint, "conversation_request_generations": legacy_generations}


async def schedule_queued_connection(db, worker_id):
    """Prepare one original session for this Worker, never replay an old input.

    Lease expiry alone is insufficient. A persisted QUEUED message is required;
    an unresolved original delivery blocks dispatch, but never discards new text.
    """
    now = await service.clock(db)
    queued = select(CloudConversationMessage.id).where(
        CloudConversationMessage.attempt_id == CloudAttempt.id,
        CloudConversationMessage.role == "USER", CloudConversationMessage.status == "QUEUED").exists()
    unresolved = select(CloudConversationMessage.id).where(
        CloudConversationMessage.attempt_id == CloudAttempt.id,
        CloudConversationMessage.role == "USER",
        CloudConversationMessage.status.in_(["DELIVERING", "UNKNOWN"])).exists()
    owner = select(CloudWorkGrant.worker_id).where(CloudWorkGrant.attempt_id == CloudAttempt.id).order_by(
        CloudWorkGrant.lease_generation.desc()).limit(1).scalar_subquery()
    query = select(CloudTask).join(CloudAttempt, CloudAttempt.id == CloudTask.latest_attempt_id).where(
        CloudTask.status == "RECOVERY_REQUIRED", CloudAttempt.status == "RECOVERY_REQUIRED",
        CloudAttempt.lease_owner.is_(None), owner == worker_id, queued, ~unresolved,
        ~select(CloudTaskDeletion.task_id).where(CloudTaskDeletion.task_id == CloudTask.id).exists())
    for task in await db.scalars(query.order_by(CloudAttempt.queued_at, CloudAttempt.id)
                                .with_for_update(of=CloudTask, skip_locked=True)):
        attempt = await service._attempt(db, task, task.latest_attempt_id)
        if attempt.reason in PERMANENT_CONNECTION_ERRORS:
            continue
        retry_at = attempt.checkpoint.get("native_resume", {}).get("next_retry_at")
        if retry_at is not None:
            try:
                if now < datetime.fromisoformat(retry_at):
                    continue
            except (TypeError, ValueError):
                # A malformed internal scheduling record is not permission to retry.
                continue
        message = await db.scalar(select(CloudConversationMessage).where(
            CloudConversationMessage.attempt_id == attempt.id,
            CloudConversationMessage.role == "USER", CloudConversationMessage.status == "QUEUED")
            .order_by(CloudConversationMessage.created_at, CloudConversationMessage.id).limit(1))
        if message is None:
            continue
        try:
            await enqueue_connection(db, task=task, attempt=attempt,
                operation_key=message.operation_key, actor_ref=message.actor_ref)
        except HTTPException as error:
            if error.status_code not in {401, 403, 409}:
                raise
            continue
        await db.flush()
        return
