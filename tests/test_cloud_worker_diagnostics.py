"""Fixed host diagnostics retain first errors without exposing runtime data."""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from hypertest.cloud import __main__ as entry
from hypertest.cloud import worker as worker_module
from hypertest.cloud.worker import (
    CloudWorker,
    host_model_metadata,
    private_root,
    runtime_diagnostic_metadata,
)
from hypertest.cloud.worker_diagnostics import (
    attach_failure,
    exception_metadata,
    failure_code,
    failure_metadata,
)


def test_host_traceback_only_contains_fixed_repository_file_function_and_line(tmp_path):
    path = tmp_path / "private-path-canary"
    path.write_text("not a directory")
    with pytest.raises(FileExistsError) as captured:
        private_root(path)
    result = exception_metadata(captured.value)
    assert result["type"] == "FileExistsError"
    assert any(frame["file"] == "cloud/worker.py" and frame["function"] == "private_root" for frame in result["frames"])
    assert all(type(frame["line"]) is int for frame in result["frames"])
    assert "private-" not in json.dumps(result) and str(tmp_path) not in json.dumps(result)


def test_untrusted_exception_type_code_attributes_and_forged_diagnostics_are_projected():
    error = type("private-type-canary", (RuntimeError,), {})("private exception message")
    error.code = "private-code-canary"
    attach_failure(error, {"type": "private-type-canary", "message": "private",
        "frames": [{"file": "/private/path", "line": 4, "function": "private"},
            {"file": ["private"], "line": 4},
            {"file": "cloud/worker.py", "line": True, "function": "private"},
            {"file": "cloud/worker.py", "line": 12, "function": "private-function"}]},
        [{"stage": "private-stage", "error": {"message": "private"}},
            {"stage": "REPORTER_CLOSE", "error": {"type": "ValueError", "message": "private", "frames": []}}])
    assert failure_code(error) == "CLOUD_WORKER_FAILED"
    assert failure_metadata(error) == {"primary": {"type": "OTHER", "frames": [
        {"file": "cloud/worker.py", "line": 12, "function": "OTHER"}]},
        "secondary": [{"stage": "REPORTER_CLOSE", "error": {"type": "ValueError", "frames": []}}]}


def test_host_model_observation_is_scope_aggregate_counts_and_drain_without_credentials_or_raw_provider_data():
    raw = {"requests": 14, "upstream_successes": 2, "upstream_completed": 2, "inflight": 0,
        "closed": True, "drained": True, "api_key": "private-key", "url": "https://private-provider",
        "response": "private-answer"}
    broker = SimpleNamespace(observation=lambda: raw)
    observed = host_model_metadata({"ROOT": broker, "private-scope": broker}, {"local_processes_stopped": True})
    assert observed == {"source": "host-managed-model-brokers", "namespace_stopped": True,
        "scopes": [{"scope": "ROOT", "requests": 14, "upstream_successes": 2, "upstream_completed": 2,
            "inflight": 0, "refused_scope_count": None, "upstream_status_counts": {},
            "transport_failure_counts": {}, "refused_category_counts": {}, "closed": True, "drained": True}]}
    assert "private" not in json.dumps(observed)


def test_host_model_diagnostics_keep_only_bounded_fixed_status_transport_and_refusal_counts():
    raw = {"requests": 3, "upstream_successes": 0, "upstream_completed": 0, "inflight": 0,
        "closed": True, "drained": True, "refused_scope_count": 2000000,
        "upstream_status_counts": {"401": 1, "429": 2, "599": 0, "OTHER": 4,
            "200": True, "500": -1, "600": 2, "099": 3, 403: 8, "private-url": 1},
        "transport_failure_counts": {"DNS": 1, "TLS": 2000000, "TIMEOUT": 2, "CONNECT": False,
            "OTHER": "private-error", "private-exception": 1},
        "refused_category_counts": {"MESSAGE_SCHEMA": 3, "REQUEST_LIMIT": 1, "IDENTITY": 2,
            "ENDPOINT": -1, "TOKENS": True, "private-prompt": 7}, "body": "private-response"}
    observed = host_model_metadata({"CODEX": SimpleNamespace(observation=lambda: raw)}, {})
    scope = observed["scopes"][0]
    assert scope["refused_scope_count"] == 1000000
    assert scope["upstream_status_counts"] == {"401": 1, "429": 2, "599": 0, "OTHER": 4}
    assert scope["transport_failure_counts"] == {"DNS": 1, "TLS": 1000000, "TIMEOUT": 2}
    assert scope["refused_category_counts"] == {"IDENTITY": 2, "MESSAGE_SCHEMA": 3, "REQUEST_LIMIT": 1}
    assert "private" not in json.dumps(observed) and observed["namespace_stopped"] is False


