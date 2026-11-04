"""Conversation delivery and output visibility, synthetic dedicated test DB only."""
import asyncio
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import dispatched, worker_submit

from hypertest.application import cloud_tasks as service
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudConversationMessage, CloudTask

pytest_plugins = ("test_cloud_tasks",)


@pytest.fixture
async def chat(cloud_context, monkeypatch, tmp_path):
    context = cloud_context
    token = "conversation-worker-" + "x" * 40
    path = tmp_path / "token"
    path.write_text(token)
    path.chmod(0o600)
    settings = get_settings()
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_api_token_file", str(path))
    monkeypatch.setattr(settings, "cloud_worker_api_worker_id", "chat-fixture")
    queued = await dispatched(context)
    async with AsyncSessionLocal() as db:
        claim = await service.claim_attempt(db, "chat-fixture", project_id=UUID(context["project_id"]))
    worker = service.WorkerIdentity("chat-fixture", claim["lease_token"], claim["generation"], claim["work_token"])
    running = await worker_submit(context, worker, queued, "TRANSITION", status="RUNNING")
    body = {"project_id": context["project_id"], "task_id": queued["task_id"], "attempt_id": queued["attempt_id"],
        "identity": {"worker_id": worker.worker_id, "lease_token": worker.lease_token,
                     "generation": worker.generation, "work_token": worker.work_token}}
    session = "cloud-" + queued["attempt_id"]
    worker_headers = {"Authorization": "Bearer " + token}
    url = f"/api/v1/cloud/tasks/{queued['task_id']}/conversation"
    start = {**body, "event_key": "state:running", "session_id": session,
             "role": "SYSTEM", "state": "RUNNING"}
    result = await context["client"].post("/api/v1/cloud/worker/conversation/append", json=start, headers=worker_headers)
    assert result.status_code == 200, result.text
    return {**context, "body": body, "worker_headers": worker_headers, "url": url, "session": session,
            "queued": queued, "version": running["version"]}


async def worker(chat, route, **fields):
    return await chat["client"].post("/api/v1/cloud/worker/conversation/" + route,
        headers=chat["worker_headers"], json={**chat["body"], **fields})


async def user(chat, key="user:one", text="Please explain the blocker."):
    return await chat["client"].post(chat["url"], headers=chat["headers"], json={
        "project_id": chat["project_id"], "attempt_id": chat["queued"]["attempt_id"],
        "generation": chat["body"]["identity"]["generation"], "operation_key": key, "text": text})


async def history(chat, after=0):
    response = await chat["client"].get(chat["url"], headers=chat["headers"],
        params={"project_id": chat["project_id"], "after": after})
    assert response.status_code == 200, response.text
    return response.json()


async def test_partial_reply_visible_without_final_report_or_version_change(chat):
    fields = {"session_id": chat["session"], "event_key": "assistant:7", "event_seq": 7,
              "role": "ASSISTANT", "text": "Blocked: the test account is missing."}
    first = await worker(chat, "append", **fields)
    assert first.status_code == 200, first.text
    repeated = await worker(chat, "append", **fields)
    assert repeated.json() == first.json()
    assert (await worker(chat, "append", **{**fields, "text": "different"})).status_code == 409
    page = await history(chat)
    assert page["messages"][-1]["text"] == fields["text"]
    assert page["session"]["can_send"]
    summary = await chat["client"].get(chat["url"].removesuffix("/conversation") + "/summary",
        headers=chat["headers"], params={"project_id": chat["project_id"]})
    assert summary.json()["version"] == chat["version"]
    assert summary.json()["reported_result"] == "NOT_RUN"
    assert (await history(chat, page["next_cursor"]))["messages"] == []


