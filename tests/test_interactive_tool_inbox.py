"""The inbox is durable transport under one existing Worker, never a second task queue."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from test_connector_constraints import paired_device  # noqa: F401
from test_interactive_constraints import interactive_owner as _interactive_owner
from test_interactive_constraints import interactive_source as _interactive_source

from hypertest.application.services import canonical_json_sha256
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.connector import HarnessDeviceGrant
from hypertest.domain.harness import RunToolCall
from hypertest.domain.interactive import (
    InteractiveExecutionGrant,
    InteractiveToolRequest,
    interactive_claim_identity,
)

interactive_source = _interactive_source
interactive_owner = _interactive_owner


async def short_grant(db, owner, *, device_id=None):
    short = InteractiveExecutionGrant(interactive_binding_id=owner["attachment_id"],
        integration_grant_id=owner["grant_id"], job_id=owner["job_id"],
        device_grant_id=device_id or owner["device_grant_id"],
        token_hash=uuid4().hex + uuid4().hex, binding_epoch=1,
        claim_identity=interactive_claim_identity(owner["attachment_id"], owner["claim"]),
        call_id=uuid4().hex, host_attachment_id=owner["host_attachment_id"],
        not_before=await db.scalar(select(func.clock_timestamp())),
        host_proof_sha256="b" * 64, expires_at=datetime.now(UTC) + timedelta(seconds=15))
    db.add(short)
    await db.flush()
    return short


def request(owner, short_id, *, key="one-operation", tool="request_execution", args=None):
    arguments = args if args is not None else {"idempotency_key": key}
    return InteractiveToolRequest(interactive_binding_id=owner["attachment_id"],
        execution_grant_id=short_id, integration_grant_id=owner["grant_id"],
        actor_identity_id=owner["actor_id"], client_instance_id=owner["client_id"],
        job_id=owner["job_id"], binding_epoch=1,
        claim_identity=interactive_claim_identity(owner["attachment_id"], owner["claim"]),
        tool_call_id=uuid4().hex, idempotency_key=key, tool_name=tool,
        input_digest=canonical_json_sha256({"tool": tool, "arguments": arguments}), arguments=arguments)


async def test_inbox_strict_tools_and_original_identity_are_database_enforced(interactive_owner):
    owner = interactive_owner
    async with AsyncSessionLocal() as db:
        short = await short_grant(db, owner)
        await db.commit()
        short_id = short.id
        for tool, args in [("shell", {"command": "unauthorized"}), ("get_state", {"command": "unauthorized"})]:
            db.add(request(owner, short_id, key=uuid4().hex, tool=tool, args=args))
            with pytest.raises(DBAPIError, match="strict supported business schema"):
                await db.commit()
            await db.rollback()
        item = request(owner, short_id)
        db.add(item)
        await db.commit()
        item_id = item.id
        item.binding_epoch = 2
        with pytest.raises(DBAPIError, match="authorization are immutable"):
            await db.commit()
        await db.rollback()
        item = await db.get(InteractiveToolRequest, item_id)
        await db.delete(item)
        with pytest.raises(DBAPIError, match="history cannot be deleted"):
            await db.commit()
        await db.rollback()


async def test_claimed_unknown_inbox_cannot_requeue_or_repeat_a_write(interactive_owner):
    owner = interactive_owner
    async with AsyncSessionLocal() as db:
        short = await short_grant(db, owner)
        short_id = short.id
        item = request(owner, short_id)
        db.add(item)
        await db.commit()
        item_id = item.id
        item.status, item.claimed_at = "RUNNING", datetime.now(UTC)
        await db.commit()
        item.status, item.finished_at = "UNKNOWN", datetime.now(UTC)
        await db.commit()
        item.status = "QUEUED"
        with pytest.raises(DBAPIError, match="only exact recorded-operation reconciliation"):
            await db.commit()
        await db.rollback()
        db.add(request(owner, short_id))
        with pytest.raises(DBAPIError, match="uq_interactive_tool_key"):
            await db.commit()
        await db.rollback()
        item = await db.get(InteractiveToolRequest, item_id)
        assert item.status == "UNKNOWN" and item.result is None
        assert item.claimed_at is not None and item.finished_at is not None


async def test_unknown_inbox_reconciles_only_the_same_recorded_tool_result(interactive_owner):
    """Only ledger correlation is exercised; no Canonical fact or Runner is fabricated."""
    owner = interactive_owner
    async with AsyncSessionLocal() as db:
        short = await short_grant(db, owner)
        item = request(owner, short.id, tool="request_mission", args={
            "idempotency_key": "one-operation", "mission_type": "ANALYZE_REQUIREMENTS"})
        db.add(item)
        await db.commit()
        item.status, item.claimed_at = "RUNNING", datetime.now(UTC)
        await db.commit()
        item.status, item.finished_at = "UNKNOWN", datetime.now(UTC)
        await db.commit()
        call = RunToolCall(binding_id=owner["binding_id"], durable_job_id=owner["job_id"],
            binding_epoch=1, tool_name=item.tool_name, idempotency_key=item.idempotency_key,
            input_sha256=item.input_digest, status="STARTED")
        db.add(call)
        await db.flush()
        call.status, call.result, call.finished_at = "SUCCEEDED", {"status": "SCOPE_FIXTURE"}, datetime.now(UTC)
        await db.commit()
        item.status, item.result = "SUCCEEDED", dict(call.result)
        await db.commit()
        assert item.status == "SUCCEEDED"
        item.status = "RUNNING"
        with pytest.raises(DBAPIError, match="terminal interactive tool cannot replay"):
            await db.commit()
        await db.rollback()


async def test_device_rotation_does_not_reauthorize_an_old_short_grant(interactive_owner):
    owner = interactive_owner
    async with AsyncSessionLocal() as db:
        short = await short_grant(db, owner)
        await db.commit()
        short_id = short.id
        old = await db.get(HarnessDeviceGrant, owner["device_grant_id"])
        node_id = old.node_id
        old.status, old.revoked_at, old.row_version = "REVOKED", datetime.now(UTC), old.row_version + 1
        fresh = HarnessDeviceGrant(node_id=node_id, token_hash=uuid4().hex + uuid4().hex,
            key_version=uuid4().hex, operator_identity_id="test-operator",
            not_before=await db.scalar(select(func.clock_timestamp())),
            expires_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(fresh)
        await db.commit()
        fresh_id = fresh.id
        db.add(request(owner, short_id))
        with pytest.raises(DBAPIError, match="original current Worker claim and registered execution scope"):
            await db.commit()
        await db.rollback()
        with pytest.raises(DBAPIError, match="exact current device grant"):
            await short_grant(db, owner)
        await db.rollback()
        replacement = await short_grant(db, owner, device_id=fresh_id)
        db.add(request(owner, replacement.id))
        await db.commit()


async def test_worker_lease_loss_can_record_unknown_but_cannot_publish_an_outcome(interactive_owner):
    from hypertest.domain.jobs import DurableJob

    owner = interactive_owner
    async with AsyncSessionLocal() as db:
        short = await short_grant(db, owner)
        item = request(owner, short.id)
        db.add(item)
        await db.commit()
        item.status, item.claimed_at = "RUNNING", datetime.now(UTC)
        await db.commit()
        item_id = item.id
        job = await db.get(DurableJob, owner["job_id"])
        job.lease_expires_at = await db.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        await db.commit()
        item.status, item.result, item.finished_at = "SUCCEEDED", {"result": "unauthorized"}, datetime.now(UTC)
        with pytest.raises(DBAPIError, match="stale interactive Worker cannot publish"):
            await db.commit()
        await db.rollback()
        item = await db.get(InteractiveToolRequest, item_id)
        item.status, item.finished_at = "UNKNOWN", datetime.now(UTC)
        await db.commit()
        assert item.status == "UNKNOWN" and item.result is None


async def test_terminal_job_cleanup_rejects_unsent_and_preserves_consumed_uncertainty(interactive_owner, monkeypatch):
    from unittest.mock import AsyncMock

    from hypertest.application.jobs import cleanup_job_resources
    from hypertest.domain.jobs import DurableJob, JobStatus

    owner = interactive_owner
    monkeypatch.setattr("hypertest.runner.backends.cleanup_docker_job_resources", AsyncMock(return_value={}))
    forbidden_bridge = AsyncMock(side_effect=AssertionError("no managed Bridge for current Agent"))
    monkeypatch.setattr("hypertest.application.persistent.cleanup_bound_call", forbidden_bridge)
    async with AsyncSessionLocal() as db:
        short = await short_grant(db, owner)
        queued = request(owner, short.id, key="unsent")
        consumed = request(owner, short.id, key="consumed")
        db.add_all([queued, consumed])
        await db.commit()
        queued_id, consumed_id = queued.id, consumed.id
        consumed.status, consumed.claimed_at = "RUNNING", datetime.now(UTC)
        await db.commit()
        job = await db.get(DurableJob, owner["job_id"])
        job.status, job.finished_at, job.lease_expires_at = JobStatus.FAILED, datetime.now(UTC), None
        await db.commit()
        outcome = await cleanup_job_resources(db, job, on_worker=True)
        assert outcome["queued_tools_rejected"] == 1 and outcome["running_tools_unknown"] == 1
        await db.refresh(queued)
        await db.refresh(consumed)
        assert queued.id == queued_id and queued.status == "REJECTED"
        assert consumed.id == consumed_id and consumed.status == "UNKNOWN"
        assert consumed.claimed_at is not None and consumed.result is None
        assert queued.error_code == consumed.error_code == "WORKER_JOB_TERMINATED"
    forbidden_bridge.assert_not_called()
