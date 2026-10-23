"""Explicit authorization, frozen intent and cleanup checks; no model calls."""

import importlib
import json
import os
from pathlib import Path

import pytest

from hypertest.cloud.errors import CloudBlocked


@pytest.fixture
def model_probe(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "ops" / "deepseek"))
    return importlib.import_module("probe_model")


def test_model_probe_requires_explicit_flag_before_identity_or_runtime(model_probe, monkeypatch, capsys):
    monkeypatch.setattr(model_probe, "run_probe", lambda **_: pytest.fail("probe started"))
    assert model_probe.main([]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "NOT_RUN", "reason": "EXPLICIT_MODEL_PROBE_FLAG_REQUIRED", "test_result": "NOT_RUN"}


def test_existing_private_intent_is_never_overwritten_or_replayed(model_probe, tmp_path):
    root = model_probe._new_private_state(tmp_path / "run")
    model_probe._write_once(root / "intent.json", {"frozen": "original"})
    with pytest.raises(CloudBlocked) as error:
        model_probe._new_private_state(root)
    assert error.value.code == "MODEL_PROBE_STATE_EXISTS"
    assert json.loads((root / "intent.json").read_text()) == {"frozen": "original"}
    assert (root / "intent.json").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("credit,endpoint,code", [
    (0, "https://api.deepseek.com/anthropic", "MODEL_PROBE_RESERVE_REQUIRED"),
    (100, "https://unapproved.invalid", "MODEL_PROBE_ENDPOINT_UNSUPPORTED"),
])
@pytest.mark.asyncio
async def test_budget_and_endpoint_reject_before_identity_or_sdk(model_probe, tmp_path, monkeypatch, credit, endpoint, code):
    monkeypatch.setattr(model_probe, "inspect_outer_profile", lambda: pytest.fail("outer admission reached"))
    monkeypatch.setattr(model_probe, "_read_private_key", lambda _: pytest.fail("identity read"))
    with pytest.raises(CloudBlocked) as error:
        await model_probe.run_probe(state_directory=tmp_path / "run", key_file=tmp_path / "key",
            base_url=endpoint, model="deepseek-flash", credit_reserve_microunits=credit, timeout_seconds=30)
    assert error.value.code == code and not (tmp_path / "run").exists()


