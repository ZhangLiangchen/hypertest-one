"""Original-session continuation admission; synthetic DB records, no SDK calls."""
from uuid import UUID

from test_cloud_native_session_anchor import _anchor, _payload
from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import post, worker_submit
from test_cloud_worker_claim_recovery import api, queued, request, target
from test_cloud_worker_claim_recovery import claim_context as claim_context

from hypertest.application import cloud_tasks as service
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudAttempt, CloudTask


async def recoverable(context, *, anchor=False, pending_message=False):
    work = await queued(context)
    body = request(context)
    claimed = (await api(context, "", body)).json()["claim"]
    if anchor:
        identity = service.WorkerIdentity(context["worker_id"], claimed["lease_token"],
                                          claimed["generation"], claimed["work_token"])
        await _anchor(_payload(context, work), identity)
    if pending_message:
        identity = service.WorkerIdentity(context["worker_id"], claimed["lease_token"],
                                          claimed["generation"], claimed["work_token"])
        work = await worker_submit(context, identity, work, "TRANSITION", status="RUNNING")
        worker_body = {**target(context, claimed), "session_id": "cloud-" + work["attempt_id"]}
        state = await context["client"].post("/api/v1/cloud/worker/conversation/append",
            headers=context["worker_headers"], json={**worker_body, "event_key": "fixture:running",
                "role": "SYSTEM", "state": "RUNNING"})
        assert state.status_code == 200, state.text
        message = await context["client"].post(f"/api/v1/cloud/tasks/{work['task_id']}/conversation",
            headers=context["headers"], json={"project_id": context["project_id"], "attempt_id": work["attempt_id"],
                "generation": claimed["generation"], "operation_key": "fixture:original-user-input",
                "text": "Inspect the existing blocker."})
        assert message.status_code == 200, message.text
        polled = await context["client"].post("/api/v1/cloud/worker/conversation/poll",
            headers=context["worker_headers"], json=worker_body)
        assert polled.json()["message"]["id"] == message.json()["id"]
        claimed["fixture_message_id"] = message.json()["id"]
    assert (await api(context, "/reconcile", body)).status_code == 200
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(work["task_id"]))
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        return {**work, "version": task.version, "generation": attempt.lease_generation}, claimed


async def resume(context, work, **changes):
    return await post({**context, "headers": context["operator_headers"]}, "RESUME_ATTEMPT", work["version"],
        task_id=work["task_id"], attempt_id=work["attempt_id"], reason="Resume synthetic saved conversation",
        **{"identity_source": "OPERATOR_ADOPTED", "continuation": "Explain the remaining blocker.",
           "reconciliation": {"old_owner_fenced": True, "local_processes_stopped": True,
               "external_operations_reconciled": True, "observations": "Synthetic fixture; no SDK or external work ran."},
           **changes})


async def test_adoption_keeps_attempt_result_and_only_original_worker_claims_new_generation(claim_context):
    context = claim_context
    work, old = await recoverable(context)
    accepted = await resume(context, work)
    assert accepted.status_code == 200, accepted.text
    intent = accepted.json()["native_resume"]
    assert intent["historical_identity_preanchored"] is False
    assert intent["target_generation"] == work["generation"] + 1
    async with AsyncSessionLocal() as db:
        assert await service.claim_attempt(db, "other-worker", project_id=UUID(context["project_id"])) is None
    claimed = (await api(context, "", request(context, 2))).json()["claim"]
    assert claimed["attempt"]["id"] == work["attempt_id"]
    assert claimed["generation"] == intent["target_generation"] > old["generation"]
    assert claimed["attempt"]["reported_result"] == "NOT_RUN"
    assert "native_session_anchor" not in claimed["attempt"]["checkpoint"]
    payload = {**target(context, claimed), "operation_key": intent["operation_key"],
               "snapshot_sha256": "b" * 64, "identity_source": "OPERATOR_ADOPTED"}
    async def identity(body):
        return await context["client"].post("/api/v1/cloud/worker/resume/identity",
                                             headers=context["worker_headers"], json=body)
    first = await identity(payload)
    assert first.status_code == 200, first.text
    assert first.json()["historical_identity_preanchored"] is False
    assert (await identity(payload)).json() == first.json()
    assert (await identity({**payload, "snapshot_sha256": "c" * 64})).status_code == 409
    assert (await identity({**payload, "identity": target(context, old)["identity"]})).status_code == 409


async def test_resume_requires_stop_attestation_and_cannot_manufacture_old_anchor(claim_context):
    context = claim_context
    work, _ = await recoverable(context)
    denied = await resume(context, work, identity_source="PRE_PROMPT_ANCHORED")
    assert denied.status_code == 409 and denied.json()["detail"] == "NATIVE_SESSION_ORIGINAL_ANCHOR_REQUIRED"
    for key in ("old_owner_fenced", "local_processes_stopped", "external_operations_reconciled"):
        proof = {"old_owner_fenced": True, "local_processes_stopped": True,
                 "external_operations_reconciled": True, "observations": "Synthetic observation", key: False}
        denied = await resume(context, work, reconciliation=proof)
        assert denied.status_code == 409 and denied.json()["detail"] == "NATIVE_RESUME_RECONCILIATION_REQUIRED"
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        attempt.checkpoint = {**attempt.checkpoint, "pending_operation_keys": ["original-unknown-key"]}
        await db.commit()
    denied = await resume(context, work)
    assert denied.status_code == 409 and denied.json()["detail"] == "NATIVE_SESSION_ORIGINAL_OPERATIONS_PENDING"


async def test_anchored_resume_preserves_original_anchor_and_does_not_rewrite_prompt(claim_context):
    context = claim_context
    work, _ = await recoverable(context, anchor=True)
    accepted = await resume(context, work, identity_source="PRE_PROMPT_ANCHORED")
    assert accepted.status_code == 200, accepted.text
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.checkpoint["native_session_anchor"]["generation"] == 1
        intent = attempt.checkpoint["native_resume"]
        assert intent["historical_identity_preanchored"] is True
        assert intent["continuation"] == "Explain the remaining blocker."
        assert intent["source_generation"] == 1


async def test_resume_cannot_bypass_unknown_user_input_but_accepts_original_sdk_receipt(claim_context):
    context = claim_context
    work, original = await recoverable(context, pending_message=True)
    denied = await resume(context, work)
    assert denied.status_code == 409 and denied.json()["detail"] == "NATIVE_RESUME_MESSAGE_DELIVERY_UNKNOWN"
    acknowledged = await context["client"].post("/api/v1/cloud/worker/conversation/ack",
        headers=context["worker_headers"], json={**target(context, original),
            "session_id": "cloud-" + work["attempt_id"], "message_id": original["fixture_message_id"],
            "status": "DELIVERED", "sdk_message_id": "original-sdk-receipt"})
    assert acknowledged.status_code == 200, acknowledged.text
    accepted = await resume(context, work)
    assert accepted.status_code == 200, accepted.text
