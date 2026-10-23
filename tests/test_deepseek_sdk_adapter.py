"""No-model SDK contracts. Run in isolation; never invoke a real dsh in these tests."""

from __future__ import annotations

import importlib.metadata
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hypertest.deepseek_harness import (
    SDK_VERSION,
    AdapterError,
    DependencyError,
    SdkCompatibility,
    compatibility,
    inspect_compatibility,
    probe,
    probe_protocol,
)
from hypertest.deepseek_harness._worker import SdkDriver
from hypertest.deepseek_harness._worker import main as worker_main
from hypertest.deepseek_harness.models import SERVER_NAME, SERVER_VERSION, StopObservation
from hypertest.deepseek_harness.supervisor import ProcessSupervisor, clean_environment


def test_metadata_only_inspection_without_sdk(monkeypatch):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(compatibility.metadata, "version", missing)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("doctor spawned a process"))
    report = inspect_compatibility()
    assert report.as_public_dict() == {
        "sdk_installed": False, "runtime_installed": False, "sdk_version": None,
        "runtime_version": None, "versions_match": False, "pinned_version": SDK_VERSION,
        "compatible": False, "issues": ["SDK_NOT_INSTALLED", "RUNTIME_NOT_INSTALLED"],
    }


def test_version_pair_is_exact_not_semver_compatible(monkeypatch):
    monkeypatch.setattr(compatibility.metadata, "version", lambda name:
        SDK_VERSION if name == "deepseek-harness-sdk" else "0.2.1rc3")
    report = inspect_compatibility()
    assert not report.compatible
    assert report.issues == ("RUNTIME_VERSION_UNSUPPORTED", "SDK_RUNTIME_VERSION_MISMATCH")
    assert not report.as_public_dict()["versions_match"]


def test_clean_environment_has_no_ambient_identity_or_platform_secrets(tmp_path, monkeypatch):
    for key in ("DATABASE_URL", "HYPERTEST_OPERATOR_KEY", "SSH_AUTH_SOCK", "DEEPSEEK_API_KEY",
                "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HTTP_PROXY", "PYTHONPATH"):
        monkeypatch.setenv(key, "private-canary-do-not-inherit")
    environment = clean_environment(tmp_path)
    assert not set(environment) & {
        "DATABASE_URL", "HYPERTEST_OPERATOR_KEY", "SSH_AUTH_SOCK", "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HTTP_PROXY",
    }
    assert "private-canary-do-not-inherit" not in json.dumps(environment)
    assert environment["HOME"] == str(tmp_path / "private-home")
    assert environment["DSH_HOME"] == str(tmp_path / "dsh-home")
    assert environment["PYTHONPATH"] == str(Path(__file__).resolve().parents[1] / "src")


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True, "1", 601])
def test_probe_rejects_invalid_deadline_before_dependency_or_process(value, monkeypatch):
    monkeypatch.setattr(probe, "inspect_compatibility", lambda: pytest.fail("dependency inspection"))
    with pytest.raises(AdapterError, match="INVALID_RUNTIME_TIMEOUT"):
        probe_protocol(timeout_seconds=value)


def test_probe_missing_dependency_does_not_construct_supervisor(monkeypatch):
    monkeypatch.setattr(probe, "inspect_compatibility", lambda: SdkCompatibility(None, None, False, ("SDK_NOT_INSTALLED",)))
    monkeypatch.setattr(probe, "ProcessSupervisor", lambda *a: pytest.fail("supervisor constructed"))
    with pytest.raises(DependencyError, match="SDK_DEPENDENCY_UNAVAILABLE"):
        probe_protocol()


class ProbeSupervisorFixture:
    failure = None
    stop_absent = True
    instances = []

    def __init__(self, root):
        self.root = root
        self.commands = []
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        assert all((self.root / name).is_dir() for name in ("workspace", "dsh-home", "private-home", "tmp"))
        assert self.root.stat().st_mode & 0o077 == 0

    def request(self, command, payload, timeout):
        self.commands.append((command, payload))
        assert "prompt" not in payload and "resume" not in payload
        assert not any("key" in key or "token" in key for key in payload)
        if self.failure:
            raise AdapterError(self.failure)
        return {"server_name": SERVER_NAME, "server_version": SERVER_VERSION, "session_created": True}

    def stop(self):
        self.stopped = True
        return StopObservation(True, self.stop_absent)


