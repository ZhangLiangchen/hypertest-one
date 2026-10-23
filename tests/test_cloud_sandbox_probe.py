"""No-prompt production diagnostic dispatch and the exact shared SDK contract."""

import importlib
import io
import json
import os
import socket
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hypertest.cloud import sandbox as sandbox_module
from hypertest.cloud import sdk, sdk_driver
from hypertest.cloud.errors import CloudBlocked


def test_probe_rejects_prompt_before_sdk_import_or_process(monkeypatch):
    monkeypatch.setattr(sdk, "inspect_sdk", lambda: pytest.fail("SDK inspected"))
    for config in ({"prompt": "must-not-send"}, {"resume": True}):
        with pytest.raises(CloudBlocked) as error:
            sdk.probe_official_sdk(config)
        assert error.value.code == "PROBE_PROMPT_FORBIDDEN"


def test_protocol_mode_never_starts_model_relay_or_run(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"mode":"PROTOCOL_PROBE"}'))
    monkeypatch.setattr(sdk_driver, "start_sandbox_relay", lambda *_: pytest.fail("relay started"))
    monkeypatch.setattr(sdk_driver, "run_official_sdk", lambda *a, **k: pytest.fail("prompt path entered"))
    monkeypatch.setattr(sdk_driver, "probe_official_sdk", lambda _, **kwargs: {"model_prompt_sent": False})
    assert sdk_driver.main() == 0
    assert json.loads(capsys.readouterr().out) == {"model_prompt_sent": False}


def test_probe_shared_constructor_initializes_directory_and_closes_without_prompt(monkeypatch):
    calls = []

    class Client:
        def start(self):
            calls.append("start")

        def initialize(self, **kwargs):
            calls.append("initialize")
            return SimpleNamespace(serverInfo=SimpleNamespace(
                name="deepseek-harness-sdk-runtime", version="0.0.1"))

        def get_working_directory(self, session_id):
            calls.append("working-directory/get")
            return "/workspace"

        def close(self):
            calls.append("close")

        def session_prompt(self, *args, **kwargs):
            pytest.fail("prompt sent")

    monkeypatch.setattr(sdk, "inspect_sdk", lambda: {})
    monkeypatch.setattr(sdk, "_official_client", lambda _: Client())
    observed = sdk.probe_official_sdk({"workspace": "/workspace", "dsh_home": "/home/agent/dsh",
        "session_id": "probe", "model": "deepseek-flash", "max_tokens": 1024,
        "timeout_seconds": 10})
    assert calls == ["start", "initialize", "working-directory/get", "close"]
    assert observed["model_prompt_sent"] is False and observed["test_result"] == "NOT_RUN"


def test_empty_root_preserves_standard_readonly_shell_and_interpreter_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(sandbox_module, "inspect_resource_envelope", lambda **_: {})
    monkeypatch.setattr(sandbox_module.sys, "prefix", "/usr")
    standard_paths = {"/bin", "/sbin", "/lib", "/lib64"}
    monkeypatch.setattr(sandbox_module.Path, "exists", lambda self: str(self) in standard_paths)
    sandbox = sandbox_module.BubblewrapSandbox(workspace=tmp_path / "workspace",
        dsh_home=tmp_path / "home", broker_socket=tmp_path / "model.sock",
        policy=sandbox_module.SandboxPolicy(30, 1, 1024))
    command = sandbox.command()
    assert any(command[i:i + 3] == ["--setenv", "SHELL", "/bin/sh"] for i in range(len(command) - 2))
    assert "/etc" not in command and "/etc/passwd" not in command
    for path in standard_paths:
        assert any(command[i:i + 3] == ["--ro-bind", path, path] for i in range(len(command) - 2))
        assert not any(command[i:i + 3] == ["--bind", path, path] for i in range(len(command) - 2))


@pytest.mark.parametrize("condition", ["missing", "unmounted", "not_executable", "writable", "setuid"])
def test_sdk_shell_admission_requires_executable_readonly_tools(monkeypatch, condition):
    original_resolve = sandbox_module.Path.resolve
    original_stat = sandbox_module.Path.stat

    def resolve(self, *args, **kwargs):
        if str(self) != "/bin/sh":
            return original_resolve(self, *args, **kwargs)
        if condition == "missing":
            raise FileNotFoundError("private host path")
        return Path("/tmp/private-shell" if condition == "unmounted" else "/usr/bin/fixture-shell")

    def shell_stat(self, *args, **kwargs):
        if str(self) not in {"/tmp/private-shell", "/usr/bin/fixture-shell"}:
            return original_stat(self, *args, **kwargs)
        mode = 0o777 if condition == "writable" else 0o4755 if condition == "setuid" else 0o755
        return SimpleNamespace(st_mode=stat.S_IFREG | mode)

    monkeypatch.setattr(sandbox_module.Path, "resolve", resolve)
    monkeypatch.setattr(sandbox_module.Path, "stat", shell_stat)
    monkeypatch.setattr(sandbox_module.os, "access", lambda *_: condition != "not_executable")
    with pytest.raises(CloudBlocked) as error:
        sandbox_module.require_readonly_shell()
    assert error.value.code == "SHELL_UNAVAILABLE" and "private" not in str(error.value)


