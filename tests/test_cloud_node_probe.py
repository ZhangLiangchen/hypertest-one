"""Pinned Node namespace diagnostics using inert subprocesses, never models."""

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

from hypertest.cloud.errors import CloudBlocked


@pytest.fixture
def node_probe(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "ops" / "deepseek"))
    return importlib.import_module("probe_node_profile")


def node_metadata():
    return {"node_started": True, "node_version": "22.22.0", "passwd_present": False,
        "user_info_available": False, "user_info_code": "ERR_SYSTEM_ERROR", "shell_present": False}


def test_node_probe_requires_explicit_flag_before_payload_or_process(node_probe, monkeypatch, capsys):
    monkeypatch.setattr(node_probe, "probe", lambda *a, **k: pytest.fail("probe started"))
    assert node_probe.main(["--payload", "/fixture", "--manifest-sha256", "0" * 64]) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "NOT_RUN",
        "code": "EXPLICIT_NODE_PROFILE_PROBE_REQUIRED", "model_started": False}


def test_node_projection_drops_user_information_and_arbitrary_error_details(node_probe):
    value = {**node_metadata(), "username": "private-user", "homedir": "/private/home", "message": "private-error"}
    projected = node_probe.project_node_metadata(json.dumps(value).encode())
    assert projected == node_metadata() and "private" not in json.dumps(projected)
    for change in ({"node_version": "private-version"}, {"node_version": "24.0.0"},
            {"user_info_code": "private-code"}, {"shell_present": "private-shell"}):
        with pytest.raises(CloudBlocked) as caught:
            node_probe.project_node_metadata(json.dumps({**node_metadata(), **change}).encode())
        assert caught.value.code == "NODE_METADATA_INVALID"


async def test_node_reader_waits_for_all_chunks_and_enforces_bound(node_probe):
    class Stream:
        def __init__(self, chunks):
            self.chunks = iter(chunks)

        async def read(self, _):
            return next(self.chunks, b"")

    assert await node_probe.read_node_output(Stream([b'{"node_', b'started":true}', b"\n"])) == b'{"node_started":true}\n'
    with pytest.raises(CloudBlocked):
        await node_probe.read_node_output(Stream([b"x" * 4097]))


async def test_node_uses_unchanged_namespace_limits_and_fixed_script_then_stops(node_probe, tmp_path, monkeypatch):
    order, captured = [], {}
    monkeypatch.setattr(node_probe, "inspect_outer_profile", lambda: order.append("outer-admission"))
    monkeypatch.setattr(node_probe, "verify_payload", lambda *a: order.append("payload-verification"))

    class Stream:
        def __init__(self):
            output = json.dumps(node_metadata()).encode()
            self.chunks = iter([output[:20], output[20:]])

        async def read(self, _):
            return next(self.chunks, b"")

    class Process:
        returncode = None
        stdout = Stream()

        async def wait(self):
            self.returncode = 0
            return 0

    class Sandbox:
        def __init__(self, **kwargs):
            captured["sandbox"] = kwargs
            self.process = None

        def command(self):
            return ["fixture-bwrap", "--unshare-all", "--clearenv", sys.executable, "-m", "hypertest.cloud.sdk_driver"]

        async def stop(self):
            order.append("namespace-stop")
            return {"local_processes_stopped": True, "runtime_started": True}

    async def subprocess(*args, **kwargs):
        order.append("node-start")
        captured["args"], captured["subprocess"] = args, kwargs
        return Process()

    monkeypatch.setattr(node_probe, "BubblewrapSandbox", Sandbox)
    monkeypatch.setattr(node_probe.asyncio, "create_subprocess_exec", subprocess)
    result = await node_probe.probe(tmp_path, "0" * 64, timeout_seconds=5)
    assert order == ["outer-admission", "payload-verification", "node-start", "namespace-stop"]
    assert captured["args"][-4:] == ("/opt/hypertest-delegates/bin/node", "--input-type=module", "-e", node_probe.SCRIPT)
    policy = captured["sandbox"]["policy"]
    assert policy.memory_bytes == 4 * 1024**3 and policy.aggregate_memory_bytes == 2 * 1024**3
    assert policy.aggregate_processes == 256
    assert captured["subprocess"]["env"] == {"PATH": os.defpath}
    assert captured["subprocess"]["start_new_session"] is True
    assert callable(captured["subprocess"]["preexec_fn"])
    assert result["status"] == "OBSERVED" and result["node"] == node_metadata()
    assert result["sdk_started"] is False and result["model_started"] is False and result["codex_started"] is False
    assert not captured["sandbox"]["workspace"].parent.exists()
