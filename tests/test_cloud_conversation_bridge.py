"""Fenced conversation transport with synthetic APIs and no SDK/model work."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from hypertest.cloud.conversation_bridge import ConversationBridge, recover_conversation_spool
from hypertest.cloud.errors import CloudBlocked
from hypertest.sync_core import digest

IDENTITY = {"project_id": "00000000-0000-4000-8000-000000000001", "task_id": "00000000-0000-4000-8000-000000000002",
            "attempt_id": "00000000-0000-4000-8000-000000000003", "generation": 2,
            "session_id": "cloud-00000000-0000-4000-8000-000000000003"}


def frame(text="visible", sequence=1):
    return {"assistant_message": {"session_id": IDENTITY["session_id"], "event_sequence": sequence,
        "text": text, "interrupted": False, "content_status": "ACCEPTED"}}


class API:
    def __init__(self):
        self.events, self.requests, self.messages = {}, [], []
        self.reject = False
        self.unavailable = False
        self.lose_append = False
        self.lose_ack = False
        self.pending = None
        self.legacy_digest = False
        self.request_generation = None

    async def request(self, operation, body):
        self.requests.append((operation, body))
        if operation == "conversation/validate":
            if self.unavailable:
                raise OSError("synthetic outage")
            return {"accepted": not self.reject}
        if operation == "conversation/append":
            expected = {"text": "", "event_seq": None, "state": None, "reason_code": None, "observed_at": None, **body}
            self.events.setdefault(body["event_key"], {**body, **IDENTITY, "status": "RECORDED", "request_digest": digest(expected)})
            if self.lose_append:
                self.lose_append = False
                raise OSError("synthetic lost response")
            return self.events[body["event_key"]]
        if operation == "conversation/poll":
            if self.pending:
                return {"message": None, "pending_message_id": self.pending}
            if self.messages:
                value = self.messages.pop(0)
                self.pending = value["id"]
                expected = {key: IDENTITY[key] for key in ("project_id", "task_id", "attempt_id")}
                if self.legacy_digest:
                    expected["generation"] = self.request_generation or IDENTITY["generation"]
                return {"message": {**value, **IDENTITY, "role": "USER", "status": "DELIVERING",
                                    **({"request_generation": self.request_generation} if self.request_generation is not None else {}),
                                    "request_digest": digest({**expected, "text": value["text"]})}}
            return {"message": None}
        if operation == "conversation/ack":
            if self.lose_ack:
                self.lose_ack = False
                raise OSError("synthetic lost ack")
            self.pending = None
            return {**IDENTITY, "id": body["message_id"], "status": body["status"],
                    "sdk_message_id": body.get("sdk_message_id")}
        raise AssertionError(operation)


def make(tmp_path, api=None, *, spool=None, ready=True):
    api = api or API()
    async def assert_current(): pass
    broker = SimpleNamespace(identity=SimpleNamespace(generation=2, worker_id="host-worker"), api=api,
                             **{key: IDENTITY[key] for key in ("project_id", "task_id", "attempt_id")},
                             _body=lambda **fields: fields, assert_current=assert_current)
    adapter = SimpleNamespace()
    bridge = ConversationBridge(broker, adapter, IDENTITY["session_id"], private_root=spool or tmp_path / "private")
    if ready:
        bridge.session_ready.set()
    return bridge, api, adapter


@pytest.mark.asyncio
async def test_secret_rejection_stores_only_empty_placeholder(tmp_path):
    bridge, api, _ = make(tmp_path)
    api.reject = True
    runner = asyncio.create_task(bridge.run())
    try:
        await bridge.accept_frame(frame("exact-project-secret"))
        await bridge.flush()
        rows = bridge.db.execute("SELECT payload FROM observations").fetchall()
        assert len(rows) == 1 and "exact-project-secret" not in rows[0][0]
        assert json.loads(rows[0][0])["reason_code"] == "CONTENT_REJECTED"
        assert next(iter(api.events.values()))["text"] == ""
    finally:
        await bridge.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_artifact_rejection_notice_has_no_body_or_task_state_and_never_prompts(tmp_path):
    bridge, api, adapter = make(tmp_path)
    async def unexpected(*args): pytest.fail("artifact rejection cannot prompt the model")
    adapter.send_message = unexpected
    runner = asyncio.create_task(bridge.run())
    try:
        await bridge.record_rejection({"key_sha256": "a" * 64, "reason_code": "ARTIFACT_REJECTED"})
        await bridge.record_rejection({"key_sha256": "b" * 64, "reason_code": "ARTIFACT_CONTENT_REJECTED"})
        await bridge.flush()
        events = list(api.events.values())
        assert [event["reason_code"] for event in events] == ["ARTIFACT_REJECTED", "ARTIFACT_CONTENT_REJECTED"]
        assert all(event["role"] == "SYSTEM" and event["text"] == "" and "state" not in event for event in events)
        assert not any(operation == "conversation/validate" for operation, _ in api.requests)
    finally:
        await bridge.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.asyncio
async def test_unavailable_secret_admission_never_persists_unvalidated_text(tmp_path):
    bridge, api, _ = make(tmp_path)
    api.unavailable = True
    runner = asyncio.create_task(bridge.run())
    await bridge.accept_frame(frame("unvalidated-text"))
    for _ in range(50):
        if any(operation == "conversation/validate" for operation, _ in api.requests):
            break
        await asyncio.sleep(0.01)
    assert bridge.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    await bridge.close()
    runner.cancel()
    await asyncio.gather(runner, return_exceptions=True)
    import sqlite3
    with sqlite3.connect(tmp_path / "private" / "conversation.sqlite3") as db:
        saved = db.execute("SELECT payload FROM observations").fetchone()[0]
    assert "unvalidated-text" not in saved and "CONVERSATION_GAP" in saved


@pytest.mark.asyncio
async def test_lost_append_response_repeats_only_same_observation(tmp_path):
    bridge, api, _ = make(tmp_path)
    api.lose_append = True
    runner = asyncio.create_task(bridge.run())
    try:
        await bridge.accept_frame(frame())
        await bridge.flush(timeout=3)
        submitted = [body for op, body in api.requests if op == "conversation/append"]
        assert len(submitted) >= 2 and all(body == submitted[0] for body in submitted)
        assert len(api.events) == 1
    finally:
        await bridge.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_digest,request_generation", [(False, None), (True, None), (True, 1)])
async def test_user_delivery_once_even_when_platform_ack_response_is_lost(tmp_path, legacy_digest, request_generation):
    bridge, api, adapter = make(tmp_path)
    api.legacy_digest = legacy_digest
    api.request_generation = request_generation
    api.messages = [{"id": "original-user-message", "text": "Continue"}]
    api.lose_ack = True
    sent = []
    async def send_message(request_id, text):
        sent.append((request_id, text))
        await bridge.accept_frame({"user_message_ack": {"request_id": request_id,
            "status": "DELIVERED", "message_id": "sdk-durable-1"}})
    adapter.send_message = send_message
    runner = asyncio.create_task(bridge.run())
    try:
        for _ in range(150):
            row = bridge.db.execute("SELECT confirmed FROM inputs").fetchone()
            if row == (1,):
                break
            await asyncio.sleep(0.01)
        assert row == (1,)
        assert sent == [("original-user-message", "Continue")]
        acknowledgements = [body for op, body in api.requests if op == "conversation/ack"]
        assert len(acknowledgements) >= 2
        assert all(body == acknowledgements[0] for body in acknowledgements)
    finally:
        await bridge.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_unrestored_session_never_claims_user_input(tmp_path):
    bridge, api, adapter = make(tmp_path, ready=False)
    api.messages = [{"id": "original-user-message", "text": "Continue"}]
    async def unexpected(*args): pytest.fail("unrestored session must not deliver input")
    adapter.send_message = unexpected
    runner = asyncio.create_task(bridge.run())
    try:
        await bridge.accept_frame(frame())
        await bridge.flush()
        assert len(api.messages) == 1 and not any(op == "conversation/poll" for op, _ in api.requests)
        assert bridge.session_ready.is_set() is False
    finally:
        await bridge.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.asyncio
async def test_lost_poll_claim_does_not_deliver_unknown_original_message(tmp_path):
    bridge, api, adapter = make(tmp_path)
    api.pending = "lost-poll-message"
    async def unexpected(*args): pytest.fail("uncertain original input must not be delivered")
    adapter.send_message = unexpected
    runner = asyncio.create_task(bridge.run())
    try:
        for _ in range(100):
            row = bridge.db.execute("SELECT status,confirmed FROM inputs").fetchone()
            if row == ("UNKNOWN", 1):
                break
            await asyncio.sleep(0.01)
        assert row == ("UNKNOWN", 1)
    finally:
        await bridge.close()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


class RecoveryAPI:
    def __init__(self, original):
        self.original, self.calls = original, []

    async def request(self, operation, body):
        assert operation in {"conversation/recover-append", "conversation/recover-ack"}
        assert body["worker_id"] == "host-worker" and "identity" not in body
        assert all(body[key] == IDENTITY[key] for key in ("project_id", "task_id", "attempt_id", "generation"))
        self.calls.append((operation, body))
        fields = {key: value for key, value in body.items() if key not in {"project_id", "task_id", "attempt_id", "worker_id", "generation"}}
        return await self.original.request(operation.replace("recover-", ""), fields)


def recovery_spool(tmp_path):
    attempt = tmp_path / ("attempt-" + IDENTITY["attempt_id"])
    attempt.mkdir(mode=0o700)
    return attempt / "conversation" / "generation-2"


async def test_restart_replays_only_observations_and_ack_without_execution_credential(tmp_path):
    root = recovery_spool(tmp_path)
    bridge, api, _ = make(tmp_path, spool=root)
    payload = {"event_key": bridge._key("assistant", 7), "session_id": IDENTITY["session_id"],
        "role": "ASSISTANT", "text": "Previously admitted public text", "event_seq": 7,
        "observed_at": "2026-11-04T08:00:00+00:00"}
    bridge._save(payload)
    bridge.db.execute("INSERT INTO inputs(message_id,status) VALUES('unknown-original', 'DELIVERING')")
    bridge.db.execute("INSERT INTO inputs(message_id,status,sdk_message_id) VALUES('known-original', 'DELIVERED', 'sdk-original')")
    bridge.db.commit()
    await bridge.close()
    api.lose_ack = True
    recovery = RecoveryAPI(api)
    assert await recover_conversation_spool(recovery, root, "host-worker") is True
    assert await recover_conversation_spool(recovery, root, "host-worker") is False
    appends = [body for operation, body in recovery.calls if operation.endswith("append")]
    assert len(appends) == 1 and all(appends[0][key] == value for key, value in payload.items())
    acks = [body for operation, body in recovery.calls if operation.endswith("ack")]
    assert [body["status"] for body in acks] == ["UNKNOWN", "UNKNOWN", "DELIVERED"]
    assert acks[0] == acks[1] and acks[-1]["sdk_message_id"] == "sdk-original"


@pytest.mark.parametrize("mutation", ["wrong-worker", "wrong-directory", "missing-descriptor"])
async def test_recovery_refuses_unbound_or_mismatched_private_spool(tmp_path, mutation):
    root = recovery_spool(tmp_path)
    bridge, api, _ = make(tmp_path, spool=root)
    if mutation == "missing-descriptor":
        bridge.db.execute("DELETE FROM metadata WHERE key='descriptor'")
        bridge.db.commit()
    await bridge.close()
    if mutation == "wrong-directory":
        moved = root.with_name("generation-3")
        root.rename(moved)
        root = moved
    recovery = RecoveryAPI(api)
    with pytest.raises(CloudBlocked) as error:
        await recover_conversation_spool(recovery, root, "another-worker" if mutation == "wrong-worker" else "host-worker")
    assert error.value.code == "CONVERSATION_SPOOL_INVALID" and recovery.calls == []
