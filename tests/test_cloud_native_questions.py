"""Synthetic native SDK question bridge; no provider or SUT is invoked."""
import json
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from hypertest.cloud import sdk
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.native_sdk_driver import QuestionChannel, _PipeInput


class Input:
    def __init__(self):
        self.read_fd, self.write_fd = os.pipe()

    def send(self, frame):
        os.write(self.write_fd, json.dumps(frame).encode() + b"\n")

    def close(self):
        os.close(self.read_fd)
        os.close(self.write_fd)


@pytest.fixture
def channel():
    source, emitted = Input(), queue.Queue()
    bridge = QuestionChannel("root-session", emitted.put, source=_PipeInput(source.read_fd))
    try:
        yield bridge, source, emitted
    finally:
        bridge.close()
        assert not bridge.reader.is_alive()
        source.close()


@pytest.mark.parametrize("sdk_failure", [False, True])
def test_driver_exits_cleanly_while_worker_keeps_question_pipe_open(sdk_failure):
    # Exercise real interpreter finalization, without an SDK/model or business DB.
    # Closing stdin through communicate() would hide the original SIGABRT.
    script = """
import resource
import sys
import time
from hypertest.cloud import native_sdk_driver as driver
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
def no_model(config, emit, question_channel):
    time.sleep(0.1)
    if sys.argv[1] == 'fail':
        raise RuntimeError('synthetic SDK failure')
driver.run = no_model
raise SystemExit(driver.main())
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    child = subprocess.Popen([sys.executable, "-P", "-c", script, "fail" if sdk_failure else "success"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        child.stdin.write(json.dumps({"workspace": "synthetic", "dsh_home": "synthetic",
            "session_id": "synthetic", "title": "Synthetic", "prompt": "No model", "interaction_enabled": True}).encode() + b"\n")
        child.stdin.flush()
        assert child.wait(timeout=5) == (1 if sdk_failure else 0)
        assert not child.stderr.read()
        output = child.stdout.read()
        assert (b'"code":"SDK_RUN_FAILED"' in output) is sdk_failure
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        child.stdin.close()
        child.stdout.close()
        child.stderr.close()


def test_pipe_reader_preserves_coalesced_config_and_answer_frames():
    source = Input()
    try:
        os.write(source.write_fd, b'{"config":1}\n{"answer":2}\n')
        reader = _PipeInput(source.read_fd)
        assert reader.readline(1024) == b'{"config":1}\n'
        assert reader.readline(1024) == b'{"answer":2}\n'
    finally:
        source.close()


def request(**changes):
    values = {"request_id": "question-1", "session_id": "root-session",
              "questions": [{"id": "format", "question": "Choose", "options": [{"label": "CSV"}]}]}
    return SimpleNamespace(**{**values, **changes})


@pytest.mark.parametrize("approval", [False, True])
def test_original_sdk_question_is_answered_once_and_handed_off(channel, approval):
    bridge, source, emitted = channel
    cancel = threading.Event()
    original = request(questions=[{"id": "allow-once", "question": "Allow this Harness operation?",
        "intent": {"kind": "approval"}, "options": [{"label": "Allow"}, {"label": "Deny"}]}]) if approval else request()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(bridge.ask, original, cancel)
        event = emitted.get(timeout=2)
        assert event["user_question"]["request_id"] == "question-1"
        assert event["user_question"]["questions"] == original.questions
        answer = {"answers": [{"id": "allow-once", "selected": ["Allow"]}]} if approval else {"answers": [{"id": "format", "selected": ["CSV"]}]}
        source.send({"type": "question_response", "request_id": "question-1", "answer": answer})
        assert future.result(timeout=2) == answer
        assert emitted.get(timeout=2) == {"user_question_handed_off": {"request_id": "question-1"}}
        source.send({"type": "question_response", "request_id": "question-1", "answer": answer})


def test_sdk_cancellation_discards_late_answer(channel):
    bridge, source, emitted = channel
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(bridge.ask, request(), cancel)
        assert "user_question" in emitted.get(timeout=2)
        cancel.set()
        assert future.result(timeout=2) == {"cancelled": True}
        assert emitted.get(timeout=2) == {"user_question_cancelled": {"request_id": "question-1"}}
        source.send({"type": "question_response", "request_id": "question-1", "answer": {"answers": []}})
        assert emitted.empty()


def test_wrong_session_question_does_not_reach_operator(channel):
    bridge, _, emitted = channel
    with pytest.raises(ValueError):
        bridge.ask(request(session_id="other-session"), threading.Event())
    assert emitted.empty()


def test_native_pair_inspection_is_strict_and_separate_from_legacy(monkeypatch):
    native = ModuleType("deepseek_harness")
    runtime = ModuleType("deepseek_harness_runtime")

    class Config:
        def __init__(self, on_user_question=None):
            pass

    class Harness:
        def resume_session(self):
            pass

    native.HarnessConfig = native.DeepSeekHarnessConfig = Config
    native.DeepSeekHarness = Harness
    runtime.resolve_bundled_launch_args = lambda: ("/synthetic/runtime",)
    monkeypatch.setitem(__import__("sys").modules, "deepseek_harness", native)
    monkeypatch.setitem(__import__("sys").modules, "deepseek_harness_runtime", runtime)
    monkeypatch.setattr(sdk.importlib.metadata, "version", lambda _: "0.2.2a2")
    assert sdk.inspect_native_sdk()["user_questions_api_available"] is True
    monkeypatch.setattr(sdk.importlib.metadata, "version", lambda _: "0.2.1rc2")
    with pytest.raises(CloudBlocked) as failure:
        sdk.inspect_native_sdk()
    assert failure.value.code == "SDK_VERSION_MISMATCH"
