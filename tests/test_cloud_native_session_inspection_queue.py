"""One-shot native inspection admission; no real SDK, model, or SUT work."""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import select
from test_cloud_native_session_anchor import _anchor, _payload
from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import dispatched, legacy_dispatched

from hypertest.api.cloud_schemas import CloudMutation
from hypertest.application import cloud_native_session_restore as restore
from hypertest.application import cloud_tasks as service
from hypertest.application import cloud_worker_claims
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import (
    CloudAttempt,
    CloudNativeSessionRestore,
    CloudOperationReceipt,
    CloudTask,
)


@pytest.fixture
async def prepared(cloud_context, monkeypatch):
    context = cloud_context
    monkeypatch.setattr(get_settings(), "cloud_native_session_inspection_enabled", True)
    receipt = await dispatched(context)
    worker_id = "fixture-worker-" + uuid4().hex
    original_attempt, original_resolution = service.claim_attempt, service.claim_resolution
    async def scoped_attempt(db, worker_id, lease_seconds=90, **kwargs):
        return await original_attempt(db, worker_id, lease_seconds,
            **{**kwargs, "project_id": UUID(context["project_id"])})
    async def scoped_resolution(db, worker_id, lease_seconds=90, **kwargs):
        return await original_resolution(db, worker_id, lease_seconds,
            **{**kwargs, "project_id": UUID(context["project_id"])})
    monkeypatch.setattr(service, "claim_attempt", scoped_attempt)
    monkeypatch.setattr(service, "claim_resolution", scoped_resolution)
    async with AsyncSessionLocal() as db:
        claim = await service.claim_attempt(db, worker_id, project_id=UUID(context["project_id"]))
    worker = service.WorkerIdentity(worker_id, claim["lease_token"], claim["generation"], claim["work_token"])
    anchor = await _anchor(_payload(context, receipt), worker)
    async with AsyncSessionLocal() as db:
        await service.fence_attempt_for_recovery(db, UUID(receipt["task_id"]), UUID(receipt["attempt_id"]),
                                                 worker, "WORKER_INTERRUPTED")
    context["receipt"], context["anchor"], context["worker_id"] = receipt, anchor, worker_id
    return context


def inspect_body(context, *, key="inspection-request-original", **changes):
    data = {"project_id": context["project_id"], "task_id": context["receipt"]["task_id"],
        "attempt_id": context["receipt"]["attempt_id"], "expected_version": context["anchor"]["version"],
        "operation": "INSPECT_NATIVE_SESSION", "operation_key": key,
        "anchor_operation_key": "native-anchor-original",
        "reconciliation": {"old_owner_fenced": True, "local_processes_stopped": True,
                           "external_operations_reconciled": True, "observations": "Synthetic fixtures only"}}
    data.update(changes)
    return data


async def enqueue(context, body=None):
    """Seed a historical accepted inspection, as it existed before admission was disabled.

    This fixture exercises recovery of already accepted records, not new admission.
    """
    body = body or inspect_body(context)
    payload = TypeAdapter(CloudMutation).validate_python(body)
    actor = "operator:" + get_settings().connector_operator_identity
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(CloudOperationReceipt).where(
            CloudOperationReceipt.project_id == payload.project_id,
            CloudOperationReceipt.operation_key == payload.operation_key))
        if existing:
            return await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"], json=body)
        try:
            await service.project(db, payload.project_id, lock=True)
            await service._lock(db, f"cloud-native-inspection-task:{payload.task_id}")
            task = await service._task(db, payload.task_id, payload.project_id, lock=True)
            attempt = await service._attempt(db, task, payload.attempt_id)
            inspection = await restore.enqueue_inspection(db, task=task, attempt=attempt,
                payload=payload, actor_ref=actor, worker=None)
            task.version += 1
            await db.flush()
            response = {"status": "ACCEPTED", "profile": service.PROFILE,
                "project_id": str(payload.project_id), "operation_key": payload.operation_key,
                "operation": payload.operation, "version": task.version, "task_id": str(task.id),
                "attempt_id": str(attempt.id), "checkpoint": attempt.checkpoint,
                "native_session_inspection": inspection}
            snapshot = await service._snapshot(db, task)
            db.add(CloudOperationReceipt(id=uuid7(), project_id=payload.project_id, task_id=task.id,
                attempt_id=attempt.id, operation_key=payload.operation_key, operation=payload.operation,
                actor_ref=actor, input_digest=service.canonical_json_sha256(service._safe_payload(payload)),
                expected_version=payload.expected_version, accepted_version=task.version,
                response=response, task_snapshot=snapshot))
            await db.commit()
            return httpx.Response(200, json=response)
        except HTTPException as error:
            await db.rollback()
            return httpx.Response(error.status_code, json={"detail": error.detail})


