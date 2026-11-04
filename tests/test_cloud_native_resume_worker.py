"""Native continuation and concurrent routing without invoking Harness or git."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_cloud_native_worker import claim_response, mock_worker_api
from test_cloud_native_worker import loop_args as loop_args

from hypertest.cloud import native_worker
from hypertest.cloud.errors import CloudBlocked


async def test_claim_state_from_other_slot_cannot_advance_original(tmp_path, loop_args):
    class API:
        async def request(self, operation, body):
            return {**claim_response(), "slot_id": "slot-2"}
    with pytest.raises(CloudBlocked) as error:
        await native_worker._run_slot(API(), loop_args, tmp_path, tmp_path, "slot-1")
    assert error.value.code == "CLAIM_SLOT_MISMATCH"
    assert not (tmp_path / "claim-pending.json").exists()


async def test_slots_run_concurrently_and_failure_isolated(tmp_path, monkeypatch, loop_args):
    both_running = asyncio.Event()
    running, closed = [], []
    class API:
        async def request(self, operation, body):
            if operation == "claim/state":
                return {**claim_response(), "slot_id": body["slot_id"]}
            if operation == "claim":
                return claim_response(body, kind="ATTEMPT", closed=False, claim={"slot": body["slot_id"]})
            closed.append(body["slot_id"])
            return claim_response(body, kind="ATTEMPT")
    async def execute(api, args, state, claim):
        running.append(claim["slot"])
        if len(running) == 2:
            both_running.set()
        await asyncio.wait_for(both_running.wait(), 1)
        if claim["slot"] == "slot-1":
            raise CloudBlocked("SYNTHETIC", "One failed session")
    monkeypatch.setattr(native_worker, "execute", execute)
    slots = [tmp_path / "slot-1", tmp_path / "slot-2"]
    for slot in slots:
        slot.mkdir(mode=0o700)
    result = await asyncio.gather(*(native_worker._run_slot(API(), loop_args, tmp_path, slot, slot.name)
                                    for slot in slots), return_exceptions=True)
    assert isinstance(result[0], CloudBlocked) and result[1] == 0
    assert set(running) == set(closed) == {"slot-1", "slot-2"}
    assert all(native_worker.pending_claim(slot, loop_args.worker_id) is None for slot in slots)


async def test_supervisor_starts_four_independent_slots(tmp_path, monkeypatch, loop_args):
    loop_args.once, loop_args.max_sessions = False, 4
    slots = []
    async def run_slot(api, args, state, slot_state, slot_id, **kwargs):
        slots.append((slot_id, slot_state))
        return 0
    async def no_network(*args):
        pytest.fail("No claim should be sent by this scheduling fixture")
    monkeypatch.setattr(native_worker, "_run_slot", run_slot)
    mock_worker_api(monkeypatch, no_network)
    assert await native_worker.run(loop_args) == 0
    assert {slot for slot, _ in slots} == {"slot-1", "slot-2", "slot-3", "slot-4"}
    assert len({path for _, path in slots}) == 4


async def test_original_claim_restart_also_replays_saved_observations_without_sdk(tmp_path, monkeypatch, loop_args):
    from test_cloud_native_worker import claim_request

    from hypertest.cloud import conversation_bridge, sdk
    spool = tmp_path / ("attempt-" + str(uuid4())) / "conversation" / "generation-1"
    spool.mkdir(parents=True)
    original = claim_request()
    original.pop("slot_id")
    native_worker.prepare_claim(tmp_path, original)
    recovered, calls = [], []
    async def recover(api, root, *, worker_id):
        recovered.append((root, worker_id))
        return False
    async def request(operation, body):
        calls.append((operation, body))
        assert operation == "claim/reconcile"
        return claim_response(original, kind="ABANDONED")
    def no_sdk(): pytest.fail("Historical observation replay must not open Harness")
    monkeypatch.setattr(conversation_bridge, "recover_conversation_spool", recover)
    monkeypatch.setattr(sdk, "inspect_native_sdk", no_sdk)
    mock_worker_api(monkeypatch, request)
    assert await native_worker.run(loop_args) == 0
    assert recovered == [(spool, loop_args.worker_id)] and calls == [("claim/reconcile", original)]


async def test_historical_replay_isolates_failures_and_does_not_sweep_new_sessions(tmp_path, monkeypatch):
    from hypertest.cloud import conversation_bridge
    def make_spool():
        path = tmp_path / ("attempt-" + str(uuid4())) / "conversation" / "generation-1"
        path.mkdir(parents=True)
        return path
    first, second = make_spool(), make_spool()
    snapshot = native_worker._conversation_spools(tmp_path)
    new_live = make_spool()
    seen = []
    async def recover(api, root, *, worker_id):
        seen.append(root)
        if root == first:
            raise CloudBlocked("CONVERSATION_READBACK_MISMATCH", "Keep original observation")
        return False
    monkeypatch.setattr(conversation_bridge, "recover_conversation_spool", recover)
    await native_worker._recover_conversations(None, snapshot, "worker", once=True)
    assert set(seen) == {first, second} and new_live not in seen


@pytest.mark.parametrize(("identity_ok", "completion_rejected", "publisher_failure"),
    [(True, False, False), (False, False, False), (True, True, False), (True, False, True)])
async def test_resume_verifies_identity_before_new_message_and_uses_original_workspace(
        tmp_path, monkeypatch, identity_ok, completion_rejected, publisher_failure):
    from hypertest.cloud import (
        artifacts,
        conversation_bridge,
        live_question_bridge,
        native_git,
        native_sdk_adapter,
        reporter,
    )
    from hypertest.config import get_settings
    events = []
    reader_release = asyncio.Event()
    attempt_id = "synthetic-attempt"
    root = tmp_path / ("attempt-" + attempt_id)
    workspace = root / "workspace"
    workspace.mkdir(parents=True, mode=0o700)
    original_prompt = root / "prompt-intent.json"
    original_prompt.write_text("original immutable prompt identity")
    intent = {"target_generation": 3, "continuation": "Explain this blocker.", "operation_key": "resume-new-message"}
    claim = {"task": {"id": "task", "project_id": "project", "title": "Task", "inputs": {"budgets": None}},
        "attempt": {"id": attempt_id, "checkpoint": {"native_resume": intent}}}
    class Broker:
        def __init__(self, *args):
            self.identity = SimpleNamespace(generation=3)
        async def assert_current(self): pass
        async def renew(self, *args): pass
        def suspend_writes(self): pass
        async def fence_for_recovery(self, reason): events.append("fenced")
    class Reporter:
        namespace = "fixture"
        journal = SimpleNamespace(db=SimpleNamespace(execute=lambda *args: []))
        def __init__(self, **kwargs):
            assert kwargs["workspace"] == workspace
        async def recover(self): events.append("recover")
        def drain_rejections(self): return []
        async def submit_handoff(self, *args):
            events.append("running")
            return SimpleNamespace(synced=True)
        async def submit_native_completion(self, *args, **kwargs):
            events.append("complete")
            return SimpleNamespace(synced=True, receipt={})
        async def prevalidate_native_completion(self, handoff, _digest):
            events.append("preview:" + handoff.key)
            if handoff.key == "rejected":
                from hypertest.cloud.handoff_rejections import HandoffRejected
                raise HandoffRejected({"reason": "REPORT_CONTENT_REJECTED"})
        def close(self): pass
    class Process:
        returncode = None if completion_rejected else 0
        async def wait(self): return 0
    process = Process()
    class Adapter:
        def __init__(self, **kwargs): assert kwargs["workspace"] == workspace
        async def resume(self, **kwargs):
            events.append("resume")
            assert args._native_startup_lock.locked()
            assert kwargs["continuation"] == intent["continuation"] and "prompt" not in kwargs
            assert kwargs["session_id"] == "cloud-" + attempt_id
            assert kwargs["resume_identity"] == {"digest": "fixed"}
            return process
        async def start(self, **kwargs): pytest.fail("Resume must not start a fresh session")
        async def stop(self):
            events.append("stop")
            reader_release.set()
        async def close_session(self):
            events.append("close")
            process.returncode = 0
    class Conversation:
        failure = None
        def __init__(self, *args, **kwargs): pass
        async def run(self):
            if publisher_failure:
                self.failure = CloudBlocked("CONVERSATION_READBACK_MISMATCH", "Publisher failed while stdout waits")
                raise self.failure
            await asyncio.Event().wait()
        async def flush(self): pass
        async def record_state(self, state, *args): events.append(state)
        async def close(self): pass
        def stop_accepting(self): pass
    class Bridge:
        tasks = {}
        def __init__(self, *args, **kwargs):
            self.conversation = kwargs["conversation"]
            self.runtime_ready = asyncio.Event()
        async def read(self, process):
            self.runtime_ready.set()
            if publisher_failure:
                await reader_release.wait()
        def check(self):
            if self.conversation.failure:
                raise self.conversation.failure
        async def close(self): pass
    async def identity(**kwargs):
        events.append("identity")
        assert args._native_startup_lock.locked()
        if not identity_ok:
            raise CloudBlocked("IDENTITY_UNCONFIRMED", "Refuse before any new message")
        return {"digest": "fixed"}
    collected = 0
    async def collect(*args, **kwargs):
        nonlocal collected
        assert not startup_lock.locked()
        collected += 1
        key = "rejected" if completion_rejected and collected == 1 else "final"
        return SimpleNamespace(operation="COMPLETE_ATTEMPT", key=key), "digest"
    def no_checkout(*args, **kwargs): pytest.fail("Resume cannot checkout or rebuild an old prompt")
    monkeypatch.setattr(get_settings(), "cloud_memory_enabled", False)
    monkeypatch.setattr(native_worker, "RemoteBroker", Broker)
    monkeypatch.setattr(native_worker, "native_execution_task", lambda task, attempt: (task, {}, False))
    monkeypatch.setattr(native_worker, "prepare_continuation_identity", identity)
    monkeypatch.setattr(native_worker, "native_prompt", no_checkout)
    monkeypatch.setattr(native_git.NativeGitResolver, "checkout", no_checkout)
    monkeypatch.setattr(reporter, "CloudTaskReporter", Reporter)
    monkeypatch.setattr(native_sdk_adapter, "NativeSdkAdapter", Adapter)
    monkeypatch.setattr(conversation_bridge, "ConversationBridge", Conversation)
    monkeypatch.setattr(live_question_bridge, "LiveQuestionBridge", Bridge)
    monkeypatch.setattr(native_worker.CloudWorker, "collect", collect)
    monkeypatch.setattr(artifacts, "write_workspace_receipt", lambda *args: None)
    startup_lock = asyncio.Lock()
    args = SimpleNamespace(worker_id="fixture", dsh_home=str(tmp_path), lease_seconds=90,
                           _native_startup_lock=startup_lock)
    if publisher_failure:
        with pytest.raises(CloudBlocked) as error:
            await asyncio.wait_for(native_worker.execute(None, args, tmp_path, claim), 1)
        assert error.value.code == "CONVERSATION_READBACK_MISMATCH"
        assert events == ["recover", "identity", "running", "resume", "fenced", "stop", "INTERRUPTED"]
    elif identity_ok:
        await native_worker.execute(None, args, tmp_path, claim)
        close_events = ["preview:rejected", "preview:final", "close"] if completion_rejected else []
        assert events == ["recover", "identity", "running", "resume", *close_events, "CLOSED", "complete"]
        assert (root / "continuation-intent-3.json").exists()
    else:
        with pytest.raises(CloudBlocked, match="Refuse"):
            await native_worker.execute(None, args, tmp_path, claim)
        assert events == ["recover", "identity", "fenced", "stop"]
        assert not (root / "continuation-intent-3.json").exists()
    assert original_prompt.read_text() == "original immutable prompt identity"
    assert not startup_lock.locked()
