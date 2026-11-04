"""Public-text projection and single-reader SDK conversations; no model calls."""
import json
import os
import queue
import shutil
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from hypertest.cloud import native_sdk_driver as driver
from hypertest.cloud.native_conversation import MAX_MESSAGE_BYTES, project_assistant_message


def notification(*, session="root", sequence=4, content=None, kind="assistant/message", interrupted=False):
    return SimpleNamespace(method="session.event", payload={"sessionId": session,
        "event": {"type": kind, "seq": sequence, "data": {"message": {"content": content or []},
        "interrupted": interrupted}}})


def test_projection_keeps_only_committed_root_public_text():
    result = project_assistant_message(notification(content=[{"type": "text", "text": "A"},
        {"type": "reasoning", "text": "private reasoning"}, {"type": "tool-call", "arguments": "private"},
        {"type": "text", "text": "B"}], interrupted=True), "root", environment={})
    assert result == {"session_id": "root", "event_sequence": 4, "text": "AB",
                      "interrupted": True, "content_status": "ACCEPTED"}
    assert project_assistant_message(notification(session="child", content=[{"type": "text", "text": "child"}]), "root") is None
    assert project_assistant_message(notification(kind="assistant/chunk"), "root") is None


@pytest.mark.parametrize("text,environment,status", [
    ("glpat-" + "a" * 20, {}, "REDACTED"),
    ("key is exact-secret", {"DEEPSEEK_API_KEY": "exact-secret"}, "REDACTED"),
    ("x" * (MAX_MESSAGE_BYTES + 1), {}, "TOO_LARGE"),
])
def test_rejected_text_never_survives_projection(text, environment, status):
    result = project_assistant_message(notification(content=[{"type": "text", "text": text}]), "root", environment=environment)
    assert result["text"] == "" and result["content_status"] == status


def test_single_reader_routes_question_and_message_and_close():
    read_fd, write_fd = os.pipe()
    emitted = queue.Queue()
    channel = driver.QuestionChannel("root", emitted.put, source=driver._PipeInput(read_fd))
    try:
        def send(value):
            os.write(write_fd, json.dumps(value).encode() + b"\n")
        send({"type": "user_message", "request_id": "message-1", "text": "Continue"})
        assert channel.commands.get(timeout=2) == {"type": "user_message", "request_id": "message-1", "text": "Continue"}
        send({"type": "close"})
        assert channel.commands.get(timeout=2) == {"type": "close"}
        assert channel.closing.is_set()
    finally:
        channel.close()
        os.close(read_fd)
        os.close(write_fd)


def fake_sdk(monkeypatch, *, events=None, resume_failure=False, restored_cwd=None):
    calls = []
    module = ModuleType("deepseek_harness")

    class Config:
        def __init__(self, **values): self.values = values

    class Subscription:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def drain(self, observe):
            while events:
                observe(events.pop(0))

    class Client:
        def __init__(self, config): self.config = config
        def __enter__(self): return self
        def __exit__(self, *args): calls.append("shutdown")
        def initialize(self, **kwargs):
            env = self.config.values["env"]
            Path(env["DSH_SDK_CORDIS_HANDSHAKE"]).write_text(json.dumps({"phase": "registered",
                "nonce": env["DSH_SDK_CORDIS_NONCE"], "root": env["DSH_SDK_CORDIS_ROOT"]}))
            return SimpleNamespace(serverInfo=SimpleNamespace(name="deepseek-harness-sdk-runtime", version="0.0.1"))
        def subscribe_notifications(self): return Subscription()
        def session_prompt(self, session, content, **kwargs):
            calls.append(("prompt", session, content[0]["text"]))
            return "message-" + str(len(calls))
        def request(self, method, *args, **kwargs): calls.append(method)
        def resume_session(self, session):
            calls.append(("resume", session))
            if resume_failure:
                raise RuntimeError("missing or already owned session")
        def get_working_directory(self, session): return restored_cwd or self.config.values["cwd"]

    module.HarnessConfig, module.HarnessClient = Config, Client
    monkeypatch.setitem(__import__("sys").modules, "deepseek_harness", module)
    monkeypatch.setattr(driver, "read_native_selection", lambda **kwargs: {"provider": "synthetic", "model": "synthetic"})
    monkeypatch.setattr("hypertest.cloud.native_cordis.prepare_cordis_overlay", lambda directory, **kwargs: directory / "overlay.yml")
    return calls


def test_persistent_runtime_delivers_new_message_once_and_drains_before_close(monkeypatch, tmp_path):
    events = [notification(content=[{"type": "text", "text": "Visible reply"}])]
    calls = fake_sdk(monkeypatch, events=events)
    commands = queue.Queue()
    channel = SimpleNamespace(commands=commands, closed=False, ask=lambda *args: {})
    emitted = []
    commands.put({"type": "user_message", "request_id": "queued-user-1", "text": "New instruction"})
    commands.put({"type": "close"})
    driver.run({"workspace": str(tmp_path), "dsh_home": str(tmp_path), "session_id": "root",
        "title": "Synthetic", "prompt": "Original", "keep_alive": True}, emitted.append, channel)
    assert calls == [("prompt", "root", "Original"), ("prompt", "root", "New instruction"), "session/wait", "shutdown"]
    assert emitted[0] == {"runtime_ready": {"session_id": "root"}}
    assert {"user_message_ack": {"request_id": "queued-user-1", "status": "DELIVERED", "message_id": "message-2"}} in emitted
    assert any(row.get("assistant_message", {}).get("text") == "Visible reply" for row in emitted)


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", ["root", "another-session"])
async def test_runtime_ready_is_bound_to_exact_session(session_id):
    import asyncio

    from hypertest.cloud.errors import CloudBlocked
    from hypertest.cloud.live_question_bridge import LiveQuestionBridge

    stream = asyncio.StreamReader()
    stream.feed_data(json.dumps({"runtime_ready": {"session_id": session_id}}).encode() + b"\n")
    stream.feed_eof()
    bridge = LiveQuestionBridge(None, None, "root")
    if session_id == "root":
        await bridge.read(SimpleNamespace(stdout=stream))
        assert bridge.runtime_ready.is_set()
    else:
        with pytest.raises(CloudBlocked) as error:
            await bridge.read(SimpleNamespace(stdout=stream))
        assert error.value.code == "SDK_RUNTIME_READY_INVALID" and not bridge.runtime_ready.is_set()