@pytest.fixture
def host_profile_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "ops" / "deepseek"))
    return importlib.import_module("probe_host_profile")


@pytest.fixture
def protocol_probe_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "ops" / "deepseek"))
    return importlib.import_module("probe_cloud_sandbox")


def test_protocol_parser_accepts_phase_lines_and_one_complete_terminal(protocol_probe_module):
    frames = [{"runtime_phase": "SDK_START"}, {"runtime_phase": "INITIALIZE"},
        {"runtime_phase": "CLOSE"}, {"runtime_observation": "PROTOCOL_OBSERVED",
         "model_prompt_sent": False, "initialized": True, "session_created": True, "runtime_closed": True}]
    result = protocol_probe_module._protocol_observation(b"\n".join(json.dumps(frame).encode() for frame in frames))
    assert result == {"protocol_observed": True, "last_phase": "CLOSE"}


def test_protocol_parser_preserves_first_error_without_native_error_text(protocol_probe_module):
    first = {"phase": "SESSION_CREATE", "type": "JSON_RPC", "rpc_numeric_code": -32000}
    frames = [{"runtime_phase": "SESSION_CREATE"},
        {"runtime_observation": "ERROR", "sdk_error": {**first, "message": "private error"}},
        {"runtime_phase": "CLOSE"},
        {"runtime_observation": "ERROR", "sdk_error": {"phase": "CLOSE", "type": "TIMEOUT"}},
        {"runtime_observation": "PROTOCOL_OBSERVED", "model_prompt_sent": False,
         "initialized": True, "session_created": True, "runtime_closed": True}]
    result = protocol_probe_module._protocol_observation(b"\n".join(json.dumps(frame).encode() for frame in frames))
    assert result["protocol_observed"] is False and result["sdk_error"] == first
    assert result["last_phase"] == "CLOSE" and "private" not in json.dumps(result)


@pytest.mark.parametrize("sdk_error", [False, True])
@pytest.mark.asyncio
async def test_bounded_reader_waits_past_first_flushed_phase(protocol_probe_module, sdk_error):
    terminal = ({"runtime_observation": "ERROR", "sdk_error": {"phase": "INITIALIZE", "type": "JSON_RPC", "rpc_numeric_code": -32000}}
        if sdk_error else {"runtime_observation": "PROTOCOL_OBSERVED", "model_prompt_sent": False,
            "initialized": True, "session_created": True, "runtime_closed": True})
    encoded = json.dumps(terminal).encode() + b"\n"
    chunks = [b'{"runtime_phase":"CONFIGURATION"}\n', encoded[:12], encoded[12:], b""]

    class Output:
        async def read(self, maximum):
            chunk = chunks.pop(0)
            assert len(chunk) <= maximum
            return chunk

    collected = bytearray()
    output = await protocol_probe_module.read_metadata_output(Output(), collected)
    assert output == bytes(collected) and encoded in output
    result = protocol_probe_module._protocol_observation(output)
    assert result["protocol_observed"] is not sdk_error
    assert len(chunks) == (1 if sdk_error else 0)


@pytest.mark.asyncio
async def test_bounded_reader_rejects_oversize_metadata(protocol_probe_module):
    class Output:
        async def read(self, maximum):
            return b"x" * maximum

    with pytest.raises(CloudBlocked) as error:
        await protocol_probe_module.read_metadata_output(Output(), bytearray())
    assert error.value.code == "RUNTIME_OBSERVATION_LIMIT"


