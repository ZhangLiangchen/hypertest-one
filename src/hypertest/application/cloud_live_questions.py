"""Fenced live SDK questions, independent from paused WAITING_INPUT."""
from __future__ import annotations

import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.application import cloud_tasks as service
from hypertest.domain.cloud_tasks import CloudLiveQuestion, CloudTaskDeletion, CloudWorkGrant


def validate_questions(questions):
    if not isinstance(questions, list) or not 1 <= len(questions) <= 20 or len(json.dumps(questions, ensure_ascii=False).encode()) > 32768:
        raise HTTPException(422, "Invalid question batch")
    ids = set()
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("id"), str) or not 1 <= len(q["id"]) <= 255 or q["id"] in ids:
            raise HTTPException(422, "Invalid question identity")
        ids.add(q["id"])
        if not isinstance(q.get("question"), str) or not 1 <= len(q["question"]) <= 8000:
            raise HTTPException(422, "Invalid question text")
        intent = q.get("intent")
        if intent is not None and (not isinstance(intent, dict) or intent.get("kind") not in {"plan-review", "approval"}):
            raise HTTPException(403, "Unsupported question intent")
        options = q.get("options", [])
        if not isinstance(options, list) or len(options) > 40:
            raise HTTPException(422, "Invalid question options")
        labels = []
        for option in options:
            if not isinstance(option, dict) or not isinstance(option.get("label"), str) or not 1 <= len(option["label"]) <= 512:
                raise HTTPException(422, "Invalid option label")
            labels.append(option["label"])
        if len(labels) != len(set(labels)) or ("multiSelect" in q and not isinstance(q["multiSelect"], bool)):
            raise HTTPException(422, "Invalid question options")


def validate_answer(questions, answer):
    if answer["cancelled"]:
        if answer["answers"]:
            raise HTTPException(422, "Cancelled question cannot include answers")
        return
    items = answer["answers"]
    if not isinstance(items, list) or len(items) != len(questions):
        raise HTTPException(422, "Every question requires one answer")
    by_id = {q["id"]: q for q in questions}
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {"id", "selected", "custom"} or item.get("id") not in by_id or item["id"] in seen:
            raise HTTPException(422, "Invalid answer identity")
        seen.add(item["id"])
        q = by_id[item["id"]]
        selected = item.get("selected")
        labels = {o["label"] for o in q.get("options", [])}
        if not isinstance(selected, list) or any(not isinstance(v, str) or v not in labels for v in selected) or len(selected) != len(set(selected)) or (not q.get("multiSelect", False) and len(selected) > 1):
            raise HTTPException(422, "Invalid selected options")
        custom = item.get("custom")
        if custom is not None and (not isinstance(custom, str) or len(custom) > 16000):
            raise HTTPException(422, "Invalid custom answer")
        if not q.get("multiSelect", False) and (q.get("intent") or {}).get("kind") not in {"plan-review", "approval"} and selected and isinstance(custom, str) and custom.strip():
            raise HTTPException(422, "Single selection cannot include a custom answer")
        if not selected and not (isinstance(custom, str) and custom.strip()):
            raise HTTPException(422, "An answer is required")


def projected(row, active):
    status = row.status
    if not active and status in {"OPEN", "ANSWERED", "DELIVERING"}:
        status = "UNKNOWN" if status == "DELIVERING" else "CANCELLED"
    return {"id": str(row.id), "attempt_id": str(row.attempt_id), "generation": row.generation,
        "status": status, "request_id": row.request_id, "session_id": row.session_id, "request_digest": row.request_digest, "created_at": row.created_at.isoformat(), "expires_at": row.expires_at.isoformat(),
        "questions": [{**q, "multiple": q.get("multiSelect", False), "allow_custom": True} for q in row.questions],
        "answer": row.answer, "answer_operation_key": row.answer_operation_key, "answer_digest": row.answer_digest}


async def task_attempt(db, project_id, task_id, attempt_id=None):
    task = await service._task(db, task_id, project_id, lock=True)
    if await db.get(CloudTaskDeletion, task.id):
        raise HTTPException(409, "Cloud Task has been deleted")
    if attempt_id is None:
        attempt_id = task.latest_attempt_id
    if attempt_id is None:
        raise HTTPException(409, "No current attempt")
    attempt = await service._attempt(db, task, attempt_id)
    return task, attempt


