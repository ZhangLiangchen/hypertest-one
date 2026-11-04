"""Explicit continuation of one fenced native Attempt; never replay old input."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.application import cloud_tasks as service
from hypertest.domain.cloud_tasks import CloudConversationMessage, CloudWorkGrant

DEFAULT_CONTINUATION = (
    "Continue this testing task from the saved conversation and accepted artifacts. "
    "First check what remains unfinished. Preserve prior results and original operation identities; "
    "never repeat an operation whose outcome is unknown."
)


async def enqueue_resume(db, *, task, attempt, payload, actor_ref, worker):
    """Called inside the existing versioned control transaction and Task lock."""
    if worker is not None or not actor_ref.startswith("operator:"):
        raise HTTPException(403, "NATIVE_RESUME_OPERATOR_REQUIRED")
    from .cloud_native_session_restore import _admit
    await _admit(db, task, attempt)
    if await db.scalar(select(CloudConversationMessage.id).where(
            CloudConversationMessage.attempt_id == attempt.id,
            CloudConversationMessage.role == "USER",
            CloudConversationMessage.status.in_(("DELIVERING", "UNKNOWN"))).limit(1)):
        raise HTTPException(409, "NATIVE_RESUME_MESSAGE_DELIVERY_UNKNOWN")
    if service.attempt_inputs(task, attempt).get("budgets") is not None:
        raise HTTPException(409, "NATIVE_RESUME_LEGACY_BUDGET_UNSUPPORTED")
    proof = payload.reconciliation
    if (not isinstance(proof, dict)
            or any(proof.get(key) is not True for key in
                   ("old_owner_fenced", "local_processes_stopped", "external_operations_reconciled"))
            or not isinstance(proof.get("observations"), str)
            or not 1 <= len(proof["observations"].strip()) <= 4096
            or proof.get("pending_operation_keys")):
        raise HTTPException(409, "NATIVE_RESUME_RECONCILIATION_REQUIRED")
    original = await db.scalar(select(CloudWorkGrant).where(
        CloudWorkGrant.attempt_id == attempt.id).order_by(CloudWorkGrant.lease_generation.desc()).limit(1))
    if original is None:
        raise HTTPException(409, "NATIVE_RESUME_ORIGINAL_WORKER_REQUIRED")
    source = payload.identity_source
    anchor = attempt.checkpoint.get("native_session_anchor")
    if source == "PRE_PROMPT_ANCHORED" and (not isinstance(anchor, dict)
            or anchor.get("worker_id") != original.worker_id
            or anchor.get("session_id") != "cloud-" + str(attempt.id)
            or anchor.get("input_digest") != attempt.input_digest):
        raise HTTPException(409, "NATIVE_SESSION_ORIGINAL_ANCHOR_REQUIRED")
    if source not in {"PRE_PROMPT_ANCHORED", "OPERATOR_ADOPTED"}:
        raise HTTPException(422, "NATIVE_RESUME_IDENTITY_SOURCE_INVALID")
    now = await service.clock(db)
    intent = {"profile": "hypertest-native-continuation/v1", "operation_key": payload.operation_key,
        "worker_id": original.worker_id, "source_generation": original.lease_generation,
        "target_generation": attempt.lease_generation + 1, "session_id": "cloud-" + str(attempt.id),
        "input_digest": attempt.input_digest, "identity_source": source,
        "continuation": payload.continuation, "requested_by": actor_ref,
        "requested_at": now.isoformat(), "reconciliation_source": "OPERATOR_ATTESTATION",
        "reconciliation": {key: proof[key] for key in
            ("old_owner_fenced", "local_processes_stopped", "external_operations_reconciled", "observations")},
        "historical_identity_preanchored": source == "PRE_PROMPT_ANCHORED"}
    checkpoint = dict(attempt.checkpoint)
    previous = checkpoint.get("native_resume")
    if previous is not None:
        checkpoint["native_resume_history"] = [*checkpoint.get("native_resume_history", []), previous]
    checkpoint["native_resume"] = intent
    attempt.checkpoint = checkpoint
    service._state(task, attempt, "PREPARING", "Explicit original-session continuation requested", now)
    return intent


async def record_identity(db, *, task_id, attempt_id, identity, operation_key, snapshot_sha256, identity_source):
    """Accept only this generation's current identity, before any new input."""
    task = await service._task(db, task_id, lock=True)
    attempt = await service._attempt(db, task, attempt_id)
    await service.worker_authority(db, task, attempt, identity)
    intent = attempt.checkpoint.get("native_resume", {})
    if (intent.get("operation_key") != operation_key or intent.get("worker_id") != identity.worker_id
            or intent.get("target_generation") != identity.generation
            or intent.get("identity_source") != identity_source):
        raise HTTPException(409, "NATIVE_RESUME_IDENTITY_TARGET_MISMATCH")
    observation = {"operation_key": operation_key, "generation": identity.generation,
        "identity_source": identity_source, "snapshot_sha256": snapshot_sha256,
        "session_id": intent["session_id"], "historical_identity_preanchored": identity_source == "PRE_PROMPT_ANCHORED"}
    observations = dict(attempt.runtime_metadata.get("native_resume_identities", {}))
    previous = observations.get(str(identity.generation))
    if previous is not None and previous != observation:
        raise HTTPException(409, "NATIVE_RESUME_IDENTITY_CONFLICT")
    if previous is None:
        observations[str(identity.generation)] = observation
        attempt.runtime_metadata = {**attempt.runtime_metadata, "native_resume_identities": observations}
        service._events(db, task.project_id, "worker:" + identity.worker_id,
            "NATIVE_RESUME_IDENTITY", task.id, {"attempt_id": str(attempt.id), **observation})
        await db.commit()
    return observation
