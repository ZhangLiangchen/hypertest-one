"""Ordinary messages reconnect the original session without a second prompt."""
from uuid import UUID

import pytest
from sqlalchemy import select

from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import post, worker_submit
from test_cloud_worker_claim_recovery import api, queued, request, target
from test_cloud_worker_claim_recovery import claim_context as claim_context

from hypertest.application import cloud_tasks as service
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


async def claim_next(context, sequence):
    # The real Worker closes its per-slot claim before taking another one.
    state = (await api(context, "/state")).json()
    if not state["closed"]:
        original = {"worker_id": context["worker_id"], "slot_id": "slot-1", "sequence": state["sequence"],
                    "request_key": state["request_key"], "lease_seconds": 90, "supports_attempt_manifest": True}
        assert (await api(context, "/reconcile", original)).status_code == 200
    claimed = (await api(context, "", request(context, sequence))).json()["claim"]
    identity = service.WorkerIdentity(context["worker_id"], claimed["lease_token"], claimed["generation"], claimed["work_token"])
    await worker_submit(context, identity, {"task_id": claimed["task"]["id"], "attempt_id": claimed["attempt"]["id"],
        "version": claimed["task"]["version"]}, "TRANSITION", status="RUNNING")
    return claimed


async def poll(context, claim):
    return await context["client"].post("/api/v1/cloud/worker/conversation/poll", headers=context["worker_headers"],
        json={**target(context, claim), "session_id": "cloud-" + claim["attempt"]["id"]})


async def test_missing_anchor_reconnects_from_send_with_one_queued_message(claim_context):
    context = claim_context
    work, original = await setup(context)
    await close(context, original)
    view = await context["client"].get(f"/api/v1/cloud/tasks/{work['task_id']}/conversation", headers=context["headers"],
                                      params={"project_id": context["project_id"]})
    assert view.json()["session"]["can_send"] and view.json()["session"]["can_reconnect"]
    sent = await send(context, work)
    assert sent.status_code == 200, sent.text
    assert (await send(context, work)).json() == sent.json()
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        intent = attempt.checkpoint["native_resume"]
        assert intent["mode"] == "RESTORE_ONLY" and intent["worker_id"] == context["worker_id"]
        assert not {"continuation", "identity_source", "reconciliation", "native_session_anchor"} & intent.keys()
        assert "native_session_anchor" not in attempt.checkpoint and attempt.reported_result == "NOT_RUN"
        assert await service.claim_attempt(db, "different-worker", project_id=UUID(context["project_id"])) is None
    claimed = await claim_next(context, 2)
    assert claimed["attempt"]["id"] == work["attempt_id"] and claimed["generation"] == sent.json()["generation"]
    assert (await poll(context, claimed)).json()["message"]["id"] == sent.json()["id"]
    assert (await poll(context, claimed)).json()["message"] is None


async def test_failed_connection_preserves_unattempted_message_and_original_digest(claim_context):
    context = claim_context
    work, original = await setup(context)
    await close(context, original)
    sent = (await send(context, work)).json()
    claimed = await claim_next(context, 2)
    await close(context, claimed)  # No polling or SDK delivery ever occurred.
    history = await context["client"].get(f"/api/v1/cloud/tasks/{work['task_id']}/conversation",
        headers=context["headers"], params={"project_id": context["project_id"]})
    assert history.json()["session"]["can_reconnect"]
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "RECOVERY_REQUIRED"
        retry_generation = attempt.lease_generation + 1
        assert (await db.get(CloudConversationMessage, UUID(sent["id"]))).generation == sent["generation"]
    retried = await send(context, work)
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] == sent["id"] and retried.json()["status"] == "QUEUED"
    assert retried.json()["generation"] == retry_generation
    assert (await send(context, work)).json() == retried.json()
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudConversationMessage, UUID(sent["id"]))
        assert row.status == "QUEUED" and row.generation == retried.json()["generation"]
        assert row.request_digest == sent["request_digest"]
        rows = list(await db.scalars(select(CloudConversationMessage).where(
            CloudConversationMessage.attempt_id == UUID(work["attempt_id"]),
            CloudConversationMessage.role == "USER")))
        assert [message.id for message in rows] == [row.id]
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "PREPARING"
        assert attempt.checkpoint["native_resume"]["operation_key"] == sent["operation_key"]
    claimed_again = await claim_next(context, 3)
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
    assert (await send(context, work, "message:two")).status_code == 409
    assert (await send(context, work)).json()["status"] == "UNKNOWN"
    acknowledged = await context["client"].post("/api/v1/cloud/worker/conversation/ack", headers=context["worker_headers"],
        json={**target(context, original), "session_id": "cloud-" + work["attempt_id"], "message_id": sent["id"],
              "status": "DELIVERED", "sdk_message_id": "original-sdk-message"})
    assert acknowledged.status_code == 200, acknowledged.text
    assert (await send(context, work, "message:two")).status_code == 200


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
