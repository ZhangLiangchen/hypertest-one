"""Operator choices are immutable notes, never commands or Agent reports."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import legacy_claimed, post, read_all, worker_submit

from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudAttempt, CloudOperationReceipt, CloudTask


@pytest.mark.asyncio
async def test_record_recovery_choice_preserves_unknown_and_fixed_history(cloud_context):
    context = cloud_context
    receipt, _, worker = await legacy_claimed(context)
    recovery = await worker_submit(context, worker, receipt, "TRANSITION", status="RECOVERY_REQUIRED",
                                   reason="synthetic interruption")
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(receipt["attempt_id"]))
        attempt.checkpoint = {**attempt.checkpoint, "pending_operation_keys": ["original-unknown"],
                              "external_operations_reconciled": False}
        await db.commit()
    operator = {**context, "headers": context["operator_headers"]}
    fields = {"task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"],
              "choice": "CONTINUE_ORIGINAL_SESSION", "note": "Inspect before any continuation."}
    key = "recovery-choice-" + uuid4().hex
    denied = await post(context, "RECORD_RECOVERY_CHOICE", recovery["version"], operation_key=key, **fields)
    assert denied.status_code == 403
    stale = await post(operator, "RECORD_RECOVERY_CHOICE", recovery["version"] - 1, operation_key=key, **fields)
    assert stale.status_code == 409
    invalid = await post(operator, "RECORD_RECOVERY_CHOICE", recovery["version"], operation_key=key,
                         **{**fields, "note": "x" * 4097})
    assert invalid.status_code == 422
    saved = await post(operator, "RECORD_RECOVERY_CHOICE", recovery["version"], operation_key=key, **fields)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    item = result["recovery_choice"]
    assert item["actor_ref"].startswith("operator:")
    assert item["identity_anchor"] == "MISSING" and item["action_started"] is False
    assert item["recorded_at"] and item["choice"] == fields["choice"] and item["note"] == fields["note"]
    previous = await read_all(context, receipt["task_id"], recovery["version"])
    fixed = await read_all(context, receipt["task_id"], result["version"])
    assert previous["recovery_choices"] == [] and fixed["recovery_choices"] == [item]
    attempt = fixed["attempts"][-1]
    assert fixed["task"]["status"] == attempt["status"] == "RECOVERY_REQUIRED"
    assert attempt["checkpoint"]["pending_operation_keys"] == ["original-unknown"]
    assert attempt["checkpoint"]["external_operations_reconciled"] is False
    assert attempt["reported_result"] == "NOT_RUN"
    summary = await context["client"].get(f"/api/v1/cloud/tasks/{receipt['task_id']}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert summary.status_code == 200 and summary.json()["recovery_choices"] == [item]
    assert summary.json()["recovery"]["identity_anchor"] == "MISSING"
    assert summary.json()["recovery"]["identity_anchor_verifies_session"] is False
    same = await post(operator, "RECORD_RECOVERY_CHOICE", recovery["version"], operation_key=key, **fields)
    assert same.json() == result
    conflict = await post(operator, "RECORD_RECOVERY_CHOICE", recovery["version"], operation_key=key,
                          **{**fields, "note": "Changed request"})
    assert conflict.status_code == 409
    by_key = await context["client"].get("/api/v1/cloud/operations/by-key", params={
        "project_id": context["project_id"], "operation_key": key}, headers=context["operator_headers"])
    assert by_key.status_code == 200 and by_key.json() == result
    for choice in ("RETEST", "END_EXECUTION"):
        nxt = await post(operator, "RECORD_RECOVERY_CHOICE", result["version"],
                         **({**fields, "choice": choice, "note": "  "} if choice == "RETEST" else
                            {k: v for k, v in {**fields, "choice": choice}.items() if k != "note"}))
        assert nxt.status_code == 200, nxt.text
        result = nxt.json()
        assert result["recovery_choice"]["note"] == ""
    final = await read_all(context, receipt["task_id"], result["version"])
    assert [x["choice"] for x in final["recovery_choices"]] == ["CONTINUE_ORIGINAL_SESSION", "RETEST", "END_EXECUTION"]
    assert final["task"]["status"] == "RECOVERY_REQUIRED" and final["attempts"][-1]["checkpoint"] == attempt["checkpoint"]
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(receipt["task_id"]))
        assert task.latest_attempt_id == UUID(receipt["attempt_id"])
        attempts = list(await db.scalars(select(CloudAttempt).where(CloudAttempt.task_id == task.id)))
        assert len(attempts) == 1
        receipts = list(await db.scalars(select(CloudOperationReceipt).where(CloudOperationReceipt.task_id == task.id,
                          CloudOperationReceipt.operation == "RECORD_RECOVERY_CHOICE")))
        assert len(receipts) == 3


@pytest.mark.asyncio
async def test_record_choice_rejects_non_recovery_and_wrong_attempt(cloud_context):
    context = cloud_context
    receipt, _, worker = await legacy_claimed(context)
    operator = {**context, "headers": context["operator_headers"]}
    fields = {"task_id": receipt["task_id"], "attempt_id": receipt["attempt_id"],
              "choice": "END_EXECUTION", "note": "Record a choice only."}
    active = await post(operator, "RECORD_RECOVERY_CHOICE", receipt["version"], **fields)
    assert active.status_code == 409
    recovery = await worker_submit(context, worker, receipt, "TRANSITION", status="RECOVERY_REQUIRED",
                                   reason="synthetic interruption")
    wrong = await post(operator, "RECORD_RECOVERY_CHOICE", recovery["version"],
                       **{**fields, "attempt_id": str(uuid4())})
    assert wrong.status_code == 409


@pytest.mark.asyncio
async def test_new_session_inspection_is_rejected_without_enqueue(cloud_context):
    context = cloud_context
    receipt, _, worker = await legacy_claimed(context)
    recovery = await worker_submit(context, worker, receipt, "TRANSITION", status="RECOVERY_REQUIRED",
                                   reason="synthetic interruption")
    operator = {**context, "headers": context["operator_headers"]}
    rejected = await post(operator, "INSPECT_NATIVE_SESSION", recovery["version"], task_id=receipt["task_id"],
        attempt_id=receipt["attempt_id"], anchor_operation_key="old-anchor",
        reconciliation={"observations": "synthetic"})
    assert rejected.status_code == 409 and "NATIVE_SESSION_INSPECTION_UNSAFE_DISABLED" in rejected.text
    capability = (await context["client"].get("/api/v1/cloud/capabilities")).json()["recovery"]
    assert capability["native_session_inspection_supported"] is False
    async with AsyncSessionLocal() as db:
        from hypertest.domain.cloud_tasks import CloudNativeSessionRestore
        assert not list(await db.scalars(select(CloudNativeSessionRestore).where(
            CloudNativeSessionRestore.attempt_id == UUID(receipt["attempt_id"]))))
        task = await db.get(CloudTask, UUID(receipt["task_id"]))
        assert task.version == recovery["version"] and task.status == "RECOVERY_REQUIRED"
