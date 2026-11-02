"""Synthetic native SDK question bridge; no provider or SUT is invoked."""
import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType, SimpleNamespace

import pytest

from hypertest.cloud import sdk
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.native_sdk_driver import QuestionChannel


class Input:
    def __init__(self):
        self.lines = queue.Queue()

    def readline(self, _limit):
        return self.lines.get(timeout=5)

    def send(self, frame):
        self.lines.put(json.dumps(frame).encode() + b"\n")


@pytest.fixture
def channel(monkeypatch):
    source, emitted = Input(), queue.Queue()
    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=source))
    bridge = QuestionChannel("root-session", emitted.put)
    yield bridge, source, emitted
    source.lines.put(b"")
    bridge.reader.join(timeout=2)
    assert not bridge.reader.is_alive()


def request(**changes):
    values = {"request_id": "question-1", "session_id": "root-session",
              "questions": [{"id": "format", "question": "Choose", "options": [{"label": "CSV"}]}]}
    return SimpleNamespace(**{**values, **changes})


def test_original_sdk_question_is_answered_once_and_handed_off(channel):
    bridge, source, emitted = channel
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(bridge.ask, request(), cancel)
        event = emitted.get(timeout=2)
        assert event["user_question"]["request_id"] == "question-1"
        answer = {"answers": [{"id": "format", "selected": ["CSV"]}]}
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


def test_wrong_session_and_authorization_question_do_not_reach_operator(channel):
    bridge, _, emitted = channel
    with pytest.raises(ValueError):
        bridge.ask(request(session_id="other-session"), threading.Event())
    approval = request(questions=[{"id": "a", "question": "Allow?", "intent": {"kind": "approval"}}])
    assert bridge.ask(approval, threading.Event()) == {"cancelled": True}
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