@pytest.mark.parametrize("error_exit_timeout", [False, True])
@pytest.mark.asyncio
async def test_protocol_probe_reads_multiline_metadata_before_wait_and_always_stops_namespace(protocol_probe_module, monkeypatch, error_exit_timeout):
    module = protocol_probe_module
    order = []
    first = {"phase": "SESSION_CREATE", "type": "JSON_RPC", "rpc_numeric_code": -32000}
    terminal = ({"runtime_observation": "ERROR", "sdk_error": first} if error_exit_timeout else
        {"runtime_observation": "PROTOCOL_OBSERVED", "model_prompt_sent": False,
         "initialized": True, "session_created": True, "runtime_closed": True})

    class Output:
        sent = False

        async def read(self, _):
            if self.sent:
                return b""
            self.sent = True
            order.append("read")
            return b'{"runtime_phase":"INITIALIZE"}\n' + json.dumps(terminal).encode() + b"\n"

    class Process:
        stdout = Output()
        returncode = None if error_exit_timeout else 0

        async def wait(self):
            order.append("wait")
            if error_exit_timeout:
                raise TimeoutError("private secondary exit failure")
            return 0

    class Sandbox:
        def __init__(self, **kwargs):
            pass

        async def start(self, config):
            assert config["mode"] == "PROTOCOL_PROBE" and "prompt" not in config and "resume" not in config
            return Process()

        async def stop(self):
            order.append("stop")
            return {"local_processes_stopped": True}

    monkeypatch.setattr(module, "BubblewrapSandbox", Sandbox)
    result = await module.probe(backend="sandbox", address_space_gib=4, timeout=10)
    assert order == ["read", "wait", "stop"] and result["runtime_closed"] is True
    if error_exit_timeout:
        assert result["status"] == "BLOCKED" and result["runtime"]["sdk_error"] == first
        assert result["reason"] == "SDK_PROTOCOL_INITIALIZATION_FAILED" and result["process_exit_unobserved"] is True
    else:
        assert result["status"] == "OBSERVED" and result["production_namespace_proven"] is True
    assert "private" not in json.dumps(result)