def request(context, sequence=1, key="inspection-claim-original"):
    return {"worker_id": context["worker_id"], "sequence": sequence, "request_key": key, "lease_seconds": 90}


@pytest.mark.asyncio
async def test_default_disabled_and_unanchored_history_refused(prepared, monkeypatch):
    context = prepared
    for enabled in (False, True):
        monkeypatch.setattr(get_settings(), "cloud_native_session_inspection_enabled", enabled)
        disabled = await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"],
                                                json=inspect_body(context))
        assert disabled.status_code == 409 and "NATIVE_SESSION_INSPECTION_UNSAFE_DISABLED" in disabled.text
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(CloudNativeSessionRestore.id).where(
            CloudNativeSessionRestore.attempt_id == UUID(context["receipt"]["attempt_id"]))) is None


@pytest.mark.asyncio
async def test_original_key_idempotence_and_preserved_attempt(prepared):
    context = prepared
    body = inspect_body(context)
    first = await enqueue(context, body)
    assert first.status_code == 200, first.text
    replay = await enqueue(context, body)
    assert replay.status_code == 200 and replay.json() == first.json()
    bad = await enqueue(context, {**body, "anchor_operation_key": "other-original-anchor"})
    assert bad.status_code == 409
    view = await context["client"].get("/api/v1/cloud/native-session-inspections/by-key",
        headers=context["operator_headers"], params={"project_id": context["project_id"], "operation_key": body["operation_key"]})
    assert view.status_code == 200 and view.json()["state"] == "PENDING"
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(context["receipt"]["attempt_id"]))
        task = await db.get(CloudTask, UUID(context["receipt"]["task_id"]))
        assert task.latest_attempt_id == attempt.id and task.status == attempt.status == "RECOVERY_REQUIRED"
        assert task.reported_result == attempt.reported_result == "NOT_RUN"
        assert task.version == body["expected_version"] + 1


@pytest.mark.asyncio
async def test_unobserved_proof_and_non_operator_rejected(prepared):
    context = prepared
    body = inspect_body(context)
    bad = await enqueue(context, {**body, "reconciliation": {**body["reconciliation"],
                                                            "external_operations_reconciled": False}})
    assert bad.status_code == 409
    non_operator = await context["client"].post("/api/v1/cloud/operations", headers=context["headers"], json=body)
    assert non_operator.status_code == 403


@pytest.mark.asyncio
async def test_absent_claim_is_sealed_before_any_new_request(prepared):
    assert (await enqueue(prepared)).status_code == 200
    original = request(prepared)
    async with AsyncSessionLocal() as db:
        sealed = await restore.reconcile_claim(db, original)
        assert sealed["kind"] == "ABANDONED" and sealed["closed"]
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await restore.claim(db, original)
        assert error.value.detail == "NATIVE_SESSION_CLAIM_QUERY_ONLY"
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(CloudNativeSessionRestore).where(
            CloudNativeSessionRestore.attempt_id == UUID(prepared["receipt"]["attempt_id"])))
        assert row.state == "PENDING"
    async with AsyncSessionLocal() as db:
        issued = await restore.claim(db, request(prepared, 2, "inspection-claim-second"))
        assert issued["kind"] == "INSPECTION" and issued["inspection"]["token"]