@pytest.mark.parametrize("reason", ["SDK_SESSION_BUSY", "SDK_SESSION_UNAVAILABLE", "WORKER_RUNTIME_FAILED"])
async def test_worker_failure_publishes_through_http_and_recovers_same_observation(chat, tmp_path, reason):
    from hypertest.cloud.conversation_bridge import ConversationBridge

    async def request(route, body):
        response = await chat["client"].post("/api/v1/cloud/worker/" + route,
            headers=chat["worker_headers"], json=body)
        assert response.status_code == 200, response.text
        return response.json()
    identity = chat["body"]["identity"]
    broker = SimpleNamespace(api=SimpleNamespace(request=request), identity=SimpleNamespace(**identity),
        **{key: chat["body"][key] for key in ("project_id", "task_id", "attempt_id")},
        _body=lambda **fields: {**chat["body"], **fields})
    bridge = ConversationBridge(broker, None, chat["session"], private_root=tmp_path / "conversation")
    runner = asyncio.create_task(bridge.run())
    try:
        if reason.startswith("SDK_SESSION_"):
            await bridge.accept_frame({"runtime_observation": "ERROR", "code": reason})
        else:
            await bridge.record_state("INTERRUPTED", reason)
        await bridge.flush()
        bridge.check()
        encoded, accepted = bridge.db.execute("SELECT payload,accepted FROM observations").fetchone()
        assert accepted == 1
        payload = json.loads(encoded)
        original = (await worker(chat, "lookup", event_key=payload["event_key"])).json()
        assert original["state"] == "INTERRUPTED" and original["reason_code"] == reason
        assert original["text"] == "" and original["status"] == "RECORDED"
        fenced = await chat["client"].post("/api/v1/cloud/worker/fence", headers=chat["worker_headers"],
            json={**chat["body"], "reason": reason})
        assert fenced.status_code == 200, fenced.text
        recovered = await chat["client"].post("/api/v1/cloud/worker/conversation/recover-append",
            headers=chat["worker_headers"], json={**payload,
                **{key: chat["body"][key] for key in ("project_id", "task_id", "attempt_id")},
                "worker_id": identity["worker_id"], "generation": identity["generation"]})
        assert recovered.status_code == 200, recovered.text
        assert recovered.json() == original
        records = [row for row in (await history(chat))["messages"] if row["event_key"] == payload["event_key"]]
        assert records == [original]
    finally:
        await bridge.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_arbitrary_runtime_reason_is_not_accepted_as_conversation_content(chat):
    response = await worker(chat, "append", session_id=chat["session"], event_key="failure:arbitrary",
        role="SYSTEM", state="INTERRUPTED", reason_code="untrusted-runtime-error-text")
    assert response.status_code == 422
    assert all(row["event_key"] != "failure:arbitrary" for row in (await history(chat))["messages"])


@pytest.mark.parametrize("operation", ["append", "renew"])
async def test_poll_and_worker_routes_lock_task_before_attempt(chat, monkeypatch, operation):
    """Real concurrent API transactions: original-read and active take one order."""
    locked = asyncio.Event()
    release = asyncio.Event()
    original_attempt = service._attempt

    async def paused_attempt(*args, **kwargs):
        row = await original_attempt(*args, **kwargs)
        if asyncio.current_task().get_name() == "worker-lock-order-writer":
            locked.set()
            await release.wait()
        return row

    monkeypatch.setattr(service, "_attempt", paused_attempt)
    if operation == "append":
        request = worker(chat, "append", session_id=chat["session"], event_key="assistant:concurrent",
                         role="ASSISTANT", text="Synthetic concurrent observation")
    else:
        request = chat["client"].post("/api/v1/cloud/worker/renew", headers=chat["worker_headers"],
                                     json={**chat["body"], "lease_seconds": 90})
    writer = asyncio.create_task(request, name="worker-lock-order-writer")
    polling = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)
        # A separate real DB transaction must already be unable to acquire the
        # Task. Previously original_read/active held only Attempt here, allowing
        # poll to take Task and producing the opposite Task/Attempt wait cycle.
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError) as error:
                await db.scalar(select(CloudTask).where(CloudTask.id == UUID(chat["queued"]["task_id"]))
                                .with_for_update(nowait=True))
            assert error.value.orig.sqlstate == "55P03"
            await db.rollback()
        polling = asyncio.create_task(worker(chat, "poll", session_id=chat["session"]))
        await asyncio.sleep(0)
        release.set()
        response, polled = await asyncio.wait_for(asyncio.gather(writer, polling), timeout=5)
        assert response.status_code == 200, response.text
        assert polled.status_code == 200 and polled.json() == {"message": None}
        assert (await worker(chat, "poll", session_id=chat["session"])).status_code == 200
    finally:
        release.set()
        for task in (writer, polling):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (writer, polling) if task is not None), return_exceptions=True)


async def test_reply_claimed_once_and_ack_has_incremental_cursor(chat):
    sent = await user(chat)
    assert sent.status_code == 200, sent.text
    assert (await user(chat)).json() == sent.json()
    assert (await user(chat, text="changed")).status_code == 409
    before = (await history(chat))["next_cursor"]
    polled = await worker(chat, "poll", session_id=chat["session"])
    assert polled.json()["message"]["id"] == sent.json()["id"]
    repeated = await worker(chat, "poll", session_id=chat["session"])
    assert repeated.json()["message"] is None
    assert repeated.json()["pending_message_id"] == sent.json()["id"]
    ack = {"session_id": chat["session"], "message_id": sent.json()["id"],
           "status": "DELIVERED", "sdk_message_id": "sdk-message-17"}
    accepted = await worker(chat, "ack", **ack)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["cursor"] > before
    assert (await worker(chat, "ack", **ack)).json() == accepted.json()
    changed = await history(chat, before)
    assert changed["messages"][-1]["status"] == "DELIVERED"
    assert changed["messages"][-1]["sdk_message_id"] == "sdk-message-17"
    assert (await worker(chat, "ack", **{**ack, "sdk_message_id": "other"})).status_code == 409