@pytest.mark.parametrize("value", [None, "private-diagnostic", ["private"], True])
def test_host_model_diagnostics_do_not_persist_malformed_counter_maps(value):
    raw = {"refused_scope_count": True, "upstream_status_counts": value,
        "transport_failure_counts": value, "refused_category_counts": value}
    scope = host_model_metadata({"CODEX": SimpleNamespace(observation=lambda: raw)}, {})["scopes"][0]
    assert scope["refused_scope_count"] is None
    assert scope["upstream_status_counts"] == scope["transport_failure_counts"] == scope["refused_category_counts"] == {}
    assert "private" not in json.dumps(scope)


@pytest.mark.asyncio
async def test_worker_reprojects_live_activity_and_keeps_only_fixed_counts_and_last_64_frames():
    frames = [{"runtime_activity": {"kind": "TOOL_CALL", "tool": "BASH", "sequence": index,
        "args": "private-command-canary", "id": "private-call-id"}} for index in range(70)]
    frames.extend([
        {"runtime_activity": {"kind": "TOOL_RESULT", "is_error": "private-value", "error_code": "private-error",
            "call_sequence": ["private-sequence"], "content": "private-tool-result"}},
        {"runtime_activity": {"kind": "APPROVAL_DECIDED", "outcome": "unavailable", "text": "private-approval"}},
        {"runtime_activity": {"kind": "TURN_END", "reason": "blocked", "text": "private-answer"}},
        {"runtime_observation": "IDLE", "finish_reason": "blocked", "session_id": "private-session",
            "reported_result": "PASS"},
    ])

    class Stream:
        async def readline(self):
            return json.dumps(frames.pop(0)).encode() + b"\n" if frames else b""

    diagnostics = {}
    await CloudWorker.consume_runtime(SimpleNamespace(stdout=Stream()), diagnostics=diagnostics)
    result = runtime_diagnostic_metadata(diagnostics)
    assert result["activity_counts"] == {"TOOL_CALL": 70, "TOOL_RESULT": 1, "APPROVAL_DECIDED": 1, "TURN_END": 1}
    assert len(result["recent_activity"]) == 64 and result["recent_activity"][0]["sequence"] == 9
    assert result["recent_activity"][-3] == {"kind": "TOOL_RESULT", "is_error": None,
        "error_code": "OTHER", "call_sequence": None}
    assert result["idle_finish_reason"] == "blocked"
    assert "private" not in json.dumps(result) and "PASS" not in json.dumps(result)


def test_private_diagnostic_projection_rechecks_count_names_values_and_activity_payloads():
    source = {"activity_counts": {"TOOL_CALL": 1000001, "private-kind": 3, "STATUS": True, "STEP_START": -1},
        "recent_activity": [{"kind": "TOOL_CALL", "tool": "BASH", "sequence": index,
            "input": "private-source"} for index in range(100)], "idle_finish_reason": ["private-reason"]}
    result = runtime_diagnostic_metadata(source)
    assert result["activity_counts"] == {"TOOL_CALL": 1000000, "OTHER": 3}
    assert len(result["recent_activity"]) == 64 and result["recent_activity"][0]["sequence"] == 36
    assert result["idle_finish_reason"] == "OTHER" and "private" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected", [(value, value) for value in (
    "completed", "aborted", "blocked", "error", "max-tokens", "interrupted", "forked", "OTHER", None)] + [
        ("private finish message", "OTHER"), ({"private": "reason"}, "OTHER")])
async def test_idle_reason_uses_shared_full_enum_without_inferring_business_completion(reason, expected):
    class Stream:
        sent = False

        async def readline(self):
            if self.sent:
                return b""
            self.sent = True
            return json.dumps({"runtime_observation": "IDLE", "finish_reason": reason,
                "task_status": "COMPLETED", "reported_result": "PASS"}).encode() + b"\n"

    diagnostics = {}
    await CloudWorker.consume_runtime(SimpleNamespace(stdout=Stream()), diagnostics=diagnostics)
    assert runtime_diagnostic_metadata(diagnostics) == {
        "source": "sandbox-runtime-reported", "idle_finish_reason": expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("dispose_failure", [False, True])
async def test_worker_entry_prints_safe_first_failure_even_when_engine_dispose_also_fails(monkeypatch, capsys, dispose_failure):
    settings = SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True)
    monkeypatch.setattr(entry, "get_settings", lambda: settings)
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *_: None)

    class Worker:
        def __init__(self, *_):
            pass

        async def run_once(self):
            raise RuntimeError("private DB Git credential message")

    class Engine:
        async def dispose(self):
            if dispose_failure:
                raise ValueError("private disposal message")

    monkeypatch.setattr(worker_module, "CloudWorker", Worker)
    monkeypatch.setitem(sys.modules, "hypertest.db.session", SimpleNamespace(AsyncSessionLocal=object(), engine=Engine()))
    assert await entry.run(once=True) == 1
    output = capsys.readouterr().out
    reports = [json.loads(line) for line in output.splitlines()]
    assert all(item["code"] == "CLOUD_WORKER_FAILED" for item in reports)
    assert all(item["worker_diagnostics"]["primary"]["type"] == "RuntimeError" for item in reports)
    if dispose_failure:
        assert reports[-1]["worker_diagnostics"]["secondary"][-1]["stage"] == "ENGINE_DISPOSE"
    assert "private" not in output
