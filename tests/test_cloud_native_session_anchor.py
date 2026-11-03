"""Pre-prompt native session identity is anchored by the original fenced Worker."""
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import select
from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import legacy_claimed, post, read_all, worker_submit

from hypertest.api.cloud_schemas import CloudMutation
from hypertest.application import cloud_tasks as service
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import (
    CloudAttempt,
    CloudOperationReceipt,
    CloudTask,
    CloudWorkGrant,
)


def _payload(context, receipt, **changes):
    fields = {"project_id": context["project_id"], "task_id": receipt["task_id"],
        "attempt_id": receipt["attempt_id"], "expected_version": receipt["version"],
        "operation_key": "native-anchor-original", "operation": "ANCHOR_NATIVE_SESSION",
        "identity_profile": "hypertest-native-session-identity/v1", "snapshot_sha256": "a" * 64,
        "input_digest": receipt["input_digest"], "session_id": "cloud-" + receipt["attempt_id"]}
    fields.update(changes)
    return TypeAdapter(CloudMutation).validate_python(fields)


async def _anchor(payload, identity, *, native_worker=True):
    async with AsyncSessionLocal() as db:
        return await service.mutate(db, payload, "worker:" + identity.worker_id,
                                    worker=identity, native_worker=native_worker)


@pytest.mark.asyncio
async def test_anchor_is_native_fenced_pre_prompt_idempotent_and_immutable(cloud_context):
    context = cloud_context
    receipt, claim, identity = await legacy_claimed(context)
    payload = _payload(context, receipt)
    # Public Operator/control authorization is not a Worker execution capability.
    public = await post(context, "ANCHOR_NATIVE_SESSION", receipt["version"],
                        operation_key="public-anchor", task_id=receipt["task_id"],
                        attempt_id=receipt["attempt_id"], identity_profile=payload.identity_profile,
                        snapshot_sha256=payload.snapshot_sha256, input_digest=payload.input_digest,
                        session_id=payload.session_id)
    assert public.status_code == 403
    with pytest.raises(HTTPException) as error:
        await _anchor(payload, identity, native_worker=False)
    assert error.value.status_code == 403

    accepted = await _anchor(payload, identity)
    anchor = accepted["native_session_anchor"]
    assert anchor == {"identity_profile": payload.identity_profile, "snapshot_sha256": "a" * 64,
        "input_digest": receipt["input_digest"], "session_id": payload.session_id,
        "worker_id": identity.worker_id, "generation": identity.generation}
    assert accepted["version"] == receipt["version"] + 1
    assert accepted["checkpoint"]["native_session_anchor"] == anchor
    fixed = await read_all(context, receipt["task_id"], accepted["version"])
    original = next(row for row in fixed["attempts"] if row["id"] == receipt["attempt_id"])
    assert original["checkpoint"]["native_session_anchor"] == anchor
    assert await _anchor(payload, identity) == accepted
    with pytest.raises(HTTPException) as error:
        await _anchor(_payload(context, receipt, snapshot_sha256="b" * 64), identity)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await _anchor(_payload(context, receipt, operation_key="second-anchor",
            expected_version=accepted["version"]), identity)
    assert error.value.detail == "NATIVE_SESSION_ANCHOR_MUST_PRECEDE_RUNTIME"
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(receipt["task_id"]))
        attempt = await db.get(CloudAttempt, UUID(receipt["attempt_id"]))
        rows = list(await db.scalars(select(CloudOperationReceipt).where(
            CloudOperationReceipt.attempt_id == attempt.id,
            CloudOperationReceipt.operation == "ANCHOR_NATIVE_SESSION")))
        assert len(rows) == 1
        assert task.status == attempt.status == "PREPARING"
        assert task.reported_result == attempt.reported_result == "NOT_RUN"
        assert task.latest_attempt_id == attempt.id


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"input_digest": "b" * 64},
    {"session_id": "cloud-different-attempt"},
])
async def test_anchor_rejects_mismatched_original_identity(cloud_context, changes):
    receipt, _, identity = await legacy_claimed(cloud_context)
    with pytest.raises(HTTPException) as error:
        await _anchor(_payload(cloud_context, receipt, **changes), identity)
    assert error.value.detail == "NATIVE_SESSION_ANCHOR_IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_anchor_cannot_be_added_after_running_or_after_fence(cloud_context):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    running = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 60, "request_limits": [
            {"scope": "ROOT", "max_requests": 1, "cost_per_request_microunits": 1}]})
    with pytest.raises(HTTPException) as error:
        await _anchor(_payload(context, receipt, expected_version=running["version"]), identity)
    assert error.value.detail == "NATIVE_SESSION_ANCHOR_IDENTITY_MISMATCH"
    async with AsyncSessionLocal() as db:
        await service.fence_attempt_for_recovery(db, UUID(receipt["task_id"]), UUID(receipt["attempt_id"]),
                                                 identity, "WORKER_RUNTIME_FAILED")
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(receipt["task_id"]))
        version = task.version
    with pytest.raises(HTTPException) as error:
        await _anchor(_payload(context, receipt, expected_version=version), identity)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_anchor_cannot_be_backfilled_by_a_later_generation(cloud_context):
    receipt, _, identity = await legacy_claimed(cloud_context)
    later_lease, later_work = "fixture-later-lease-token", "fixture-later-work-token"
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(receipt["attempt_id"]))
        grant = await db.scalar(select(CloudWorkGrant).where(CloudWorkGrant.attempt_id == attempt.id))
        grant.revoked_at = datetime.now(UTC)
        attempt.lease_generation = 2
        attempt.lease_token_hash = service.token_hash(later_lease)
        db.add(CloudWorkGrant(project_id=attempt.project_id, attempt_id=attempt.id,
            token_hash=service.token_hash(later_work), worker_id=identity.worker_id,
            lease_generation=2, expires_at=attempt.lease_expires_at, created_at=datetime.now(UTC)))
        await db.commit()
    later = service.WorkerIdentity(identity.worker_id, later_lease, 2, later_work)
    with pytest.raises(HTTPException) as error:
        await _anchor(_payload(cloud_context, receipt), later)
    assert error.value.detail == "NATIVE_SESSION_ANCHOR_IDENTITY_MISMATCH"
