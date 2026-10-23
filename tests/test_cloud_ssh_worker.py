"""SSH Worker admission and completion boundaries; inert transports only."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.cloud import worker as worker_module
from hypertest.cloud import worker_admission as admission
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.manifests import MANIFEST_PROFILE, Handoff, task_prompt
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy
from hypertest.cloud.ssh_profile import SSH_SOCKET, validate_profile
from hypertest.cloud.ssh_profile import digest as ssh_digest
from hypertest.cloud.worker import CloudWorker
from hypertest.cloud.worker_diagnostics import attach_failure, failure_metadata
from hypertest.config import Settings
from hypertest.sync_core import digest


def ssh_environment():
    raw = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + b"a" * 32
    public = "ssh-ed25519 " + base64.b64encode(raw).decode()
    environment = {"connection": "SSH", "host": "192.0.2.10", "port": 2222,
        "user": "diagnostics", "host_key": public, "require_matching_deployment": False,
        "ssh_access": {"profile": "SSH_FIXED_DIAGNOSTICS_V1", "helper_sha256": "a" * 64,
            "catalog_sha256": "0" * 64, "authority_public_key": public,
            "max_operations": 8, "actions": [{"key": "health", "script_path": "/opt/hypertest-ssh/actions/health",
                "script_sha256": "b" * 64, "timeout_seconds": 30,
                "stdout_limit_bytes": 65536, "stderr_limit_bytes": 65536}]}}
    catalog = {"profile": "SSH_FIXED_DIAGNOSTICS_V1", "target": "ssh://diagnostics@192.0.2.10:2222",
        **{key: environment["ssh_access"][key] for key in
           ("helper_sha256", "authority_public_key", "max_operations", "actions")}}
    environment["ssh_access"]["catalog_sha256"] = ssh_digest(catalog)
    return environment


def ssh_manifest():
    environment = ssh_environment()
    target = validate_profile(environment).target
    return {"inputs": {"authorization": {"targets": ["https://example.invalid/sut.git", target],
        "network_targets": [target], "permitted_actions": ["git:read", "framework:execute", "environment:read"]},
        "budgets": {"total_seconds": 60}}, "configuration": {"environment": environment},
        "resolution": {"repositories": {"sut": {}, "framework": {}}}}


def test_ssh_stays_independently_disabled_without_a_client_digest():
    settings = Settings(_env_file=None)
    assert settings.cloud_ssh_enabled is False and settings.cloud_ssh_executable_sha256 == ""
    with pytest.raises(CloudBlocked) as error:
        SandboxPolicy(60, 1, 1024).validate(ssh_manifest())
    assert error.value.code == "REMOTE_NETWORK_UNSUPPORTED"


@pytest.mark.parametrize("route,connection,expected", [
    ("LOCAL_ONLY", "SSH", "LOCAL_MODE_REQUIRED"),
    ("LOCAL_ONLY", "NONE", "LOCAL_MODE_REQUIRED"),
    ("WEB_ONLY", "SSH", "CLOUD_WEB_ONLY"),
    ("WEB_ONLY", "NONE", "CLOUD_WEB_ONLY"),
    ("WEB_ONLY", "HTTPS", "ENVIRONMENT_CAPABILITY_UNSUPPORTED"),
    ("unknown", "NONE", "CLOUD_ACCESS_POLICY_INVALID"),
])
def test_environment_route_only_restricts_and_never_enables_https(route, connection, expected):
    manifest = ssh_manifest()
    manifest["configuration"]["environment"] = {"connection": connection, "cloud_access_policy": route}
    manifest["inputs"]["authorization"]["network_targets"] = []
    manifest["inputs"]["authorization"]["permitted_actions"] = ["git:read", "framework:execute"]
    with pytest.raises(CloudBlocked) as error:
        SandboxPolicy(60, 1, 1024).validate(manifest)
    assert error.value.code == expected


@pytest.mark.parametrize("change", ["network-extra", "target-missing", "write-action", "host-drift", "deployment"])
def test_ssh_policy_requires_the_exact_frozen_readonly_capability(change):
    manifest = ssh_manifest()
    policy = SandboxPolicy(60, 1, 1024, ssh_profile=validate_profile(manifest["configuration"]["environment"]))
    policy.validate(manifest)
    authorization = manifest["inputs"]["authorization"]
    if change == "network-extra":
        authorization["network_targets"].append("ssh://diagnostics@192.0.2.11:2222")
    elif change == "target-missing":
        authorization["targets"] = []
    elif change == "write-action":
        authorization["permitted_actions"].append("environment:write")
    elif change == "host-drift":
        manifest["configuration"]["environment"]["host"] = "192.0.2.11"
    else:
        manifest["configuration"]["environment"]["require_matching_deployment"] = True
    with pytest.raises(CloudBlocked):
        policy.validate(manifest)


def test_namespace_only_mounts_the_canonical_host_socket_readonly(tmp_path):
    profile = validate_profile(ssh_environment())
    path = tmp_path / "ssh.sock"
    with socket.socket(socket.AF_UNIX) as stream:
        stream.bind(str(path))
        sandbox = BubblewrapSandbox(workspace=tmp_path, dsh_home=tmp_path,
            broker_socket=tmp_path / "model.sock", policy=SandboxPolicy(60, 1, 1024, ssh_profile=profile), ssh_socket=path)
        assert sandbox.ssh_mounts() == ["--ro-bind", str(path), SSH_SOCKET]
        link = tmp_path / "linked.sock"
        link.symlink_to(path)
        sandbox.ssh_socket = link
        with pytest.raises(CloudBlocked, match="canonical Unix"):
            sandbox.ssh_mounts()
        sandbox.ssh_socket = path
        sandbox.policy = SandboxPolicy(60, 1, 1024)
        with pytest.raises(CloudBlocked):
            sandbox.ssh_mounts()


def test_task_instructions_only_expose_fixed_action_keys_and_get_only_recovery():
    task, attempt = {"id": str(uuid4()), "frozen_manifest": ssh_manifest()}, {"id": str(uuid4())}
    profile = validate_profile(task["frozen_manifest"]["configuration"]["environment"])
    prompt = json.loads(task_prompt(task, attempt, ssh_profile=profile))
    assert prompt["capabilities"]["remote_network"] is False
    assert prompt["capabilities"]["ssh"]["actions"] == ["health"]
    text = " ".join(prompt["instructions"])
    assert "invoke --key KEY --action ACTION" in text and "query --operation UUID" in text
    assert "Never invoke again" in text and "no SSH credentials or general network" in text
    assert json.loads(task_prompt(task, attempt))["capabilities"]["ssh"] is False


@pytest.mark.parametrize("fault", ["missing-uid", "wrong-uid", "wrong-gid", "lookup-error"])
def test_ssh_local_identity_refuses_unresolved_or_mismatched_nss_without_account_output(monkeypatch, fault):
    private_os = SimpleNamespace(**vars(os))
    private_os.geteuid, private_os.getegid = lambda: 997, lambda: 988
    monkeypatch.setattr(admission, "os", private_os)

    def lookup(uid):
        assert uid == 997
        if fault == "missing-uid":
            raise KeyError("private-nss-account-canary")
        if fault == "lookup-error":
            raise OSError("private-nss-path-canary")
        return SimpleNamespace(pw_uid=998 if fault == "wrong-uid" else 997,
            pw_gid=989 if fault == "wrong-gid" else 988, pw_name="private-account-canary")

    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwuid=lookup))
    with pytest.raises(CloudBlocked) as error:
        admission.inspect_ssh_local_identity()
    observed = admission.blocked_observation(error.value, scope="BEFORE_NEXT_CLAIM")
    assert observed["code"] == "SSH_LOCAL_IDENTITY_UNAVAILABLE"
    assert observed["check_work_claimed"] is False
    assert "private-" not in json.dumps(observed) and "private-" not in str(error.value)


@pytest.mark.parametrize("uid,gid", [(997, 988), (0, 0)])
def test_ssh_nss_identity_only_reports_resolution_and_primary_gid_match(monkeypatch, uid, gid):
    # The existing outer service profile owns the nonroot rule, not this NSS check.
    private_os = SimpleNamespace(**vars(os))
    private_os.geteuid, private_os.getegid = lambda: uid, lambda: gid
    monkeypatch.setattr(admission, "os", private_os)
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwuid=lambda value:
        SimpleNamespace(pw_uid=value, pw_gid=gid, pw_name="private-name", pw_dir="/private-home")))
    assert admission.inspect_ssh_local_identity() == {"resolved": True, "primary_gid_matches": True}


def test_ssh_credentials_check_nss_before_reading_any_secret(monkeypatch):
    settings = SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True, cloud_ssh_enabled=True)
    monkeypatch.setattr(admission, "_credential_paths", lambda _: pytest.fail("credential path checked before NSS refusal"))

    def missing():
        raise CloudBlocked("SSH_LOCAL_IDENTITY_UNAVAILABLE", "fixed refusal")

    monkeypatch.setattr(admission, "inspect_ssh_local_identity", missing)
    with pytest.raises(CloudBlocked) as error:
        admission.admit_credentials(settings)
    assert error.value.code == "SSH_LOCAL_IDENTITY_UNAVAILABLE"


@pytest.mark.parametrize("ssh_enabled", [False, True])
def test_credential_admission_nss_is_ssh_opt_in_only(monkeypatch, ssh_enabled):
    checked = []
    settings = SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True, cloud_ssh_enabled=ssh_enabled,
        cloud_codex_enabled=False, cloud_credential_key_file="wrapping", cloud_model_key_file="model")
    monkeypatch.setattr(admission, "_credential_paths", lambda _: None)
    monkeypatch.setattr(admission, "CredentialCipher", SimpleNamespace(from_key_file=lambda _: None))
    monkeypatch.setattr(admission, "read_private_file", lambda *a, **k: b"fixture-only-key")
    monkeypatch.setattr(admission, "read_ssh_authority", lambda _: b"fixture-only-authority")

    def identity():
        assert ssh_enabled
        checked.append(True)
        return {"resolved": True, "primary_gid_matches": True}

    monkeypatch.setattr(admission, "inspect_ssh_local_identity", identity)
    observed = admission.admit_credentials(settings)
    assert checked == ([True] if ssh_enabled else [])
    if ssh_enabled:
        assert observed["ssh_local_identity"] == {"resolved": True, "primary_gid_matches": True}
    else:
        assert observed == {"wrapping_key_readable": True, "deepseek_key_readable": True}


async def test_ssh_worker_rejects_missing_nss_before_database_or_claim_without_service_profile(monkeypatch):
    settings = SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True, cloud_ssh_enabled=True,
        cloud_service_release_sha256="")
    calls = {"database": 0, "resolution": 0, "attempt": 0, "model": 0}
    monkeypatch.setattr(worker_module, "inspect_resource_envelope", lambda: pytest.fail("resource admission entered"))
    private_os = SimpleNamespace(**vars(os))
    private_os.geteuid, private_os.getegid = lambda: 997, lambda: 988
    monkeypatch.setattr(admission, "os", private_os)

    def missing(uid):
        assert uid == 997
        raise KeyError("private-nss-account-canary")

    def database():
        calls["database"] += 1
        pytest.fail("database opened before NSS refusal")

    async def resolution(*args, **kwargs):
        calls["resolution"] += 1
        pytest.fail("resolution claimed before NSS refusal")

    async def attempt(*args, **kwargs):
        calls["attempt"] += 1
        pytest.fail("attempt claimed before NSS refusal")

    def model(*args, **kwargs):
        calls["model"] += 1
        pytest.fail("model started before NSS refusal")

    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwuid=missing))
    monkeypatch.setattr(worker_module.service, "claim_resolution", resolution)
    monkeypatch.setattr(worker_module.service, "claim_attempt", attempt)
    monkeypatch.setattr(worker_module, "ModelBroker", model)
    worker = CloudWorker(database, settings, "inert-worker")
    with pytest.raises(CloudBlocked) as error:
        await worker.run_once()
    assert error.value.code == "SSH_LOCAL_IDENTITY_UNAVAILABLE"
    assert calls == {"database": 0, "resolution": 0, "attempt": 0, "model": 0}


async def test_ssh_disabled_worker_does_not_resolve_nss_before_inert_poll(monkeypatch):
    settings = SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True, cloud_ssh_enabled=False,
        cloud_worker_lease_seconds=30)
    monkeypatch.setattr(worker_module, "inspect_ssh_local_identity", lambda: pytest.fail("SSH-off NSS lookup"))
    monkeypatch.setattr(worker_module, "inspect_resource_envelope", lambda: None)

    class Session:
        async def __aenter__(self):
            return object()
        async def __aexit__(self, *_):
            return False

    async def no_work(*args, **kwargs):
        return None

    for name in ("expire_leases", "claim_resolution", "claim_attempt"):
        monkeypatch.setattr(worker_module.service, name, no_work)
    assert await CloudWorker(Session, settings, "inert-worker").run_once() is False


@pytest.mark.parametrize("unsafe", ["mutable", "wrong-digest", "writable", "symlink", "nonroot"])
def test_ssh_client_requires_readonly_root_owned_pinned_executable(tmp_path, monkeypatch, unsafe):
    path = tmp_path / "ssh"
    path.write_bytes(b"inert executable fixture")
    path.chmod(0o755)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    private_os = SimpleNamespace(**vars(os))
    original_fstat = os.fstat

    def trusted_stat(descriptor):
        values = list(original_fstat(descriptor))
        values[4] = 1234 if unsafe == "nonroot" else 0
        return os.stat_result(values)

    private_os.fstat = trusted_stat
    private_os.fstatvfs = lambda _: SimpleNamespace(f_flag=0 if unsafe == "mutable" else os.ST_RDONLY)
    monkeypatch.setattr(admission, "os", private_os)
    settings = SimpleNamespace(cloud_ssh_executable=str(path), cloud_ssh_executable_sha256=expected)
    if unsafe == "wrong-digest":
        settings.cloud_ssh_executable_sha256 = "0" * 64
    elif unsafe == "writable":
        path.chmod(0o777)
    elif unsafe == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        settings.cloud_ssh_executable = str(link)
    with pytest.raises(CloudBlocked) as error:
        admission.inspect_ssh_client(settings)
    assert error.value.code == "SSH_CLIENT_UNTRUSTED"


def test_ssh_client_hashes_the_same_descriptor_and_has_no_path_fallback(tmp_path, monkeypatch):
    path = tmp_path / "ssh"
    path.write_bytes(b"inert pinned executable")
    path.chmod(0o755)
    private_os = SimpleNamespace(**vars(os))
    original_fstat = os.fstat

    def trusted_stat(descriptor):
        values = list(original_fstat(descriptor))
        values[4] = 0
        return os.stat_result(values)

    private_os.fstat = trusted_stat
    private_os.fstatvfs = lambda _: SimpleNamespace(f_flag=os.ST_RDONLY)
    monkeypatch.setattr(admission, "os", private_os)
    settings = SimpleNamespace(cloud_ssh_executable=str(path),
        cloud_ssh_executable_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert admission.inspect_ssh_client(settings) == {"client_sha256": settings.cloud_ssh_executable_sha256, "readonly": True}
    settings.cloud_ssh_executable = "ssh"
    with pytest.raises(CloudBlocked):
        admission.inspect_ssh_client(settings)


@pytest.mark.parametrize("host_closed,canonical_closed,preparation_seconds,cutoff", [
    (True, True, 0, False), (True, False, 0, False), (False, True, 0, False),
    (True, True, 31, False), (True, True, 0, True), (False, True, 0, True),
])
async def test_worker_requires_both_remote_observations_after_local_stop_before_completion(tmp_path, monkeypatch, host_closed, canonical_closed, preparation_seconds, cutoff):
    import hypertest.cloud.ssh_broker as ssh_module
    import hypertest.cloud.ssh_tickets as tickets_module

    timeline, submitted = [], []
    elapsed = [0]
    monkeypatch.setattr(worker_module, "time", SimpleNamespace(
        monotonic=lambda: 1000 + elapsed[0], time=lambda: 2000 + elapsed[0]))
    manifest = ssh_manifest()
    profile = validate_profile(manifest["configuration"]["environment"])
    claim = {"task": {"id": str(uuid4()), "project_id": str(uuid4()), "version": 1,
        "frozen_manifest": manifest, "input_digest": digest(manifest)},
        "attempt": {"id": str(uuid4()), "input_digest": digest(manifest), "checkpoint": {}},
        "budget_remaining": {"seconds": 60, "cost_microunits": 3}}
    settings = SimpleNamespace(cloud_runtime_root=str(tmp_path / "runtime"), cloud_worker_lease_seconds=30,
        cloud_attempt_timeout_seconds=60, cloud_model_request_cost_microunits=1, cloud_model_max_requests=1,
        cloud_model_max_tokens=1024, cloud_model_base_url="https://model.invalid", cloud_model="fixture",
        cloud_model_key_file="never-read-model", cloud_codex_enabled=False, cloud_codex_model="placeholder",
        cloud_ssh_enabled=True, cloud_ssh_executable="/usr/bin/ssh", cloud_ssh_executable_sha256="a" * 64)

    class Broker:
        def __init__(self, sessions, claim, worker_id):
            self.task_id, self.project_id = claim["task"]["id"], claim["task"]["project_id"]
            self.attempt_id, self.identity = claim["attempt"]["id"], SimpleNamespace(generation=1)
        async def assert_current(self):
            pass
        async def renew(self, seconds):
            pass
        async def credentials(self):
            return {"ENVIRONMENT": b"private-ssh-key-canary"}

    class Authority:
        def __init__(self, sessions, **kwargs):
            assert kwargs["task_id"] == claim["task"]["id"]
        async def remote_closed(self):
            timeline.append("canonical-read")
            return canonical_closed

    class SSH:
        def __init__(self, socket_path, **kwargs):
            assert kwargs["ssh_key"] == b"private-ssh-key-canary"
            assert kwargs["signing_key"] == b"private-signing-key-canary"
            assert kwargs["profile"] == profile
            assert kwargs["deadline"] == 2030  # Original end2060 minus30; never reset after Git.
        async def start(self):
            timeline.append("ssh-start")
        async def close(self):
            if cutoff:
                assert Process.returncode is None and "model-close" not in timeline
                assert "namespace-stop" not in timeline
                assert all(operation != "COMPLETE_ATTEMPT" for operation, _, _ in submitted)
                timeline.append("ssh-close-root-running")
            timeline.append("ssh-close")
        def observation(self):
            return {"closed": True, "remote_closed": host_closed, "pending_operations": [], "inflight": 0,
                "stdout": "private-output-canary", "key": "private-ssh-key-canary"}

    class Reporter:
        def __init__(self, **kwargs):
            pass
        async def recover(self):
            pass
        async def submit_handoff(self, handoff, source_digest, **kwargs):
            if handoff.payload.get("status") == "RUNNING":
                assert handoff.payload["runtime_metadata"]["ssh"]["hard_deadline_epoch"] == 2030
                assert handoff.payload["budget_reservation"]["reserved_seconds"] == 60
            submitted.append((handoff.operation, handoff.payload, kwargs))
            return SimpleNamespace(synced=True, receipt={})
        def pending(self):
            return []
        def close(self):
            pass

    class Process:
        returncode = None if cutoff else 0
        stdout = None
        async def wait(self):
            return 0

    class Sandbox:
        def __init__(self, **kwargs):
            assert kwargs["policy"].ssh_profile == profile
            assert kwargs["policy"].memory_bytes == 4 * 1024**3
            assert kwargs["ssh_socket"].name == "ssh.sock"
        def command(self):
            return []
        async def start(self, config):
            assert "private-ssh-key-canary" not in json.dumps(config)
            assert "private-signing-key-canary" not in json.dumps(config)
            if cutoff:
                elapsed[0] = 31
            return Process()
        async def stop(self):
            Process.returncode = 0
            timeline.append("namespace-stop")
            return {"local_processes_stopped": True}

    class Model:
        requests = 0
        def __init__(self, *args, **kwargs):
            assert kwargs["deadline"] == 1060  # Root/model keeps the original full deadline.
            timeline.append("model-created")
        def __enter__(self):
            return self
        def __exit__(self, *_):
            timeline.append("model-close")
        def observation(self):
            return {"drained": True, "closed": True, "inflight": 0}

    authority_module = ModuleType("hypertest.application.cloud_ssh")
    authority_module.WorkerSshAuthority = Authority
    monkeypatch.setitem(sys.modules, "hypertest.application.cloud_ssh", authority_module)
    for name, value in (("CloudBroker", Broker), ("CloudTaskReporter", Reporter),
                        ("BubblewrapSandbox", Sandbox), ("ModelBroker", Model)):
        monkeypatch.setattr(worker_module, name, value)
    monkeypatch.setattr(ssh_module, "SshBroker", SSH)
    monkeypatch.setattr(tickets_module, "signer_public_key", lambda _: profile.authority_public_key)
    monkeypatch.setattr(worker_module, "inspect_ssh_client", lambda _: {})
    monkeypatch.setattr(worker_module, "read_ssh_authority", lambda _: b"private-signing-key-canary")
    monkeypatch.setattr(worker_module, "read_model_key", lambda _: b"private-model-key-canary")
    monkeypatch.setattr(worker_module, "inspect_sdk", lambda: {})
    monkeypatch.setattr(worker_module, "inspect_resource_envelope", lambda **_: {
        "kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024**3, "swap_max_bytes": 0, "pids_max": 256})
    worker = CloudWorker(None, settings, "fixture")
    async def checkout(resolved, destination, token):
        destination.mkdir()
        elapsed[0] = preparation_seconds
    async def consume(*args, **kwargs):
        return None
    async def collect(*args, **kwargs):
        handoff = Handoff(profile=MANIFEST_PROFILE, task_id=claim["task"]["id"],
            attempt_id=claim["attempt"]["id"], key="complete", operation="COMPLETE_ATTEMPT", payload={})
        return handoff, digest(handoff.model_dump(mode="json"))
    worker.resolver = SimpleNamespace(checkout=checkout)
    monkeypatch.setattr(worker, "consume_runtime", consume)
    monkeypatch.setattr(worker, "collect", collect)
    if preparation_seconds:
        with pytest.raises(CloudBlocked) as error:
            await worker.execute(claim)
        assert error.value.code == "SSH_CLEANUP_WINDOW_EXHAUSTED"
        assert "model-created" not in timeline and "ssh-start" not in timeline
        assert submitted[-1][1]["status"] == "FAILED"
        assert all(operation != "COMPLETE_ATTEMPT" for operation, _, _ in submitted)
        return
    if host_closed and canonical_closed:
        await worker.execute(claim)
        completed = [kwargs for operation, _, kwargs in submitted if operation == "COMPLETE_ATTEMPT"]
        assert len(completed) == 1 and completed[0]["external_operations_reconciled"] is True
        assert completed[0]["budget_settlement"]["namespace_stopped"] is True
    else:
        with pytest.raises(CloudBlocked) as error:
            await worker.execute(claim)
        assert error.value.code == "SSH_RECONCILIATION_REQUIRED"
        assert all(operation != "COMPLETE_ATTEMPT" for operation, _, _ in submitted)
        assert submitted[-1][1]["status"] == "RECOVERY_REQUIRED"
        assert all("budget_settlement" not in payload for _, payload, _ in submitted)
    if cutoff:
        assert timeline.index("ssh-close-root-running") < timeline.index("namespace-stop")
        assert timeline.index("ssh-close-root-running") < timeline.index("model-close")
    else:
        assert timeline.index("namespace-stop") < timeline.index("ssh-close")
        assert timeline.index("model-close") < timeline.index("ssh-close")
    files = list(Path(settings.cloud_runtime_root).rglob("*.json"))
    assert "private-ssh-key-canary" not in "".join(path.read_text() for path in files)
    assert "private-output-canary" not in "".join(path.read_text() for path in files)


def test_service_ssh_identity_uses_exact_loadcredential_leaf_and_stays_independent(tmp_path, monkeypatch):
    root = tmp_path / "credentials"
    directory = root / "worker.service"
    directory.mkdir(parents=True)
    monkeypatch.setattr(admission, "CREDENTIALS_ROOT", root)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(directory))
    settings = SimpleNamespace(cloud_codex_enabled=False, cloud_ssh_enabled=True,
        cloud_credential_key_file=str(directory / "wrapping-key"),
        cloud_model_key_file=str(directory / "deepseek-key"),
        cloud_ssh_authority_key_file=str(directory / "ssh-authority"))
    admission._credential_paths(settings)
    settings.cloud_ssh_authority_key_file = str(directory / "wrapping-key")
    with pytest.raises(CloudBlocked) as error:
        admission._credential_paths(settings)
    assert error.value.code == "WORKER_CREDENTIAL_PATH_MISMATCH"
    with pytest.raises(CloudBlocked) as error:
        admission.read_ssh_authority(settings)
    assert error.value.code == "WORKER_SSH_CONFIGURATION_INVALID"


def test_ssh_cleanup_failure_keeps_only_the_closed_stage_and_error_metadata():
    error = CloudBlocked("SSH_RECONCILIATION_REQUIRED", "fixed safe primary")
    attach_failure(error, {"type": "CloudBlocked", "frames": []}, [
        {"stage": "SSH_REMOTE_CLEANUP", "error": {"type": "TimeoutError", "frames": [],
            "stderr": "private-ssh-stderr-canary"}},
        {"stage": "private-arbitrary-stage", "error": {"type": "ValueError", "frames": []}},
    ])
    assert failure_metadata(error) == {"primary": {"type": "CloudBlocked", "frames": []},
        "secondary": [{"stage": "SSH_REMOTE_CLEANUP", "error": {"type": "TimeoutError", "frames": []}}]}
