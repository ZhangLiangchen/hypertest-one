"""Cloud runtime contracts; inert subprocess/SDK fixtures only, no models or SUT."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.cloud import sdk
from hypertest.cloud import worker as worker_module
from hypertest.cloud.artifacts import write_workspace_receipt
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.manifests import MANIFEST_PROFILE, Handoff
from hypertest.cloud.reporter import CloudSyncAdapter, CloudTaskReporter
from hypertest.cloud.sandbox import SandboxPolicy
from hypertest.cloud.worker import CloudWorker
from hypertest.cloud.worker_diagnostics import failure_metadata
from hypertest.sync_core import FrozenIntent, digest


def test_disabled_worker_does_not_claim_or_construct_runtime():
    worker = CloudWorker(lambda: pytest.fail("database touched"),
        SimpleNamespace(cloud_enabled=False, cloud_worker_enabled=False), "fixture")
    with pytest.raises(CloudBlocked, match="explicitly enabled"):
        worker.enabled()


def test_scope_rejects_remote_or_external_actions_before_model():
    policy = SandboxPolicy(60, 1, 1024)
    manifest = {"inputs": {"authorization": {"network_targets": ["https://sut.invalid"],
        "permitted_actions": ["git:read", "framework:execute"]}, "budgets": {"total_seconds": 60}}}
    with pytest.raises(CloudBlocked) as error:
        policy.validate(manifest)
    assert error.value.code == "REMOTE_NETWORK_UNSUPPORTED"
    manifest["inputs"]["authorization"]["network_targets"] = []
    manifest["inputs"]["authorization"]["permitted_actions"].append("ci:execute")
    with pytest.raises(CloudBlocked) as error:
        policy.validate(manifest)
    assert error.value.code == "ACTION_CAPABILITY_UNSUPPORTED"


def test_receipt_write_cannot_follow_agent_symlink(tmp_path):
    workspace, outside = tmp_path / "workspace", tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / ".hypertest-cloud").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CloudBlocked) as error:
        write_workspace_receipt(workspace, "key", {"status": "ACCEPTED"})
    assert error.value.code == "RECEIPT_PATH_UNSAFE"
    assert list(outside.iterdir()) == []


def test_receipt_is_immutable_and_original_content_readable(tmp_path):
    receipt = {"status": "ACCEPTED", "version": 3}
    write_workspace_receipt(tmp_path, "key", receipt)
    write_workspace_receipt(tmp_path, "key", receipt)
    assert json.loads((tmp_path / ".hypertest-cloud/receipts/key.json").read_text()) == receipt
    with pytest.raises(CloudBlocked) as error:
        write_workspace_receipt(tmp_path, "key", {"status": "ACCEPTED", "version": 4})
    assert error.value.code == "RECEIPT_CONFLICT"


class PageBroker:
    identity = SimpleNamespace(generation=1)

    def __init__(self):
        self.document = {"task": {"id": "task", "project_id": "project", "version": 2},
                         "attempts": [{"id": "attempt", "checkpoint": {}}]}
        self.offsets = []

    async def page(self, *, version, offset, limit):
        content = json.dumps(self.document)
        chunk = content[offset:offset + 31]
        self.offsets.append(offset)
        return {"task_id": "task", "version": version, "offset": offset,
            "total_characters": len(content), "content": chunk,
            "next_offset": offset + len(chunk), "complete": offset + len(chunk) == len(content)}


async def test_cloud_readback_uses_total_characters_and_fixed_accepted_version():
    broker = PageBroker()
    adapter = CloudSyncAdapter(broker)
    intent = FrozenIntent("cloud:attempt", "key", {"task_id": "task", "project_id": "project",
        "attempt_id": "attempt", "generation": 1}, {"operation": "TRANSITION"}, 1)
    result = await adapter.readback(intent, {"version": 2, "checkpoint": {}})
    assert result == broker.document
    assert broker.offsets == list(range(0, len(json.dumps(broker.document)), 31))


async def test_reporter_refuses_terminal_without_worker_external_action_proof(tmp_path):
    broker = SimpleNamespace(attempt_id="attempt", task_id="task", project_id="project", version=1)
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private", workspace=tmp_path / "workspace")
    handoff = Handoff(profile=MANIFEST_PROFILE, task_id="task", attempt_id="attempt",
        key="terminal", operation="COMPLETE_ATTEMPT", payload={})
    try:
        with pytest.raises(CloudBlocked) as error:
            await reporter.submit_handoff(handoff, digest(handoff.model_dump()), runtime_stopped=True)
        assert error.value.code == "RUNTIME_STILL_ACTIVE"
        assert reporter.pending() == []
    finally:
        reporter.close()


async def test_changed_accepted_handoff_is_rejected_not_silently_skipped(tmp_path):
    ready = tmp_path / ".hypertest-cloud/ready"
    ready.mkdir(parents=True)
    handoff = Handoff(profile=MANIFEST_PROFILE, task_id="task", attempt_id="attempt",
        key="analysis", operation="SUBMIT_ASSETS", payload={"assets": []})
    (ready / "analysis.json").write_text(handoff.model_dump_json())
    worker = CloudWorker(None, None, "fixture")
    reporter = SimpleNamespace(broker=SimpleNamespace(task_id="task", attempt_id="attempt"))
    with pytest.raises(CloudBlocked) as error:
        await worker.collect(reporter, tmp_path, {"analysis": "different-original-digest"}, stopped=False)
    assert error.value.code == "HANDOFF_CHANGED"


def test_production_boundary_does_not_auto_resume_or_send_replacement_prompt(monkeypatch):
    monkeypatch.setattr(sdk, "inspect_sdk", lambda: {})
    with pytest.raises(CloudBlocked) as error:
        sdk.run_official_sdk({"resume": True}, "never sent")
    assert error.value.code == "SDK_RESUME_UNSUPPORTED"


def test_official_client_receipt_and_wait_not_runresult_transcript(tmp_path, monkeypatch):
    """Exercise our production SDK boundary through the actual optional client."""
    official = pytest.importorskip("deepseek_harness")
    runtime = tmp_path / "runtime.py"
    runtime.write_text('''import json,pathlib,sys
for line in sys.stdin:
 request=json.loads(line); method=request["method"]
 with pathlib.Path("methods.jsonl").open("a") as file:file.write(json.dumps(method)+"\\n")
 if method=="initialize": result={"serverInfo":{"name":"deepseek-harness-sdk-runtime","version":"0.0.1"}}
 elif method=="session/prompt": result={"messageId":"queued-1"}
 elif method=="session/wait":
  print(json.dumps({"jsonrpc":"2.0","method":"session.event","params":{"sessionId":"root","event":{"type":"turn/end","data":{"reason":{"kind":"private-canary-reason"}}}}}),flush=True)
  result={}
 elif method=="shutdown":result={}
 else:raise RuntimeError("unexpected method")
 print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}),flush=True)
 if method=="shutdown":break
''')
    real_client = official.HarnessClient

    def fixture_client(config):
        return real_client(config, _launch_args=(sys.executable, str(runtime)))

    monkeypatch.setattr(official, "HarnessClient", fixture_client)
    monkeypatch.setattr(sdk, "inspect_sdk", lambda: {})
    result = sdk.run_official_sdk({"session_id": "root", "dsh_home": str(tmp_path / "home"),
        "workspace": str(tmp_path), "base_url": "http://127.0.0.1:1", "model": "deepseek-flash",
        "max_tokens": 1000, "timeout_seconds": 2}, "fixture-only-no-real-model")
    assert result.message_id == "queued-1" and result.finish_reason == "OTHER"
    assert not hasattr(result, "events") and not hasattr(result, "notifications")
    assert [json.loads(line) for line in (tmp_path / "methods.jsonl").read_text().splitlines()] == [
        "initialize", "session/prompt", "session/wait", "shutdown"]


@pytest.mark.parametrize("sdk_failure", [False, True])
@pytest.mark.parametrize("cleanup_failure", [False, True])
@pytest.mark.parametrize("native_enabled", [False, True])
async def test_idle_without_terminal_handoff_preserves_recovery_and_never_replays_prompt(tmp_path, monkeypatch, sdk_failure, cleanup_failure, native_enabled):
    transitions = []
    transition_metadata = []
    starts = []
    stops = []
    resources = {"address_space_rlimit_bytes": (16 if native_enabled else 4) * 1024**3,
        "aggregate_memory_ceiling_bytes": 4 * 1024**3, "aggregate_processes_ceiling": 256,
        "observed_cgroup": {"kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024**3,
            "swap_max_bytes": 0, "pids_max": 256}}

    class Broker:
        def __init__(self, sessions, claim, worker_id):
            self.task_id, self.project_id, self.attempt_id = (claim["task"]["id"],
                claim["task"]["project_id"], claim["attempt"]["id"])
            self.identity = SimpleNamespace(generation=1)

        async def assert_current(self):
            pass

        async def credentials(self):
            return {}

        async def renew(self, seconds):
            pass

    class Reporter:
        def __init__(self, *, broker, **kwargs):
            self.broker = broker

        async def recover(self):
            pass

        async def submit_handoff(self, handoff, source_digest, **kwargs):
            transitions.append(handoff.payload["status"])
            transition_metadata.append(handoff.payload)
            if cleanup_failure and handoff.payload["status"] == "RECOVERY_REQUIRED":
                raise KeyError("private-secondary-transition")
            return SimpleNamespace(synced=True, receipt={})

        def pending(self):
            return []

        def close(self):
            if cleanup_failure:
                raise ValueError("private-secondary-close")

    class EmptyStream:
        frames = iter((
            {"runtime_phase": "INITIALIZE"},
            {"runtime_observation": "ERROR", "sdk_error": {"phase": "INITIALIZE", "type": "JSON_RPC",
                "rpc_numeric_code": -32603, "message": "private-model-canary"}},
            {"runtime_phase": "CLOSE"},
            {"runtime_observation": "ERROR", "sdk_error": {"phase": "CLOSE", "type": "TIMEOUT"}},
        ) if sdk_failure else (
            {"runtime_phase": "WAIT"},
            {"runtime_activity": {"kind": "TOOL_RESULT", "is_error": True,
                "error_code": "SANDBOX_UNAVAILABLE", "call_sequence": 1, "content": "private-tool-canary"}},
            {"runtime_phase": "CLOSE"},
            {"runtime_observation": "IDLE", "finish_reason": "blocked", "session_id": "private-session-canary"},
        ))

        async def readline(self):
            frame = next(self.frames, None)
            return b"" if frame is None else json.dumps(frame).encode() + b"\n"

    class Process:
        returncode = 0
        stdout = EmptyStream()

        async def wait(self):
            return 0

    class Sandbox:
        def __init__(self, **kwargs):
            assert kwargs["policy"].memory_bytes == resources["address_space_rlimit_bytes"]
            assert kwargs["policy"].aggregate_memory_bytes == 4 * 1024**3
            assert kwargs["policy"].aggregate_processes == 256

        def command(self):
            return []

        async def start(self, config):
            path = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"]) / "prompt-intent.json"
            intent = json.loads(path.read_bytes())
            assert config["max_tokens"] == 16384
            assert set(intent) == {"state", "session_id", "generation", "prompt_sha256", "runtime_limits"}
            assert intent["runtime_limits"] == {"model": config["model"], "max_tokens": config["max_tokens"],
                **resources,
                "timeout_seconds": config["timeout_seconds"], "reasoning_effort": config.get("reasoning_effort"),
                "codex_model": settings.cloud_codex_model if native_enabled else None,
                "request_limits": ([{"scope": "ROOT", "max_requests": 1}, {"scope": "CODEX", "max_requests": 1}]
                    if native_enabled else [{"scope": "ROOT", "max_requests": 1}])}
            assert path.stat().st_mode & 0o077 == 0
            assert "prompt" not in intent and "fixture-only-no-service-key" not in path.read_text()
            starts.append(config["session_id"])
            return Process()

        async def stop(self):
            stops.append(True)
            if cleanup_failure and len(stops) > 1:
                raise PermissionError("private-secondary-stop")
            return {"local_processes_stopped": True}

    class Model:
        requests = 0

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(worker_module, "CloudBroker", Broker)
    monkeypatch.setattr(worker_module, "CloudTaskReporter", Reporter)
    monkeypatch.setattr(worker_module, "BubblewrapSandbox", Sandbox)
    monkeypatch.setattr(worker_module, "ModelBroker", Model)
    monkeypatch.setattr(worker_module, "CodexOAuthBroker", Model)
    monkeypatch.setattr(worker_module, "inspect_sdk", lambda: {})
    monkeypatch.setattr(worker_module, "inspect_resource_envelope", lambda **kwargs: {
        **resources["observed_cgroup"], "private_path": "private-cgroup-canary"})
    monkeypatch.setattr(worker_module, "verify_payload", lambda *_: {})
    monkeypatch.setattr(worker_module, "read_cloud_codex_identity", lambda *args, **kwargs: object())
    monkeypatch.setattr(worker_module, "read_model_key", lambda _: b"fixture-only-no-service-key")
    settings = SimpleNamespace(cloud_runtime_root=str(tmp_path / "state"),
        cloud_worker_lease_seconds=30, cloud_model_request_cost_microunits=1,
        cloud_attempt_timeout_seconds=60, cloud_model_max_requests=1,
        cloud_model_max_tokens=16384, cloud_model_base_url="https://model.invalid",
        cloud_model_key_file="not-read", cloud_model="deepseek-flash", cloud_codex_enabled=native_enabled,
        cloud_codex_model="gpt-5.6-sol", cloud_codex_payload="not-mounted", cloud_codex_payload_sha256="a" * 64,
        cloud_codex_oauth_file="not-read", cloud_codex_max_requests=1, cloud_codex_request_credits=1)
    manifest = {"inputs": {"authorization": {"network_targets": [],
        "permitted_actions": ["git:read", "framework:execute"]}, "budgets": {"total_seconds": 60,
            "accounting_unit": "REQUEST_CREDITS" if native_enabled else "CONSERVATIVE_MICROUNITS"}},
        "configuration": {"environment": {"connection": "NONE"}},
        "resolution": {"repositories": {"sut": {}, "framework": {}}}}
    claim = {"task": {"id": str(uuid4()), "project_id": str(uuid4()), "version": 1,
        "frozen_manifest": manifest, "input_digest": digest(manifest)},
        "attempt": {"id": str(uuid4()), "input_digest": digest(manifest), "checkpoint": {}},
        "budget_remaining": {"seconds": 60, "cost_microunits": 10}}
    worker = CloudWorker(None, settings, "fixture")

    async def checkout(resolved, destination, token):
        destination.mkdir()

    worker.resolver = SimpleNamespace(checkout=checkout)
    with pytest.raises(CloudBlocked) as error:
        await worker.execute(claim)
    assert error.value.code == ("SDK_RUN_FAILED" if sdk_failure else "EXPLICIT_HANDOFF_MISSING")
    assert transitions == ["RUNNING", "RECOVERY_REQUIRED"]
    assert transition_metadata[0]["runtime_metadata"]["runtime_limits"] == resources
    assert "private-cgroup-canary" not in json.dumps(transition_metadata)
    assert len(starts) == 1 and stops
    if sdk_failure:
        expected = {"source": "sandbox-runtime-reported", "last_phase": "CLOSE",
            "first_sdk_error": {"phase": "INITIALIZE", "type": "JSON_RPC", "rpc_numeric_code": -32603}}
        assert transition_metadata[-1]["reason"] == "SDK_RUN_FAILED"
        assert transition_metadata[-1]["runtime_metadata"]["sdk_diagnostics"] == expected
        path = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"]) / "runtime-diagnostics.json"
        assert json.loads(path.read_bytes()) == expected and path.stat().st_mode & 0o077 == 0
        assert "private-model-canary" not in json.dumps(transition_metadata) + path.read_text()
    else:
        expected = {"source": "sandbox-runtime-reported", "last_phase": "CLOSE",
            "activity_counts": {"TOOL_RESULT": 1}, "recent_activity": [{"kind": "TOOL_RESULT",
                "is_error": True, "error_code": "SANDBOX_UNAVAILABLE", "call_sequence": 1}],
            "idle_finish_reason": "blocked"}
        assert transition_metadata[-1]["runtime_metadata"]["sdk_diagnostics"] == expected
        path = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"]) / "runtime-diagnostics.json"
        assert json.loads(path.read_bytes()) == expected and path.stat().st_mode & 0o077 == 0
        assert "private-" not in path.read_text()
    observed = failure_metadata(error.value)
    assert observed["primary"]["type"] == "CloudBlocked"
    if cleanup_failure:
        assert {entry["stage"] for entry in observed["secondary"]} >= {"NAMESPACE_STOP", "REPORT_TRANSITION", "REPORTER_CLOSE"}
    assert "private-" not in json.dumps(observed)
    metadata = transition_metadata[-1]["runtime_metadata"]
    assert "worker_diagnostics" in metadata and "host_model_observation" in metadata
    model_observation = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"]) / "model-observations.json"
    assert json.loads(model_observation.read_bytes()) == metadata["host_model_observation"]
    assert model_observation.stat().st_mode & 0o077 == 0
    first = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"]) / "worker-error.json"
    assert json.loads(first.read_bytes())["primary"]["type"] == "CloudBlocked"
    with pytest.raises(CloudBlocked) as error:
        await worker.execute(claim)
    assert error.value.code == "ATTEMPT_RECOVERY_REQUIRED"
    assert len(starts) == 1
