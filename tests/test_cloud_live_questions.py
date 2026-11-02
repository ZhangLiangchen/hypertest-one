"""Live questions: synthetic DB/API tests, no model or external actions."""
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import dispatched, worker_submit

from hypertest.application import cloud_tasks as service
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudLiveQuestion

pytest_plugins = ("test_cloud_tasks",)


async def test_live_question_fenced_delivery_and_original_keys(cloud_context, monkeypatch, tmp_path):
    context = cloud_context
    token = "worker-test-" + "x" * 40
    token_file = tmp_path / "worker-token"
    token_file.write_text(token)
    token_file.chmod(0o600)
    settings = get_settings()
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_api_token_file", str(token_file))
    monkeypatch.setattr(settings, "cloud_worker_api_worker_id", "live-fixture")
    queued = await dispatched(context)
    async with AsyncSessionLocal() as db:
        claim = await service.claim_attempt(db, "live-fixture", project_id=UUID(context["project_id"]))
    worker = service.WorkerIdentity("live-fixture", claim["lease_token"], claim["generation"], claim["work_token"])
    await worker_submit(context, worker, queued, "TRANSITION", status="RUNNING")
    client = context["client"]
    headers = {"Authorization": "Bearer " + token}
    identity = {"worker_id": worker.worker_id, "lease_token": worker.lease_token,
        "generation": worker.generation, "work_token": worker.work_token}
    body = {"project_id": context["project_id"], "task_id": queued["task_id"],
        "attempt_id": queued["attempt_id"], "identity": identity}
    questions = [{"id": "q1", "question": "Choose a synthetic option", "options": [{"label": "yes"}, {"label": "no"}]}]
    original = {**body, "request_id": "sdk-request-1", "session_id": "cloud-" + queued["attempt_id"],
        "questions": questions, "timeout_seconds": 600}
    url = "/api/v1/cloud/worker/live-question/"
    opened = await client.post(url + "open", headers=headers, json=original)
    assert opened.status_code == 200, opened.text
    assert opened.json()["status"] == "OPEN"
    question_id = opened.json()["id"]
    replay = await client.post(url + "open", headers=headers, json=original)
    assert replay.json()["id"] == question_id
    conflict = await client.post(url + "open", headers=headers, json={**original, "timeout_seconds": 100})
    assert conflict.status_code == 409
    lookup = await client.post(url + "lookup", headers=headers, json={**body, "request_id": "sdk-request-1", "session_id": "cloud-" + queued["attempt_id"]})
    assert lookup.json()["request_digest"] == opened.json()["request_digest"]
    wrong_session = await client.post(url + "open", headers=headers, json={**original, "session_id": "other"})
    assert wrong_session.status_code == 403
    unauthorized = await client.post(url + "open", headers=headers, json={**original, "identity": {**identity, "generation": identity["generation"] + 1}})
    assert unauthorized.status_code == 409
    secret = "glpat-" + "x" * 24
    rejected = await client.post(url + "open", headers=headers, json={**original, "request_id": "secret", "questions": [{**questions[0], "question": secret}]})
    assert rejected.status_code == 422
    wrong_project = await client.get(f"/api/v1/cloud/tasks/{queued['task_id']}/live-questions", headers=context["headers"], params={"project_id": str(uuid4())})
    assert wrong_project.status_code in {403, 404}
    invalid = await client.post(url + "open", headers=headers, json={**original, "request_id": "other", "questions": [{**questions[0], "intent": {"kind": "approval"}}]})
    assert invalid.status_code == 403
    target = f"/api/v1/cloud/tasks/{queued['task_id']}/live-questions/{question_id}/answer"
    answer = {"project_id": context["project_id"], "operation_key": "answer:1",
        "answers": [{"id": "q1", "selected": ["yes"]}], "cancelled": False}
    wrong = await client.post(target, headers=context["headers"], json={**answer, "answers": [{"id": "q1", "selected": ["forged"]}]})
    assert wrong.status_code == 422
    both = await client.post(target, headers=context["headers"], json={**answer, "answers": [{"id": "q1", "selected": ["yes"], "custom": "other"}]})
    assert both.status_code == 422
    forbidden = await client.post(target, headers=context["headers"], json={**answer, "answers": [{"id": "q1", "selected": [], "custom": secret}]})
    assert forbidden.status_code == 422
    accepted = await client.post(target, headers=context["headers"], json=answer)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ANSWERED"
    assert (await client.post(target, headers=context["headers"], json=answer)).json()["answer_operation_key"] == "answer:1"
    assert (await client.post(target, headers=context["headers"], json={**answer, "operation_key": "other"})).status_code == 409
    poll = await client.post(url + "poll", headers=headers, json={**body, "question_id": question_id})
    assert poll.json()["answers"] == answer["answers"] and poll.json()["status"] == "DELIVERING"
    repeated = await client.post(url + "poll", headers=headers, json={**body, "question_id": question_id})
    assert repeated.json() == {"id": question_id, "status": "DELIVERING"}
    second = await client.post(url + "open", headers=headers, json={**original, "request_id": "sdk-request-2"})
    second_id = second.json()["id"]
    second_target = f"/api/v1/cloud/tasks/{queued['task_id']}/live-questions/{second_id}/answer"
    cancelled = await client.post(second_target, headers=context["headers"], json={"project_id": context["project_id"], "operation_key": "cancel:1", "cancelled": True})
    assert cancelled.status_code == 200
    delivery = await client.post(url + "poll", headers=headers, json={**body, "question_id": second_id})
    assert delivery.json()["cancelled"] is True and delivery.json()["answers"] == []
    handed = await client.post(url + "finish", headers=headers, json={**body, "question_id": second_id, "outcome": "DELIVERED"})
    assert handed.status_code == 200 and handed.json()["status"] == "DELIVERED"
    expired = await client.post(url + "open", headers=headers, json={**original, "request_id": "sdk-expired"})
    expired_id = expired.json()["id"]
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudLiveQuestion, UUID(expired_id))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    expired_target = f"/api/v1/cloud/tasks/{queued['task_id']}/live-questions/{expired_id}/answer"
    assert (await client.post(expired_target, headers=context["headers"], json={**answer, "operation_key": "expired"})).status_code == 409
    assert (await client.post(url + "poll", headers=headers, json={**body, "question_id": expired_id})).status_code == 409
    fourth = await client.post(url + "open", headers=headers, json={**original, "request_id": "sdk-concurrent"})
    fourth_target = f"/api/v1/cloud/tasks/{queued['task_id']}/live-questions/{fourth.json()['id']}/answer"
    a, b = await asyncio.gather(*(client.post(fourth_target, headers=context["headers"], json={**answer, "operation_key": key}) for key in ("concurrent:1", "concurrent:2")))
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    key_conflict = await client.post(fourth_target, headers=context["headers"], json={**answer, "operation_key": "answer:1"})
    assert key_conflict.status_code == 409
    third = await client.post(url + "open", headers=headers, json={**original, "request_id": "sdk-request-3"})
    assert third.status_code == 200
    third_target = f"/api/v1/cloud/tasks/{queued['task_id']}/live-questions/{third.json()['id']}/answer"
    # A fence while delivery is uncertain must never yield the answer to another process.
    fence = await client.post("/api/v1/cloud/worker/fence", headers=headers, json={**body, "reason": "WORKER_INTERRUPTED"})
    assert fence.status_code == 200
    assert (await client.post(url + "poll", headers=headers, json={**body, "question_id": question_id})).status_code == 409
    assert (await client.post(third_target, headers=context["headers"], json={**answer, "operation_key": "late"})).status_code == 409
    items = await client.get(f"/api/v1/cloud/tasks/{queued['task_id']}/live-questions",
        headers=context["headers"], params={"project_id": context["project_id"]})
    assert items.status_code == 200 and items.json()["items"][0]["status"] == "UNKNOWN"