@pytest.mark.asyncio
async def test_lost_claim_and_finish_never_redeliver_or_repeat(prepared):
    assert (await enqueue(prepared)).status_code == 200
    original = request(prepared)
    async with AsyncSessionLocal() as db:
        first = await restore.claim(db, original)
    assert first["kind"] == "INSPECTION"
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await restore.claim(db, original)
        assert error.value.detail == "NATIVE_SESSION_CLAIM_QUERY_ONLY"
    data = first["inspection"]
    async with AsyncSessionLocal() as db:
        result = await restore.finish(db, worker_id=prepared["worker_id"], inspection_id=UUID(data["id"]),
            claim_key=original["request_key"], token=data["token"], status="RESTORED")
        assert result["state"] == "RESTORED"
        assert result["observation"]["continuation_started"] is False
        assert result["observation"]["session_content_authenticity"] == "UNPROVEN"
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await restore.finish(db, worker_id=prepared["worker_id"], inspection_id=UUID(data["id"]),
                claim_key=original["request_key"], token=data["token"], status="RESTORED")
        assert error.value.detail == "NATIVE_SESSION_RESULT_QUERY_ONLY"
    async with AsyncSessionLocal() as db:
        observed = await restore.read_result_by_claim(db, worker_id=prepared["worker_id"], claim_key=original["request_key"])
        assert observed["state"] == "RESTORED" and "token" not in observed


@pytest.mark.asyncio
async def test_unknown_original_inspection_and_legacy_claim_cannot_relaunch(prepared):
    assert (await enqueue(prepared)).status_code == 200
    original = request(prepared)
    async with AsyncSessionLocal() as db:
        assert (await restore.claim(db, original))["kind"] == "INSPECTION"
    async with AsyncSessionLocal() as db:
        assert (await restore.reconcile_claim(db, original))["closed"]
    async with AsyncSessionLocal() as db:
        result = await restore.read_result_by_claim(db, worker_id=prepared["worker_id"], claim_key=original["request_key"])
        assert result["state"] == "UNKNOWN"
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await cloud_worker_claims.claim(db, {"worker_id": prepared["worker_id"], "sequence": 1,
                "request_key": "ordinary-claim-original", "lease_seconds": 90, "supports_attempt_manifest": True})
        assert error.value.detail == "LEGACY_CLAIM_RECOVERY_ONLY"
    async with AsyncSessionLocal() as db:
        ordinary = await cloud_worker_claims.claim(db, {"worker_id": prepared["worker_id"], "slot_id": "slot-1",
            "sequence": 1, "request_key": "new-slot-original-key", "lease_seconds": 90,
            "supports_attempt_manifest": True})
        assert ordinary["kind"] == "EMPTY"  # Recovery work is never an ordinary new claim.


@pytest.mark.asyncio
async def test_worker_identity_version_and_cancel_fence(prepared):
    context = prepared
    queued = await enqueue(context)
    assert queued.status_code == 200
    async with AsyncSessionLocal() as db:
        other = await restore.claim(db, {**request(context), "worker_id": context["worker_id"] + "-other"})
        assert other["kind"] == "EMPTY"
    async with AsyncSessionLocal() as db:
        first = await restore.claim(db, request(context))
    data = first["inspection"]
    async with AsyncSessionLocal() as db:
        assert await restore.assert_active(db, worker_id=context["worker_id"], inspection_id=UUID(data["id"]),
            claim_key=request(context)["request_key"], token=data["token"]) == {"active": True}
    cancel = await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"], json={
        "project_id": context["project_id"], "task_id": context["receipt"]["task_id"],
        "attempt_id": context["receipt"]["attempt_id"], "operation": "CANCEL_ATTEMPT",
        "operation_key": "cancel-inspection-fixture", "expected_version": queued.json()["version"], "reason": "fixture"})
    assert cancel.status_code == 200, cancel.text
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException):
            await restore.assert_active(db, worker_id=context["worker_id"], inspection_id=UUID(data["id"]),
                claim_key=request(context)["request_key"], token=data["token"])
        result = await restore.read_result_by_claim(db, worker_id=context["worker_id"], claim_key=request(context)["request_key"])
        assert result["state"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_other_attempt_slot_can_run_during_original_inspection(prepared):
    context = prepared
    assert (await enqueue(context)).status_code == 200
    await legacy_dispatched(context)

    async def inspect_claim():
        async with AsyncSessionLocal() as db:
            try:
                return await restore.claim(db, request(context))
            except HTTPException as error:
                return error.detail

    async def ordinary_claim():
        async with AsyncSessionLocal() as db:
            try:
                return await cloud_worker_claims.claim(db, {"worker_id": context["worker_id"], "slot_id": "slot-1", "sequence": 1,
                    "request_key": "ordinary-claim-original", "lease_seconds": 90, "supports_attempt_manifest": True})
            except HTTPException as error:
                return error.detail

    inspected, ordinary = await asyncio.gather(inspect_claim(), ordinary_claim())
    assert inspected["kind"] == "INSPECTION" and ordinary["kind"] == "ATTEMPT"
    assert ordinary["claim"]["attempt"]["id"] != inspected["inspection"]["attempt_id"]


@pytest.mark.asyncio
async def test_task_version_change_before_claim_blocks_inspection(prepared):
    context = prepared
    assert (await enqueue(context)).status_code == 200
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(context["receipt"]["task_id"]))
        task.version += 1
        await db.commit()
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await restore.claim(db, request(context))
        assert error.value.detail == "NATIVE_SESSION_TASK_VERSION_CHANGED"
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(CloudNativeSessionRestore).where(
            CloudNativeSessionRestore.attempt_id == UUID(context["receipt"]["attempt_id"])))
        assert row.state == "PENDING" and row.claim_key is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["RECONCILE_ATTEMPT", "RESUME_ATTEMPT"])
