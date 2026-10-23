"""ADR-024 PostgreSQL positive contract; no real host or SUT execution claim."""
import asyncio
from uuid import UUID, uuid4

from sqlalchemy import func, select
from test_session_tasks import body, counts, sync
from test_session_tasks import context as context

from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.session_tasks import SyncReceipt, TaskOperationReceipt


async def test_create_edit_bind_sync_share_one_id_and_contiguous_fixed_versions(context):
    f = context
    before = await counts()
    created = await f["c"].post(f"/api/v1/projects/{f['project_id']}/local-tasks", json={
        "idempotency_key": "create-roundtrip", "title": "Precreated Local task",
        "objective": "One stable ID", "plan_markdown": "# Approved analysis"})
    assert created.status_code == 200, created.text
    original = created.json()
    task = original["task"]
    task_id = task["id"]
    assert task["version"] == 1 and task["binding_state"] == "UNBOUND"
    assert task["status"] == "DRAFT" and task["reported_result"] == "NOT_RUN"
    assert task["creator_actor_ref"].startswith("web:")
    assert task["intended_actor_ref"].startswith("interactive:")
    assert all(task[field] is None for field in (
        "provider", "session_id", "owner_actor_ref", "source", "last_synced_at", "bound_at"))
    edited = await f["c"].patch("/api/v1/tasks/" + task_id, json={
        "expected_version": 1, "title": "Reviewed before source binding"})
    assert edited.status_code == 200 and edited.json()["task"]["version"] == 2
    payload = {"project_id": f["project_id"], "task_id": task_id, "provider": "codex",
        "session_id": "positive-native-reference-" + uuid4().hex,
        "expected_version": 2, "idempotency_key": "bind-roundtrip"}
    bound = await f["c"].post("/api/v1/interactive/tasks/bind", json=payload, headers=f["headers"])
    assert bound.status_code == 200, bound.text
    receipt = bound.json()
    assert receipt["version"] == 3 and receipt["task_id"] == task_id
    detail = (await f["c"].get("/api/v1/tasks/" + task_id)).json()
    assert detail["task"]["source"] is None and detail["task"]["last_synced_at"] is None
    assert detail["task"]["bound_at"] is not None and detail["sync_history"] == []
    assert [row["action"] for row in detail["management_history"]] == ["CREATE", "UPDATE"]
    assert len(detail["binding_history"]) == 1
    accepted = await sync(f, body(f, task_id=task_id, expected_version=3,
                                  session_id=payload["session_id"]))
    assert accepted.status_code == 200 and accepted.json()["version"] == 4
    latest = (await f["c"].get("/api/v1/tasks/" + task_id)).json()
    assert latest["task"]["id"] == task_id and latest["task"]["reported_result"] == "FAIL"
    assert latest["task"]["source"] == "AGENT_REPORTED"
    assert latest["task"]["last_synced_at"] is not None
    assert len(latest["sync_history"]) == 1
    for version, state in ((1, "UNBOUND"), (2, "UNBOUND"), (3, "BOUND"), (4, "BOUND")):
        pinned = await f["c"].get("/api/v1/tasks/" + task_id, params={"version": version})
        assert pinned.status_code == 200 and pinned.json()["task"]["version"] == version
        assert pinned.json()["task"]["binding_state"] == state
        assert (pinned.json()["task"]["source"] is None) == (version < 4)
    assert (await f["c"].post("/api/v1/interactive/tasks/bind", json=payload,
                             headers=f["headers"])).json() == receipt
    assert (await f["c"].get("/api/v1/interactive/tasks/bindings/by-key", params={
        "project_id": f["project_id"], "idempotency_key": payload["idempotency_key"]},
        headers=f["headers"])).json() == receipt
    assert (await f["c"].get(f"/api/v1/projects/{f['project_id']}/local-tasks/by-key", params={
        "idempotency_key": "create-roundtrip"})).json() == original
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TaskOperationReceipt).where(
            TaskOperationReceipt.task_id == UUID(task_id))) == 2
        assert await db.scalar(select(func.count()).select_from(SyncReceipt).where(
            SyncReceipt.task_id == UUID(task_id))) == 1
    assert await counts() == before


async def test_two_tasks_competing_for_one_source_accept_exactly_one(context):
    f = context
    tasks = []
    for index in range(2):
        response = await f["c"].post(f"/api/v1/projects/{f['project_id']}/local-tasks", json={
            "idempotency_key": f"competing-create-{index}", "title": f"Candidate {index}"})
        assert response.status_code == 200, response.text
        tasks.append(response.json()["task"]["id"])
    session_id = "one-real-source-" + uuid4().hex
    responses = await asyncio.gather(*[f["c"].post("/api/v1/interactive/tasks/bind", headers=f["headers"],
        json={"project_id": f["project_id"], "task_id": task_id, "provider": "codex",
              "session_id": session_id, "expected_version": 1, "idempotency_key": f"competing-bind-{index}"})
        for index, task_id in enumerate(tasks)])
    assert sorted(item.status_code for item in responses) == [200, 409]
    details = [(await f["c"].get("/api/v1/tasks/" + task_id)).json() for task_id in tasks]
    assert sorted(item["task"]["version"] for item in details) == [1, 2]
    assert sorted(item["task"]["binding_state"] for item in details) == ["BOUND", "UNBOUND"]
    assert sum(len(item["binding_history"]) for item in details) == 1
    assert all(item["sync_history"] == [] for item in details)
