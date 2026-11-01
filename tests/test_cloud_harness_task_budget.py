"""Synthetic control-plane integration for Harness-owned execution policy.

These tests require the dedicated regression database selected by
HYPERTEST_TEST_DATABASE_URL. They do not launch a Harness or invoke a SUT.
"""
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from test_cloud_tasks import (
    FRAMEWORK_ORIGIN,
    FRAMEWORK_SHA,
    ORIGIN,
    SHA,
    configuration,
    dispatched,
    draft,
    inputs,
    post,
    read_all,
    worker_submit,
)

from hypertest.application import cloud_tasks as service
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudInputResolution, CloudTask, ProjectCloudConfigRevision

pytest_plugins = ("test_cloud_tasks",)


async def test_new_task_rejects_platform_budget(cloud_context):
    context = cloud_context
    configured = await post(context, "CONFIGURE", configuration=configuration())
    assert configured.status_code == 200, configured.text
    response = await post(context, "CREATE_TASK", title="Synthetic budget rejection",
        config_id=configured.json()["config_id"], inputs=inputs())
    assert response.status_code == 422
    assert response.json()["detail"] == "Cloud Task budget is not accepted"


async def test_no_budget_claim_runs_with_fencing_and_no_reservation(cloud_context):
    context = cloud_context
    task_inputs = inputs()
    task_inputs.pop("budgets")
    receipt = await dispatched(context, task_inputs=task_inputs)
    async with AsyncSessionLocal() as db:
        claim = await service.claim_attempt(db, "fixture-worker", project_id=UUID(context["project_id"]))
    assert claim["task"]["inputs"]["budgets"] is None
    assert claim["budget_remaining"] is None
    assert "preparation_budget_reservation" not in claim["attempt"]["runtime_metadata"]
    identity = service.WorkerIdentity("fixture-worker", claim["lease_token"], claim["generation"], claim["work_token"])
    with pytest.raises(HTTPException, match="cannot reserve one"):
        await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING",
            budget_reservation={"reserved_seconds": 60, "request_limits": [
                {"scope": "ROOT", "max_requests": 1, "cost_per_request_microunits": 1}]})
    running = await worker_submit(context, identity, receipt, "TRANSITION", status="RUNNING")
    async with AsyncSessionLocal() as db:
        task = await service._task(db, UUID(receipt["task_id"]))
        attempt = await service._attempt(db, task, UUID(receipt["attempt_id"]))
        assert attempt.status == "RUNNING" and "budget_reservation" not in attempt.runtime_metadata
        assert await service.fence_attempt_for_recovery(db, task.id, attempt.id, identity, "WORKER_LEASE_UNCONFIRMED")
    with pytest.raises(HTTPException):
        await worker_submit(context, identity, running, "SUBMIT_ASSETS", assets=[{
            "kind": "REPORT", "key": "late", "title": "Late fixture", "markdown": "Not accepted after fence"}])
    async with AsyncSessionLocal() as db:
        assert await service.claim_attempt(db, "restart-worker", project_id=UUID(context["project_id"])) is None


async def test_legacy_draft_is_versioned_and_requires_fresh_resolution(cloud_context):
    context = cloud_context
    task_inputs = inputs()
    old_budget = task_inputs.pop("budgets")
    created = await draft(context, task_inputs=task_inputs)
    # Fixture represents a pre-existing, undispatched legacy draft. Its synthetic
    # database setup is deliberately separate from the current CREATE contract.
    # A historical accepted resolution was recorded against draft version 3
    # with a digest that includes the old budget.
    old_version = 3
    old_resolution = uuid4()
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(created["task_id"]))
        config = await db.get(ProjectCloudConfigRevision, task.config_id)
        task.inputs = {**task.inputs, "budgets": old_budget}
        # The real database permits a single version increment per update.
        task.version = old_version - 1
        await db.flush()
        task.version = old_version
        await db.flush()
        old_digest = service.canonical_json_sha256(
            {"inputs": task.inputs, "config_id": str(task.config_id), "config_digest": config.digest})
        old_result = {"repositories": {
            "sut": {"url": ORIGIN, "commit_sha": SHA, "selector": task.inputs["sut_selector"]},
            "framework": {"url": FRAMEWORK_ORIGIN, "commit_sha": FRAMEWORK_SHA,
                          "selector": task.inputs["framework_selector"]}},
            "environment_observation": {"deployment": "UNKNOWN", "source": "synthetic-fixture"},
            "observed_at": datetime.now(UTC).isoformat(), "source": "synthetic-fixture-no-git-executed"}
        db.add(CloudInputResolution(id=old_resolution, project_id=task.project_id,
            task_id=task.id, operation_key="fixture-legacy-resolution", source_draft_version=old_version - 1,
            accepted_task_version=old_version, source_digest=old_digest, status="ACCEPTED",
            result=old_result, digest=service.canonical_json_sha256(old_result),
            accepted_at=datetime.now(UTC), requested_by="fixture-legacy-operator"))
        await db.commit()
    rejected = await post(context, "DISPATCH", old_version, task_id=created["task_id"], resolution_id=str(old_resolution))
    assert rejected.status_code == 409
    assert "resolving versions again" in rejected.json()["detail"]
    original_key = "fixture-migrate-draft"
    resolved = await post(context, "RESOLVE_INPUTS", old_version, operation_key=original_key, task_id=created["task_id"])
    assert resolved.status_code == 200 and resolved.json()["legacy_draft_budget_removed"] is True
    assert resolved.json()["version"] == old_version + 1
    snapshot = await read_all(context, created["task_id"], resolved.json()["version"])
    assert snapshot["task"]["inputs"]["budgets"] is None
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(created["task_id"]))
        config = await db.get(ProjectCloudConfigRevision, task.config_id)
        resolution = await db.get(CloudInputResolution, UUID(resolved.json()["resolution_id"]))
        assert resolution.source_draft_version == resolved.json()["version"]
        assert resolution.source_digest == service.canonical_json_sha256(
            {"inputs": task.inputs, "config_id": str(task.config_id), "config_digest": config.digest})
    replay = await post(context, "RESOLVE_INPUTS", old_version, operation_key=original_key, task_id=created["task_id"])
    assert replay.status_code == 200 and replay.json() == resolved.json()
    stale = await post(context, "DISPATCH", old_version, task_id=created["task_id"], resolution_id=str(old_resolution))
    assert stale.status_code == 409
    stale_resolution = await post(context, "DISPATCH", resolved.json()["version"],
        task_id=created["task_id"], resolution_id=str(old_resolution))
    assert stale_resolution.status_code == 409
    assert "accepted immutable resolution" in stale_resolution.json()["detail"]
    async with AsyncSessionLocal() as db:
        retained = await db.get(CloudInputResolution, old_resolution)
        assert retained.status == "ACCEPTED" and retained.source_digest == old_digest
        assert retained.accepted_task_version == old_version