@pytest.mark.asyncio
async def test_adapter_message_pipe_failure_cannot_repeat_delivery(tmp_path):
    from hypertest.cloud.errors import CloudBlocked
    from hypertest.cloud.native_sdk_adapter import NativeSdkAdapter

    class Input:
        writes = 0
        def is_closing(self): return False
        def write(self, value): self.writes += 1
        async def drain(self): raise BrokenPipeError

    pipe = Input()
    adapter = NativeSdkAdapter(workspace=tmp_path, dsh_home=tmp_path)
    adapter.process = SimpleNamespace(returncode=None, stdin=pipe)
    with pytest.raises(CloudBlocked, match="requires reconciliation"):
        await adapter.send_message("message-1", "Continue")
    with pytest.raises(CloudBlocked, match="cannot be delivered again"):
        await adapter.send_message("message-1", "Continue")
    assert pipe.writes == 1


@pytest.mark.parametrize("send_message", [False, True])
def test_resume_restores_without_any_implicit_prompt_then_delivers_original_user_id(monkeypatch, tmp_path, send_message):
    from hypertest.cloud import native_cordis

    calls = fake_sdk(monkeypatch)
    def overlay(directory, **kwargs):
        (directory / "hypertest-cordis-root.mjs").write_text(native_cordis._HOOK)
        return directory / "overlay.yml"
    monkeypatch.setattr(native_cordis, "prepare_cordis_overlay", overlay)
    commands = queue.Queue()
    channel = SimpleNamespace(commands=commands, closed=False, ask=lambda *args: {})
    if send_message:
        commands.put({"type": "user_message", "request_id": "original-platform-user-id", "text": "User's new message"})
    commands.put({"type": "close"})
    emitted = []
    driver.run({"workspace": str(tmp_path), "dsh_home": str(tmp_path), "session_id": "original-root",
        "title": "Original title", "prompt": None, "resume": True, "keep_alive": True}, emitted.append, channel)
    assert calls == [("resume", "original-root"),
        *([("prompt", "original-root", "User's new message")] if send_message else []), "session/wait", "shutdown"]
    assert {"session_ready": {"session_id": "original-root"}} in emitted
    assert not any("prompt_enqueued" in item for item in emitted)
    if send_message:
        assert {"user_message_ack": {"request_id": "original-platform-user-id", "status": "DELIVERED", "message_id": "message-2"}} in emitted


@pytest.mark.parametrize("failure", ["owned-or-missing", "wrong-workspace"])
def test_failed_restore_never_announces_session_ready_or_sends_input(monkeypatch, tmp_path, failure):
    from hypertest.cloud import native_cordis

    calls = fake_sdk(monkeypatch, resume_failure=failure == "owned-or-missing",
                     restored_cwd=str(tmp_path.parent) if failure == "wrong-workspace" else None)
    def overlay(directory, **kwargs):
        (directory / "hypertest-cordis-root.mjs").write_text(native_cordis._HOOK)
        return directory / "overlay.yml"
    monkeypatch.setattr(native_cordis, "prepare_cordis_overlay", overlay)
    emitted = []
    with pytest.raises((RuntimeError, ValueError)):
        driver.run({"workspace": str(tmp_path), "dsh_home": str(tmp_path), "session_id": "original-root",
                    "title": "Original title", "prompt": None, "resume": True}, emitted.append)
    assert calls == [("resume", "original-root"), "shutdown"]
    assert not any("session_ready" in item or "prompt_enqueued" in item for item in emitted)


@pytest.mark.parametrize("target", ["nextTurn", "nextStep", "empty"])
def test_restored_hook_preserves_native_inbox_without_imposing_a_gate(tmp_path, target):
    from hypertest.cloud.native_cordis import _HOOK

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed for the fixed Cordis hook check")
    hook = tmp_path / "hook.mjs"
    hook.write_text(driver.restored_session_hook(_HOOK))
    script = """
import {apply} from './hook.mjs';
let callback;
const ctx = {on(name, handler) { callback = handler; }};
apply(ctx, {title:'Synthetic'});
const pending = {id:'old-inbox-message'};
const inbox = {nextTurn:[],nextStep:[],hasPending:process.env.TEST_TARGET !== 'empty'};
if (process.env.TEST_TARGET !== 'empty') inbox[process.env.TEST_TARGET].push(pending);
try { await callback({agent:{id:'root',inbox}}); console.log('accepted'); }
catch(error) { console.log(error.message); }
console.log(JSON.stringify(inbox));
"""
    env = {**os.environ, "DSH_SDK_CORDIS_ROOT": "root", "DSH_SDK_CORDIS_NONCE": "a" * 64,
           "DSH_SDK_CORDIS_HANDSHAKE": str(tmp_path / "registered.json"), "TEST_TARGET": target}
    result = subprocess.run([node, "--input-type=module", "-"], input=script, text=True, cwd=tmp_path,
                            env=env, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    outcome, state = result.stdout.splitlines()
    assert outcome == "accepted"
    if target != "empty":
        assert json.loads(state)[target] == [{"id": "old-inbox-message"}]
