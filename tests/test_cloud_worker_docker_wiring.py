"""Docker profile is available only through a trusted, closed admission path."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.cloud import worker
from hypertest.cloud.errors import CloudBlocked
from hypertest.sync_core import digest


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass


class Runtime:
    async def admit(self):
        pytest.fail("Docker runtime must not be admitted for a rejected configuration")


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,codex,expected", [
    (False, False, "DOCKER_ADMISSION_UNAVAILABLE"),
    (True, True, "DOCKER_DELEGATION_UNSUPPORTED"),
])
async def test_no_docker_claim_before_profile_and_delegation_admission(monkeypatch, enabled, codex, expected):
    async def expire(_db):
        pass

    monkeypatch.setattr(worker.service, "expire_leases", expire)
    monkeypatch.setattr(worker.service, "CONTAINER_CREATE_INTENT_ENABLED", enabled)
    monkeypatch.setattr(worker, "inspect_resource_envelope", lambda: {})
    settings = SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True, cloud_ssh_enabled=False,
                               cloud_codex_enabled=codex)
    instance = worker.CloudWorker(Session, settings, "fixture", docker_runtime=Runtime())
    with pytest.raises(CloudBlocked) as error:
        await instance.run_once()
    assert error.value.code == expected


@pytest.mark.asyncio
async def test_direct_execute_cannot_bypass_docker_admission(monkeypatch):
    monkeypatch.setattr(worker.service, "CONTAINER_CREATE_INTENT_ENABLED", True)
    instance = worker.CloudWorker(lambda: pytest.fail("database reached"), None, "fixture", docker_runtime=Runtime())
    with pytest.raises(CloudBlocked) as error:
        await instance.execute({})
    assert error.value.code == "DOCKER_ADMISSION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_docker_worker_uses_shared_checkout_and_stops_before_model_drain(monkeypatch, tmp_path):
    events = []
    task_id, project_id, attempt_id = (str(uuid4()) for _ in range(3))
    now = datetime.now(UTC)
    manifest = {"inputs": {"authorization": {"network_targets": [], "permitted_actions": ["git:read", "framework:execute"],
        "expires_at": (now + timedelta(minutes=5)).isoformat()}, "budgets": {"total_seconds": 60}},
        "configuration": {"environment": {"connection": "NONE"}},
        "resolution": {"repositories": {"sut": {}, "framework": {}}}}
    claim = {"task": {"id": task_id, "project_id": project_id, "version": 1,
                      "frozen_manifest": manifest, "input_digest": digest(manifest)},
             "attempt": {"id": attempt_id, "input_digest": digest(manifest), "checkpoint": {},
                         "runtime_metadata": {"preparation_budget_reservation": {"claimed_at": now.isoformat()}}},
             "budget_remaining": {"seconds": 60, "cost_microunits": 10}}

    class Broker:
        def __init__(self, _sessions, _claim, _worker_id):
            self.task_id, self.project_id, self.attempt_id = task_id, project_id, attempt_id
            self.identity = SimpleNamespace(generation=1)

        async def assert_current(self):
            pass

        async def credentials(self):
            return {}

    class Reporter:
        def __init__(self, **_kwargs):
            self.version = 1

        async def recover(self):
            pass

        async def submit_handoff(self, handoff, _digest, **_kwargs):
            events.append("report:" + handoff.operation)
            return SimpleNamespace(synced=True, receipt={})

        def pending(self):
            return []

        def close(self):
            pass

    class Model:
        requests = 0
        closed = False

        def __init__(self, path, **_kwargs):
            assert path == layout.broker / "model.sock"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True
            events.append("model-drain")

        def observation(self):
            return {"closed": self.closed, "drained": self.closed, "inflight": 0, "requests": 0}

    class Process:
        returncode = None

        class Stream:
            async def readline(self):
                return b""

        stdout = Stream()

        async def wait(self):
            return self.returncode

    process = Process()

    class Sandbox:
        async def start(self, _config):
            events.append("sandbox-start")
            return process

        async def stop(self):
            process.returncode = 0
            events.append("sandbox-stop")
            return {"local_processes_stopped": True, "runtime_started": True}

    class Docker:
        def layout(self, _task, _attempt):
            return layout

        def sandbox(self, **kwargs):
            assert kwargs["layout"] is layout and kwargs["expected_sockets"] == ("model.sock",)
            return Sandbox()

    root = tmp_path / "shared"
    root.mkdir()
    for name in ("sut", "framework", "dsh-home", "broker"):
        (root / name).mkdir(mode=0o700)
    layout = SimpleNamespace(workspace=root, dsh_home=root / "dsh-home", broker=root / "broker")
    monkeypatch.setattr(worker.service, "CONTAINER_CREATE_INTENT_ENABLED", True)
    monkeypatch.setattr(worker, "CloudBroker", Broker)
    monkeypatch.setattr(worker, "CloudTaskReporter", Reporter)
    monkeypatch.setattr(worker, "ModelBroker", Model)
    monkeypatch.setattr(worker, "inspect_sdk", lambda: {})
    monkeypatch.setattr(worker, "read_model_key", lambda _path: b"synthetic")
    monkeypatch.setattr(worker, "write_workspace_receipt", lambda *_args: None)
    monkeypatch.setattr(worker, "inspect_resource_envelope", lambda **_kwargs: {"kind": "CGROUP_V2",
        "memory_max_bytes": 1024**3, "swap_max_bytes": 0, "pids_max": 64})
    terminal = SimpleNamespace(key="synthetic", operation="COMPLETE_ATTEMPT")

    async def collect(*_args, **_kwargs):
        return terminal, "a" * 64

    async def checkout(_repository, path, *, token, private_empty):
        assert token is None and private_empty is True and path.is_dir()
        events.append("checkout:" + path.name)

    monkeypatch.setattr(worker.CloudWorker, "collect", collect)
    settings = SimpleNamespace(cloud_runtime_root=str(tmp_path / "private"), cloud_worker_lease_seconds=30,
        cloud_model_request_cost_microunits=1, cloud_attempt_timeout_seconds=60, cloud_model_max_requests=1,
        cloud_model_max_tokens=1024, cloud_model_base_url="https://model.invalid", cloud_model_key_file="unused",
        cloud_model="deepseek-flash", cloud_codex_enabled=False)
    instance = worker.CloudWorker(None, settings, "fixture", docker_runtime=Docker())
    instance._docker_admitted = True
    instance.resolver = SimpleNamespace(checkout=checkout)
    await instance.execute(claim)
    assert events[:2] == ["checkout:sut", "checkout:framework"]
    assert events.index("sandbox-stop") < events.index("model-drain") < events.index("report:COMPLETE_ATTEMPT")
