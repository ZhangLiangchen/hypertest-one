"""Single-original Docker control semantics without a model or real credentials."""
import asyncio
import hashlib
import json
import time
from uuid import uuid4

import pytest
from test_cloud_docker_attempt_spec import candidate, inspect_fixture

from hypertest.cloud import docker_attempt, docker_attempt_spec
from hypertest.cloud.container_guard import authenticate_bootstrap, authenticate_heartbeat
from hypertest.cloud.docker_attempt import DockerAttempt, DockerEngine, DockerOriginalObservation
from hypertest.cloud.errors import CloudBlocked


def setup_attempt():
    spec = candidate()
    key = b"x" * 32
    spec["scope"]["key_sha256"] = hashlib.sha256(key).hexdigest()
    spec["spec_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in spec.items() if k != "spec_sha256"},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    scope = spec["scope"]
    intent = {**{k: scope[k] for k in ("project_id", "task_id", "attempt_id", "generation", "key_sha256", "clock_sha256")},
        "container_name": spec["container_name"], "image_id": spec["image_id"], "spec_sha256": spec["spec_sha256"],
        "hard_deadline": scope["deadline_epoch"], "state": "UNCONFIRMED", "container_id": None,
        "operation_key": "original-only"}
    return spec, key, intent


@pytest.fixture(autouse=True)
def linux_worker(monkeypatch):
    # The unit fake models a same-kernel Linux Worker/Agent pair.
    monkeypatch.setattr(docker_attempt.sys, "platform", "linux")
    monkeypatch.setattr(docker_attempt, "clock_domain_digest", lambda: "f" * 64)


class Writer:
    def __init__(self, on_close):
        self.data = bytearray()
        self.closed = False
        self.on_close = on_close

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        if not self.closed:
            self.on_close()
        self.closed = True


class Engine:
    def __init__(self, spec):
        self.raw = inspect_fixture(spec)
        self.raw["State"].update(Status="created", Running=False, Pid=0)
        self.calls = []
        self.reader = asyncio.StreamReader()
        self.auto_exit = True
        self.writer = Writer(self.disconnect)
        self.fail_create = False

    def disconnect(self):
        if self.auto_exit and self.raw["State"]["Status"] == "running":
            self.raw["State"].update(Status="exited", Running=False, Pid=0, ExitCode=70)
            self.reader.feed_eof()

    async def request(self, method, path, body=None):
        self.calls.append((method, path))
        if path.startswith("/containers/create?"):
            if self.fail_create:
                raise CloudBlocked("DOCKER_ENGINE_UNCONFIRMED", "unknown")
            return 201, {"Id": self.raw["Id"]}
        if path.endswith("/json"):
            return 200, self.raw
        if path.endswith("/start"):
            self.raw["State"].update(Status="running", Running=True, Pid=123)
            return 204, {}
        raise AssertionError(path)

    async def attach(self, container_id):
        assert container_id == self.raw["Id"]
        return self.reader, self.writer


def make(engine, spec, key, intent, *, bind=None, prepare=None, authority=None):
    async def default_bind(container_id, raw):
        assert container_id == raw["Id"]

    async def default_authority():
        return time.monotonic_ns() + 10_000_000_000

    async def envelope():
        return {identity: docker_attempt_spec.ResourceLimit(**limit)
                for identity, limit in spec["envelope"]["existing"].items()}

    return DockerAttempt(engine=engine, spec=spec, intent=intent, key=key, bind_id=bind or default_bind,
                         prepare_start=prepare or default_bind,
                         authority_window=authority or default_authority, observe_envelope=envelope)


def config(spec):
    return {"workspace": "/workspace", "dsh_home": "/home/agent/dsh", "session_id": "cloud-" + spec["scope"]["attempt_id"],
            "model": "deepseek-flash", "max_tokens": 100, "timeout_seconds": 30, "prompt": "fixture"}


@pytest.mark.asyncio
async def test_create_attach_authenticated_heartbeat_and_stop_original_id():
    spec, key, intent = setup_attempt()
    engine = Engine(spec)
    attempt = make(engine, spec, key, intent)
    assert await attempt.start(config(spec)) is attempt
    init, heartbeat, _ = bytes(engine.writer.data).split(b"\n", 2)
    scope = {**spec["scope"], "spec_sha256": spec["spec_sha256"]}
    actual_key, _ = authenticate_bootstrap(init, scope)
    assert actual_key == key
    assert authenticate_heartbeat(heartbeat, key=key, scope=scope, previous_seq=0, now_ns=time.monotonic_ns())[0] == 1
    stopped = await attempt.stop()
    assert stopped["local_processes_stopped"] and stopped["engine"]["container_id"] == "e" * 64
    assert stopped["engine"]["cgroup_independently_observed"] is False
    assert all("e" * 64 in path for method, path in engine.calls if "/json" in path)
    assert not any("/stop?" in path for _, path in engine.calls)
    with pytest.raises(CloudBlocked, match="reconciliation"):
        await attempt.start(config(spec))


@pytest.mark.asyncio
async def test_unknown_create_is_never_replayed_and_cannot_claim_stopped():
    spec, key, intent = setup_attempt()
    engine = Engine(spec)
    engine.fail_create = True
    attempt = make(engine, spec, key, intent)
    for action in (lambda: attempt.start(config(spec)), lambda: attempt.start(config(spec)), attempt.stop):
        with pytest.raises(CloudBlocked):
            await action()
    assert sum(path.startswith("/containers/create?") for _, path in engine.calls) == 1


@pytest.mark.asyncio
async def test_no_start_if_id_binding_or_authority_fails():
    spec, key, intent = setup_attempt()
    engine = Engine(spec)

    async def failed_bind(_container_id, _raw):
        raise CloudBlocked("DB_UNAVAILABLE", "unconfirmed")

    attempt = make(engine, spec, key, intent, bind=failed_bind)
    with pytest.raises(CloudBlocked):
        await attempt.start(config(spec))
    assert not any(path.endswith("/start") for _, path in engine.calls)

    engine = Engine(spec)

    async def expired():
        return time.monotonic_ns()

    attempt = make(engine, spec, key, intent, authority=expired)
    with pytest.raises(CloudBlocked):
        await attempt.start(config(spec))
    assert not engine.calls


@pytest.mark.asyncio
async def test_mismatched_clock_domain_never_creates(monkeypatch):
    spec, key, intent = setup_attempt()
    engine = Engine(spec)
    attempt = make(engine, spec, key, intent)
    monkeypatch.setattr(docker_attempt, "clock_domain_digest", lambda: "a" * 64)
    with pytest.raises(CloudBlocked) as error:
        await attempt.start(config(spec))
    assert error.value.code == "DOCKER_SHARED_CLOCK_UNAVAILABLE"
    assert not engine.calls


@pytest.mark.asyncio
async def test_start_intent_failure_never_sends_start():
    spec, key, intent = setup_attempt()
    engine = Engine(spec)

    async def failed_start_intent(_container_id, _raw):
        raise CloudBlocked("DB_UNAVAILABLE", "unconfirmed")

    attempt = make(engine, spec, key, intent, prepare=failed_start_intent)
    with pytest.raises(CloudBlocked):
        await attempt.start(config(spec))
    assert not any(path.endswith("/start") for _, path in engine.calls)
    assert engine.writer.closed


@pytest.mark.asyncio
async def test_lease_loss_closes_attach_and_surfaces_failure():
    spec, key, intent = setup_attempt()
    engine = Engine(spec)
    calls = 0

    async def authority():
        nonlocal calls
        calls += 1
        return time.monotonic_ns() + (10_000_000_000 if calls <= 4 else 0)

    attempt = make(engine, spec, key, intent, authority=authority)
    await attempt.start(config(spec))
    await asyncio.wait_for(attempt._heartbeat, 2)
    assert engine.writer.closed
    with pytest.raises(CloudBlocked) as error:
        await attempt.stdout.read()
    assert error.value.code == "DOCKER_LEASE_UNCONFIRMED"
    assert (await attempt.stop())["local_processes_stopped"]


@pytest.mark.asyncio
async def test_truncated_output_is_not_treated_as_clean_eof():
    spec, key, intent = setup_attempt()
    engine = Engine(spec)
    attempt = make(engine, spec, key, intent)
    await attempt.start(config(spec))
    engine.reader.feed_data(b"\x01\x00\x00\x00\x00\x00\x00\x05")
    engine.reader.feed_eof()
    with pytest.raises(CloudBlocked) as error:
        await asyncio.wait_for(attempt.stdout.read(), 2)
    assert error.value.code == "DOCKER_OUTPUT_UNCONFIRMED"
    assert (await attempt.stop())["local_processes_stopped"]


@pytest.mark.asyncio
async def test_unconfirmed_stop_only_inspects_original_id(monkeypatch):
    spec, key, intent = setup_attempt()
    engine = Engine(spec)
    engine.auto_exit = False
    monkeypatch.setattr(docker_attempt, "_STOP_TIMEOUT", 0.01)
    attempt = make(engine, spec, key, intent)
    await attempt.start(config(spec))
    for _ in range(2):
        with pytest.raises(CloudBlocked):
            await attempt.stop()
    assert not any("/stop?" in path for _, path in engine.calls)
    # A later exact-ID stopped observation may resolve the uncertainty.
    engine.raw["State"].update(Status="exited", Running=False, Pid=0)
    engine.reader.feed_eof()
    assert (await attempt.stop())["local_processes_stopped"]


@pytest.mark.asyncio
async def test_engine_admission_reads_have_fixed_shapes_and_reject_ambiguous_inputs(monkeypatch):
    engine = DockerEngine("/run/docker.sock")
    identity = "a" * 64
    calls = []

    async def exchange(method, path, body=None):
        calls.append((method, path))
        if path.startswith("/containers/json?"):
            return 200, [{"Id": identity}]
        if path.startswith("/containers/"):
            return 200, {"Id": identity}
        if path.startswith("/images/"):
            return 200, {"Id": "sha256:" + identity}
        if path.startswith("/volumes/"):
            return 200, {"Name": "private-volume"}
        raise AssertionError

    monkeypatch.setattr(engine, "_exchange", exchange)
    assert (await engine.inspect_container(identity[:12]))["Id"] == identity
    assert (await engine.inspect_image("sha256:" + identity))["Id"].endswith(identity)
    assert (await engine.inspect_volume("private-volume"))["Name"] == "private-volume"
    assert await engine.list_attempts() == [identity]
    count = len(calls)
    for action in (lambda: engine.inspect_container("../other"), lambda: engine.inspect_volume("../other"),
                   lambda: engine.inspect_image("latest")):
        with pytest.raises(CloudBlocked):
            await action()
    assert len(calls) == count


@pytest.mark.asyncio
async def test_original_name_recovery_is_read_only_and_rejects_replacement():
    spec, _key, intent = setup_attempt()
    intent["spec"] = spec
    receipt = {"status": "ACCEPTED", "operation": "PREPARE_CONTAINER_CREATE",
               "operation_key": intent["operation_key"], "project_id": intent["project_id"],
               "task_id": intent["task_id"], "attempt_id": intent["attempt_id"], "container_create_intent": intent}
    raw = inspect_fixture(spec)

    class OriginalEngine:
        async def inspect_original_name(self, name):
            assert name == spec["container_name"]
            return raw

        async def inspect_container(self, identity):
            assert identity == raw["Id"]
            return raw

    original = DockerOriginalObservation(engine=OriginalEngine(), receipt=receipt)
    with pytest.raises(CloudBlocked):
        await original.inspect_raw_id("e" * 64)
    assert (await original.inspect_raw())["Id"] == "e" * 64
    assert (await original.inspect_raw_id("e" * 64))["Id"] == "e" * 64
    raw["Id"] = "f" * 64
    with pytest.raises(CloudBlocked):
        await original.inspect_raw()
    assert not hasattr(original, "start") and not hasattr(original, "stop")
    bad = {**receipt, "task_id": str(uuid4())}
    with pytest.raises(CloudBlocked):
        DockerOriginalObservation(engine=OriginalEngine(), receipt=bad)