@pytest.fixture
def probe_supervisor(monkeypatch):
    ProbeSupervisorFixture.instances = []
    ProbeSupervisorFixture.failure = None
    ProbeSupervisorFixture.stop_absent = True
    monkeypatch.setattr(probe, "inspect_compatibility", lambda: SdkCompatibility(SDK_VERSION, SDK_VERSION, True, ()))
    monkeypatch.setattr(probe, "ProcessSupervisor", ProbeSupervisorFixture)
    return ProbeSupervisorFixture


def test_probe_has_no_prompt_resume_or_auth_and_removes_private_state(probe_supervisor):
    report = probe_protocol(timeout_seconds=1)
    instance = probe_supervisor.instances[-1]
    assert [command for command, _ in instance.commands] == ["start", "close"]
    assert instance.stopped and not instance.root.exists()
    assert report.as_public_dict() == {
        "runtime_started": True, "initialized": True, "session_created": True,
        "runtime_closed": True, "server_name": SERVER_NAME, "server_version": SERVER_VERSION,
        "model_prompt_sent": False, "test_result": "NOT_RUN",
    }


def test_timeout_still_stops_before_temporary_home_cleanup(probe_supervisor):
    probe_supervisor.failure = "SDK_TIMEOUT"
    with pytest.raises(AdapterError, match="SDK_TIMEOUT"):
        probe_protocol()
    instance = probe_supervisor.instances[-1]
    assert instance.stopped and not instance.root.exists()


def test_stop_unknown_dominates_initialization_failure(probe_supervisor):
    probe_supervisor.failure = "SDK_TIMEOUT"
    probe_supervisor.stop_absent = False
    with pytest.raises(AdapterError, match="RUNTIME_STOP_UNCONFIRMED"):
        probe_protocol()


def test_probe_worker_rejects_prompt_transport_without_importing_sdk(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "sequence": 1, "command": "send", "payload": {"prompt": "secret-canary"}}) + "\n"))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    assert worker_main() == 0
    assert json.loads(output.getvalue()) == {"sequence": 1, "error": "SDK_PROTOCOL_UNSUPPORTED"}
    assert "secret-canary" not in output.getvalue()


def test_worker_disables_history_inventory_and_sanitizes_sdk_diagnostics(monkeypatch, tmp_path):
    configurations = []

    class Client:
        def __init__(self, config):
            configurations.append(config)
            raise RuntimeError("credential-canary-from-SDK-diagnostics")

    monkeypatch.setitem(sys.modules, "deepseek_harness", SimpleNamespace(HarnessClient=Client, HarnessConfig=lambda **kwargs: kwargs))
    command = {"sequence": 1, "command": "start", "payload": {"session_id": "probe",
        "dsh_home": str(tmp_path / "dsh-home"), "workspace": "/workspace", "timeout_seconds": 1}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(command) + "\n"))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    assert worker_main() == 0
    assert json.loads(output.getvalue()) == {"sequence": 1, "error": "SDK_OPERATION_FAILED"}
    assert "credential-canary" not in output.getvalue()
    assert len(configurations) == 1
    config = configurations[0]
    assert config["profile"] == "sdk" and len(config["patches"]) == 1
    patch = Path(config["patches"][0])
    assert patch.parent == tmp_path and patch.stat().st_mode & 0o777 == 0o600
    assert json.loads(patch.read_text()) == [
        {"id": "session-log-deepseek", "name": "@deepseek-ai/dsh-session-log-deepseek", "disabled": True},
        {"id": "plugin-package-inventory-deepseek", "name": "@deepseek-ai/dsh-plugin-package-inventory-deepseek", "disabled": True},
    ]


