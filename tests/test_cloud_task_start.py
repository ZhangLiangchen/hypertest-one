"""One durable start intention; synthetic protocol work in a dedicated test DB."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_cloud_tasks import (
    FRAMEWORK_ORIGIN,
    FRAMEWORK_SHA,
    ORIGIN,
    SHA,
    draft,
    inputs,
    legacy_draft,
    new_inputs,
    post,
    read_all,
)
from test_cloud_tasks import cloud_context as _cloud_context

from hypertest.application import cloud_tasks as service
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import (
    CloudAttempt,
    CloudInputResolution,
    CloudOperationReceipt,
    CloudTask,
)
from hypertest.domain.interactive import InteractiveIntegrationGrant
from hypertest.domain.models import Project

cloud_context = _cloud_context


async def claim_sources(context):
    async with AsyncSessionLocal() as db:
        claim = await service.claim_resolution(db, "fixture-worker", project_id=UUID(context["project_id"]))
    assert claim is not None
    result = {"repositories": {
        "sut": {"url": ORIGIN, "commit_sha": SHA, "selector": claim["task"]["inputs"]["sut_selector"]},
        "framework": {"url": FRAMEWORK_ORIGIN, "commit_sha": FRAMEWORK_SHA,
                      "selector": claim["task"]["inputs"]["framework_selector"]}},
        "environment_observation": {"deployment": "UNKNOWN", "source": "synthetic-fixture"},
        "observed_at": datetime.now(UTC).isoformat(), "source": "synthetic-fixture-no-git-executed"}
    return claim, result


async def accept_sources(claim, result):
    async with AsyncSessionLocal() as db:
        return await service.accept_resolution(db, UUID(claim["resolution"]["id"]), "fixture-worker",
            claim["lease_token"], result, work_token=claim["work_token"])


async def test_start_persists_intent_and_acceptance_queues_exactly_one_attempt(cloud_context):
    context = cloud_context
    created = await draft(context)
    task_id = created["task_id"]
    key = "start-original"
    started = await post(context, "START_TASK", 1, operation_key=key, task_id=task_id)
    assert started.status_code == 200, started.text
    receipt = started.json()
    assert receipt["version"] == 2 and receipt["start_requested"] is True
    assert receipt["resolution_status"] == "PENDING" and "attempt_id" not in receipt
    fixed = await read_all(context, task_id, 2)
    assert fixed["task"]["status"] == "DRAFT" and fixed["attempts"] == []
    assert fixed["resolutions"][0]["source_draft_version"] == 2
    assert (await post(context, "START_TASK", 1, operation_key=key, task_id=task_id)).json() == receipt
    assert (await post(context, "START_TASK", 2, operation_key=key, task_id=task_id)).status_code == 409
    async with AsyncSessionLocal() as db:
        summary = await service.task_summary(db, UUID(task_id))
        assert summary["resolutions"][0]["start_requested"] is True
    # Worker acceptance alone completes the durable intent; no second client POST.
    claim, result = await claim_sources(context)
    accepted = await accept_sources(claim, result)
    assert accepted["version"] == 3 and accepted["attempt_id"]
    assert await accept_sources(claim, result) == accepted
    async with AsyncSessionLocal() as db:
        accepted_receipt = await db.scalar(select(CloudOperationReceipt).where(
            CloudOperationReceipt.task_id == UUID(task_id), CloudOperationReceipt.operation == "ACCEPT_RESOLUTION"))
        assert str(accepted_receipt.attempt_id) == accepted["attempt_id"]
    finished = await read_all(context, task_id, 3)
    assert finished["task"]["status"] == "QUEUED"
    assert finished["task"]["reported_result"] == "NOT_RUN"
    assert finished["task"]["frozen_manifest"]["resolution"]["repositories"]["sut"]["commit_sha"] == SHA
    assert len(finished["attempts"]) == 1
    assert finished["attempts"][0]["authorization_grant_id"] == context["grant"]["grant_id"]
    assert (await post(context, "START_TASK", 1, operation_key=key, task_id=task_id)).json() == receipt
    assert (await post(context, "START_TASK", 3, task_id=task_id)).status_code == 409


async def test_start_reuses_current_manual_resolution(cloud_context):
    context = cloud_context
    created = await draft(context)
    requested = await post(context, "RESOLVE_INPUTS", 1, task_id=created["task_id"])
    assert requested.status_code == 200
    claim, result = await claim_sources(context)
    accepted = await accept_sources(claim, result)
    assert "attempt_id" not in accepted
    started = await post(context, "START_TASK", accepted["version"], task_id=created["task_id"])
    assert started.status_code == 200, started.text
    assert started.json()["attempt_id"]
    final = await read_all(context, created["task_id"], started.json()["version"])
    assert final["task"]["status"] == "QUEUED"
    assert len(final["resolutions"]) == 1 and len(final["attempts"]) == 1


@pytest.mark.parametrize("status", ["PENDING", "RESOLVING", "RECOVERY_REQUIRED"])
async def test_start_cannot_bypass_original_unresolved_preparation(cloud_context, status):
    context = cloud_context
    created = await draft(context)
    requested = await post(context, "RESOLVE_INPUTS", 1, task_id=created["task_id"])
    async with AsyncSessionLocal() as db:
        resolution = await db.get(CloudInputResolution, UUID(requested.json()["resolution_id"]))
        resolution.status = status
        await db.commit()
    denied = await post(context, "START_TASK", 2, task_id=created["task_id"])
    assert denied.status_code == 409, denied.text
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudInputResolution).where(
            CloudInputResolution.task_id == UUID(created["task_id"]))) == 1
        assert await db.scalar(select(func.count()).select_from(CloudAttempt).where(
            CloudAttempt.task_id == UUID(created["task_id"]))) == 0


async def test_failed_preparation_needs_a_new_explicit_start(cloud_context):
    context = cloud_context
    created = await draft(context)
    first = (await post(context, "START_TASK", 1, task_id=created["task_id"])).json()
    async with AsyncSessionLocal() as db:
        resolution = await db.get(CloudInputResolution, UUID(first["resolution_id"]))
        resolution.status = "FAILED"
        await db.commit()
    second = await post(context, "START_TASK", 2, task_id=created["task_id"])
    assert second.status_code == 200, second.text
    assert second.json()["resolution_id"] != first["resolution_id"]
    fixed = await read_all(context, created["task_id"], 3)
    assert [row["status"] for row in fixed["resolutions"]] == ["FAILED", "PENDING"]
    assert fixed["attempts"] == []


@pytest.mark.parametrize("change", ["cancel", "edit", "revoke", "disabled", "expired"])
async def test_late_resolution_cannot_start_after_intent_or_authority_changes(cloud_context, monkeypatch, change):
    context = cloud_context
    if change == "expired":
        data = inputs(budgets=None)
        data["authorization"]["expires_at"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
        created = await legacy_draft(context, task_inputs=data)
    else:
        created = await draft(context)
    requested = await post(context, "START_TASK", 1, task_id=created["task_id"])
    assert requested.status_code == 200, requested.text
    claim, result = await claim_sources(context)
    if change == "cancel":
        assert (await post(context, "CANCEL_TASK", 2, task_id=created["task_id"], reason="Fixture cancelled")).status_code == 200
    elif change == "edit":
        async with AsyncSessionLocal() as db:
            project = await db.get(Project, UUID(context["project_id"]))
            project_version = project.row_version
        assert (await post(context, "UPDATE_TASK", 2, task_id=created["task_id"],
            expected_project_version=project_version, title="Changed fixture", inputs=new_inputs())).status_code == 200
    elif change == "revoke":
        async with AsyncSessionLocal() as db:
            grant = await db.get(InteractiveIntegrationGrant, UUID(context["grant"]["grant_id"]))
            grant.status, grant.revoked_at = "REVOKED", datetime.now(UTC)
            grant.row_version += 1
            await db.commit()
    elif change == "disabled":
        monkeypatch.setattr(get_settings(), "cloud_enabled", False)
    else:
        async def expired(_db):
            return datetime.now(UTC) + timedelta(minutes=2)
        monkeypatch.setattr(service, "clock", expired)
    with pytest.raises(HTTPException):
        await accept_sources(claim, result)
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(created["task_id"]))
        assert task.latest_attempt_id is None and task.frozen_manifest is None
        assert await db.scalar(select(func.count()).select_from(CloudAttempt).where(CloudAttempt.task_id == task.id)) == 0


async def test_start_removes_legacy_draft_budget_before_resolution(cloud_context):
    context = cloud_context
    created = await legacy_draft(context, task_inputs=inputs())
    started = await post(context, "START_TASK", 1, task_id=created["task_id"])
    assert started.status_code == 200, started.text
    assert started.json()["legacy_draft_budget_removed"] is True
    fixed = await read_all(context, created["task_id"], 2)
    assert fixed["task"]["inputs"]["budgets"] is None
    claim, result = await claim_sources(context)
    accepted = await accept_sources(claim, result)
    assert accepted["attempt_id"]
