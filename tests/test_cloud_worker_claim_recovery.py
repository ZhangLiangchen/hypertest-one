"""Claim recovery against an explicit test DB; no runtime, model or SUT calls."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_cloud_tasks import (
    FRAMEWORK_ORIGIN,
    FRAMEWORK_SHA,
    ORIGIN,
    SHA,
    new_inputs,
    post,
    read_all,
)
from test_cloud_tasks import cloud_context as cloud_context

from hypertest.application import cloud_tasks as service
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import (
    CloudAttempt,
    CloudInputResolution,
    CloudTask,
    CloudWorkerClaimState,
    CloudWorkGrant,
)
from hypertest.domain.models import AuditEvent, OutboxEvent


@pytest.fixture
async def claim_context(cloud_context, monkeypatch, tmp_path):
    context = {**cloud_context, "worker_id": "claim-fixture-" + uuid4().hex}
    token = "claim-fixture-token-" + uuid4().hex
    key = tmp_path / "worker-token"
    key.write_text(token)
    key.chmod(0o600)
    settings = get_settings()
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_api_worker_id", context["worker_id"])
    monkeypatch.setattr(settings, "cloud_worker_api_token_file", str(key))
    context["worker_headers"] = {"Authorization": "Bearer " + token}
    # Queue selection remains real; restrict this fixture to its own Project so
    # unrelated synthetic queued work from another test cannot be acquired.
    original_resolution, original_attempt = service.claim_resolution, service.claim_attempt

    async def scoped_resolution(db, worker_id, lease_seconds=90, **kwargs):
        return await original_resolution(db, worker_id, lease_seconds,
            **{**kwargs, "project_id": UUID(context["project_id"])})

    async def scoped_attempt(db, worker_id, lease_seconds=90, **kwargs):
        return await original_attempt(db, worker_id, lease_seconds,
            **{**kwargs, "project_id": UUID(context["project_id"])})

    monkeypatch.setattr(service, "claim_resolution", scoped_resolution)
    monkeypatch.setattr(service, "claim_attempt", scoped_attempt)
    yield context
    # Retire only this fixture's still-queued synthetic work so a later test's
    # global Worker cannot acquire it. Recovery evidence stays untouched.
    async with AsyncSessionLocal() as db:
        queued_tasks = [(str(task.id), str(task.latest_attempt_id), task.version) for task in await db.scalars(
            select(CloudTask).where(CloudTask.project_id == UUID(context["project_id"]), CloudTask.status == "QUEUED"))]
    for task_id, attempt_id, version in queued_tasks:
        cancelled = await post(context, "CANCEL_ATTEMPT", version, task_id=task_id,
                               attempt_id=attempt_id, reason="Synthetic fixture cleanup")
        assert cancelled.status_code == 200, cancelled.text


def request(context, sequence=1, **changes):
    return {"worker_id": context["worker_id"], "sequence": sequence,
            "request_key": "claim-" + uuid4().hex, "lease_seconds": 90,
            "supports_attempt_manifest": True, **changes}


async def api(context, operation, body=None):
    return await context["client"].post("/api/v1/cloud/worker/claim" + operation,
        headers=context["worker_headers"], json=body or {"worker_id": context["worker_id"]})


async def pending_resolution(context):
    created = await post(context, "CREATE_TASK", title="Synthetic claim recovery",
        expected_project_version=1, inputs=new_inputs(expected_outputs=["REPORT"]))
    assert created.status_code == 200, created.text
    resolved = await post(context, "RESOLVE_INPUTS", 1, task_id=created.json()["task_id"])
    assert resolved.status_code == 200, resolved.text
    return resolved.json()


async def queued(context, pending=None):
    pending = pending or await pending_resolution(context)
    async with AsyncSessionLocal() as db:
        claimed = await service.claim_resolution(db, "synthetic-source-resolver", project_id=UUID(context["project_id"]))
        assert claimed["resolution"]["id"] == pending["resolution_id"]
        result = {"repositories": {
            "sut": {"url": ORIGIN, "commit_sha": SHA, "selector": claimed["task"]["inputs"]["sut_selector"]},
            "framework": {"url": FRAMEWORK_ORIGIN, "commit_sha": FRAMEWORK_SHA,
                          "selector": claimed["task"]["inputs"]["framework_selector"]}},
            "environment_observation": {"state": "UNOBSERVED"},
            "observed_at": datetime.now(UTC).isoformat(), "source": "synthetic-claim-protocol-no-git"}
        accepted = await service.accept_resolution(db, UUID(pending["resolution_id"]), "synthetic-source-resolver",
            claimed["lease_token"], result, work_token=claimed["work_token"])
    sent = await post(context, "DISPATCH", accepted["version"], task_id=pending["task_id"],
                      resolution_id=pending["resolution_id"])
    assert sent.status_code == 200, sent.text
    return sent.json()


def target(context, claimed):
    return {"project_id": context["project_id"], "task_id": claimed["task"]["id"],
        "attempt_id": claimed["attempt"]["id"], "identity": {
            "worker_id": context["worker_id"], "lease_token": claimed["lease_token"],
            "work_token": claimed["work_token"], "generation": claimed["generation"]}}


async def assert_no_capabilities(context, body, claimed=None):
    assert "claim" not in body
    assert "lease_token" not in json.dumps(body) and "work_token" not in json.dumps(body)
    async with AsyncSessionLocal() as db:
        row = await db.scalar(text("SELECT row_to_json(s)::text FROM cloud_worker_claim_states s WHERE worker_id=:worker"),
                              {"worker": context["worker_id"]})
        audit = list(await db.scalars(select(AuditEvent.event_metadata).where(
            AuditEvent.project_id == UUID(context["project_id"]))))
        events = list(await db.scalars(select(OutboxEvent.payload).where(
            OutboxEvent.aggregate_id.in_(select(CloudTask.id).where(CloudTask.project_id == UUID(context["project_id"]))))))
    if claimed:
        for secret in (claimed["lease_token"], claimed["work_token"]):
            assert secret not in json.dumps(body)
            assert secret not in row
            assert secret not in json.dumps(audit + events)


async def test_claim_empty_state_is_read_only_and_duplicate_never_claims_new_work(claim_context):
    context = claim_context
    initial = await api(context, "/state")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {"worker_id": context["worker_id"], "sequence": 0, "request_key": None,
                              "kind": "EMPTY", "closed": True}
    async with AsyncSessionLocal() as db:
        assert await db.get(CloudWorkerClaimState, context["worker_id"]) is None
    body = request(context)
    empty = await api(context, "", body)
    assert empty.status_code == 200 and empty.json()["kind"] == "EMPTY" and empty.json()["closed"] is True
    work = await queued(context)
    duplicate = await api(context, "", body)
    assert duplicate.status_code == 409
    state = await api(context, "/state")
    assert state.json()["sequence"] == 1 and state.json()["kind"] == "EMPTY"
    await assert_no_capabilities(context, state.json())
    async with AsyncSessionLocal() as db:
        assert (await db.get(CloudAttempt, UUID(work["attempt_id"]))).status == "QUEUED"
    next_body = request(context, 2)
    claimed = await api(context, "", next_body)
    assert claimed.status_code == 200 and claimed.json()["claim"]["attempt"]["id"] == work["attempt_id"]
    assert (await api(context, "/reconcile", next_body)).json()["closed"] is True


async def test_lost_attempt_response_fences_original_once_and_allows_next_claim(claim_context):
    context = claim_context
    first, second = await queued(context), await queued(context)
    body = request(context)
    response = await api(context, "", body)
    assert response.status_code == 200, response.text
    claimed = response.json()["claim"]
    assert claimed["attempt"]["id"] == first["attempt_id"]
    assert (await api(context, "", request(context, 2))).status_code == 409
    assert (await api(context, "", body)).status_code == 409
    reconciled = await api(context, "/reconcile", body)
    assert reconciled.status_code == 200 and reconciled.json()["closed"] is True
    await assert_no_capabilities(context, reconciled.json(), claimed)
    current = await context["client"].post("/api/v1/cloud/worker/assert", headers=context["worker_headers"], json=target(context, claimed))
    assert current.status_code == 409
    async with AsyncSessionLocal() as db:
        old = await db.get(CloudAttempt, UUID(first["attempt_id"]))
        task = await db.get(CloudTask, UUID(first["task_id"]))
        assert old.status == task.status == "RECOVERY_REQUIRED" and old.reported_result == "NOT_RUN"
        assert old.checkpoint.get("external_operations_reconciled") is not True
        version = task.version
        grants = list(await db.scalars(select(CloudWorkGrant).where(CloudWorkGrant.attempt_id == old.id)))
        assert grants and all(grant.revoked_at is not None for grant in grants)
        assert (await db.get(CloudAttempt, UUID(second["attempt_id"]))).status == "QUEUED"
    assert (await api(context, "/reconcile", body)).json() == reconciled.json()
    async with AsyncSessionLocal() as db:
        assert (await db.get(CloudTask, UUID(first["task_id"]))).version == version
    next_body = request(context, 2)
    next_response = await api(context, "", next_body)
    assert next_response.status_code == 200 and next_response.json()["claim"]["attempt"]["id"] == second["attempt_id"]
    assert (await api(context, "/reconcile", next_body)).json()["closed"] is True
    assert (await api(context, "", body)).status_code == 409
    old_read = await api(context, "/reconcile", body)
    assert old_read.status_code == 200 and old_read.json()["kind"] == "RETIRED" and old_read.json()["current_sequence"] == 2


async def test_absent_claim_is_sealed_before_late_request_can_execute(claim_context):
    context = claim_context
    work = await queued(context)
    original = request(context)
    sealed = await api(context, "/reconcile", original)
    assert sealed.status_code == 200 and sealed.json()["kind"] == "ABANDONED" and sealed.json()["closed"] is True
    assert (await api(context, "", original)).status_code == 409
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "QUEUED" and attempt.lease_generation == 0
    next_body = request(context, 2)
    assert (await api(context, "", next_body)).json()["claim"]["attempt"]["id"] == work["attempt_id"]
    assert (await api(context, "/reconcile", next_body)).json()["closed"] is True


async def test_concurrent_claim_and_reconcile_never_leave_live_authority(claim_context):
    context = claim_context
    work = await queued(context)
    original = request(context)
    claimed, reconciled = await asyncio.gather(api(context, "", original), api(context, "/reconcile", original))
    assert reconciled.status_code == 200 and reconciled.json()["closed"] is True
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert await db.scalar(select(func.count()).select_from(CloudWorkGrant).where(
            CloudWorkGrant.worker_id == context["worker_id"], CloudWorkGrant.revoked_at.is_(None))) == 0
        if claimed.status_code == 200:
            assert reconciled.json()["kind"] == "ATTEMPT" and attempt.status == "RECOVERY_REQUIRED"
        else:
            assert claimed.status_code == 409
            assert reconciled.json()["kind"] == "ABANDONED" and attempt.status == "QUEUED"
    assert (await api(context, "", original)).status_code == 409
    await assert_no_capabilities(context, reconciled.json(), claimed.json().get("claim"))


async def test_claim_identity_parameters_and_sequence_cannot_be_reused(claim_context):
    context = claim_context
    original = request(context)
    for operation in ("", "/reconcile", "/state"):
        body = original if operation != "/state" else {"worker_id": context["worker_id"]}
        assert (await context["client"].post("/api/v1/cloud/worker/claim" + operation, json=body)).status_code == 401
        assert (await api(context, operation, {**body, "worker_id": "different-worker"})).status_code == 403
    for field in ("sequence", "request_key"):
        assert (await api(context, "", {key: value for key, value in original.items() if key != field})).status_code == 422
    assert (await api(context, "", request(context, 2))).status_code == 409
    assert (await api(context, "", original)).status_code == 200
    for changes in ({"request_key": "different-key-" + uuid4().hex}, {"lease_seconds": 91}, {"supports_attempt_manifest": False}):
        for operation in ("", "/reconcile"):
            rejected = await api(context, operation, {**original, **changes})
            assert rejected.status_code == 409 and rejected.json()["detail"] == "CLAIM_REQUEST_CONFLICT"
    state = await api(context, "/state")
    assert state.json()["request_key"] == original["request_key"] and state.json()["sequence"] == 1


@pytest.mark.parametrize("same_key", [False, True])
async def test_concurrent_claims_allocate_at_most_one_task_for_one_sequence(claim_context, same_key):
    context = claim_context
    first, second = await queued(context), await queued(context)
    body = request(context)
    other = body if same_key else request(context)
    responses = await asyncio.gather(api(context, "", body), api(context, "", other))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner_index = next(index for index, response in enumerate(responses) if response.status_code == 200)
    winner_body = (body, other)[winner_index]
    claimed = responses[winner_index].json()["claim"]
    assert claimed["attempt"]["id"] == first["attempt_id"]
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudWorkGrant).where(
            CloudWorkGrant.worker_id == context["worker_id"])) == 1
        assert (await db.get(CloudAttempt, UUID(second["attempt_id"]))).status == "QUEUED"
    assert (await api(context, "/reconcile", winner_body)).json()["closed"] is True
    # No second capability or queue advancement came from the losing request.
    await assert_no_capabilities(context, (await api(context, "/state")).json(), claimed)


async def test_claim_and_attempt_lease_roll_back_as_one_transaction(claim_context, monkeypatch):
    context = claim_context
    work = await queued(context)
    original_claim = service.claim_attempt

    async def fail_after_acquisition(*args, **kwargs):
        claimed = await original_claim(*args, **kwargs)
        assert claimed is not None
        raise RuntimeError("synthetic failure before claim receipt commit")

    monkeypatch.setattr(service, "claim_attempt", fail_after_acquisition)
    body = request(context)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await api(context, "", body)
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(work["attempt_id"]))
        assert attempt.status == "QUEUED" and attempt.lease_generation == 0 and attempt.lease_owner is None
        assert await db.scalar(select(func.count()).select_from(CloudWorkGrant).where(
            CloudWorkGrant.worker_id == context["worker_id"])) == 0
        row = await db.get(CloudWorkerClaimState, context["worker_id"])
        assert row is None or row.sequence == 0
    monkeypatch.setattr(service, "claim_attempt", original_claim)
    response = await api(context, "", body)
    assert response.status_code == 200 and response.json()["claim"]["attempt"]["id"] == work["attempt_id"]
    assert (await api(context, "/reconcile", body)).json()["closed"] is True


async def test_database_preserves_claim_highwater_and_original_request(claim_context):
    context = claim_context
    await queued(context)
    original = request(context)
    assert (await api(context, "", original)).status_code == 200

    async def rejects(statement):
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(statement), {"worker": context["worker_id"]})
                await db.commit()
            await db.rollback()

    await rejects("UPDATE cloud_worker_claim_states SET sequence=2 WHERE worker_id=:worker")
    assert (await api(context, "/reconcile", original)).json()["closed"] is True
    for statement in (
        "DELETE FROM cloud_worker_claim_states WHERE worker_id=:worker",
        "UPDATE cloud_worker_claim_states SET sequence=3 WHERE worker_id=:worker",
        "UPDATE cloud_worker_claim_states SET request_key='rewritten-original-key' WHERE worker_id=:worker",
        "UPDATE cloud_worker_claim_states SET request_digest=repeat('0',64) WHERE worker_id=:worker",
        "UPDATE cloud_worker_claim_states SET closed=false WHERE worker_id=:worker",
    ):
        await rejects(statement)
    state = await api(context, "/state")
    assert state.json() == {"worker_id": context["worker_id"], "sequence": 1,
        "request_key": original["request_key"], "kind": "ATTEMPT", "closed": True}


async def test_resolution_claim_recovery_revokes_capability_without_accepting_input(claim_context):
    context = claim_context
    pending = await pending_resolution(context)
    body = request(context)
    response = await api(context, "", body)
    assert response.status_code == 200 and response.json()["kind"] == "RESOLUTION"
    claimed = response.json()["claim"]
    reconciled = await api(context, "/reconcile", body)
    assert reconciled.status_code == 200 and reconciled.json()["closed"] is True
    await assert_no_capabilities(context, reconciled.json(), claimed)
    original_target = {"project_id": context["project_id"], "task_id": pending["task_id"],
        "resolution_id": pending["resolution_id"], "identity": {"worker_id": context["worker_id"],
            "lease_token": claimed["lease_token"], "work_token": claimed["work_token"], "generation": claimed["generation"]}}
    denied = await context["client"].post("/api/v1/cloud/worker/resolution/assert",
        headers=context["worker_headers"], json=original_target)
    assert denied.status_code == 409
    async with AsyncSessionLocal() as db:
        resolution = await db.get(CloudInputResolution, UUID(pending["resolution_id"]))
        assert resolution.status == "RECOVERY_REQUIRED" and resolution.result is None and resolution.digest is None
        assert (await db.get(CloudTask, UUID(pending["task_id"]))).status == "DRAFT"
        grants = list(await db.scalars(select(CloudWorkGrant).where(CloudWorkGrant.resolution_id == resolution.id)))
        assert grants and all(grant.revoked_at is not None for grant in grants)


async def test_fenced_resolution_recovery_allows_removal_after_new_resolution_and_attempt(claim_context):
    context = claim_context
    pending = await pending_resolution(context)
    task_id = pending["task_id"]
    original_snapshot = await read_all(context, task_id, pending["version"])
    original_claim = request(context)
    assert (await api(context, "", original_claim)).json()["kind"] == "RESOLUTION"
    assert (await api(context, "/reconcile", original_claim)).json()["closed"] is True

    # Explicitly resolve again, then finish a new synthetic queued Attempt.
    # No Git, SDK, or SUT is run, and the first resolution is never replayed.
    new_resolution = await post(context, "RESOLVE_INPUTS", pending["version"], task_id=task_id)
    assert new_resolution.status_code == 200, new_resolution.text
    work = await queued(context, new_resolution.json())
    cancelled = await post(context, "CANCEL_ATTEMPT", work["version"], task_id=task_id,
        attempt_id=work["attempt_id"], reason="Synthetic fixture; no execution")
    assert cancelled.status_code == 200, cancelled.text
    version = cancelled.json()["version"]
    terminal_snapshot = await read_all(context, task_id, version)
    summary = await context["client"].get(f"/api/v1/cloud/tasks/{task_id}/summary",
        headers=context["headers"], params={"project_id": context["project_id"]})
    assert summary.status_code == 200, summary.text
    assert summary.json()["management"]["can_delete"] is True
    assert summary.json()["management"]["delete_blocking_reasons"] == []

    deleted = await post(context, "DELETE_TASK", version, task_id=task_id)
    assert deleted.status_code == 200, deleted.text
    assert await read_all(context, task_id, pending["version"]) == original_snapshot
    assert await read_all(context, task_id, version) == terminal_snapshot
    async with AsyncSessionLocal() as db:
        old = await db.get(CloudInputResolution, UUID(pending["resolution_id"]))
        assert old.status == "RECOVERY_REQUIRED" and old.result is None and old.digest is None
        assert old.accepted_at is None and old.accepted_task_version is None
        assert old.lease_token_hash is None and old.lease_expires_at is None
        grants = list(await db.scalars(select(CloudWorkGrant).where(CloudWorkGrant.resolution_id == old.id)))
        assert grants and all(grant.revoked_at is not None for grant in grants)
    directory = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/tasks",
        headers=context["headers"])
    assert task_id not in [item["task_id"] for item in directory.json()["items"]]


@pytest.mark.parametrize("blocking_state", ["PENDING", "RESOLVING", "LEASE_HASH", "LEASE_EXPIRY", "EXPIRED_GRANT"])
async def test_resolution_removal_requires_complete_fencing(claim_context, blocking_state):
    context = claim_context
    pending = await pending_resolution(context)
    task_id = pending["task_id"]
    original_claim = request(context)
    if blocking_state != "PENDING":
        assert (await api(context, "", original_claim)).json()["kind"] == "RESOLUTION"
    if blocking_state not in {"PENDING", "RESOLVING"}:
        # Represent legacy partial fencing only in the dedicated fixture DB.
        async with AsyncSessionLocal() as db:
            resolution = await db.get(CloudInputResolution, UUID(pending["resolution_id"]))
            resolution.status = "RECOVERY_REQUIRED"
            if blocking_state != "LEASE_HASH":
                resolution.lease_token_hash = None
            resolution.lease_expires_at = (datetime.now(UTC) - timedelta(seconds=1)
                if blocking_state == "LEASE_EXPIRY" else None)
            grants = list(await db.scalars(select(CloudWorkGrant).where(CloudWorkGrant.resolution_id == resolution.id)))
            assert grants
            for grant in grants:
                if blocking_state == "EXPIRED_GRANT":
                    grant.expires_at = grant.created_at + timedelta(microseconds=1)
                else:
                    grant.revoked_at = datetime.now(UTC)
            await db.commit()
    summary = await context["client"].get(f"/api/v1/cloud/tasks/{task_id}/summary",
        headers=context["headers"], params={"project_id": context["project_id"]})
    assert summary.status_code == 200, summary.text
    assert summary.json()["management"]["can_delete"] is False
    assert summary.json()["management"]["delete_blocking_reasons"] == ["UNRESOLVED_INPUT_RESOLUTION"]
    denied = await post(context, "DELETE_TASK", pending["version"], task_id=task_id)
    assert denied.status_code == 409 and denied.json()["detail"] == "Unresolved input resolution prevents deletion"
    # Leave no synthetic pending resolver for another test to acquire.
    if blocking_state == "PENDING":
        assert (await post(context, "CANCEL_TASK", pending["version"], task_id=task_id,
            reason="Synthetic fixture cleanup")).status_code == 200
    else:
        assert (await api(context, "/reconcile", original_claim)).json()["closed"] is True


async def test_terminal_attempt_reconciliation_preserves_accepted_result_and_history(claim_context):
    context = claim_context
    await queued(context)
    body = request(context)
    claimed = (await api(context, "", body)).json()["claim"]
    common = target(context, claimed)
    version = claimed["task"]["version"]

    async def submit(operation, **fields):
        nonlocal version
        response = await context["client"].post("/api/v1/cloud/worker/submit", headers=context["worker_headers"],
            json={**common, "payload": {"project_id": common["project_id"], "task_id": common["task_id"],
                "attempt_id": common["attempt_id"], "operation": operation, "operation_key": "claim-fixture-" + uuid4().hex,
                "expected_version": version, **fields}})
        assert response.status_code == 200, response.text
        version = response.json()["version"]
        return response.json()

    await submit("TRANSITION", status="RUNNING", reason="Synthetic protocol test only")
    assets = await submit("SUBMIT_ASSETS", assets=[{"kind": "REPORT", "key": "report", "title": "Synthetic report",
                         "markdown": "No SDK or SUT invoked", "reported_result": "NOT_RUN"}])
    report_id = assets["assets"][0]["id"]
    await submit("COMPLETE_NATIVE_ATTEMPT", final_report_revision=report_id, reported_result="NOT_RUN",
        usage_seconds=0, cost_microunits=0,
        runtime_observation="DIRECT_SDK_PROCESS_EXITED", completion_manifest={"required_asset_ids": [report_id],
            "scope_and_gaps": "Synthetic protocol test", "no_tests_reason": "No model or SUT",
            "all_local_processes_stopped": False, "external_operations_reconciled": False, "pending_operation_keys": []})
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(common["task_id"]))
        attempt = await db.get(CloudAttempt, UUID(common["attempt_id"]))
        before = (task.status, task.reported_result, task.version, attempt.status, attempt.reported_result, json.dumps(attempt.checkpoint, sort_keys=True))
    reconciled = await api(context, "/reconcile", body)
    assert reconciled.status_code == 200 and reconciled.json()["closed"] is True
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(common["task_id"]))
        attempt = await db.get(CloudAttempt, UUID(common["attempt_id"]))
        after = (task.status, task.reported_result, task.version, attempt.status, attempt.reported_result, json.dumps(attempt.checkpoint, sort_keys=True))
    assert before == after and task.status == "COMPLETED"
    await assert_no_capabilities(context, reconciled.json(), claimed)
