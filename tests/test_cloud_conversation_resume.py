"""Durable messages drive Worker delivery without a second prompt or user reconnect."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import post, worker_submit
from test_cloud_worker_claim_recovery import api, queued, request, target
from test_cloud_worker_claim_recovery import claim_context as claim_context

from hypertest.application import cloud_tasks as service
from hypertest.application.cloud_conversation_resume import schedule_queued_connection
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudAttempt, CloudConversationMessage, CloudTask


async def setup(context):
    work = await queued(context)
    claim = (await api(context, "", request(context))).json()["claim"]
    identity = service.WorkerIdentity(context["worker_id"], claim["lease_token"], claim["generation"], claim["work_token"])
    await worker_submit(context, identity, work, "TRANSITION", status="RUNNING")
    return work, claim


async def close(context, claim):
    identity = service.WorkerIdentity(context["worker_id"], claim["lease_token"], claim["generation"], claim["work_token"])
    async with AsyncSessionLocal() as db:
        await service.fence_attempt_for_recovery(db, UUID(claim["task"]["id"]), UUID(claim["attempt"]["id"]),
                                                identity, "WORKER_INTERRUPTED")


async def send(context, work, key="message:one", **changes):
    return await context["client"].post(f"/api/v1/cloud/tasks/{work['task_id']}/conversation", headers=context["headers"],
        json={"project_id": context["project_id"], "attempt_id": work["attempt_id"], "operation_key": key,
              "text": "Explain the existing blocker.", **changes})


async def next_claim_response(context, sequence):
    # The real Worker closes its per-slot claim before taking another one.
    state = (await api(context, "/state")).json()
    if not state["closed"]:
        original = {"worker_id": context["worker_id"], "slot_id": "slot-1", "sequence": state["sequence"],
                    "request_key": state["request_key"], "lease_seconds": 90, "supports_attempt_manifest": True}
        assert (await api(context, "/reconcile", original)).status_code == 200
    response = await api(context, "", request(context, sequence))
    assert response.status_code == 200, response.text
    return response.json()


async def claim_next(context, sequence):
    claimed = (await next_claim_response(context, sequence))["claim"]
    assert claimed is not None
    identity = service.WorkerIdentity(context["worker_id"], claimed["lease_token"], claimed["generation"], claimed["work_token"])
    await worker_submit(context, identity, {"task_id": claimed["task"]["id"], "attempt_id": claimed["attempt"]["id"],
        "version": claimed["task"]["version"]}, "TRANSITION", status="RUNNING")
    return claimed


async def poll(context, claim):
    return await context["client"].post("/api/v1/cloud/worker/conversation/poll", headers=context["worker_headers"],
        json={**target(context, claim), "session_id": "cloud-" + claim["attempt"]["id"]})


async def test_offline_send_only_saves_then_worker_claim_restores_original_session(claim_context):
    context = claim_context
    work, original = await setup(context)
    await close(context, original)
    view = await context["client"].get(f"/api/v1/cloud/tasks/{work['task_id']}/conversation", headers=context["headers"],
                                      params={"project_id": context["project_id"]})
    assert view.json()["session"]["can_send"] and not view.json()["session"]["can_reconnect"]
    assert view.json()["session"]["state"] == "PAUSED"
    sent = await send(context, work)
    assert sent.status_code == 200, sent.text
    assert (await send(context, work)).json() == sent.json()
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "RECOVERY_REQUIRED" and "native_resume" not in attempt.checkpoint
        assert attempt.reported_result == "NOT_RUN"
        await schedule_queued_connection(db, "different-worker")
        assert attempt.status == "RECOVERY_REQUIRED" and "native_resume" not in attempt.checkpoint
        assert await service.claim_attempt(db, "different-worker", project_id=UUID(context["project_id"])) is None
    claimed = await claim_next(context, 2)
    assert claimed["attempt"]["id"] == work["attempt_id"] and claimed["generation"] > sent.json()["generation"]
    intent = claimed["attempt"]["checkpoint"]["native_resume"]
    assert intent["mode"] == "RESTORE_ONLY" and intent["worker_id"] == context["worker_id"]
    assert not {"continuation", "identity_source", "reconciliation", "native_session_anchor"} & intent.keys()
    assert (await poll(context, claimed)).json()["message"]["id"] == sent.json()["id"]
    assert (await poll(context, claimed)).json()["message"] is None


@pytest.mark.parametrize("reason", ["WORKER_INTERRUPTED", "SDK_SESSION_BUSY"])
async def test_failed_connection_preserves_unattempted_message_and_original_digest(claim_context, reason):
    context = claim_context
    work, original = await setup(context)
    await close(context, original)
    sent = (await send(context, work)).json()
    claimed = await claim_next(context, 2)
    # The child failed before polling or SDK input delivery. The fixed reason
    # must pass the actual Worker fence schema and retain the queued message.
    fenced = await context["client"].post("/api/v1/cloud/worker/fence", headers=context["worker_headers"],
        json={**target(context, claimed), "reason": reason})
    assert fenced.status_code == 200, fenced.text
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        original_checkpoint, original_generation = dict(attempt.checkpoint), attempt.lease_generation
        original_version = (await db.get(CloudTask, UUID(work["task_id"]))).version
    retried = await send(context, work)
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] == sent["id"] and retried.json()["status"] == "QUEUED"
    assert retried.json()["generation"] == claimed["generation"]
    assert (await send(context, work)).json() == retried.json()
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        assert row.status == "QUEUED" and row.generation == claimed["generation"]
        assert row.request_digest == sent["request_digest"]
        rows = list(await db.scalars(select(CloudConversationMessage).where(
            CloudConversationMessage.attempt_id == UUID(work["attempt_id"]),
            CloudConversationMessage.role == "USER")))
        assert [message.id for message in rows] == [row.id]
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "RECOVERY_REQUIRED"
        assert attempt.reason == reason
        assert attempt.checkpoint == original_checkpoint and attempt.lease_generation == original_generation
        assert (await db.get(CloudTask, UUID(work["task_id"]))).version == original_version
    assert (await next_claim_response(context, 3))["claim"] is None
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        intent = {**attempt.checkpoint["native_resume"],
                  "next_retry_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
        attempt.checkpoint = {**attempt.checkpoint, "native_resume": intent}
        await db.commit()
    claimed_again = await claim_next(context, 4)
    assert (await poll(context, claimed_again)).json()["message"]["id"] == sent["id"]
    assert (await poll(context, claimed_again)).json()["message"] is None


@pytest.mark.parametrize("status", ["DELIVERING", "UNKNOWN", "DELIVERED"])
async def test_original_key_never_reconnects_an_attempted_message(claim_context, status):
    context = claim_context
    work, original = await setup(context)
    sent = (await send(context, work)).json()
    await close(context, original)
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        row.status = status
        row.sdk_message_id = "original-sdk-message" if status == "DELIVERED" else None
        await db.commit()
    retried = await send(context, work)
    assert retried.status_code == 200 and retried.json()["status"] == status
    assert retried.json()["id"] == sent["id"] and retried.json()["generation"] == sent["generation"]
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "RECOVERY_REQUIRED" and "native_resume" not in attempt.checkpoint


async def test_original_key_conflicts_do_not_reconnect_queued_message(claim_context):
    context = claim_context
    work, original = await setup(context)
    sent = (await send(context, work)).json()
    await close(context, original)
    conflict = await send(context, work, text="Different request under the same key.")
    assert conflict.status_code == 409 and conflict.json()["detail"] == "CONVERSATION_MESSAGE_CONFLICT"
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        row.actor_ref = "different-original-actor"
        await db.commit()
    conflict = await send(context, work)
    assert conflict.status_code == 409 and conflict.json()["detail"] == "CONVERSATION_MESSAGE_CONFLICT"
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "RECOVERY_REQUIRED" and "native_resume" not in attempt.checkpoint
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        assert row.status == "QUEUED" and row.generation == sent["generation"]


async def test_legacy_queued_digest_keeps_its_original_generation_after_reconnect(claim_context):
    context = claim_context
    work, original = await setup(context)
    sent = (await send(context, work)).json()
    legacy_digest = service.canonical_json_sha256({"project_id": context["project_id"],
        "task_id": work["task_id"], "attempt_id": work["attempt_id"], "text": sent["text"],
        "generation": original["generation"]})
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        row.request_digest = legacy_digest  # A previously accepted old-format request.
        await db.commit()
    await close(context, original)
    assert (await send(context, work, "message:two")).status_code == 200
    recovered = await send(context, work, generation=original["generation"])
    assert recovered.status_code == 200 and recovered.json()["request_digest"] == legacy_digest
    current = await claim_next(context, 2)
    message = (await poll(context, current)).json()["message"]
    assert message["id"] == sent["id"] and message["request_generation"] == original["generation"]
    assert message["generation"] == current["generation"] and message["request_digest"] == legacy_digest


async def test_unknown_message_is_not_bypassed_or_replayed(claim_context):
    context = claim_context
    work, original = await setup(context)
    sent = (await send(context, work)).json()
    assert (await poll(context, original)).json()["message"]["id"] == sent["id"]
    await close(context, original)
    next_message = await send(context, work, "message:two")
    assert next_message.status_code == 200 and next_message.json()["status"] == "QUEUED"
    assert (await send(context, work)).json()["status"] == "UNKNOWN"
    assert (await next_claim_response(context, 2))["claim"] is None
    async with AsyncSessionLocal() as db:
        old = await db.get(CloudConversationMessage, UUID(sent["id"]))
        assert old.status == "UNKNOWN" and old.generation == original["generation"]
        assert old.request_digest == sent["request_digest"]
    acknowledged = await context["client"].post("/api/v1/cloud/worker/conversation/ack", headers=context["worker_headers"],
        json={**target(context, original), "session_id": "cloud-" + work["attempt_id"], "message_id": sent["id"],
              "status": "DELIVERED", "sdk_message_id": "original-sdk-message"})
    assert acknowledged.status_code == 200, acknowledged.text
    claimed = await claim_next(context, 3)
    assert (await poll(context, claimed)).json()["message"]["id"] == next_message.json()["id"]


async def test_no_queued_input_does_not_restart_old_task(claim_context):
    context = claim_context
    work, original = await setup(context)
    await close(context, original)
    assert (await next_claim_response(context, 2))["claim"] is None
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "RECOVERY_REQUIRED" and "native_resume" not in attempt.checkpoint


async def test_messages_saved_before_first_worker_claim_are_delivered_once(claim_context):
    context = claim_context
    work = await queued(context)
    sent = await send(context, work)
    assert sent.status_code == 200 and sent.json()["status"] == "QUEUED", sent.text
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.lease_generation == 0 and attempt.status == "QUEUED"
    claimed = await claim_next(context, 1)
    delivered = (await poll(context, claimed)).json()["message"]
    assert delivered["id"] == sent.json()["id"] and delivered["generation"] == claimed["generation"]
    assert (await poll(context, claimed)).json()["message"] is None


async def test_expired_lease_with_saved_input_is_resumed_by_claim(claim_context):
    context = claim_context
    work, original = await setup(context)
    sent = (await send(context, work)).json()
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    # Another slot observes expiry and takes pending input without another send.
    result = await api(context, "", request(context, slot_id="slot-2"))
    assert result.status_code == 200, result.text
    claimed = result.json()["claim"]
    assert claimed["attempt"]["id"] == work["attempt_id"]
    assert claimed["generation"] > original["generation"]
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        assert row.status == "QUEUED" and row.generation == claimed["generation"]


async def test_manual_resume_retired_and_cancelled_attempt_does_not_reconnect(claim_context):
    context = claim_context
    work, original = await setup(context)
    await close(context, original)
    async with AsyncSessionLocal() as db:
        version = (await db.get(CloudTask, UUID(work["task_id"]))).version
    retired = await post(context, "RESUME_ATTEMPT", version, task_id=work["task_id"], attempt_id=work["attempt_id"],
        reason="Historical schema", identity_source="OPERATOR_ADOPTED", reconciliation={"old_owner_fenced": True})
    assert retired.status_code == 410
    assert (await send(context, work)).status_code == 200
    cancelled = await post(context, "CANCEL_ATTEMPT", version, task_id=work["task_id"], attempt_id=work["attempt_id"], reason="Stop this task")
    assert cancelled.status_code == 200, cancelled.text
    assert (await send(context, work, "message:two")).status_code == 409
    assert (await send(context, work)).json()["status"] == "CANCELLED"


async def test_revoked_execution_authorization_preserves_queue_without_resuming(claim_context):
    from hypertest.domain.interactive import InteractiveIntegrationGrant

    context = claim_context
    work, original = await setup(context)
    await close(context, original)
    sent = (await send(context, work)).json()
    async with AsyncSessionLocal() as db:
        grant = await db.get(InteractiveIntegrationGrant, UUID(context["grant"]["grant_id"]))
        now = await service.clock(db)
        grant.status = "REVOKED"
        grant.row_version += 1
        grant.revoked_at = now
        await db.commit()
    rejected = await context["client"].post(f"/api/v1/cloud/tasks/{work['task_id']}/conversation",
        headers=context["operator_headers"], json={"project_id": context["project_id"],
        "attempt_id": work["attempt_id"], "operation_key": "message:denied", "text": "No execution grant."})
    assert rejected.status_code == 409
    assert (await next_claim_response(context, 2))["claim"] is None
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        assert attempt.status == "RECOVERY_REQUIRED" and "native_resume" not in attempt.checkpoint
        assert row.status == "QUEUED" and row.generation == sent["generation"]


async def test_permanent_session_identity_failure_does_not_retry_saved_input(claim_context):
    context = claim_context
    work, original = await setup(context)
    fenced = await context["client"].post("/api/v1/cloud/worker/fence", headers=context["worker_headers"],
        json={**target(context, original), "reason": "SDK_SESSION_UNAVAILABLE"})
    assert fenced.status_code == 200, fenced.text
    sent = (await send(context, work)).json()
    assert (await next_claim_response(context, 2))["claim"] is None
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        assert attempt.status == "RECOVERY_REQUIRED" and "native_resume" not in attempt.checkpoint
        assert row.status == "QUEUED" and row.generation == sent["generation"]
