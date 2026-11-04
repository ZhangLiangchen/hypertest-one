"""Internal connection scheduling for an ordinary message to an offline session."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.application import cloud_tasks as service
from hypertest.domain.cloud_tasks import CloudConversationMessage, CloudWorkGrant


async def original_worker(db, attempt):
    return await db.scalar(select(CloudWorkGrant.worker_id).where(
        CloudWorkGrant.attempt_id == attempt.id).order_by(CloudWorkGrant.lease_generation.desc()).limit(1))


async def enqueue_connection(db, *, task, attempt, operation_key, actor_ref):
    """Caller holds the Task lock; save this intent with the same USER message.

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
        "requested_at": now.isoformat()}
    checkpoint = {**attempt.checkpoint, "native_resume": intent}
    legacy_generations = dict(checkpoint.get("conversation_request_generations", {}))
    # QUEUED proves that no SDK send was attempted. Only these messages may
    # move to the new connection; sent/unknown identities stay put.
    from .cloud_conversation import next_cursor
    for row in await db.scalars(select(CloudConversationMessage).where(
            CloudConversationMessage.attempt_id == attempt.id,
            CloudConversationMessage.role == "USER", CloudConversationMessage.status == "QUEUED")):
        current_digest = service.canonical_json_sha256({"project_id": str(row.project_id),
            "task_id": str(row.task_id), "attempt_id": str(row.attempt_id), "text": row.text})
        if row.request_digest != current_digest:
            legacy_generations.setdefault(str(row.id), row.generation)
        row.generation, row.cursor = generation, await next_cursor(db, task.id)
    if legacy_generations:
        checkpoint["conversation_request_generations"] = legacy_generations
    attempt.checkpoint = checkpoint
    service._state(task, attempt, "PREPARING", "Reconnecting the original Harness session", now)
    service._events(db, task.project_id, actor_ref, "CONVERSATION_CONNECT_REQUESTED", task.id,
        {"attempt_id": str(attempt.id), "generation": generation, "operation_key": operation_key})
    return generation
