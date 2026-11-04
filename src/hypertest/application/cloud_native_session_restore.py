"""One-shot inspection of a fenced original native SDK session.

This module is disabled by default.  It never sends prompts, resumes a test,
or changes an Attempt's status or result. Historical inspection recovery keeps
the legacy slot lock; other slots can serve other Attempts independently.
"""
from __future__ import annotations

import hmac
import re
import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.domain.cloud_tasks import (
    CloudNativeInspectionClaimState,
    CloudNativeSessionRestore,
    CloudOperationReceipt,
)

from . import cloud_tasks as service
from .services import canonical_json_sha256

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,127}$")
_ACTIVE = ("STARTED", "UNKNOWN")
_CLAIM_FIELDS = {"worker_id", "sequence", "request_key", "lease_seconds"}


def _enabled():
    if not get_settings().cloud_native_session_inspection_enabled:
        raise HTTPException(503, "NATIVE_SESSION_INSPECTION_DISABLED")


def _view(row, *, now=None):
    # An expired/unknown claim is never automatically released or reissued.
    state = "UNKNOWN" if row.state == "STARTED" and now is not None and now >= row.expires_at else row.state
    return {"id": str(row.id), "project_id": str(row.project_id), "task_id": str(row.task_id),
            "attempt_id": str(row.attempt_id), "request_key": row.request_key, "state": state,
            "original_anchor_key": row.original_anchor_key, "worker_id": row.worker_id,
            "original_generation": row.original_generation, "observation": row.observation}


async def _admit(db, task, attempt, *, expected_task_version=None):
    from .cloud_ssh import ensure_remote_closed

    if (task.latest_attempt_id != attempt.id or task.status != "RECOVERY_REQUIRED"
            or attempt.status != "RECOVERY_REQUIRED" or not await service._owner_fenced(db, attempt)):
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_OWNER_NOT_FENCED")
    if expected_task_version is not None and task.version != expected_task_version:
        raise HTTPException(409, "NATIVE_SESSION_TASK_VERSION_CHANGED")
    if attempt.checkpoint.get("cancellation_requested") or attempt.checkpoint.get("pending_operation_keys"):
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_OPERATIONS_PENDING")
    if await service._delegations_unresolved(db, attempt):
        raise HTTPException(409, "NATIVE_SESSION_DELEGATIONS_UNRESOLVED")
    await service._ensure_container_closed(db, task.id)
    await ensure_remote_closed(db, task_id=task.id)
    await service._current_grant(db, attempt.authorization_grant_id, task.project_id)


