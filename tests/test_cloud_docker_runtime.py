"""Runtime composition must recheck service and current original membership."""
from types import SimpleNamespace

import pytest

from hypertest.cloud import docker_runtime
from hypertest.cloud.docker_attempt_spec import ResourceLimit
from hypertest.cloud.docker_service_admission import DockerServiceProfile
from hypertest.cloud.errors import CloudBlocked


@pytest.mark.asyncio
async def test_service_and_members_are_rechecked_for_original_create(monkeypatch, tmp_path):
    worker_id = "a" * 64
    worker_limit = ResourceLimit(1024**3, 1024**3, 64)
    agent_limit = ResourceLimit(1024**3, 1024**3, 64)
    profile = DockerServiceProfile("compose", "worker", "sha256:" + "b" * 64, "c" * 40,
        "shared", str(tmp_path / "shared"), "private", str(tmp_path), "/engine/socket", "/run/docker.sock", ())
    observed = {"worker_container_id": worker_id, "worker_limit": worker_limit}
    calls = []

    async def service(_settings, _profile, _engine):
        return observed

    class Lock:
        fd = 9

        def close(self):
            self.fd = None

    async def members(**kwargs):
        calls.append(kwargs)
        return {worker_id: worker_limit}

    class Engine:
        async def inspect_image(self, image_id):
            return {"Id": image_id, "Config": {"Env": ["PATH=/usr/bin"]}}

    class Sandbox:
        def __init__(self, **kwargs):
            self.observe = kwargs["observe_envelope"]
            self._attempt = SimpleNamespace(container_id="d" * 64)
            self._create_key = "original"
            self.spec = {"spec_sha256": "e" * 64}

    monkeypatch.setattr(docker_runtime, "inspect_docker_service", service)
    monkeypatch.setattr(docker_runtime, "DockerWorkerLock", lambda _path: Lock())
    monkeypatch.setattr(docker_runtime, "admit_members", members)
    monkeypatch.setattr(docker_runtime, "DockerSandbox", Sandbox)
    runtime = docker_runtime.DockerRuntime(settings=object(), profile=profile, sessions=None, engine=Engine(),
                                          attempt_limit=agent_limit)
    await runtime.admit()
    sandbox = runtime.sandbox(layout=SimpleNamespace(volume_name="shared"), broker=None, reporter=None,
        private_root=tmp_path, policy=SimpleNamespace(aggregate_memory_bytes=4 * 1024**3, aggregate_processes=256),
        deadline_epoch=1, expected_sockets=("model.sock",))
    assert await sandbox.observe() == {worker_id: worker_limit}
    assert calls[-1]["current_create_key"] == "original" and calls[-1]["current_container_id"] == "d" * 64
    observed["worker_container_id"] = "f" * 64
    with pytest.raises(CloudBlocked):
        await sandbox.observe()
    runtime.close()
    with pytest.raises(CloudBlocked):
        runtime.layout({}, {})
