"""Explicit closure of fenced source preparation; no Git, Agent, or SUT runs."""
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_cloud_task_start import accept_sources, claim_sources
from test_cloud_tasks import post, read_all
from test_cloud_worker_claim_recovery import (
    api,
    pending_resolution,
    request,
)
from test_cloud_worker_claim_recovery import claim_context as claim_context
from test_cloud_worker_claim_recovery import cloud_context as cloud_context

from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudAttempt, CloudInputResolution, CloudWorkGrant


async def fenced(context):
    pending = await pending_resolution(context)
    claim_request = request(context)
    claimed = (await api(context, "", claim_request)).json()
    assert claimed["kind"] == "RESOLUTION"
    assert (await api(context, "/reconcile", claim_request)).json()["closed"] is True
    return pending, claimed


def closure(pending, **changes):
    return {"task_id": pending["task_id"], "resolution_id": pending["resolution_id"],
        "original_operation_key": pending["operation_key"],
        "reason": "Synthetic process exited; no accepted source result; keep Git outcome unconfirmed",
        "local_processes_stopped": True, **changes}


async def test_close_preserves_original_identity_and_allows_explicit_new_start(claim_context):
    context = claim_context
    pending, _ = await fenced(context)
    original = await read_all(context, pending["task_id"], 2)
    fields = closure(pending, operation_key="close-original")
    response = await post(context, "CLOSE_INPUT_RESOLUTION", 2, **fields)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["version"] == 3 and receipt["resolution_status"] == "FAILED"
    assert receipt["resolution_closure"]["original_status"] == "RECOVERY_REQUIRED"
    assert receipt["resolution_closure"]["git_execution_outcome"] == "UNCONFIRMED"
    assert receipt["resolution_closure"]["independent_process_stop_proof"] is False
    assert (await post(context, "CLOSE_INPUT_RESOLUTION", 2, **fields)).json() == receipt
    changed = {**fields, "reason": "different assertion"}
    assert (await post(context, "CLOSE_INPUT_RESOLUTION", 2, **changed)).status_code == 409
    assert await read_all(context, pending["task_id"], 2) == original
    closed = await read_all(context, pending["task_id"], 3)
    row = closed["resolutions"][0]
    assert row["status"] == "FAILED" and row["operation_key"] == pending["operation_key"]
    assert row["source_digest"] == original["resolutions"][0]["source_digest"]
    assert row["result"] is None and row["digest"] is None
    assert closed["task"]["status"] == "DRAFT" and closed["task"]["reported_result"] == "NOT_RUN"
    assert closed["attempts"] == []
    started = await post(context, "START_TASK", 3, task_id=pending["task_id"])
    assert started.status_code == 200, started.text
    assert started.json()["resolution_id"] != pending["resolution_id"]
    claim, result = await claim_sources(context)
    accepted = await accept_sources(claim, result)
    assert accepted["attempt_id"]
    finished = await read_all(context, pending["task_id"], accepted["version"])
    assert finished["task"]["status"] == "QUEUED" and len(finished["attempts"]) == 1


@pytest.mark.parametrize("change", ["wrong-key", "wrong-task", "stale-version", "no-stop", "status", "lease", "grant", "no-claim-close"])
async def test_closure_rejects_missing_identity_authority_or_stopping(claim_context, change):
    context = claim_context
    if change == "no-claim-close":
        pending = await pending_resolution(context)
        # A state label without original claim closure is not recovery proof.
        async with AsyncSessionLocal() as db:
            row = await db.get(CloudInputResolution, UUID(pending["resolution_id"]))
            row.status = "RECOVERY_REQUIRED"
            await db.commit()
    else:
        pending, claimed = await fenced(context)
    fields = closure(pending)
    version = 2
    if change == "wrong-key":
        fields["original_operation_key"] = "wrong-original"
    elif change == "wrong-task":
        another = await pending_resolution(context)
        fields["task_id"] = another["task_id"]
    elif change == "stale-version":
        version = 1
    elif change == "no-stop":
        fields["local_processes_stopped"] = False
    elif change in {"status", "lease", "grant"}:
        async with AsyncSessionLocal() as db:
            row = await db.get(CloudInputResolution, UUID(pending["resolution_id"]))
            if change == "status":
                row.status = "RESOLVING"
            elif change == "lease":
                row.lease_token_hash = "f" * 64
            else:
                grant = await db.scalar(select(CloudWorkGrant).where(CloudWorkGrant.resolution_id == row.id))
                # Insert a distinct unrevoked grant: revocation itself is immutable.
                db.add(CloudWorkGrant(project_id=grant.project_id, resolution_id=row.id,
                    worker_id=grant.worker_id, lease_generation=1, token_hash="a" * 64,
                    created_at=grant.created_at, expires_at=grant.expires_at))
            await db.commit()
    denied = await post(context, "CLOSE_INPUT_RESOLUTION", version, **fields)
    assert denied.status_code in {404, 409, 422}, denied.text
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudInputResolution, UUID(pending["resolution_id"]))
        assert row.status != "FAILED"
        assert await db.scalar(select(func.count()).select_from(CloudAttempt).where(
            CloudAttempt.task_id == UUID(pending["task_id"]))) == 0