async def enqueue_inspection(db, *, task, attempt, payload, actor_ref, worker):
    """Queue under mutate's Task/Attempt locks and immutable operation receipt."""
    _enabled()
    if worker is not None or not actor_ref.startswith("operator:"):
        raise HTTPException(403, "NATIVE_SESSION_INSPECTION_OPERATOR_REQUIRED")
    proof = payload.reconciliation
    if (not isinstance(proof, dict)
            or set(proof) != {"old_owner_fenced", "local_processes_stopped", "external_operations_reconciled", "observations"}
            or any(proof.get(key) is not True for key in
                   ("old_owner_fenced", "local_processes_stopped", "external_operations_reconciled"))
            or not isinstance(proof.get("observations"), str)
            or not 1 <= len(proof["observations"].strip()) <= 4096):
        raise HTTPException(409, "NATIVE_SESSION_RECONCILIATION_REQUIRED")
    await _admit(db, task, attempt)
    anchor = await db.scalar(select(CloudOperationReceipt).where(
        CloudOperationReceipt.project_id == task.project_id,
        CloudOperationReceipt.task_id == task.id,
        CloudOperationReceipt.attempt_id == attempt.id,
        CloudOperationReceipt.operation_key == payload.anchor_operation_key,
        CloudOperationReceipt.operation == "ANCHOR_NATIVE_SESSION"))
    if anchor is None or not isinstance(anchor.response, dict):
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_ANCHOR_REQUIRED")
    original = anchor.response.get("native_session_anchor")
    snapshot = anchor.task_snapshot
    snap_attempts = snapshot.get("attempts", []) if isinstance(snapshot, dict) else []
    matching = [x for x in snap_attempts if isinstance(x, dict) and x.get("id") == str(attempt.id)]
    if (not isinstance(original, dict) or anchor.response.get("status") != "ACCEPTED"
            or anchor.response.get("attempt_id") != str(attempt.id)
            or anchor.response.get("operation_key") != payload.anchor_operation_key
            or original.get("identity_profile") != "hypertest-native-session-identity/v1"
            or original.get("session_id") != "cloud-" + str(attempt.id)
            or original.get("input_digest") != attempt.input_digest
            or not re.fullmatch(r"[a-f0-9]{64}", str(original.get("snapshot_sha256", "")))
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", str(original.get("worker_id", "")))
            or type(original.get("generation")) is not int or original["generation"] < 1
            or len(matching) != 1 or matching[0].get("checkpoint", {}).get("native_session_anchor") != original
            or attempt.checkpoint.get("native_session_anchor") != original):
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_ANCHOR_MISMATCH")
    if await db.scalar(select(CloudNativeSessionRestore.id).where(
            CloudNativeSessionRestore.attempt_id == attempt.id)):
        raise HTTPException(409, "NATIVE_SESSION_INSPECTION_ALREADY_RECORDED")
    row = CloudNativeSessionRestore(id=uuid7(), project_id=task.project_id, task_id=task.id,
        attempt_id=attempt.id, request_key=payload.operation_key, requested_by=actor_ref,
        expected_version=payload.expected_version, original_anchor_key=payload.anchor_operation_key,
        identity_digest=original["snapshot_sha256"], input_digest=original["input_digest"],
        session_id=original["session_id"], worker_id=original["worker_id"],
        original_generation=original["generation"], state="PENDING",
        observation={"reconciliation_source": "OPERATOR_ATTESTATION", "independent_stop_proof": False,
                     "old_owner_fenced": True, "local_processes_stopped": True,
                     "external_operations_reconciled": True, "observations": proof["observations"]})
    db.add(row)
    await db.flush()
    return _view(row)


async def block_ordinary_claim_if_inspection_active(db, worker_id):
    """Called only while holding the ordinary Worker slot transaction lock."""
    if await db.scalar(select(CloudNativeSessionRestore.id).where(
            CloudNativeSessionRestore.worker_id == worker_id,
            CloudNativeSessionRestore.state.in_(_ACTIVE)).limit(1)):
        raise HTTPException(409, "NATIVE_SESSION_INSPECTION_OUTSTANDING")


async def lock_control_before_task(db, task_id):
    """Maintain Worker-slot -> Task -> inspection lock order for controls."""
    row = await db.scalar(select(CloudNativeSessionRestore).where(
        CloudNativeSessionRestore.task_id == task_id,
        CloudNativeSessionRestore.state.in_(("PENDING", "STARTED", "UNKNOWN"))).limit(1))
    if row is None:
        return None
    from .cloud_worker_claims import _slot
    await _slot(db, row.worker_id, create=True)
    return row.id


async def guard_control_locked(db, inspection_id, task_id, operation):
    if inspection_id is None:
        return
    row = await db.scalar(select(CloudNativeSessionRestore).where(
        CloudNativeSessionRestore.id == inspection_id, CloudNativeSessionRestore.task_id == task_id)
        .with_for_update().execution_options(populate_existing=True))
    if row is None or row.state not in {"PENDING", "STARTED", "UNKNOWN"}:
        return
    if operation in {"RECONCILE_ATTEMPT", "DELETE_TASK", "RESUME_ATTEMPT"}:
        raise HTTPException(409, "NATIVE_SESSION_INSPECTION_OUTSTANDING")
    if operation in {"CANCEL_TASK", "CANCEL_ATTEMPT"}:
        now = await service.clock(db)
        if row.state == "PENDING":
            row.state, row.finished_at = "CANCELLED", now
            row.observation = {**(row.observation or {}), "inspection_cancelled_before_start": True}
        elif row.state == "STARTED":
            # Do not claim the isolated SDK has stopped. The Worker sees the
            # revoked state through assert and must terminate its child.
            row.state = "UNKNOWN"
            row.observation = {**(row.observation or {}), "inspection_stop_observed": False}


