"""Bounded native Worker claim recovery. Recovery never returns execution capability."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.application import cloud_tasks as service
from hypertest.application.services import canonical_json_sha256
from hypertest.domain.cloud_tasks import (
    TERMINAL,
    CloudAttempt,
    CloudInputResolution,
    CloudWorkerClaimState,
    CloudWorkGrant,
)


def _view(row, worker_id):
    if row is None:
        return {"worker_id": worker_id, "sequence": 0, "request_key": None, "kind": "EMPTY", "closed": True}
    return {"worker_id": row.worker_id, "sequence": row.sequence, "request_key": row.request_key,
            "kind": row.kind, "closed": row.closed}


async def _slot(db, worker_id, *, create):
    # Also serialize first insertion: a row lock alone cannot lock an absent row.
    await service._lock(db, "cloud-worker-claim:" + worker_id)
    row = await db.scalar(select(CloudWorkerClaimState).where(CloudWorkerClaimState.worker_id == worker_id)
                          .with_for_update().execution_options(populate_existing=True))
    if row is None and create:
        now = await service.clock(db)
        row = CloudWorkerClaimState(worker_id=worker_id, sequence=0, request_key=None, request_digest=None,
            kind="EMPTY", closed=True, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
    return row


def _same_request(row, request):
    if row.request_key != request["request_key"] or row.request_digest != canonical_json_sha256(request):
        raise HTTPException(409, "CLAIM_REQUEST_CONFLICT")


def _next_sequence(row, sequence):
    if sequence != row.sequence + 1:
        raise HTTPException(409, "CLAIM_SEQUENCE_INVALID")
    if not row.closed:
        raise HTTPException(409, "CLAIM_OUTSTANDING")


def _record(row, request, kind, claimed, now):
    row.sequence, row.request_key = request["sequence"], request["request_key"]
    row.request_digest = canonical_json_sha256(request)
    row.kind, row.closed, row.updated_at = kind, kind in {"EMPTY", "ABANDONED"}, now
    row.project_id = row.task_id = row.attempt_id = row.resolution_id = row.generation = None
    if claimed is not None:
        row.project_id, row.task_id = UUID(claimed["task"]["project_id"]), UUID(claimed["task"]["id"])
        row.generation = claimed["generation"]
        if kind == "ATTEMPT":
            row.attempt_id = UUID(claimed["attempt"]["id"])
        else:
            row.resolution_id = UUID(claimed["resolution"]["id"])


async def state(db, worker_id):
    return _view(await _slot(db, worker_id, create=False), worker_id)


async def claim(db, request):
    worker_id = request["worker_id"]
    row = await _slot(db, worker_id, create=True)
    # The native inspection path uses the very same transaction lock.  Its
    # outstanding capability must never overlap an ordinary Worker claim.
    from .cloud_native_session_restore import block_ordinary_claim_if_inspection_active
    await block_ordinary_claim_if_inspection_active(db, worker_id)
    sequence = request["sequence"]
    if sequence < row.sequence:
        raise HTTPException(409, "CLAIM_SEQUENCE_RETIRED")
    if sequence == row.sequence:
        _same_request(row, request)
        raise HTTPException(409, "CLAIM_RECONCILIATION_REQUIRED")
    _next_sequence(row, sequence)
    # Every inner write, including expired/rejected candidates, belongs to this
    # transaction. No lease can commit without the same claim high-water mark.
    await service.expire_leases(db, commit=False)
    claimed = await service.claim_resolution(db, worker_id, request["lease_seconds"], commit=False)
    kind = "RESOLUTION"
    if claimed is None:
        claimed = await service.claim_attempt(db, worker_id, request["lease_seconds"],
            supports_attempt_manifest=request["supports_attempt_manifest"], commit=False)
        kind = "ATTEMPT" if claimed is not None else "EMPTY"
    _record(row, request, kind, claimed, await service.clock(db))
    await db.commit()
    # Tokens exist only in this first response. They are never in the slot,
    # state/reconcile response, audit metadata, or a replay response.
    return {**_view(row, worker_id), "claim": claimed}


async def _fence_attempt(db, row):
    task = await service._task(db, row.task_id, row.project_id, lock=True)
    attempt = await db.scalar(select(CloudAttempt).where(CloudAttempt.id == row.attempt_id,
        CloudAttempt.task_id == row.task_id, CloudAttempt.project_id == row.project_id).with_for_update())
    if attempt is None:
        raise HTTPException(409, "CLAIM_TARGET_MISSING")
    if attempt.status in TERMINAL:
        return
    if attempt.status in {"RECOVERY_REQUIRED", "WAITING_INPUT"} and await service._owner_fenced(db, attempt):
        return
    if (task.latest_attempt_id != attempt.id or attempt.lease_owner != row.worker_id
            or attempt.lease_generation != row.generation
            or attempt.status not in {"PREPARING", "RUNNING", "RECOVERY_REQUIRED"}):
        raise HTTPException(409, "CLAIM_OWNER_CHANGED")
    await service._fence(db, attempt)
    if attempt.status != "RECOVERY_REQUIRED":
        service._state(task, attempt, "RECOVERY_REQUIRED", "Original Worker claim closed without execution replay",
                       await service.clock(db))
    service._events(db, row.project_id, "worker:" + row.worker_id, "CLAIM_RECOVERY_FENCED", row.task_id,
        {"attempt_id": str(row.attempt_id), "generation": row.generation, "sequence": row.sequence})


async def _fence_resolution(db, row):
    await service._task(db, row.task_id, row.project_id, lock=True)
    resolution = await db.scalar(select(CloudInputResolution).where(CloudInputResolution.id == row.resolution_id,
        CloudInputResolution.task_id == row.task_id, CloudInputResolution.project_id == row.project_id).with_for_update())
    if resolution is None:
        raise HTTPException(409, "CLAIM_TARGET_MISSING")
    if resolution.status in {"ACCEPTED", "FAILED"}:
        return
    grants = list(await db.scalars(select(CloudWorkGrant).where(
        CloudWorkGrant.resolution_id == resolution.id, CloudWorkGrant.revoked_at.is_(None))))
    if (resolution.status == "RECOVERY_REQUIRED" and resolution.lease_token_hash is None
            and resolution.lease_expires_at is None and not grants):
        return
    if (resolution.status not in {"RESOLVING", "RECOVERY_REQUIRED"}
            or resolution.worker_id != row.worker_id or row.generation != 1
            or any(grant.worker_id != row.worker_id or grant.lease_generation != row.generation for grant in grants)):
        raise HTTPException(409, "CLAIM_OWNER_CHANGED")
    now = await service.clock(db)
    resolution.status = "RECOVERY_REQUIRED"
    resolution.lease_token_hash = resolution.lease_expires_at = None
    for grant in grants:
        grant.revoked_at = now
    service._events(db, row.project_id, "worker:" + row.worker_id, "CLAIM_RECOVERY_FENCED", row.task_id,
        {"resolution_id": str(row.resolution_id), "generation": row.generation, "sequence": row.sequence})


async def reconcile(db, request):
    """Seal an absent original request or fence its original owner; never execute."""
    worker_id = request["worker_id"]
    row = await _slot(db, worker_id, create=True)
    sequence = request["sequence"]
    if sequence < row.sequence:
        return {"worker_id": worker_id, "sequence": sequence, "request_key": request["request_key"],
                "kind": "RETIRED", "closed": True, "current_sequence": row.sequence}
    if sequence > row.sequence:
        _next_sequence(row, sequence)
        # The same lock excludes a late /claim for this sequence. A mere absent
        # lookup would not establish that the original request cannot arrive.
        _record(row, request, "ABANDONED", None, await service.clock(db))
    else:
        _same_request(row, request)
        if not row.closed:
            if row.kind == "ATTEMPT":
                await _fence_attempt(db, row)
            elif row.kind == "RESOLUTION":
                await _fence_resolution(db, row)
            else:
                raise HTTPException(409, "CLAIM_STATE_INVALID")
            row.updated_at = await service.clock(db)
            row.closed = True
    await db.commit()
    return _view(row, worker_id)