async def test_terminal_reconciliation_or_resume_blocked_during_inspection(prepared, operation):
    context = prepared
    queued = await enqueue(context)
    assert queued.status_code == 200
    async with AsyncSessionLocal() as db:
        first = await restore.claim(db, request(context))
    assert first["kind"] == "INSPECTION"
    body = {"project_id": context["project_id"], "task_id": context["receipt"]["task_id"],
        "attempt_id": context["receipt"]["attempt_id"], "operation": "RECONCILE_ATTEMPT",
        "operation_key": "reconcile-during-inspection", "expected_version": queued.json()["version"],
        "status": "FAILED", "reason": "fixture", "reconciliation": {
            "old_owner_fenced": True, "local_processes_stopped": True,
            "external_operations_reconciled": True, "observations": "fixture"}}
    if operation == "RESUME_ATTEMPT":
        body.pop("status")
        body.update(operation=operation, identity_source="PRE_PROMPT_ANCHORED")
    denied = await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"], json=body)
    assert denied.status_code == 409 and "INSPECTION_OUTSTANDING" in denied.text
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(context["receipt"]["attempt_id"]))
        assert attempt.status == "RECOVERY_REQUIRED" and attempt.reported_result == "NOT_RUN"


@pytest.mark.asyncio
async def test_cancel_racing_claim_never_leaves_inspection_active(prepared):
    context = prepared
    queued = await enqueue(context)
    assert queued.status_code == 200

    async def claim_once():
        async with AsyncSessionLocal() as db:
            try:
                return await restore.claim(db, request(context))
            except HTTPException as error:
                return error.detail

    async def cancel_once():
        return await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"], json={
            "project_id": context["project_id"], "task_id": context["receipt"]["task_id"],
            "attempt_id": context["receipt"]["attempt_id"], "operation": "CANCEL_ATTEMPT",
            "operation_key": "cancel-racing-inspection", "expected_version": queued.json()["version"], "reason": "fixture"})

    claimed, cancelled = await asyncio.gather(claim_once(), cancel_once())
    assert cancelled.status_code == 200, cancelled.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(CloudNativeSessionRestore).where(
            CloudNativeSessionRestore.attempt_id == UUID(context["receipt"]["attempt_id"])))
        assert row.state in {"CANCELLED", "UNKNOWN"}
        assert row.state != "STARTED"
    if isinstance(claimed, dict) and claimed["kind"] == "INSPECTION":
        data = claimed["inspection"]
        async with AsyncSessionLocal() as db:
            with pytest.raises(HTTPException):
                await restore.assert_active(db, worker_id=context["worker_id"], inspection_id=UUID(data["id"]),
                    claim_key=request(context)["request_key"], token=data["token"])