def _validate_claim(request):
    if (not isinstance(request, dict) or set(request) != _CLAIM_FIELDS
            or not isinstance(request.get("worker_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", request["worker_id"])
            or not isinstance(request.get("request_key"), str) or not _KEY.fullmatch(request["request_key"])
            or type(request.get("sequence")) is not int or not 1 <= request["sequence"] <= 9223372036854775807
            or type(request.get("lease_seconds")) is not int or not 15 <= request["lease_seconds"] <= 300):
        raise HTTPException(422, "NATIVE_SESSION_INSPECTION_CLAIM_INVALID")


async def _inspection_slot(db, worker_id):
    # The ordinary slot's advisory lock serializes both protocols without
    # changing legacy claim JSON, digests, sequence, or record types.
    from .cloud_worker_claims import _slot
    normal = await _slot(db, worker_id, create=True)
    row = await db.scalar(select(CloudNativeInspectionClaimState).where(
        CloudNativeInspectionClaimState.worker_id == worker_id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        now = await service.clock(db)
        row = CloudNativeInspectionClaimState(worker_id=worker_id, sequence=0, kind="EMPTY", closed=True,
                                               created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
    return normal, row


def _claim_view(row):
    return {"worker_id": row.worker_id, "sequence": row.sequence, "request_key": row.request_key,
            "kind": row.kind, "closed": row.closed,
            "inspection_id": str(row.inspection_id) if row.inspection_id else None}


def _same_request(row, request):
    if row.request_key != request["request_key"] or row.request_digest != canonical_json_sha256(request):
        raise HTTPException(409, "NATIVE_SESSION_CLAIM_CONFLICT")


def _next_sequence(row, sequence):
    if sequence != row.sequence + 1:
        raise HTTPException(409, "NATIVE_SESSION_CLAIM_SEQUENCE_INVALID")
    if not row.closed:
        raise HTTPException(409, "NATIVE_SESSION_CLAIM_OUTSTANDING")


def _record_claim(row, request, kind, inspection, now):
    row.sequence, row.request_key = request["sequence"], request["request_key"]
    row.request_digest = canonical_json_sha256(request)
    row.kind, row.closed, row.updated_at = kind, kind in {"EMPTY", "ABANDONED"}, now
    row.inspection_id = inspection.id if inspection else None


async def claim(db, request):
    """Issue capability once; a lost response is resolved by original-key reads."""
    _enabled()
    _validate_claim(request)
    worker_id, sequence = request["worker_id"], request["sequence"]
    normal, slot = await _inspection_slot(db, worker_id)
    if not normal.closed:
        raise HTTPException(409, "NATIVE_SESSION_WORKER_BUSY")
    if sequence < slot.sequence:
        raise HTTPException(409, "NATIVE_SESSION_CLAIM_SEQUENCE_RETIRED")
    if sequence == slot.sequence:
        _same_request(slot, request)
        raise HTTPException(409, "NATIVE_SESSION_CLAIM_QUERY_ONLY")
    _next_sequence(slot, sequence)
    await block_ordinary_claim_if_inspection_active(db, worker_id)
    row = await db.scalar(select(CloudNativeSessionRestore).where(
        CloudNativeSessionRestore.worker_id == worker_id, CloudNativeSessionRestore.state == "PENDING")
        .order_by(CloudNativeSessionRestore.created_at, CloudNativeSessionRestore.id)
        .with_for_update(skip_locked=True).limit(1))
    if row is None:
        _record_claim(slot, request, "EMPTY", None, await service.clock(db))
        await db.commit()
        return {**_claim_view(slot), "inspection": None}
    task = await service._task(db, row.task_id, row.project_id, lock=True)
    attempt = await service._attempt(db, task, row.attempt_id)
    await _admit(db, task, attempt, expected_task_version=row.expected_version + 1)
    anchor = attempt.checkpoint.get("native_session_anchor")
    if (not isinstance(anchor, dict) or anchor.get("snapshot_sha256") != row.identity_digest
            or anchor.get("input_digest") != row.input_digest or anchor.get("session_id") != row.session_id
            or anchor.get("worker_id") != worker_id or anchor.get("generation") != row.original_generation):
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_ANCHOR_MISMATCH")
    manifest = attempt.execution_manifest if attempt.execution_manifest is not None else task.frozen_manifest
    if not isinstance(manifest, dict) or canonical_json_sha256(manifest) != row.input_digest:
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_INPUT_MISMATCH")
    try:
        repositories = manifest["resolution"]["repositories"]
        source = {role: repositories[role]["commit_sha"] for role in ("sut", "framework")}
        if any(not isinstance(value, str) or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", value)
               for value in source.values()):
            raise ValueError("invalid source identity")
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_SOURCE_MISSING") from None
    now = await service.clock(db)
    token = secrets.token_urlsafe(32)
    row.state, row.claim_key, row.token_hash = "STARTED", request["request_key"], service.token_hash(token)
    row.started_at, row.expires_at = now, now + timedelta(seconds=request["lease_seconds"])
    _record_claim(slot, request, "INSPECTION", row, now)
    await db.commit()
    # Only the first successful response contains the one-shot capability.
    return {**_claim_view(slot), "inspection": {**_view(row),
            "identity_digest": row.identity_digest, "input_digest": row.input_digest,
            "session_id": row.session_id, "source": source, "task_version": row.expected_version + 1,
            "token": token, "expires_at": row.expires_at.isoformat()}}


async def finish(db, *, worker_id: str, inspection_id, claim_key: str, token: str, status: str):
    """Persist a bounded observation; no Attempt state or test result changes."""
    if status not in {"RESTORED", "FAILED"}:
        raise HTTPException(422, "NATIVE_SESSION_INSPECTION_RESULT_INVALID")
    _, slot = await _inspection_slot(db, worker_id)
    row = await db.scalar(select(CloudNativeSessionRestore).where(
        CloudNativeSessionRestore.id == inspection_id).with_for_update())
    if row is None or row.worker_id != worker_id or row.claim_key != claim_key:
        raise HTTPException(404, "NATIVE_SESSION_INSPECTION_NOT_FOUND")
    if row.state != "STARTED":
        raise HTTPException(409, "NATIVE_SESSION_RESULT_QUERY_ONLY")
    if slot.kind != "INSPECTION" or slot.inspection_id != row.id or slot.request_key != claim_key or slot.closed:
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_CLAIM_MISMATCH")
    if (not isinstance(token, str) or not hmac.compare_digest(row.token_hash, service.token_hash(token))):
        raise HTTPException(403, "NATIVE_SESSION_CAPABILITY_INVALID")
    now = await service.clock(db)
    if now >= row.expires_at:
        raise HTTPException(409, "NATIVE_SESSION_INSPECTION_EXPIRED_UNKNOWN")
    task = await service._task(db, row.task_id, row.project_id, lock=True)
    attempt = await service._attempt(db, task, row.attempt_id)
    await _admit(db, task, attempt, expected_task_version=row.expected_version + 1)
    row.state, row.finished_at = status, now
    slot.closed, slot.updated_at = True, now
    row.observation = {**(row.observation or {}), "source": "NATIVE_SDK_INSPECTION",
        "prompt_sent": False, "continuation_started": False, "session_content_authenticity": "UNPROVEN",
        "external_operation_proof": "NOT_PROVIDED_BY_INSPECTION"}
    await db.commit()
    return _view(row)


async def assert_active(db, *, worker_id: str, inspection_id, claim_key: str, token: str):
    """Recheck authority before and while the isolated inspection is alive."""
    _enabled()
    _, slot = await _inspection_slot(db, worker_id)
    row = await db.scalar(select(CloudNativeSessionRestore).where(
        CloudNativeSessionRestore.id == inspection_id).with_for_update())
    if (row is None or row.worker_id != worker_id or row.claim_key != claim_key
            or row.state != "STARTED" or slot.kind != "INSPECTION"
            or slot.inspection_id != row.id or slot.request_key != claim_key or slot.closed):
        raise HTTPException(409, "NATIVE_SESSION_INSPECTION_NOT_ACTIVE")
    if not isinstance(token, str) or not hmac.compare_digest(row.token_hash, service.token_hash(token)):
        raise HTTPException(403, "NATIVE_SESSION_CAPABILITY_INVALID")
    if await service.clock(db) >= row.expires_at:
        raise HTTPException(409, "NATIVE_SESSION_INSPECTION_EXPIRED_UNKNOWN")
    task = await service._task(db, row.task_id, row.project_id, lock=True)
    attempt = await service._attempt(db, task, row.attempt_id)
    await _admit(db, task, attempt, expected_task_version=row.expected_version + 1)
    return {"active": True}


async def read_by_key(db, *, project_id, request_key: str, actor_ref: str, operator: bool):
    """Read only the original request; this never grants a capability."""
    row = await db.scalar(select(CloudNativeSessionRestore).where(
        CloudNativeSessionRestore.project_id == project_id,
        CloudNativeSessionRestore.request_key == request_key))
    if row is None:
        raise HTTPException(404, "NATIVE_SESSION_INSPECTION_NOT_FOUND")
    if not operator and row.requested_by != actor_ref:
        raise HTTPException(403, "NATIVE_SESSION_INSPECTION_OWNER_REQUIRED")
    return _view(row, now=await service.clock(db))


async def read_claim(db, *, worker_id: str):
    """Read a high-water mark; no capability or inspection data is returned."""
    slot = await db.scalar(select(CloudNativeInspectionClaimState).where(
        CloudNativeInspectionClaimState.worker_id == worker_id))
    if slot is None:
        return {"worker_id": worker_id, "sequence": 0, "request_key": None,
                "kind": "EMPTY", "closed": True, "inspection_id": None}
    return _claim_view(slot)


async def read_result_by_claim(db, *, worker_id: str, claim_key: str):
    """Read an inspection's result by its original claim; never return tokens."""
    row = await db.scalar(select(CloudNativeSessionRestore).where(
        CloudNativeSessionRestore.worker_id == worker_id, CloudNativeSessionRestore.claim_key == claim_key))
    if row is None:
        raise HTTPException(404, "NATIVE_SESSION_CLAIM_NOT_FOUND_QUERY_ONLY")
    state = "UNKNOWN" if row.state == "STARTED" and await service.clock(db) >= row.expires_at else row.state
    return {"id": str(row.id), "state": state, "claim_key": claim_key,
            "request_key": row.request_key, "attempt_id": str(row.attempt_id)}


async def reconcile_claim(db, request):
    """Seal a lost original claim, never redelivering its capability or work."""
    _validate_claim(request)
    worker_id, sequence = request["worker_id"], request["sequence"]
    _, slot = await _inspection_slot(db, worker_id)
    if sequence < slot.sequence:
        return {"worker_id": worker_id, "sequence": sequence, "request_key": request["request_key"],
                "kind": "RETIRED", "closed": True, "current_sequence": slot.sequence}
    if sequence > slot.sequence:
        _next_sequence(slot, sequence)
        _record_claim(slot, request, "ABANDONED", None, await service.clock(db))
    else:
        _same_request(slot, request)
        if not slot.closed:
            row = await db.scalar(select(CloudNativeSessionRestore).where(
                CloudNativeSessionRestore.id == slot.inspection_id).with_for_update())
            if row is None or row.worker_id != worker_id or row.state not in {"STARTED", "UNKNOWN"}:
                raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_CLAIM_MISMATCH")
            # The child may have started before the lost response. Do not retry
            # or release this Worker for ordinary execution without observation.
            row.state = "UNKNOWN"
            slot.closed, slot.updated_at = True, await service.clock(db)
    await db.commit()
    return _claim_view(slot)
