"""Synthetic API-to-Worker live question without a model or SUT."""
import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import dispatched, worker_submit

from hypertest.application import cloud_tasks as service
from hypertest.cloud.live_question_bridge import LiveQuestionBridge
from hypertest.cloud.native_worker import RemoteBroker
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal


async def test_original_sdk_question_to_user_answer_and_callback(cloud_context, monkeypatch, tmp_path):
    context = cloud_context
    token = "synthetic-worker-" + "x" * 40
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
    identity = service.WorkerIdentity("live-fixture", claim["lease_token"], claim["generation"], claim["work_token"])
    await worker_submit(context, identity, queued, "TRANSITION", status="RUNNING")
    claim["task"]["version"] = queued["version"] + 1

    class WorkerAPI:
        async def request(self, operation, body):
            response = await context["client"].post("/api/v1/cloud/worker/" + operation,
                headers={"Authorization": "Bearer " + token}, json=body)
            assert response.status_code == 200, response.text
            return response.json()

    stream = asyncio.StreamReader(limit=131073)
    received = []
    class Adapter:
        async def answer_question(self, request_id, answer):
            received.append((request_id, answer))
            stream.feed_data((json.dumps({"user_question_handed_off": {"request_id": request_id}}) + "\n").encode())

    broker = RemoteBroker(WorkerAPI(), claim, "live-fixture")
    session_id = "cloud-" + queued["attempt_id"]
    bridge = LiveQuestionBridge(broker, Adapter(), session_id)
    reader = asyncio.create_task(bridge.read(SimpleNamespace(stdout=stream)))
    frame = {"user_question": {"request_id": "sdk-original", "session_id": session_id,
        "questions": [{"id": "choice", "question": "Synthetic question?", "options": [{"label": "yes"}]}]}}
    stream.feed_data((json.dumps(frame) + "\n").encode())
    url = f"/api/v1/cloud/tasks/{queued['task_id']}/live-questions"
    try:
        for _ in range(100):
            listing = await context["client"].get(url, headers=context["headers"], params={"project_id": context["project_id"]})
            if listing.json()["items"]:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("question was not published")
        question_id = listing.json()["items"][0]["id"]
        response = await context["client"].post(url + f"/{question_id}/answer", headers=context["headers"], json={
            "project_id": context["project_id"], "operation_key": "synthetic-original-answer",
            "answers": [{"id": "choice", "selected": ["yes"]}], "cancelled": False})
        assert response.status_code == 200, response.text
        for _ in range(150):
            listing = await context["client"].get(url, headers=context["headers"], params={"project_id": context["project_id"]})
            if listing.json()["items"][0]["status"] == "DELIVERED":
                break
            await asyncio.sleep(0.02)
        else:
            bridge.check()
            raise AssertionError("answer was not handed to the original callback")
        assert received == [("sdk-original", {"answers": [{"id": "choice", "selected": ["yes"]}]})]
    finally:
        stream.feed_eof()
        await reader
        await bridge.close()