async def live(db, task, attempt, row):
    try:
        await service._current_grant(db, attempt.authorization_grant_id, task.project_id)
    except HTTPException:
        return False
    now = await service.clock(db)
    grant = await db.scalar(select(CloudWorkGrant.id).where(CloudWorkGrant.attempt_id == attempt.id,
        CloudWorkGrant.lease_generation == row.generation, CloudWorkGrant.worker_id == attempt.lease_owner,
        CloudWorkGrant.revoked_at.is_(None), CloudWorkGrant.expires_at > now).limit(1))
    return bool(row.attempt_id == attempt.id and task.latest_attempt_id == attempt.id and
        attempt.status == "RUNNING" and attempt.lease_generation == row.generation and
        attempt.lease_expires_at and attempt.lease_expires_at > now and grant and row.expires_at > now)


async def fetch_row(db, task, attempt, question_id):
    row = await db.scalar(select(CloudLiveQuestion).where(CloudLiveQuestion.id == question_id,
        CloudLiveQuestion.project_id == task.project_id, CloudLiveQuestion.task_id == task.id,
        CloudLiveQuestion.attempt_id == attempt.id).with_for_update())
    if row is None:
        raise HTTPException(404, "Live question not found")
    return row


async def open_question(db, task, attempt, identity, request_id, session_id, questions, timeout_seconds):
    await service.worker_authority(db, task, attempt, identity)
    if attempt.status != "RUNNING":
        raise HTTPException(409, "Attempt is not running")
    if session_id != "cloud-" + str(attempt.id):
        raise HTTPException(403, "Question session does not match the root attempt")
    validate_questions(questions)
    await service._reject_secrets(db, task.project_id, {"request_id": request_id, "session_id": session_id, "questions": questions})
    digest = service.canonical_json_sha256({"request_id": request_id, "session_id": session_id, "questions": questions, "timeout_seconds": timeout_seconds})
    row = await db.scalar(select(CloudLiveQuestion).where(CloudLiveQuestion.attempt_id == attempt.id,
        CloudLiveQuestion.generation == identity.generation, CloudLiveQuestion.request_id == request_id).with_for_update())
    if row:
        if row.request_digest != digest:
            raise HTTPException(409, "Original question conflicts")
    else:
        row = CloudLiveQuestion(project_id=task.project_id, task_id=task.id, attempt_id=attempt.id,
            generation=identity.generation, request_id=request_id, session_id=session_id, request_digest=digest,
            questions=questions, status="OPEN", expires_at=await service.clock(db) + timedelta(seconds=timeout_seconds))
        db.add(row)
        await db.flush()
    await service.worker_authority(db, task, attempt, identity)
    if not await live(db, task, attempt, row):
        raise HTTPException(409, "Live question expired or fenced")
    result = projected(row, True)
    await db.commit()
    return result


async def worker_lookup(db, task, attempt, identity, request_id, session_id):
    await service.worker_authority(db, task, attempt, identity)
    row = await db.scalar(select(CloudLiveQuestion).where(CloudLiveQuestion.attempt_id == attempt.id,
        CloudLiveQuestion.generation == identity.generation, CloudLiveQuestion.request_id == request_id,
        CloudLiveQuestion.session_id == session_id))
    if row is None:
        raise HTTPException(404, "Original question not found")
    return projected(row, await live(db, task, attempt, row))


async def worker_poll(db, task, attempt, identity, question_id):
    await service.worker_authority(db, task, attempt, identity)
    row = await fetch_row(db, task, attempt, question_id)
    if row.generation != identity.generation or not await live(db, task, attempt, row):
        raise HTTPException(409, "Live question expired or fenced")
    result = {"id": str(row.id), "status": row.status}
    if row.status == "ANSWERED":
        row.status = "DELIVERING"
        result = {"id": str(row.id), "status": "DELIVERING", **row.answer}
    await service.worker_authority(db, task, attempt, identity)
    if not await live(db, task, attempt, row):
        raise HTTPException(409, "Live question expired or fenced")
    await db.commit()
    return result


async def worker_finish(db, task, attempt, identity, question_id, outcome):
    await service.worker_authority(db, task, attempt, identity)
    row = await fetch_row(db, task, attempt, question_id)
    if row.generation != identity.generation or not await live(db, task, attempt, row):
        raise HTTPException(409, "Live question expired or fenced")
    if row.status == outcome:
        return {"id": str(row.id), "status": row.status}
    if outcome == "DELIVERED" and row.status == "DELIVERING":
        row.status = outcome
    elif outcome in {"CANCELLED", "UNKNOWN"} and row.status in {"OPEN", "ANSWERED", "DELIVERING"}:
        row.status = "UNKNOWN" if row.status == "DELIVERING" else "CANCELLED"
    else:
        raise HTTPException(409, "Invalid live question transition")
    await db.commit()
    return {"id": str(row.id), "status": row.status}