def test_private_identity_rejects_public_file_and_symlink(model_probe, tmp_path):
    key = tmp_path / "identity"
    key.write_bytes(b"fixture-identity")
    os.chmod(key, 0o644)
    with pytest.raises(CloudBlocked):
        model_probe._read_private_key(key)
    os.chmod(key, 0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(key)
    with pytest.raises(CloudBlocked):
        model_probe._read_private_key(alias)


def test_runtime_projection_retains_no_untrusted_text(model_probe):
    output = json.dumps({"runtime_observation": "IDLE", "session_id": "untrusted-session",
        "finish_reason": "private model text", "transcript": "must not persist"}).encode()
    assert model_probe._runtime_observation(output, 0) == {"idle_observed": True, "finish_reason": "OTHER"}


def test_runtime_projection_preserves_first_sdk_error_before_later_exit_or_cleanup_frames(model_probe):
    first = {"phase": "INITIALIZE", "type": "JSON_RPC", "rpc_numeric_code": -32603}
    frames = [{"runtime_phase": "INITIALIZE"},
        {"runtime_observation": "ERROR", "sdk_error": {**first, "message": "private source text"}},
        {"runtime_phase": "CLOSE"},
        {"runtime_observation": "ERROR", "sdk_error": {"phase": "CLOSE", "type": "TIMEOUT", "rpc_numeric_code": None}},
        {"runtime_observation": "IDLE", "finish_reason": "completed", "answer": "private answer"}]
    result = model_probe._runtime_observation(b"\n".join(json.dumps(frame).encode() for frame in frames), None)
    assert result["sdk_error"] == first and result["last_phase"] == "CLOSE"
    assert result["idle_observed"] is False and "private" not in json.dumps(result)


@pytest.mark.parametrize("numeric", [True, "-32603 private", 100000, -100000, 1.5, None])
def test_sdk_error_projection_rejects_unallowlisted_values(model_probe, numeric):
    output = json.dumps({"runtime_observation": "ERROR", "sdk_error": {
        "phase": "private phase", "type": "private exception", "rpc_numeric_code": numeric},
        "message": "private message"}).encode()
    result = model_probe._runtime_observation(output, 1)
    assert result["sdk_error"] == {"phase": "OTHER", "type": "OTHER", "rpc_numeric_code": None}
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("code,retained", [("NATIVE_TOOL_UNAVAILABLE", True), ("private boundary text", False)])
def test_sdk_error_boundary_code_uses_shared_closed_allowlist(model_probe, code, retained):
    output = json.dumps({"runtime_observation": "ERROR", "sdk_error": {
        "phase": "DELEGATE_READY", "type": "CAPABILITY", "rpc_numeric_code": None,
        "boundary_code": code}}).encode()
    result = model_probe._runtime_observation(output, 1)
    assert ("boundary_code" in result["sdk_error"]) is retained
    assert "private" not in json.dumps(result)


def test_broker_diagnostics_only_publish_fixed_counts(model_probe):
    observation = {"upstream_status_counts": {"200": 1, "401": 1, "private response": 99},
        "transport_failure_counts": {"DNS": 1, "TLS": "private exception", "private cause": 99},
        "refused_category_counts": {"REQUEST_LIMIT": 6, "UNAPPROVED_EXTENSION": 1, "OTHER": 1000001,
            "MODEL": True, "MESSAGE_SCHEMA": -1, "private request body": 99},
        "refused_scope_count": 2}
    assert model_probe._broker_diagnostics(observation) == {
        "upstream_status_counts": {"200": 1, "401": 1},
        "transport_failure_counts": {"DNS": 1},
        "refused_category_counts": {"REQUEST_LIMIT": 6, "UNAPPROVED_EXTENSION": 1, "OTHER": 1000000},
        "refused_scope_count": 2}


@pytest.mark.parametrize("scenario", ["success", "turn_error", "sdk_error_exit_timeout", "exit_timeout"])
@pytest.mark.asyncio
async def test_probe_intent_precedes_key_and_runtime_stop_precedes_broker_drain(model_probe, tmp_path, monkeypatch, scenario):
    module = model_probe
    state = tmp_path / "run"
    order = []
    monkeypatch.setattr(module, "inspect_outer_profile", lambda: {"uid": 65534})
    monkeypatch.setattr(module, "inspect_sdk", lambda: {"sdk_version": "0.2.1rc2", "runtime_version": "0.2.1rc2"})

    def key_reader(_):
        intent = json.loads((state / "intent.json").read_text())
        assert intent["declared_credit_reserve_microunits"] == 100
        assert intent["max_model_requests"] == 2 and intent["automatic_replay"] is False
        order.append("identity-read")
        return b"fixture-private-identity"

    monkeypatch.setattr(module, "_read_private_key", key_reader)

    class Broker:
        def __init__(self, _, **kwargs):
            assert kwargs["max_requests"] == 2 and kwargs["max_tokens"] == 1024
            assert kwargs["api_key"] == b"fixture-private-identity"

        def __enter__(self):
            order.append("broker-start")
            return self

        def __exit__(self, *_):
            assert order[-1] == "runtime-stop"
            order.append("broker-drain")

        def observation(self):
            return {"requests": 2, "upstream_successes": 2, "upstream_completed": 2,
                "drained": True, "closed": True, "inflight": 0}

    class Output:
        reads = 0

        async def read(self, _):
            self.reads += 1
            if self.reads == 1:
                return b'{"runtime_phase":"CONFIGURATION"}\n'
            if self.reads > 2:
                return b""
            if scenario == "sdk_error_exit_timeout":
                return b'{"runtime_observation":"ERROR","sdk_error":{"phase":"PROMPT_ENQUEUE","type":"JSON_RPC","rpc_numeric_code":-32000}}\n'
            if scenario == "turn_error":
                return b'{"runtime_observation":"IDLE","finish_reason":"error"}\n'
            return b'{"runtime_observation":"IDLE","finish_reason":"completed"}\n'

    class Process:
        stdout = Output()
        returncode = 0 if scenario in {"success", "turn_error"} else None

        async def wait(self):
            if scenario not in {"success", "turn_error"}:
                raise TimeoutError("private secondary exit failure")
            return 0

    class Sandbox:
        def __init__(self, **kwargs):
            assert kwargs["policy"].max_model_requests == 2

        async def start(self, config):
            assert config["prompt"] == module.PROMPT and "api_key" not in config and "delegation" not in config
            assert "fixture-private-identity" not in json.dumps(config)
            (state / "workspace" / module.MARKER_PATH).write_bytes(module.MARKER_CONTENT)
            order.append("runtime-start")
            return Process()

        async def stop(self):
            order.append("runtime-stop")
            return {"local_processes_stopped": True}

    monkeypatch.setattr(module, "ModelBroker", Broker)
    monkeypatch.setattr(module, "BubblewrapSandbox", Sandbox)
    result = await module.run_probe(state_directory=state, key_file=tmp_path / "key",
        base_url="https://api.deepseek.com/anthropic", model="deepseek-flash",
        credit_reserve_microunits=100, timeout_seconds=30)
    assert order == ["identity-read", "broker-start", "runtime-start", "runtime-stop", "broker-drain"]
    assert result["reservation_release_eligible"] is True
    if scenario in {"success", "turn_error"}:
        assert result["status"] == "OBSERVED" and result["process_exit_unobserved"] is False
        assert result["model_http_success"] is True and result["marker_correct"] is True
        assert result["sdk_turn_succeeded"] is (scenario == "success")
    elif scenario == "sdk_error_exit_timeout":
        assert result["status"] == "BLOCKED" and result["reason"] == "MODEL_PROBE_SDK_ERROR"
        assert result["runtime"]["sdk_error"] == {"phase": "PROMPT_ENQUEUE", "type": "JSON_RPC", "rpc_numeric_code": -32000}
        assert result["process_exit_unobserved"] is True
    else:
        assert result["status"] == "BLOCKED" and result["reason"] == "MODEL_PROBE_PROCESS_EXIT_UNOBSERVED"
        assert result["process_exit_unobserved"] is True
    assert result["test_result"] == "NOT_RUN" and result["platform_task_created"] is False
    assert "fixture-private-identity" not in (state / "intent.json").read_text()
    assert "fixture-private-identity" not in (state / "observation.json").read_text()
