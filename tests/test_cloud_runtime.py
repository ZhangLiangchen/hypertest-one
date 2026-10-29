"""Cloud runtime contracts; inert subprocess/SDK fixtures only, no models or SUT."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.cloud import sdk
from hypertest.cloud import worker as worker_module
from hypertest.cloud.artifacts import write_workspace_receipt
from hypertest.cloud.broker import CloudBroker
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
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "next_offset": offset + len(chunk), "complete": offset + len(chunk) == len(content)}


async def test_cloud_readback_uses_total_characters_and_fixed_accepted_version():
    broker = PageBroker()
    adapter = CloudSyncAdapter(broker)
    intent = FrozenIntent("cloud:attempt", "key", {"task_id": "task", "project_id": "project",
        "attempt_id": "attempt", "generation": 1}, {"operation": "TRANSITION"}, 1)
    result = await adapter.readback(intent, {"version": 2, "checkpoint": {}})
    assert result == broker.document
    assert broker.offsets == list(range(0, len(json.dumps(broker.document)), 31))


@pytest.mark.parametrize("fault", ["run_id", "attempt", "execution", "case", "artifact"])
async def test_cloud_run_readback_rejects_missing_or_mismatched_results(fault):
    broker = PageBroker()
    run = {"id": "run", "attempt_id": "attempt", "run_key": "one",
           "execution": {"entrypoint": "python -m unittest", "exit_code": 1}, "reported_result": "FAIL"}
    case = {"run_id": "run", "case_revision_id": "case", "actual": "mismatch", "reported_result": "FAIL"}
    artifact = {"run_id": "run", "role": "REPORT", "artifact_id": "report"}
    broker.document.update(runs=[run], run_cases=[case], run_artifacts=[artifact])
    payload = {"operation": "SUBMIT_RUN", "run_key": "one", "execution": dict(run["execution"]),
               "reported_result": "FAIL", "cases": [{key: case[key] for key in ("case_revision_id", "actual", "reported_result")}],
               "report_artifact_ids": ["report"], "log_artifact_ids": []}
    intent = FrozenIntent("cloud:attempt", "key", {"task_id": "task", "project_id": "project",
        "attempt_id": "attempt", "generation": 1}, payload, 1)
    adapter = CloudSyncAdapter(broker)
    receipt = {"version": 2, "checkpoint": {}, "run_id": "run"}
    assert await adapter.readback(intent, receipt) == broker.document
    if fault == "run_id":
        run["id"] = "different"
    elif fault == "attempt":
        run["attempt_id"] = "different"
    elif fault == "execution":
        run["execution"]["exit_code"] = 0
    elif fault == "case":
        case["reported_result"] = "PASS"
    else:
        artifact["artifact_id"] = "different"
    with pytest.raises(ValueError, match="CLOUD_RUN_READBACK_MISMATCH"):
        await adapter.readback(intent, receipt)


async def test_cloud_completion_readback_requires_the_frozen_terminal_result():
    broker = PageBroker()
    manifest = {"required_asset_ids": ["report"], "all_local_processes_stopped": True,
                "external_operations_reconciled": True, "pending_operation_keys": [], "scope_and_gaps": "fixture"}
    checkpoint = {"final_report_revision": "report", "completion_manifest": manifest}
    broker.document["task"].update(status="COMPLETED", reported_result="FAIL")
    broker.document["attempts"][0].update(status="COMPLETED", reported_result="FAIL", checkpoint=checkpoint)
    payload = {"operation": "COMPLETE_ATTEMPT", "reported_result": "FAIL", "final_report_revision": "report",
               "completion_manifest": manifest}
    intent = FrozenIntent("cloud:attempt", "key", {"task_id": "task", "project_id": "project",
        "attempt_id": "attempt", "generation": 1}, payload, 1)
    adapter = CloudSyncAdapter(broker)
    receipt = {"version": 2, "checkpoint": checkpoint}
    assert await adapter.readback(intent, receipt) == broker.document
    broker.document["task"]["reported_result"] = "PASS"
    with pytest.raises(ValueError, match="CLOUD_COMPLETION_READBACK_MISMATCH"):
        await adapter.readback(intent, receipt)


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


async def test_suspended_broker_rejects_new_work_but_can_query_original_receipt(monkeypatch):
    claim = {"task": {"id": str(uuid4()), "project_id": str(uuid4()), "version": 1},
        "attempt": {"id": str(uuid4())}, "lease_token": "synthetic-lease", "generation": 1,
        "work_token": "synthetic-work"}
    opened = []
    class Session:
        async def __aenter__(self):
            opened.append(True)
            return self
        async def __aexit__(self, *args):
            pass
    async def original_receipt(db, project_id, key, actor):
        assert key == "original-unknown-key" and actor == "worker:fixture"
        return {"operation_key": key, "version": 2}
    monkeypatch.setattr(worker_module.service, "receipt_view", original_receipt)
    broker = CloudBroker(Session, claim, "fixture")
    broker.suspend_writes()
    for operation in (broker.assert_current(), broker.credentials(), broker.renew(90), broker.submit({})):
        with pytest.raises(CloudBlocked) as caught:
            await operation
        assert caught.value.code == "WORKER_WRITES_SUSPENDED"
    assert opened == []
    assert (await broker.receipt("original-unknown-key"))["version"] == 2
    assert len(opened) == 1


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

        def suspend_writes(self):
            pass

        async def fence_for_recovery(self, reason, *, metadata=None):
            transitions.append("RECOVERY_REQUIRED")
            transition_metadata.append({"status": "RECOVERY_REQUIRED",
                "reason": (metadata or {}).get("interruption_reason", reason),
                "runtime_metadata": metadata or {}})
            if cleanup_failure:
                raise KeyError("private-secondary-fence")

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
        assert {entry["stage"] for entry in observed["secondary"]} >= {"NAMESPACE_STOP", "SAFETY_FENCE", "REPORTER_CLOSE"}
    assert "private-" not in json.dumps(observed)
    metadata = transition_metadata[-1]["runtime_metadata"]
    assert "worker_diagnostics" in metadata
    model_observation = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"]) / "model-observations.json"
    cleanup = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"]) / "worker-cleanup.json"
    assert json.loads(model_observation.read_bytes()) == json.loads(cleanup.read_bytes())["host_model_observation"]
    assert model_observation.stat().st_mode & 0o077 == 0
    first = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"]) / "worker-error.json"
    assert json.loads(first.read_bytes())["primary"]["type"] == "CloudBlocked"
    with pytest.raises(CloudBlocked) as error:
        await worker.execute(claim)
    assert error.value.code == "ATTEMPT_RECOVERY_REQUIRED"
    assert len(starts) == 1


@pytest.mark.parametrize("fault", ["timeout", "cancel", "lease_response_lost", "report_response_lost"])
@pytest.mark.parametrize("remote_mode", ["NONE", "HTTPS"])
async def test_runtime_fault_fences_before_process_and_model_cleanup_preserving_original_intent(tmp_path, monkeypatch, fault, remote_mode):
    from hypertest.cloud import worker as module

    timeline, submitted = [], []
    elapsed = [0]
    active = asyncio.Event()
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: elapsed[0], time=lambda: 2000 + elapsed[0]))

    class Broker:
        def __init__(self, _, claim, worker_id):
            self.task_id, self.project_id = claim["task"]["id"], claim["task"]["project_id"]
            self.attempt_id, self.identity = claim["attempt"]["id"], SimpleNamespace(generation=1)
        async def assert_current(self):
            pass
        async def credentials(self):
            return {}
        async def renew(self, _):
            await active.wait()
            raise ConnectionError("synthetic renewal response lost")
        def suspend_writes(self):
            timeline.append("writes-sealed")
        async def fence_for_recovery(self, reason, **kwargs):
            if fault == "lease_response_lost":
                await asyncio.sleep(0.03)
            timeline.append("server-fenced")
            assert reason in {"RUNTIME_TIMEOUT", "WORKER_INTERRUPTED", "WORKER_LEASE_UNCONFIRMED", "REPORT_RECONCILIATION_PENDING"}

    class Reporter:
        def __init__(self, **kwargs):
            pass
        async def recover(self):
            pass
        async def submit_handoff(self, handoff, *args, **kwargs):
            submitted.append(handoff.payload["status"])
            return SimpleNamespace(synced=True, receipt={})
        def pending(self):
            return ["original-report-key"] if fault == "report_response_lost" else []
        def close(self):
            pass

    class Process:
        returncode = None

    class Sandbox:
        def __init__(self, **kwargs):
            pass
        def command(self):
            return []
        async def start(self, config):
            active.set()
            if fault == "timeout":
                elapsed[0] = 61
            if fault == "cancel":
                raise asyncio.CancelledError()
            return Process()
        async def stop(self):
            timeline.append("namespace-stopped")
            Process.returncode = 0
            return {"local_processes_stopped": True}

    class Model:
        requests = 0
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            timeline.append("model-closed")
        def observation(self):
            return {"closed": True, "drained": True, "inflight": 0}

    for name, replacement in (("CloudBroker", Broker), ("CloudTaskReporter", Reporter),
                              ("BubblewrapSandbox", Sandbox), ("ModelBroker", Model)):
        monkeypatch.setattr(module, name, replacement)
    monkeypatch.setattr(module, "inspect_sdk", lambda: {})
    monkeypatch.setattr(module, "inspect_resource_envelope", lambda **kwargs: {
        "kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024**3, "swap_max_bytes": 0, "pids_max": 256})
    monkeypatch.setattr(module, "read_model_key", lambda _: b"synthetic-no-provider-key")
    settings = SimpleNamespace(cloud_runtime_root=str(tmp_path / "runtime"), cloud_worker_lease_seconds=0.03,
        cloud_attempt_timeout_seconds=60, cloud_model_request_cost_microunits=1, cloud_model_max_requests=1,
        cloud_model_max_tokens=1024, cloud_model_base_url="https://model.invalid", cloud_model="fixture",
        cloud_model_key_file="never-read", cloud_codex_enabled=False, cloud_https_enabled=remote_mode == "HTTPS")
    manifest = {"inputs": {"authorization": {"network_targets": [], "permitted_actions": ["git:read", "framework:execute"]},
        "budgets": {"total_seconds": 60}}, "configuration": {"environment": {"connection": "NONE"}},
        "resolution": {"repositories": {"sut": {}, "framework": {}}}}
    if remote_mode == "HTTPS":
        from hypertest.application import cloud_http
        from hypertest.cloud import framework_runtime, http_broker
        from hypertest.cloud.http_profile import digest as http_digest

        class HttpAuthority:
            def __init__(self, *args, **kwargs):
                pass
            async def remote_closed(self):
                return False

        class Http:
            drained = False
            def __init__(self, *args, **kwargs):
                assert kwargs["deadline"] == 2060
            async def start(self):
                timeline.append("https-started")
            async def close(self):
                timeline.append("https-closed")

        async def inspect(*args):
            return {"profile": "FRAMEWORK_LOCKED_V1", "entrypoint_execution": "NOT_RUN"}

        monkeypatch.setattr(cloud_http, "WorkerHttpAuthority", HttpAuthority)
        monkeypatch.setattr(http_broker, "HttpBroker", Http)
        monkeypatch.setattr(framework_runtime, "inspect_framework_runtime", inspect)
        target = "https://api.example.test:443"
        access = {"profile": "HTTPS_CONTROLLED_API_V1", "allowed_addresses": ["1.1.1.1"],
            "resources": [{"key": "status", "method": "GET", "path": "/status", "timeout_seconds": 5,
                           "response_limit_bytes": 1024}], "max_operations": 2}
        access["catalog_sha256"] = http_digest({**access, "target": target})
        manifest["configuration"]["environment"] = {"connection": "HTTPS", "host": "api.example.test",
            "port": 443, "https_access": access}
        manifest["inputs"].update(framework_runtime={}, framework_entrypoints=["fixture"])
        manifest["inputs"]["authorization"].update(network_targets=[target], targets=[target],
            permitted_actions=["git:read", "framework:execute", "environment:read"])
    claim = {"task": {"id": str(uuid4()), "project_id": str(uuid4()), "frozen_manifest": manifest,
                      "input_digest": digest(manifest)},
             "attempt": {"id": str(uuid4()), "input_digest": digest(manifest), "checkpoint": {}},
             "budget_remaining": {"seconds": 60, "cost_microunits": 10}}
    worker = CloudWorker(None, settings, "fixture")
    async def checkout(*args, **kwargs):
        pass
    async def consume(*args, **kwargs):
        pass
    async def collect(*args, **kwargs):
        if fault == "report_response_lost":
            raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Synthetic receipt response lost")
        return None
    worker.resolver = SimpleNamespace(checkout=checkout)
    monkeypatch.setattr(worker, "consume_runtime", consume)
    monkeypatch.setattr(worker, "collect", collect)
    with pytest.raises((CloudBlocked, asyncio.CancelledError)):
        await worker.execute(claim)
    assert submitted == ["RUNNING"]
    assert timeline.index("writes-sealed") < timeline.index("server-fenced") < timeline.index("namespace-stopped")
    assert timeline.index("server-fenced") < timeline.index("model-closed")
    if remote_mode == "HTTPS":
        assert timeline.index("server-fenced") < timeline.index("https-closed")
    root = Path(settings.cloud_runtime_root) / ("attempt-" + claim["attempt"]["id"])
    intent = json.loads((root / "prompt-intent.json").read_bytes())
    assert intent["state"] == "SENT" and intent["generation"] == 1
    assert "prompt" not in intent
