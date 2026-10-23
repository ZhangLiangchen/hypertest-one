"""SSH safety contracts; real signatures/state files, inert manager/transport seams.

These tests do not claim real OpenSSH or systemd acceptance. The separate
authorized loopback fixture exercises those production boundaries.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hypertest.cloud import ssh_broker, ssh_client, ssh_remote
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.ssh_broker import OpenSSHTransport, SshBroker
from hypertest.cloud.ssh_profile import (
    SSH_ACCESS_PROFILE,
    TERMINAL_STATES,
    canonical_bytes,
    canonical_target,
    digest,
    project_observation,
    request_document,
    unit_name,
    validate_profile,
)
from hypertest.cloud.ssh_tickets import sign_ticket, signer_public_key, verify_ticket


def private_key():
    return Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())


@pytest.fixture
def fixture_profile():
    signing, login, host = private_key(), private_key(), private_key()
    program = b"#!/bin/sh\nprintf 'fixture-only\\n'\n"
    action = {"key": "read-deployment", "script_path": "/opt/hypertest-ssh/actions/read-deployment",
        "script_sha256": hashlib.sha256(program).hexdigest(), "timeout_seconds": 1,
        "stdout_limit_bytes": 65536, "stderr_limit_bytes": 65536}
    catalog = {"profile": SSH_ACCESS_PROFILE, "target": "ssh://fixture@127.0.0.1:2222",
        "helper_sha256": ssh_remote.helper_sha256(), "authority_public_key": signer_public_key(signing),
        "actions": [action], "max_operations": 8}
    environment = {"connection": "SSH", "host": "127.0.0.1", "port": 2222, "user": "fixture",
        "host_key": signer_public_key(host), "ssh_access": {k: v for k, v in catalog.items() if k != "target"}}
    environment["ssh_access"]["catalog_sha256"] = digest(catalog)
    return SimpleNamespace(profile=validate_profile(environment), environment=environment,
                           signing=signing, login=login, program=program)


def request_for(fixture, *, generation=1, operation_id=None, attempt_id=None):
    return request_document(operation_id=operation_id or str(uuid4()), task_id=str(uuid4()),
        attempt_id=attempt_id or str(uuid4()), generation=generation, target=fixture.profile.target,
        helper_sha256=fixture.profile.helper_sha256, catalog_sha256=fixture.profile.catalog_sha256,
        action=fixture.profile.actions[0].document(), hard_deadline=int(time.time()) + 120)


def test_literal_target_and_full_pinned_public_key(fixture_profile):
    profile = fixture_profile.profile
    assert profile.target == "ssh://fixture@127.0.0.1:2222"
    assert canonical_target("::1", 2222, "fixture") == "ssh://fixture@[::1]:2222"
    assert profile.catalog_sha256 == digest(profile.catalog_document())
    assert signer_public_key(fixture_profile.login) != profile.authority_public_key


@pytest.mark.parametrize("field,value", [("host", "example.org"), ("host", "127.000.0.1"),
    ("user", "root"), ("user", "-oProxyCommand"), ("port", True), ("port", None),
    ("host_key", "SHA256:not-a-complete-host-key")])
def test_ambient_or_incomplete_ssh_target_is_not_executable(fixture_profile, field, value):
    environment = json.loads(json.dumps(fixture_profile.environment))
    environment[field] = value
    with pytest.raises(CloudBlocked):
        validate_profile(environment)


@pytest.mark.parametrize("field,value", [("script_path", "/bin/sh"), ("timeout_seconds", 31),
    ("stdout_limit_bytes", 65537), ("stderr_limit_bytes", 65537), ("args", ["unapproved"])])
def test_action_scope_is_fixed_without_shell_arguments(fixture_profile, field, value):
    environment = json.loads(json.dumps(fixture_profile.environment))
    environment["ssh_access"]["actions"][0][field] = value
    with pytest.raises(CloudBlocked):
        validate_profile(environment)


def test_ticket_binds_verb_request_target_and_expiry(fixture_profile):
    request = request_for(fixture_profile)
    now = int(time.time())
    ticket = sign_ticket(fixture_profile.signing, request, verb="START", generation=1,
                         expires_at=now + 30, now=now)
    assert verify_ticket(ticket, request, fixture_profile.profile.authority_public_key, now=now)["verb"] == "START"
    changed = json.loads(json.dumps(ticket))
    changed["claims"]["verb"] = "STOP"
    with pytest.raises(CloudBlocked):
        verify_ticket(changed, request, fixture_profile.profile.authority_public_key, now=now)
    with pytest.raises(CloudBlocked) as error:
        verify_ticket(ticket, request, fixture_profile.profile.authority_public_key, now=now + 31)
    assert error.value.code == "SSH_TICKET_EXPIRED"
    request["target"] = "ssh://fixture@127.0.0.1:2223"
    with pytest.raises(CloudBlocked):
        verify_ticket(ticket, request, fixture_profile.profile.authority_public_key, now=now)


def test_cleanup_ticket_does_not_extend_original_deadline(fixture_profile):
    request = request_for(fixture_profile)
    now = int(time.time())
    request["hard_deadline"] = now - 10
    for verb in ("QUERY", "STOP"):
        ticket = sign_ticket(fixture_profile.signing, request, verb=verb, generation=2,
                             expires_at=now + 30, now=now)
        claims = verify_ticket(ticket, request, fixture_profile.profile.authority_public_key, now=now)
        assert claims["hard_deadline"] == now - 10
    with pytest.raises(CloudBlocked):
        sign_ticket(fixture_profile.signing, request, verb="START", generation=2, expires_at=now + 30, now=now)


def test_pkcs8_authority_keeps_same_public_identity_without_key_recreation():
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    openssh = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
    assert signer_public_key(pem) == signer_public_key(openssh)


class Manager:
    def __init__(self):
        self.values = None
        self.starts = 0
        self.stops = 0
        self.populated = False

    def start(self, request, root, *, lifetime):
        assert 1 <= lifetime <= 30
        self.starts += 1
        self.values = {"LoadState": "loaded", "ActiveState": "active", "SubState": "exited",
            "InvocationID": uuid4().hex, "ControlGroup": f"/user.slice/user-{os.geteuid()}.slice/app.slice/" + unit_name(request["operation_id"]),
            "Result": "success", "ExecMainCode": "1", "ExecMainStatus": "0",
            "Description": "hypertest-ssh:" + digest(request)}
        ssh_remote._write(root / "execution-identity.json", {"request_digest": digest(request),
            "boot_id": "00000000-0000-0000-0000-000000000001", "invocation_id": self.values["InvocationID"],
            "unit": unit_name(request["operation_id"]), "uid": os.geteuid(), "control_group": self.values["ControlGroup"]})
        for name, raw in (("stdout", b"fixture-only\n"), ("stderr", b"")):
            path = root / (name + ".raw")
            path.write_bytes(raw)
            path.chmod(0o600)
        ssh_remote._write(root / "command-result.json", {"request_digest": digest(request),
            "invocation_id": self.values["InvocationID"], "boot_id": "00000000-0000-0000-0000-000000000001",
            "started_at": int(time.time()), "exit_code": 0, "signal": None, "output_limit": False})

    def inspect(self, request):
        return self.values or {"LoadState": "not-found"}

    def empty(self, values, *, allow_removed=False):
        return not self.populated

    def stop(self, request):
        self.stops += 1
        self.populated = False
        self.values = dict(self.values, ActiveState="inactive", SubState="dead")


@pytest.fixture
def remote(tmp_path, fixture_profile):
    root = tmp_path.resolve()
    catalog = root / "catalog.json"
    catalog.write_text(json.dumps(fixture_profile.environment))
    catalog.chmod(0o444)
    state = root / "state"
    state.mkdir(mode=0o700)
    manager = Manager()
    controller = ssh_remote.RemoteController(catalog_path=catalog, state_root=state, manager=manager,
        boot_id="00000000-0000-0000-0000-000000000001", script_reader=lambda _: fixture_profile.program)
    return SimpleNamespace(controller=controller, manager=manager, root=state, fixture=fixture_profile)


def exchange(remote, request, verb="START", *, generation=None):
    now = int(time.time())
    ticket = sign_ticket(remote.fixture.signing, request, verb=verb,
        generation=generation or request["generation"], expires_at=now + 30, now=now)
    return remote.controller.exchange({"request": request, "ticket": ticket})


def test_remote_original_id_query_and_duplicate_never_launch_twice(remote):
    request = request_for(remote.fixture)
    first = exchange(remote, request)
    assert first["observation"]["state"] == "COMPLETED"
    assert first["observation"]["remote_stopped"] is True
    assert base64.b64decode(first["stdout_base64"]) == b"fixture-only\n"
    assert exchange(remote, request, "QUERY") == first
    assert exchange(remote, request, "START") == first
    assert remote.manager.starts == 1
    root = remote.root / ("attempt-" + request["attempt_id"]) / request["operation_id"]
    assert json.loads((root / "request.json").read_bytes()) == request
    assert json.loads((root / "terminal.json").read_bytes()) == first["observation"]


def test_query_not_found_does_not_register_or_start(remote):
    request = request_for(remote.fixture)
    result = exchange(remote, request, "QUERY")
    assert result["observation"]["state"] == "NOT_FOUND"
    assert result["observation"]["remote_stopped"] is False
    assert remote.manager.starts == 0
    assert not (remote.root / ("attempt-" + request["attempt_id"]) / request["operation_id"]).exists()


def test_remote_monotonic_generation_rejects_delayed_old_start(remote):
    request = request_for(remote.fixture)
    exchange(remote, request, "QUERY", generation=2)
    with pytest.raises(CloudBlocked) as error:
        exchange(remote, request, "START", generation=1)
    assert error.value.code == "SSH_REMOTE_FENCED"
    assert remote.manager.starts == 0


def test_registration_launch_crash_gap_is_query_only(remote, monkeypatch):
    request = request_for(remote.fixture)
    monkeypatch.setattr(remote.manager, "start", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private-path-canary")))
    with pytest.raises(OSError):
        exchange(remote, request)
    observed = exchange(remote, request, "QUERY")["observation"]
    assert observed["state"] == "UNKNOWN" and not observed["remote_stopped"]
    assert exchange(remote, request, "START")["observation"]["state"] == "UNKNOWN"
    assert remote.manager.starts == 0


def test_changed_request_cannot_reuse_registered_identity(remote):
    request = request_for(remote.fixture)
    exchange(remote, request)
    request["hard_deadline"] += 1
    with pytest.raises(CloudBlocked):
        exchange(remote, request)
    assert remote.manager.starts == 1


def test_unit_identity_and_empty_cgroup_are_independent_of_parent_exit(remote):
    request = request_for(remote.fixture)
    remote.manager.populated = True
    observed = exchange(remote, request)["observation"]
    assert observed["state"] == "RUNNING" and observed["remote_stopped"] is False
    old = remote.manager.values["InvocationID"]
    remote.manager.values["InvocationID"] = uuid4().hex
    result = exchange(remote, request, "STOP")["observation"]
    assert result["state"] == "UNKNOWN" and result["reason"] == "IDENTITY_CHANGED"
    assert remote.manager.stops == 0
    remote.manager.values["InvocationID"] = old
    stopped = exchange(remote, request, "STOP")["observation"]
    assert stopped["state"] == "CANCELLED" and stopped["remote_stopped"] is True


def test_retained_exited_unit_with_cleared_current_cgroup_uses_durable_original_scope(remote):
    request = request_for(remote.fixture)
    remote.manager.populated = True
    first = exchange(remote, request)["observation"]
    assert first["state"] == "RUNNING"
    root = remote.root / ("attempt-" + request["attempt_id"]) / request["operation_id"]
    original = json.loads((root / "execution-identity.json").read_bytes())
    remote.manager.values["ControlGroup"] = ""
    remote.manager.populated = False
    result = exchange(remote, request, "QUERY")["observation"]
    assert result["state"] == "COMPLETED" and result["remote_stopped"] is True
    assert result["remote_identity"] == first["remote_identity"]
    proof = json.loads((root / "stop-proof.json").read_bytes())
    assert proof["before"]["ControlGroup"] == ""
    assert proof["before"]["OriginalControlGroup"] == original["control_group"]
    assert proof["before"]["ExecutionIdentitySHA256"] == hashlib.sha256((root / "execution-identity.json").read_bytes()).hexdigest()
    assert proof["stop_job_ack"] is proof["cgroup_empty"] is True
    assert remote.manager.starts == remote.manager.stops == 1
    assert exchange(remote, request, "QUERY")["observation"] == result


@pytest.mark.parametrize("mutation", ["boot", "invocation", "description", "different-current-group", "wrong-saved-group"])
def test_empty_manager_group_does_not_relax_exact_scope_identity(remote, mutation):
    request = request_for(remote.fixture)
    remote.manager.populated = True
    exchange(remote, request)
    root = remote.root / ("attempt-" + request["attempt_id"]) / request["operation_id"]
    remote.manager.values["ControlGroup"] = ""
    if mutation == "boot":
        remote.controller.boot_id = str(uuid4())
    elif mutation == "invocation":
        remote.manager.values["InvocationID"] = uuid4().hex
    elif mutation == "description":
        remote.manager.values["Description"] = "hypertest-ssh:" + "0" * 64
    elif mutation == "different-current-group":
        remote.manager.values["ControlGroup"] = f"/user.slice/user-{os.geteuid()}.slice/replaced.service"
    else:
        path = root / "execution-identity.json"
        value = json.loads(path.read_bytes())
        value["control_group"] = "/user.slice/../system.slice/forged.service"
        path.write_bytes(canonical_bytes(value))
    remote.manager.populated = False
    if mutation == "boot":
        with pytest.raises(CloudBlocked):
            exchange(remote, request, "QUERY")
    else:
        observed = exchange(remote, request, "QUERY")["observation"]
        assert observed["state"] == "UNKNOWN" and observed["remote_stopped"] is False
    assert remote.manager.stops == 0 and not (root / "terminal.json").exists()


def test_legacy_identity_without_original_scope_is_not_backfilled_or_closed(remote):
    request = request_for(remote.fixture)
    remote.manager.populated = True
    exchange(remote, request)
    root = remote.root / ("attempt-" + request["attempt_id"]) / request["operation_id"]
    original_identity = (root / "identity.json").read_bytes()
    (root / "execution-identity.json").unlink()
    remote.manager.values["ControlGroup"] = ""
    remote.manager.populated = False
    for verb in ("QUERY", "STOP"):
        observed = exchange(remote, request, verb)["observation"]
        assert observed["state"] == "UNKNOWN" and not observed["remote_stopped"]
    assert remote.manager.starts == 1 and remote.manager.stops == 0
    assert not (root / "execution-identity.json").exists()
    assert not (root / "stop-proof.json").exists() and not (root / "terminal.json").exists()
    assert (root / "identity.json").read_bytes() == original_identity


def test_scope_record_alone_does_not_replace_durable_command_exit(remote):
    request = request_for(remote.fixture)
    remote.manager.populated = True
    exchange(remote, request)
    root = remote.root / ("attempt-" + request["attempt_id"]) / request["operation_id"]
    (root / "command-result.json").unlink()
    remote.manager.values["ControlGroup"] = ""
    remote.manager.populated = False
    observed = exchange(remote, request, "QUERY")["observation"]
    assert observed["state"] == "UNKNOWN" and not observed["remote_stopped"]
    assert remote.manager.stops == 0 and not (root / "stop-proof.json").exists()


@pytest.mark.parametrize("shape", ["valid", "wrong-user", "wrong-unit", "traversal", "multiple-controllers", "non-unified"])
def test_wrapper_accepts_only_its_kernel_observed_unified_user_unit_scope(fixture_profile, shape):
    request = request_for(fixture_profile)
    group = "/user.slice/user-996.slice/user@996.service/app.slice/" + unit_name(request["operation_id"])
    if shape == "wrong-user":
        group = group.replace("user-996.slice", "user-995.slice")
    elif shape == "wrong-unit":
        group = group.replace(unit_name(request["operation_id"]), "unrelated.service")
    elif shape == "traversal":
        group = group.replace("/app.slice/", "/app.slice/../")
    text = "0::" + group + "\n"
    if shape == "multiple-controllers":
        text += "1:memory:/unrelated\n"
    elif shape == "non-unified":
        text = "1:memory:" + group + "\n"
    if shape == "valid":
        scope = ssh_remote._execution_identity(request, "a" * 32, boot_id="00000000-0000-0000-0000-000000000001", cgroup_text=text, uid=996)
        assert scope["control_group"] == group and scope["request_digest"] == digest(request)
    else:
        with pytest.raises(CloudBlocked):
            ssh_remote._execution_identity(request, "a" * 32, boot_id="00000000-0000-0000-0000-000000000001", cgroup_text=text, uid=996)


@pytest.mark.parametrize("failure", ["stop-error", "still-active", "new-invocation", "show-error"])
def test_terminal_is_not_sealed_before_acknowledged_matching_stop(remote, monkeypatch, failure):
    request = request_for(remote.fixture)
    original_stop = remote.manager.stop
    original_inspect = remote.manager.inspect
    if failure == "stop-error":
        monkeypatch.setattr(remote.manager, "stop", lambda _: (_ for _ in ()).throw(TimeoutError()))
    elif failure == "still-active":
        monkeypatch.setattr(remote.manager, "stop", lambda _: None)
    elif failure == "new-invocation":
        def replacement_stop(value):
            original_stop(value)
            remote.manager.values["InvocationID"] = uuid4().hex
        monkeypatch.setattr(remote.manager, "stop", replacement_stop)
    else:
        def replacement_inspect(value):
            if remote.manager.stops:
                raise OSError("private-manager-canary")
            return original_inspect(value)
        monkeypatch.setattr(remote.manager, "inspect", replacement_inspect)
    result = exchange(remote, request)["observation"]
    root = remote.root / ("attempt-" + request["attempt_id"]) / request["operation_id"]
    assert result["state"] == "UNKNOWN" and result["remote_stopped"] is False
    assert not (root / "terminal.json").exists()


def test_gc_after_exact_stop_ack_keeps_durable_positive_proof(remote, monkeypatch):
    request = request_for(remote.fixture)
    original_stop = remote.manager.stop
    def gc_stop(value):
        original_stop(value)
        remote.manager.values = {"LoadState": "not-found"}
    monkeypatch.setattr(remote.manager, "stop", gc_stop)
    result = exchange(remote, request)["observation"]
    assert result["state"] == "COMPLETED" and result["remote_stopped"] is True
    root = remote.root / ("attempt-" + request["attempt_id"]) / request["operation_id"]
    proof = json.loads((root / "stop-proof.json").read_bytes())
    assert proof["stop_job_ack"] is proof["cgroup_empty"] is True
    assert proof["post_state"] == "not-found"
    # A terminal-write crash is recoverable by QUERY from the durable proof;
    # neither a new unit nor another START is necessary.
    (root / "terminal.json").unlink()
    assert exchange(remote, request, "QUERY")["observation"]["state"] == "COMPLETED"
    assert remote.manager.starts == 1 and remote.manager.stops == 1


@pytest.mark.parametrize("invocation", [None, "", "not-a-systemd-invocation", "a" * 33])
def test_action_runner_requires_the_preserved_systemd_invocation(tmp_path, monkeypatch, invocation):
    if invocation is None:
        monkeypatch.delenv("INVOCATION_ID", raising=False)
    else:
        monkeypatch.setenv("INVOCATION_ID", invocation)
    with pytest.raises(CloudBlocked) as error:
        ssh_remote.run_unit(tmp_path, tmp_path / "never-read-catalog")
    assert error.value.code == "SSH_REMOTE_INVOCATION_UNAVAILABLE"


@pytest.mark.parametrize("wrapper_path", ["/opt/hypertest-ssh/bin/unit", "/opt/hypertest-ssh/versions/r29/bin/unit"])
def test_manager_invokes_readonly_identity_preserving_wrapper_without_collect(remote, monkeypatch, tmp_path, wrapper_path):
    manager = ssh_remote.SystemdUserManager.__new__(ssh_remote.SystemdUserManager)
    manager.unit_wrapper = Path(wrapper_path)
    manager.catalog_path = tmp_path / "catalog"
    commands = []
    monkeypatch.setattr(manager, "_run", lambda command: commands.append(command))
    original_read = ssh_remote._read
    monkeypatch.setattr(ssh_remote, "_read", lambda path, *a, **kw:
        b"readonly fixture wrapper" if path == Path(wrapper_path) else original_read(path, *a, **kw))
    manager.start(request_for(remote.fixture), tmp_path, lifetime=1)
    command = commands[0]
    assert "--collect" not in command and "--property=RemainAfterExit=yes" in command
    assert wrapper_path in command and "/usr/bin/env" not in command
    wrapper = (Path(__file__).parents[1] / "ops/deepseek/ssh-unit.in").read_text()
    assert 'INVOCATION_ID="$INVOCATION_ID"' in wrapper and '/usr/bin/env -i' in wrapper


@pytest.mark.parametrize("path", ["/tmp/unit", "/bin/sh", "/opt/hypertest-ssh/versions/../bin/unit",
    "/opt/hypertest-ssh/versions/r29/bin/other", "/opt/hypertest-ssh/versions/r29/child/bin/unit",
    "/opt/hypertest-ssh/versions/-option/bin/unit"])
def test_host_wrapper_selector_cannot_become_an_agent_executable(path, monkeypatch):
    monkeypatch.setattr(ssh_remote, "_read", lambda *args, **kwargs: pytest.fail("outside wrapper root must fail before read"))
    with pytest.raises(CloudBlocked) as error:
        ssh_remote._trusted_unit_wrapper(Path(path))
    assert error.value.code == "SSH_REMOTE_WRAPPER_UNTRUSTED"


def test_readonly_remote_inputs_reject_symlink_or_writable_files(tmp_path):
    root = tmp_path.resolve()
    path = root / "input"
    path.write_bytes(b"public fixture")
    with pytest.raises(CloudBlocked):
        ssh_remote._read(path, 128, immutable=True)
    path.chmod(0o444)
    assert ssh_remote._read(path, 128, immutable=True) == b"public fixture"
    link = root / "alias"
    link.symlink_to(path)
    with pytest.raises(CloudBlocked):
        ssh_remote._read(link, 128, immutable=True)


class Authority:
    def __init__(self, request):
        self.record = {"id": request["operation_id"], "request": request, "request_digest": digest(request),
            "generation": request["generation"], "lease_expires_at": int(time.time()) + 60,
            "ticket_expires_at": int(time.time()) + 60, "allow_send": True}
        self.observations = []
        self.admitted = False
        self.revoked = False
        self.secret = False

    async def prepare_start(self, key, action_key):
        assert action_key == self.record["request"]["action"]["key"]
        record = dict(self.record, allow_send=not self.admitted)
        self.admitted = True  # Represents a committed SENT transaction.
        return record

    async def admit_control(self, operation_id, verb):
        assert operation_id == self.record["id"] and verb in {"QUERY", "STOP"}
        if self.revoked:
            raise CloudBlocked("SSH_CREDENTIAL_REVOKED", "fixture refusal")
        return dict(self.record, allow_send=False, ticket_expires_at=int(time.time()) + 60)

    async def record_observation(self, operation_id, observation):
        assert operation_id == self.record["id"]
        self.observations.append(observation)

    async def validate_output(self, stdout, stderr):
        if self.secret:
            raise CloudBlocked("SECRET_MATERIAL", "fixture refusal")

    async def remote_closed(self):
        return bool(self.observations and self.observations[-1]["remote_stopped"])


class Transport:
    def __init__(self, remote, authority, *, lose_ack=False):
        self.remote, self.authority, self.lose_ack = remote, authority, lose_ack
        self.verbs = []

    async def exchange(self, request, ticket, *, timeout):
        assert self.authority.admitted, "no wire I/O before canonical SENT"
        verb = ticket["claims"]["verb"]
        self.verbs.append(verb)
        result = self.remote.controller.exchange({"request": request, "ticket": ticket})
        if verb == "START" and self.lose_ack:
            self.lose_ack = False
            raise TimeoutError
        return result


@pytest.mark.asyncio
async def test_lost_ack_keeps_original_operation_query_only(remote, tmp_path):
    request = request_for(remote.fixture)
    authority = Authority(request)
    transport = Transport(remote, authority, lose_ack=True)
    broker = SshBroker(tmp_path / "broker.sock", profile=remote.fixture.profile, authority=authority,
        ssh_key=remote.fixture.login, signing_key=remote.fixture.signing,
        private_root=tmp_path.resolve() / "host-private", deadline=request["hard_deadline"], transport=transport)
    await broker.start()
    first = await broker.invoke("original-key", "read-deployment")
    assert first["status"] == "UNKNOWN"
    result = await broker.invoke("original-key", "read-deployment")
    assert result["observation"]["state"] == "COMPLETED"
    assert transport.verbs == ["START", "QUERY"]
    assert remote.manager.starts == 1
    observed = await broker.close()
    assert observed["closed"] and observed["remote_closed"] and observed["pending_operations"] == []


@pytest.mark.asyncio
async def test_credential_revocation_prevents_cleanup_transport_and_keeps_unknown(remote, tmp_path):
    request = request_for(remote.fixture)
    authority = Authority(request)
    transport = Transport(remote, authority, lose_ack=True)
    broker = SshBroker(tmp_path / "broker.sock", profile=remote.fixture.profile, authority=authority,
        ssh_key=remote.fixture.login, signing_key=remote.fixture.signing,
        private_root=tmp_path.resolve() / "host-private", deadline=request["hard_deadline"], transport=transport)
    await broker.start()
    assert (await broker.invoke("original-key", "read-deployment"))["status"] == "UNKNOWN"
    authority.revoked = True
    observed = await broker.close()
    assert transport.verbs == ["START"]
    assert observed["remote_closed"] is False and observed["pending_operations"] == [request["operation_id"]]


@pytest.mark.asyncio
async def test_actual_uds_client_and_output_secret_gate(remote, tmp_path, monkeypatch):
    request = request_for(remote.fixture)
    authority = Authority(request)
    authority.secret = True
    transport = Transport(remote, authority)
    socket = tmp_path.resolve() / "broker.sock"
    broker = SshBroker(socket, profile=remote.fixture.profile, authority=authority,
        ssh_key=remote.fixture.login, signing_key=remote.fixture.signing,
        private_root=tmp_path.resolve() / "host-private", deadline=request["hard_deadline"], transport=transport)
    await broker.start()
    monkeypatch.setattr(ssh_client, "SSH_SOCKET", str(socket))
    result = await ssh_client.request({"verb": "INVOKE", "key": "original-key", "action_key": "read-deployment"})
    assert result["status"] == "REFUSED" and "stdout_base64" not in result
    assert result["observation"]["remote_stopped"] is True
    assert (await broker.close())["remote_closed"] is True


@pytest.mark.asyncio
async def test_close_before_start_has_no_transport_or_socket_effect(remote, tmp_path):
    request = request_for(remote.fixture)
    authority = Authority(request)
    transport = Transport(remote, authority)
    socket = tmp_path / "not-owned.sock"
    socket.write_text("pre-existing canary")
    broker = SshBroker(socket, profile=remote.fixture.profile, authority=authority,
        ssh_key=remote.fixture.login, signing_key=remote.fixture.signing,
        private_root=tmp_path.resolve() / "never-created", deadline=request["hard_deadline"], transport=transport)
    await broker.close()
    assert not (tmp_path / "never-created").exists()
    assert socket.read_text() == "pre-existing canary" and transport.verbs == []


def test_openssh_argv_has_no_ambient_auth_or_forwarding(remote, tmp_path, monkeypatch):
    monkeypatch.setattr(ssh_broker, "_binary", lambda path, sha: Path("/usr/bin/ssh"))
    root = tmp_path.resolve() / "transport"
    root.mkdir(mode=0o700)
    transport = OpenSSHTransport(executable=Path("/usr/bin/ssh"), executable_sha256="fixture-only",
        profile=remote.fixture.profile, private_root=root, ssh_key=remote.fixture.login)
    command = transport.argv()
    assert command[-1] == "/opt/hypertest-ssh/bin/control"
    assert "IdentityAgent=none" in command and "ClearAllForwardings=yes" in command
    assert "StrictHostKeyChecking=yes" in command and "ProxyCommand=none" in command
    assert "ControlMaster=no" in command and "PasswordAuthentication=no" in command
    assert command[1:3] == ["-F", "none"]
    assert stat_mode(root / "identity") == 0o600
    transport.close()
    assert not (root / "identity").exists()


def stat_mode(path):
    return path.stat().st_mode & 0o777


def test_stop_proof_cannot_be_synthesized_from_local_shutdown(remote):
    request = request_for(remote.fixture)
    value = exchange(remote, request, "QUERY")["observation"]
    value.update(remote_stopped=True, state="COMPLETED")
    with pytest.raises(CloudBlocked):
        project_observation(value, request)


def test_unknown_or_terminal_output_metadata_never_contains_arbitrary_fields(remote):
    request = request_for(remote.fixture)
    value = exchange(remote, request)["observation"]
    assert value["state"] in TERMINAL_STATES
    value["raw_exception"] = "secret-canary"
    with pytest.raises(CloudBlocked):
        project_observation(value, request)