@pytest.mark.asyncio
async def test_cancel_serializes_with_not_yet_visible_inspection(prepared, monkeypatch):
    """A concurrent cancel must see an inspection committed after it began."""
    context = prepared
    enqueue_entered, release_enqueue, control_looked = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_enqueue = restore.enqueue_inspection
    original_control = restore.lock_control_before_task

    async def gated_enqueue(*args, **kwargs):
        # mutate already holds the Task lock, but has not inserted the row.
        enqueue_entered.set()
        await release_enqueue.wait()
        return await original_enqueue(*args, **kwargs)

    async def observed_control(*args, **kwargs):
        result = await original_control(*args, **kwargs)
        control_looked.set()
        return result

    monkeypatch.setattr(restore, "enqueue_inspection", gated_enqueue)
    monkeypatch.setattr(restore, "lock_control_before_task", observed_control)
    started = asyncio.create_task(enqueue(context))
    await asyncio.wait_for(enqueue_entered.wait(), 5)
    cancel = asyncio.create_task(context["client"].post(
        "/api/v1/cloud/operations", headers=context["operator_headers"], json={
            "project_id": context["project_id"], "task_id": context["receipt"]["task_id"],
            "attempt_id": context["receipt"]["attempt_id"], "operation": "CANCEL_ATTEMPT",
            "operation_key": "cancel-racing-enqueue-fixture",
            "expected_version": context["anchor"]["version"] + 1, "reason": "fixture"}))
    try:
        # Without the shared advisory lock this lookup can see no row and
        # then wait on the Task; the subsequently committed row is missed.
        try:
            await asyncio.wait_for(control_looked.wait(), 0.2)
        except TimeoutError:
            pass
    finally:
        release_enqueue.set()
    queued, cancelled = await asyncio.wait_for(asyncio.gather(started, cancel), 10)
    assert queued.status_code == 200, queued.text
    assert cancelled.status_code == 200, cancelled.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(CloudNativeSessionRestore).where(
            CloudNativeSessionRestore.attempt_id == UUID(context["receipt"]["attempt_id"])))
        assert row.state == "CANCELLED"
        assert row.observation["inspection_cancelled_before_start"] is True


@pytest.mark.asyncio
async def test_cancel_racing_inspection_finish_does_not_deadlock(prepared):
    context = prepared
    queued = await enqueue(context)
    assert queued.status_code == 200
    async with AsyncSessionLocal() as db:
        claimed = await restore.claim(db, request(context))
    data = claimed["inspection"]

    async def finish_once():
        async with AsyncSessionLocal() as db:
            try:
                return await restore.finish(db, worker_id=context["worker_id"], inspection_id=UUID(data["id"]),
                    claim_key=request(context)["request_key"], token=data["token"], status="RESTORED")
            except HTTPException as error:
                return error.detail

    async def cancel_once():
        return await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"], json={
            "project_id": context["project_id"], "task_id": context["receipt"]["task_id"],
            "attempt_id": context["receipt"]["attempt_id"], "operation": "CANCEL_ATTEMPT",
            "operation_key": "cancel-racing-finish-fixture", "expected_version": queued.json()["version"],
            "reason": "fixture"})

    finished, cancelled = await asyncio.wait_for(asyncio.gather(finish_once(), cancel_once()), 10)
    assert cancelled.status_code == 200, cancelled.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(CloudNativeSessionRestore).where(
            CloudNativeSessionRestore.attempt_id == UUID(context["receipt"]["attempt_id"])))
        attempt = await db.get(CloudAttempt, UUID(context["receipt"]["attempt_id"]))
        assert row.state in {"RESTORED", "UNKNOWN"}
        assert attempt.status == "RECOVERY_REQUIRED" and attempt.reported_result == "NOT_RUN"
    assert (isinstance(finished, dict) and finished["state"] == "RESTORED") or isinstance(finished, str)


@pytest.mark.asyncio
async def test_anchored_summary_and_choice_only_report_receipt_existence(prepared):
    context = prepared
    task_id = context["receipt"]["task_id"]
    summary = await context["client"].get(f"/api/v1/cloud/tasks/{task_id}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert summary.status_code == 200
    assert summary.json()["recovery"]["identity_anchor"] == "RECORDED"
    assert summary.json()["recovery"]["identity_anchor_verifies_session"] is False
    saved = await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"], json={
        "project_id": context["project_id"], "task_id": task_id,
        "attempt_id": context["receipt"]["attempt_id"], "expected_version": context["anchor"]["version"],
        "operation": "RECORD_RECOVERY_CHOICE", "operation_key": "operator-anchored-choice",
        "choice": "CONTINUE_ORIGINAL_SESSION"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["recovery_choice"]["identity_anchor"] == "RECORDED"
    assert saved.json()["recovery_choice"]["action_started"] is False
