"""Task-scoped communication, never a testing result or an execution receipt."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.application import cloud_tasks as service
from hypertest.domain.cloud_tasks import (
    CloudConversationHead,
    CloudConversationMessage,
    CloudTaskDeletion,
    CloudWorkGrant,
)


def view(row):
    fields = ("id", "project_id", "task_id", "attempt_id", "generation", "session_id", "cursor", "role",
              "text", "status", "operation_key", "event_key", "event_seq", "request_digest", "source",
              "sdk_message_id", "state", "reason_code", "created_at", "observed_at")
    result = {}
    for name in fields:
        value = getattr(row, name)
        result[name] = None if value is None else value.isoformat() if hasattr(value, "isoformat") else str(value) if name.endswith("_id") or name == "id" else value
    return result


async def next_cursor(db, task_id):
    # All callers hold the Task lock. Sequence allocation and row changes thus
    # commit in order: a reader never skips a not-yet-committed lower cursor.
    head = next((row for row in db.new if isinstance(row, CloudConversationHead) and row.task_id == task_id), None)
    if head is None:
        head = await db.get(CloudConversationHead, task_id)
    if head is None:
        head = CloudConversationHead(task_id=task_id, cursor=0)
        db.add(head)
    head.cursor += 1
    return head.cursor


async def context(db, project_id, task_id, attempt_id, *, lock=False):
    task = await service._task(db, task_id, project_id, lock=lock)
    attempt = await service._attempt(db, task, attempt_id)
    return task, attempt


async def session_view(db, task, attempt):
    if attempt is None:
        return {"state": "OFFLINE", "can_send": False, "generation": None, "session_id": None,
                "blocking_reasons": ["NO_ATTEMPT"]}
    now = await service.clock(db)
    blockers = []
    if await db.get(CloudTaskDeletion, task.id):
        blockers.append("TASK_DELETED")
    if task.latest_attempt_id != attempt.id:
        blockers.append("HISTORICAL_ATTEMPT")
    if attempt.status != "RUNNING":
        blockers.append("SESSION_NOT_RUNNING")
    if not attempt.lease_owner or not attempt.lease_expires_at or attempt.lease_expires_at <= now:
        blockers.append("SESSION_OFFLINE")
    valid_grant = await db.scalar(select(CloudWorkGrant.id).where(
        CloudWorkGrant.attempt_id == attempt.id, CloudWorkGrant.worker_id == attempt.lease_owner,
        CloudWorkGrant.lease_generation == attempt.lease_generation, CloudWorkGrant.revoked_at.is_(None),
        CloudWorkGrant.expires_at > now).limit(1))
    if not valid_grant:
        blockers.append("SESSION_OFFLINE")
    try:
        await service._current_grant(db, attempt.authorization_grant_id, task.project_id)
    except HTTPException:
        blockers.append("AUTHORIZATION_UNAVAILABLE")
    latest = await db.scalar(select(CloudConversationMessage).where(
        CloudConversationMessage.attempt_id == attempt.id,
        CloudConversationMessage.generation == attempt.lease_generation,
        CloudConversationMessage.source == "LIVE_SDK",
        CloudConversationMessage.state.is_not(None)).order_by(CloudConversationMessage.cursor.desc()).limit(1))
    state = latest.state if latest else "CONNECTING"
    if state in {"CLOSED", "INTERRUPTED"}:
        blockers.append("SESSION_OFFLINE")
    if state == "CONNECTING" and not blockers:
        blockers.append("SESSION_CONNECTING")
    if any(reason != "SESSION_CONNECTING" for reason in blockers) and state not in {"CLOSED", "INTERRUPTED"}:
        state = "OFFLINE"
    pending = await db.scalar(select(CloudConversationMessage.id).where(
        CloudConversationMessage.attempt_id == attempt.id,
        CloudConversationMessage.role == "USER", CloudConversationMessage.status == "UNKNOWN").limit(1))
    if pending:
        blockers.append("MESSAGE_DELIVERY_UNKNOWN")
    return {"state": state, "can_send": not blockers, "generation": attempt.lease_generation,
            "session_id": "cloud-" + str(attempt.id), "blocking_reasons": list(dict.fromkeys(blockers))}


async def read(db, task, attempt, after, limit):
    query = select(CloudConversationMessage).where(CloudConversationMessage.task_id == task.id,
                                                  CloudConversationMessage.cursor > after)
    if attempt is not None:
        query = query.where(CloudConversationMessage.attempt_id == attempt.id)
    rows = list(await db.scalars(query.order_by(CloudConversationMessage.cursor).limit(limit + 1)))
    page = rows[:limit]
    return {"messages": [view(row) for row in page], "next_cursor": page[-1].cursor if page else after,
            "has_more": len(rows) > limit, "session": await session_view(db, task, attempt),
            "observed_at": (await service.clock(db)).isoformat()}


async def lookup_user(db, task, operation_key):
    row = await db.scalar(select(CloudConversationMessage).where(
        CloudConversationMessage.project_id == task.project_id,
        CloudConversationMessage.task_id == task.id, CloudConversationMessage.operation_key == operation_key))
    if row is None:
        raise HTTPException(404, "CONVERSATION_MESSAGE_NOT_FOUND")
    return view(row)


async def send(db, task, attempt, actor, body):
    payload = {"project_id": str(task.project_id), "task_id": str(task.id), "attempt_id": str(attempt.id),
               "generation": body.generation, "text": body.text}
    digest = service.canonical_json_sha256(payload)
    old = await db.scalar(select(CloudConversationMessage).where(
        CloudConversationMessage.project_id == task.project_id,
        CloudConversationMessage.operation_key == body.operation_key))
    if old is not None:
        if old.request_digest != digest or old.actor_ref != actor or old.task_id != task.id:
            raise HTTPException(409, "CONVERSATION_MESSAGE_CONFLICT")
        return view(old)
    if body.generation != attempt.lease_generation or not (await session_view(db, task, attempt))["can_send"]:
        raise HTTPException(409, "CONVERSATION_SESSION_UNAVAILABLE")
    if not body.text.strip():
        raise HTTPException(422, "CONVERSATION_TEXT_REQUIRED")
    await service._reject_secrets(db, task.project_id, {"text": body.text})
    row = CloudConversationMessage(project_id=task.project_id, task_id=task.id, attempt_id=attempt.id,
        generation=body.generation, session_id="cloud-" + str(attempt.id), role="USER", text=body.text,
        status="QUEUED", operation_key=body.operation_key, request_digest=digest, source="OPERATOR_MESSAGE",
        actor_ref=actor, cursor=await next_cursor(db, task.id))
    db.add(row)
    await db.flush()
    result = view(row)
    await db.commit()
    return result


async def append(db, task, attempt, generation, actor, body, *, source="LIVE_SDK"):
    if body.session_id != "cloud-" + str(attempt.id):
        raise HTTPException(403, "CONVERSATION_SESSION_MISMATCH")
    payload = body.model_dump(mode="json", exclude={"identity", "project_id", "task_id", "attempt_id"})
    digest = service.canonical_json_sha256(payload)
    old = await db.scalar(select(CloudConversationMessage).where(
        CloudConversationMessage.attempt_id == attempt.id, CloudConversationMessage.generation == generation,
        CloudConversationMessage.event_key == body.event_key))
    if old is not None:
        if old.request_digest != digest or old.actor_ref != actor or old.source != source:
            raise HTTPException(409, "CONVERSATION_EVENT_CONFLICT")
        return view(old)
    text, status, reason = body.text, "RECORDED", body.reason_code
    try:
        await service._reject_secrets(db, task.project_id, {"text": text})
    except HTTPException as error:
        if error.status_code != 422:
            raise
        text, status, reason = "", "REJECTED", "CONTENT_REJECTED"
    if reason in {"CONTENT_REJECTED", "MESSAGE_TOO_LARGE"}:
        text, status = "", "REJECTED"
    row = CloudConversationMessage(project_id=task.project_id, task_id=task.id, attempt_id=attempt.id,
        generation=generation, session_id=body.session_id, role=body.role, text=text, status=status,
        event_key=body.event_key, event_seq=body.event_seq, request_digest=digest, source=source,
        actor_ref=actor, state=body.state, reason_code=reason, observed_at=body.observed_at,
        cursor=await next_cursor(db, task.id))
    db.add(row)
    await db.flush()
    result = view(row)
    await db.commit()
    return result


async def lookup_event(db, attempt, generation, event_key):
    row = await db.scalar(select(CloudConversationMessage).where(
        CloudConversationMessage.attempt_id == attempt.id, CloudConversationMessage.generation == generation,
        CloudConversationMessage.event_key == event_key))
    if row is None:
        raise HTTPException(404, "CONVERSATION_EVENT_NOT_FOUND")
    return view(row)


async def poll(db, task, attempt, identity, session_id):
    if session_id != "cloud-" + str(attempt.id):
        raise HTTPException(403, "CONVERSATION_SESSION_MISMATCH")
    await service.worker_authority(db, task, attempt, identity)
    if attempt.status != "RUNNING":
        raise HTTPException(409, "CONVERSATION_SESSION_UNAVAILABLE")
    query = select(CloudConversationMessage).where(CloudConversationMessage.attempt_id == attempt.id,
        CloudConversationMessage.generation == identity.generation, CloudConversationMessage.role == "USER")
    pending = await db.scalar(query.where(CloudConversationMessage.status.in_(["DELIVERING", "UNKNOWN"]))
                              .order_by(CloudConversationMessage.created_at, CloudConversationMessage.id).limit(1))
    if pending:
        return {"message": None, "pending_message_id": str(pending.id)}
    row = await db.scalar(query.where(CloudConversationMessage.status == "QUEUED")
                         .order_by(CloudConversationMessage.created_at, CloudConversationMessage.id).limit(1))
    if row is None:
        return {"message": None}
    row.status, row.cursor = "DELIVERING", await next_cursor(db, task.id)
    await db.flush()
    result = {"message": view(row)}
    await db.commit()
    return result


async def ack(db, task, attempt, generation, body):
    row = await db.scalar(select(CloudConversationMessage).where(
        CloudConversationMessage.id == body.message_id, CloudConversationMessage.task_id == task.id,
        CloudConversationMessage.attempt_id == attempt.id, CloudConversationMessage.generation == generation,
        CloudConversationMessage.role == "USER", CloudConversationMessage.session_id == body.session_id))
    if row is None:
        raise HTTPException(404, "CONVERSATION_MESSAGE_NOT_FOUND")
    if body.status == "DELIVERED" and not body.sdk_message_id:
        raise HTTPException(422, "SDK_MESSAGE_RECEIPT_REQUIRED")
    if body.status == "UNKNOWN" and body.sdk_message_id is not None:
        raise HTTPException(422, "UNKNOWN_HAS_NO_SDK_RECEIPT")
    if row.status == body.status:
        if row.sdk_message_id != body.sdk_message_id:
            raise HTTPException(409, "CONVERSATION_ACK_CONFLICT")
        return view(row)
    if row.status not in {"DELIVERING", "UNKNOWN"} or (row.status == "UNKNOWN" and body.status != "DELIVERED"):
        raise HTTPException(409, "CONVERSATION_MESSAGE_NOT_DELIVERING")
    # A delayed original SDK receipt may resolve UNKNOWN. This only records
    # admission to the original inbox and never sends a message or revives work.
    row.status, row.sdk_message_id = body.status, body.sdk_message_id
    row.cursor = await next_cursor(db, task.id)
    await db.flush()
    result = view(row)
    await db.commit()
    return result


async def fence_messages(db, attempt):
    rows = list(await db.scalars(select(CloudConversationMessage).where(
        CloudConversationMessage.attempt_id == attempt.id,
        CloudConversationMessage.status.in_(["QUEUED", "DELIVERING"]))))
    for row in rows:
        row.status = "CANCELLED" if row.status == "QUEUED" else "UNKNOWN"
        row.cursor = await next_cursor(db, attempt.task_id)
    # Lease expiry must remain observable even if the Worker died before it
    # could publish its own final event. This is a fence, not proof of stop.
    if not attempt.lease_owner:
        return
    latest = await db.scalar(select(CloudConversationMessage).where(
        CloudConversationMessage.attempt_id == attempt.id,
        CloudConversationMessage.generation == attempt.lease_generation,
        CloudConversationMessage.state.is_not(None)).order_by(CloudConversationMessage.cursor.desc()).limit(1))
    if latest is not None and latest.state in {"CLOSED", "INTERRUPTED"}:
        return
    closed = attempt.status in {"COMPLETED", "WAITING_INPUT"}
    event_key = f"control:fenced:{attempt.lease_generation}"
    db.add(CloudConversationMessage(project_id=attempt.project_id, task_id=attempt.task_id,
        attempt_id=attempt.id, generation=attempt.lease_generation,
        session_id="cloud-" + str(attempt.id), role="SYSTEM", text="", status="RECORDED",
        event_key=event_key, request_digest=service.canonical_json_sha256({"event_key": event_key}),
        source="CONTROL_PLANE", actor_ref="system:cloud-fence",
        state="CLOSED" if closed else "INTERRUPTED",
        reason_code="TURN_COMPLETED" if attempt.status == "COMPLETED" else "TURN_BLOCKED" if closed else "WORKER_INTERRUPTED",
        observed_at=await service.clock(db), cursor=await next_cursor(db, attempt.task_id)))