def test_activity_projection_drops_all_text_and_bounds_keys():
    # The projection owns no client/network/process; initialize it without transport.
    import threading
    from collections import Counter

    driver = object.__new__(SdkDriver)
    driver.session_id = "root"
    driver.counts, driver._lock = Counter(), threading.Lock()
    driver.root_status = driver.turn_kind = None
    secret = "private-prompt-answer-tool-canary"
    for method, payload in [
        ("session.event", {"sessionId": "root", "event": {"type": "assistant/message", "text": secret}}),
        ("session.event", {"sessionId": "root", "event": {"type": "turn/end", "data": {"reason": {"kind": secret}}}}),
        ("session.status", {"sessionId": "root", "status": "idle", "text": secret}),
        ("session.event", {"sessionId": "root", "event": {"type": [secret]}}),
        ("subagent.finished", {"lastAssistantMessage": secret}),
    ]:
        driver.observe(SimpleNamespace(method=method, payload=payload))
    summary = driver.snapshot()
    assert summary == {"root_status": "idle", "turn_kind": "OTHER", "activity_counts": {"turn/end": 1, "subagent.finished": 1}}
    assert secret not in json.dumps(summary)
    assert "PASS" not in json.dumps(summary) and "completed" not in json.dumps(summary)


@pytest.fixture
def official_fake_runtime(tmp_path):
    """Official client + deterministic subprocess server, not a substitute SDK."""
    try:
        if importlib.metadata.version("deepseek-harness-sdk") != SDK_VERSION:
            pytest.skip("contract requires the pinned optional SDK")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("install the cloud extra in the isolated acceptance environment")
    sdk = pytest.importorskip("deepseek_harness")
    script = tmp_path / "fake_sdk_runtime.py"
    script.write_text('''import json, pathlib, sys
root = pathlib.Path.cwd()
for line in sys.stdin:
 request = json.loads(line)
 method = request["method"]
 with (root / "methods.jsonl").open("a") as stream:
  stream.write(json.dumps(method) + "\\n")
 if method == "initialize":
  result = {"serverInfo": {"name": "deepseek-harness-sdk-runtime", "version": "0.0.1"}}
 elif method == "session/working-directory/get":
  result = {"cwd": str(root)}
 elif method == "shutdown":
  result = {}
 else:
  raise RuntimeError("unexpected model/prompt method")
 print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
 if method == "shutdown": break
''')
    config = sdk.HarnessConfig(dsh_home=str(tmp_path / "dsh-home"), cwd=str(tmp_path),
        initialize_timeout_seconds=1, request_timeout_seconds=1, shutdown_timeout_seconds=0.2)
    client = sdk.HarnessClient(config, _launch_args=(sys.executable, str(script)))
    yield client, tmp_path
    client.close()


def test_actual_official_client_probe_contract_never_sends_prompt(official_fake_runtime):
    client, root = official_fake_runtime
    driver = SdkDriver(client, "probe-contract")
    result = driver.initialize({"workspace": str(root), "provider": "deepseek-official", "model": "deepseek-flash"})
    assert result == {"server_name": SERVER_NAME, "server_version": SERVER_VERSION, "session_created": True}
    assert driver.close() == {"sdk_closed": True}
    assert [json.loads(line) for line in (root / "methods.jsonl").read_text().splitlines()] == [
        "initialize", "session/working-directory/get", "shutdown",
    ]


@pytest.mark.skipif(os.name != "posix", reason="process-group supervision is POSIX-only")
def test_supervisor_terminates_its_entire_live_group_with_stubborn_child(tmp_path, monkeypatch):
    # This fixture is an inert process tree. No Harness, model or shell is run.
    script = tmp_path / "fixture.py"
    script.write_text('''import json, os, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"])
signal.signal(signal.SIGTERM, lambda *_: None)
for line in sys.stdin:
 message = json.loads(line)
 print(json.dumps({"sequence":message["sequence"],"result":{"child_pid":child.pid}}),flush=True)
''')
    real_popen = subprocess.Popen

    def launch_fixture(_args, **kwargs):
        return real_popen([sys.executable, str(script)], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", launch_fixture)
    supervisor = ProcessSupervisor(tmp_path)
    supervisor.start()
    result = supervisor.request("start", {}, 2)
    child_pid = result["child_pid"]
    stopped = supervisor.stop()
    assert stopped.root_reaped
    assert stopped.external_operations_reconciled is False
    # Zombies may briefly retain the process-group ID under a container's PID 1.
    # Never assert group absence when the OS has not actually observed it.
    try:
        os.kill(child_pid, 0)
    except ProcessLookupError:
        assert stopped.process_group_absent
    else:
        stat_file = Path(f"/proc/{child_pid}/stat")
        if stat_file.exists():
            assert stat_file.read_text().split()[2] == "Z"
        else:
            pytest.fail("fixture child remained alive after group termination")
