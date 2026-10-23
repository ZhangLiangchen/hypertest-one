"""Explicit keyless tool probe contracts; inert SDK/process fixtures only."""
import asyncio
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hypertest.cloud import sdk_driver, tool_probe
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.tool_probe import PROBE_PROFILE, project_tool_probe

OPS = Path(__file__).resolve().parents[1] / "ops" / "deepseek"


def load_probe(monkeypatch):
    monkeypatch.syspath_prepend(str(OPS))
    spec = importlib.util.spec_from_file_location("test_sdk_tool_probe_ops", OPS / "probe_sdk_tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observation(**changes):
    return {"profile": PROBE_PROFILE, "tool_registered": True, "executed": True,
        "is_error": False, "marker_match": True, "error_code": "NONE",
        "sandbox_mode": "workspace-write", "approval_policy": "ask", **changes}


def terminal(**changes):
    return {"runtime_observation": "TOOL_PROBE_OBSERVED", "initialized": True,
        "session_created": True, "runtime_closed": True, "model_prompt_sent": False,
        "tool_probe": observation(), **changes}


def test_cli_without_explicit_flag_never_starts_a_probe(monkeypatch, capsys):
    module = load_probe(monkeypatch)

    async def forbidden(**kwargs):
        raise AssertionError("must not run")

    monkeypatch.setattr(module, "probe", forbidden)
    assert module.main([]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "EXPLICIT_SDK_TOOL_PROBE_REQUIRED"


@pytest.mark.parametrize("changes", [{"prompt": "private"}, {"resume": False}, {"patches": []},
    {"native_delegation": {}}, {"workspace": "/private"}, {"session_id": "private"}])
def test_probe_never_accepts_prompt_resume_user_patch_or_other_workspace(changes):
    config = {"mode": "SDK_TOOL_PROBE", "workspace": "/workspace", "dsh_home": "/home/agent/dsh",
        "session_id": "tool-probe-" + "a" * 32, **changes}
    with pytest.raises(CloudBlocked) as captured:
        tool_probe.write_tool_probe_configuration(config)
    assert captured.value.code == "TOOL_PROBE_CONFIGURATION_INVALID"


def test_metadata_cannot_carry_an_arbitrary_result_or_forged_success():
    assert project_tool_probe(observation()) == observation()
    for document in (observation(output="private"), observation(error_code="private"),
            observation(is_error=True), observation(executed=False), observation(sandbox_mode=["private"])):
        with pytest.raises(CloudBlocked):
            project_tool_probe(document)


def test_probe_driver_uses_no_prompt_constructor_and_no_broker(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"mode": "SDK_TOOL_PROBE", "workspace": "/workspace"})))
    monkeypatch.setattr(tool_probe, "write_tool_probe_configuration", lambda config: tmp_path / "fixed.patch.json")
    monkeypatch.setattr(tool_probe, "read_tool_probe", lambda workspace: observation())
    calls = []

    def protocol(config, *, on_phase):
        calls.append(dict(config))
        assert "prompt" not in config and config["patches"] == (str(tmp_path / "fixed.patch.json"),)
        return terminal()

    def forbidden(*args, **kwargs):
        raise AssertionError("model path must not run")

    monkeypatch.setattr(sdk_driver, "probe_official_sdk", protocol)
    monkeypatch.setattr(sdk_driver, "run_official_sdk", forbidden)
    monkeypatch.setattr(sdk_driver, "start_sandbox_relay", forbidden)
    assert sdk_driver.main() == 0 and len(calls) == 1
    assert json.loads(capsys.readouterr().out)["tool_probe"] == observation()


def test_ops_parser_preserves_fixed_sandbox_failure_and_first_sdk_error(monkeypatch):
    module = load_probe(monkeypatch)
    failure = observation(is_error=True, marker_match=False, error_code="SANDBOX_UNAVAILABLE")
    raw = json.dumps(terminal(tool_probe=failure)).encode()
    assert module.runtime_observation(raw)["tool_probe"] == failure
    frames = [{"runtime_phase": "SESSION_CREATE"}, {"runtime_observation": "ERROR", "sdk_error": {
        "phase": "SESSION_CREATE", "type": "JSON_RPC", "rpc_numeric_code": -32603, "message": "private"}},
        {"runtime_phase": "CLOSE"}]
    result = module.runtime_observation(b"\n".join(json.dumps(frame).encode() for frame in frames))
    assert result == {"sdk_error": {"phase": "SESSION_CREATE", "type": "JSON_RPC", "rpc_numeric_code": -32603}, "last_phase": "CLOSE"}
    assert "private" not in json.dumps(result)


def test_ops_parser_requires_one_closed_no_prompt_terminal(monkeypatch):
    module = load_probe(monkeypatch)
    for frames in ([terminal(model_prompt_sent=True)], [terminal(runtime_closed=False)], [terminal(), terminal()]):
        with pytest.raises(CloudBlocked):
            module.runtime_observation(b"\n".join(json.dumps(frame).encode() for frame in frames))


def test_official_plugin_uses_real_agent_public_tool_and_preserves_the_default_policy():
    source = Path(tool_probe.__file__).with_name("sdk_tool_probe.mjs").read_text()
    assert "ctx.on('agent/created'" in source and "ctx.tools.execute({ agent," in source
    assert "name: 'bash'" in source and "printf '%s\\\\n'" in source
    assert "session.append" not in source and "danger-full-access', approval" not in source
    assert "session_prompt" not in source and "process.env" not in source


@pytest.mark.parametrize("available", [True, False])
async def test_keyless_probe_keeps_production_policy_and_reports_tool_failure_without_model(monkeypatch, available):
    module = load_probe(monkeypatch)
    monkeypatch.setattr(module, "inspect_outer_profile", lambda: {})
    captured = {}
    metadata = observation() if available else observation(is_error=True, marker_match=False, error_code="SANDBOX_UNAVAILABLE")

    class Sandbox:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            assert sorted(path.name for path in kwargs["workspace"].iterdir()) == ["framework", "sut"]
            assert not list(kwargs["dsh_home"].iterdir())

        async def start(self, config):
            captured["config"] = config
            assert set(config) == {"mode", "workspace", "dsh_home", "session_id", "model", "max_tokens", "timeout_seconds"}
            stream = asyncio.StreamReader()
            stream.feed_data(json.dumps(terminal(tool_probe=metadata)).encode() + b"\n")
            stream.feed_eof()

            async def wait():
                return 0

            return SimpleNamespace(stdout=stream, returncode=0, wait=wait)

        async def stop(self):
            return {"local_processes_stopped": True, "runtime_started": True}

    monkeypatch.setattr(module, "BubblewrapSandbox", Sandbox)
    result = await module.probe(timeout_seconds=30)
    assert result["status"] == ("OBSERVED" if available else "BLOCKED")
    assert result["runtime"]["tool_probe"] == metadata
    assert result["model_prompt_sent"] is result["model_identity_read"] is result["broker_started"] is False
    assert captured["policy"].memory_bytes == 4 * 1024**3 and captured["policy"].aggregate_memory_bytes == 2 * 1024**3
    assert captured["policy"].aggregate_processes == 256 and captured["config"]["mode"] == "SDK_TOOL_PROBE"