@pytest.fixture
def safe_outer_profile(monkeypatch, host_profile_module):
    module = host_profile_module
    # Isolate this module's OS/environment view. pytest updates its own process
    # environment during a test, which must not change this admission fixture.
    monkeypatch.setattr(module, "os", SimpleNamespace(**vars(os)))
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "getuid", lambda: 65534)
    monkeypatch.setattr(module.os, "geteuid", lambda: 65534)
    monkeypatch.setattr(module.os, "getgid", lambda: 65534)
    monkeypatch.setattr(module.os, "getegid", lambda: 65534)
    monkeypatch.setattr(module.os, "environ", {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"})
    status = "NoNewPrivs:\t1\n" + "".join(f"{name}:\t0000000000000000\n" for name in module._CAPABILITIES)
    original_open = module.Path.open
    monkeypatch.setattr(module.Path, "open", lambda self, *a, **kw:
        io.StringIO(status) if str(self) == "/proc/self/status" else original_open(self, *a, **kw))
    original_stat = module.Path.stat

    def temporary_stat(self, *args, **kwargs):
        actual = original_stat(self, *args, **kwargs)
        if str(self) != "/tmp":
            return actual
        fields = list(actual)
        fields[0], fields[4] = stat.S_IFDIR | 0o1777, 0
        return os.stat_result(fields)

    monkeypatch.setattr(module.Path, "stat", temporary_stat)
    monkeypatch.setattr(module.os, "access", lambda *_: True)
    monkeypatch.setattr(module.os, "statvfs", lambda path: SimpleNamespace(
        f_flag=os.ST_NOSUID | os.ST_NODEV if path == "/tmp" else os.ST_RDONLY))
    monkeypatch.setattr(module, "inspect_resource_envelope", lambda: {
        "kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024 ** 3, "swap_max_bytes": 0, "pids_max": 256})
    return module


def test_dedicated_outer_profile_checks_effective_identity_mounts_and_resources(safe_outer_profile):
    observed = safe_outer_profile.inspect_outer_profile()
    assert observed["uid"] == 65534 and observed["capabilities_empty"] is True
    assert observed["root_readonly"] is True and observed["cgroup_readonly"] is True
    assert observed["resource_envelope"]["memory_max_bytes"] == 2 * 1024 ** 3


@pytest.mark.parametrize("condition,code", [
    ("root", "OUTER_PROFILE_IDENTITY_UNSAFE"),
    ("credential_environment", "OUTER_PROFILE_ENVIRONMENT_UNSAFE"),
    ("root_writable", "OUTER_PROFILE_ROOT_WRITABLE"),
    ("temporary_unwritable", "OUTER_PROFILE_TMP_UNWRITABLE"),
    ("temporary_noexec", "OUTER_PROFILE_TMP_FLAGS_UNSAFE"),
])
def test_outer_profile_rejects_unsafe_effective_configuration(safe_outer_profile, monkeypatch, condition, code):
    module = safe_outer_profile
    if condition == "root":
        monkeypatch.setattr(module.os, "getuid", lambda: 0)
    elif condition == "credential_environment":
        monkeypatch.setattr(module.os, "environ", {"MODEL_API_KEY": "do-not-print"})
    elif condition == "root_writable":
        monkeypatch.setattr(module.os, "statvfs", lambda _: SimpleNamespace(f_flag=0))
    elif condition == "temporary_unwritable":
        original_stat = module.Path.stat

        def unwritable_temporary_stat(self, *args, **kwargs):
            actual = original_stat(self, *args, **kwargs)
            if str(self) != "/tmp":
                return actual
            fields = list(actual)
            fields[0], fields[4] = stat.S_IFDIR | 0o755, 0
            return os.stat_result(fields)

        monkeypatch.setattr(module.Path, "stat", unwritable_temporary_stat)
    elif condition == "temporary_noexec":
        monkeypatch.setattr(module.os, "statvfs", lambda path: SimpleNamespace(
            f_flag=os.ST_NOEXEC | os.ST_NOSUID | os.ST_NODEV if path == "/tmp" else os.ST_RDONLY))
    with pytest.raises(CloudBlocked) as error:
        module.inspect_outer_profile()
    assert error.value.code == code and "do-not-print" not in str(error.value)


@pytest.mark.asyncio
async def test_outer_guard_blocks_before_runtime_and_never_prints_native_error(host_profile_module, monkeypatch):
    module = host_profile_module
    monkeypatch.setattr(module, "inspect_outer_profile", lambda: (_ for _ in ()).throw(RuntimeError("private diagnostic")))
    monkeypatch.setattr(module, "probe", lambda **_: pytest.fail("runtime started before admission"))
    result = await module.run_probe(timeout_seconds=10)
    assert result["reason"] == "OUTER_PROFILE_OBSERVATION_FAILED"
    assert result["runtime_started"] is False and "private diagnostic" not in json.dumps(result)


@pytest.mark.asyncio
async def test_outer_probe_uses_production_namespace_without_prompt_or_fallback(host_profile_module, monkeypatch):
    module = host_profile_module
    calls = []
    monkeypatch.setattr(module, "inspect_outer_profile", lambda: {"uid": 65534})

    async def namespace_probe(**kwargs):
        calls.append(kwargs)
        return {"status": "OBSERVED", "runtime_closed": True, "model_prompt_sent": False,
            "production_namespace_proven": True, "test_result": "NOT_RUN"}

    monkeypatch.setattr(module, "probe", namespace_probe)
    result = await module.run_probe(timeout_seconds=10)
    assert calls == [{"backend": "sandbox", "address_space_gib": 4, "timeout": 10}]
    assert result["model_prompt_sent"] is False and result["test_result"] == "NOT_RUN"


def test_verified_delegation_payload_and_brokers_are_mounted_readonly(tmp_path):
    payload = tmp_path / "delegates"
    payload.mkdir()
    sockets = []
    try:
        paths = {}
        for name in ("codex", "claude-code"):
            channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sockets.append(channel)
            paths[name] = tmp_path / (name + ".sock")
            channel.bind(str(paths[name]))
        sandbox = sandbox_module.BubblewrapSandbox(workspace=tmp_path / "workspace",
            dsh_home=tmp_path / "home", broker_socket=tmp_path / "model.sock",
            policy=sandbox_module.SandboxPolicy(30, 1, 1024),
            delegate_payload=payload, delegate_sockets=paths)
        mounts = sandbox.delegate_mounts()
        assert mounts[:5] == ["--dir", "/opt", "--ro-bind", str(payload), "/opt/hypertest-delegates"]
        for name, path in paths.items():
            assert any(mounts[i:i + 3] == ["--ro-bind", str(path), f"/run/{name}.sock"] for i in range(len(mounts) - 2))
        assert "--bind" not in mounts
    finally:
        for channel in sockets:
            channel.close()


@pytest.mark.parametrize("condition", ["unknown_broker", "payload_symlink", "socket_regular_file", "socket_without_payload"])
def test_invalid_delegation_mounts_fail_closed(tmp_path, condition):
    payload = tmp_path / "delegates"
    payload.mkdir()
    sockets = {}
    if condition == "payload_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(payload, target_is_directory=True)
        payload = alias
    elif condition == "socket_regular_file":
        path = tmp_path / "codex.sock"
        path.write_text("not a socket")
        sockets = {"codex": path}
    elif condition == "unknown_broker":
        sockets = {"arbitrary/path": tmp_path / "untrusted.sock"}
    elif condition == "socket_without_payload":
        payload = None
        sockets = {"codex": tmp_path / "untrusted.sock"}
    sandbox = sandbox_module.BubblewrapSandbox(workspace=tmp_path / "workspace",
        dsh_home=tmp_path / "home", broker_socket=tmp_path / "model.sock",
        policy=sandbox_module.SandboxPolicy(30, 1, 1024),
        delegate_payload=payload, delegate_sockets=sockets)
    with pytest.raises(CloudBlocked) as error:
        sandbox.delegate_mounts()
    assert error.value.code == "DELEGATE_MOUNT_INVALID"