async def test_secret_output_is_placeholder_not_a_task_failure(chat):
    secret = "glpat-" + "x" * 24
    validated = await worker(chat, "validate", text=secret)
    assert validated.json() == {"accepted": False, "reason_code": "CONTENT_REJECTED"}
    rejected = await worker(chat, "append", session_id=chat["session"], event_key="secret:one",
                            role="ASSISTANT", text=secret)
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED" and rejected.json()["text"] == ""
    assert secret not in str(await history(chat))
    assert (await user(chat, text=secret)).status_code == 422
    good = await worker(chat, "append", session_id=chat["session"], event_key="safe:two", role="ASSISTANT", text="Account missing.")
    assert good.status_code == 200
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(select(CloudConversationMessage).where(CloudConversationMessage.task_id == UUID(chat["queued"]["task_id"])))
        assert all(secret not in row.text for row in rows)


async def test_fence_keeps_history_unsent_queue_and_never_replays(chat):
    first = (await user(chat)).json()
    await worker(chat, "poll", session_id=chat["session"])
    second = (await user(chat, key="user:two", text="Another observation")).json()
    async with AsyncSessionLocal() as db:
        task = await service._task(db, UUID(chat["queued"]["task_id"]), lock=True)
        attempt = await service._attempt(db, task, UUID(chat["queued"]["attempt_id"]))
        await service._fence(db, attempt)
        await db.commit()
    page = await history(chat)
    by_id = {m["id"]: m for m in page["messages"]}
    assert by_id[first["id"]]["status"] == "UNKNOWN"
    assert by_id[second["id"]]["status"] == "QUEUED"
    assert any(m["role"] == "SYSTEM" and m["reason_code"] == "WORKER_INTERRUPTED"
               and m["source"] == "CONTROL_PLANE" for m in page["messages"])
    assert page["session"]["can_send"]
    assert page["session"]["delivery_state"] == "UNCONFIRMED"
    assert "SESSION_CONNECTING" not in page["session"]["blocking_reasons"]
    assert (await user(chat, key="user:three")).status_code == 200
    assert (await worker(chat, "poll", session_id=chat["session"])).status_code == 409
    # Late original observations can be archived without reviving the session.
    late = await worker(chat, "append", session_id=chat["session"], event_key="late:one",
                        role="ASSISTANT", text="Original last reply", state="RUNNING")
    assert late.status_code == 200
    assert (await history(chat))["session"]["can_send"]


async def test_identity_and_session_boundaries(chat):
    assert (await worker(chat, "append", session_id="another", event_key="wrong:one", role="ASSISTANT", text="no")).status_code == 403
    bad = {**chat["body"], "identity": {**chat["body"]["identity"], "generation": 999},
           "session_id": chat["session"], "event_key": "wrong:two", "role": "ASSISTANT", "text": "no"}
    assert (await chat["client"].post("/api/v1/cloud/worker/conversation/append", headers=chat["worker_headers"], json=bad)).status_code == 403
    wrong = await chat["client"].get(chat["url"], headers=chat["headers"], params={"project_id": str(uuid4())})
    assert wrong.status_code in {403, 404}
    unauth = await chat["client"].get(chat["url"], params={"project_id": chat["project_id"]})
    assert unauth.status_code in {401, 403}


async def test_restart_recovers_only_original_observations_without_execution_tokens(chat):
    fields = {"session_id": chat["session"], "event_key": "assistant:recover", "event_seq": 23,
              "role": "ASSISTANT", "text": "The browser is blocked."}
    original = (await worker(chat, "append", **fields)).json()
    message = (await user(chat)).json()
    await worker(chat, "poll", session_id=chat["session"])
    async with AsyncSessionLocal() as db:
        task = await service._task(db, UUID(chat["queued"]["task_id"]), lock=True)
        attempt = await service._attempt(db, task, UUID(chat["queued"]["attempt_id"]))
        await service._fence(db, attempt)
        await db.commit()
    target = {key: chat["body"][key] for key in ("project_id", "task_id", "attempt_id")}
    target.update(worker_id="chat-fixture", generation=chat["body"]["identity"]["generation"])
    async def recover(route, body):
        return await chat["client"].post("/api/v1/cloud/worker/conversation/" + route,
            json={**target, **body}, headers=chat["worker_headers"])
    replayed = await recover("recover-append", fields)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == original
    late = await recover("recover-append", {**fields, "event_key": "assistant:late", "event_seq": 24})
    assert late.status_code == 200
    ack = await recover("recover-ack", {"session_id": chat["session"], "message_id": message["id"],
        "status": "DELIVERED", "sdk_message_id": "original-sdk-message"})
    assert ack.status_code == 200 and ack.json()["status"] == "DELIVERED"
    assert (await history(chat))["session"]["can_send"]
    assert (await recover("recover-append", {**fields, "generation": 999})).status_code == 403
    assert (await recover("recover-append", {**fields, "worker_id": "another"})).status_code == 403
