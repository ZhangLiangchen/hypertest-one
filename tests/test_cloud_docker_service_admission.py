"""Docker service startup admission; no database, model, or Docker daemon."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from hypertest.cloud import docker_service_admission as admission
from hypertest.cloud.docker_attempt_spec import ResourceLimit
from hypertest.cloud.docker_worker_admission import WorkerMount
from hypertest.cloud.errors import CloudBlocked


class Engine:
    socket_path = "/run/cloud-docker.sock"

    def __init__(self, worker, image, volumes):
        self.worker = worker
        self.image = image
        self.volumes = volumes
        self.members = {worker["Id"]: worker}

    async def inspect_image(self, image_id):
        return deepcopy(self.image)

    async def inspect_container(self, identity):
        return deepcopy(self.members.get(identity, self.worker))

    async def inspect_volume(self, name):
        return deepcopy(self.volumes[name])

    async def list_workers(self, project, service):
        return list(self.members)


@pytest.fixture
def candidate(monkeypatch):
    worker_id = "a" * 64
    image_id = "sha256:" + "b" * 64
    commit = "c" * 40
    private_root = str(admission.RUNTIME_ROOT)
    mounts = (WorkerMount("volume", "shared", "/volume", True),
              WorkerMount("volume", "private", private_root, True),
              WorkerMount("bind", "/engine/docker.sock", "/run/cloud-docker.sock", True))
    profile = admission.DockerServiceProfile("compose", "worker", image_id, commit, "shared", "/volume",
        "private", private_root, "/engine/docker.sock", "/run/cloud-docker.sock", mounts)
    labels = {"com.docker.compose.project": "compose", "com.docker.compose.service": "worker"}
    worker = {"Id": worker_id, "Config": {"Labels": labels},
              "State": {"Status": "running", "Running": True, "Pid": 42},
              "Mounts": [{"Type": "volume", "Name": "private", "Source": "/engine/private/_data",
                          "Destination": private_root, "RW": True}]}
    image = {"Id": image_id, "Config": {"Labels": {"org.opencontainers.image.revision": commit}}}
    volumes = {"private": {"Name": "private", "Driver": "local", "Mountpoint": "/engine/private/_data", "Options": None},
               "shared": {"Name": "shared", "Driver": "local", "Mountpoint": "/engine/shared/_data", "Options": None}}
    engine = Engine(worker, image, volumes)
    settings = SimpleNamespace(cloud_codex_enabled=False, cloud_service_release_sha256="d" * 64)
    monkeypatch.setattr(admission.os, "geteuid", lambda: 997)
    monkeypatch.setattr(admission.os, "getegid", lambda: 0)
    monkeypatch.setattr(admission.socket, "gethostname", lambda: worker_id[:12])
    monkeypatch.setattr(admission, "verify_worker", lambda **kwargs: (worker_id, ResourceLimit(2**30, 2**30, 80)))
    monkeypatch.setattr(admission, "_open_root", lambda path: admission.os.open("/", admission.os.O_RDONLY))
    calls = []
    def admit(_settings, *, release_sha256):
        calls.append(release_sha256)
        return {"status": "ADMITTED", "release": {"source_commit": commit, "rootfs_image_sha256": image_id[7:]},
                "outer_profile": {"resource_envelope": {"memory_max_bytes": 2**30, "swap_max_bytes": 0, "pids_max": 80}}}
    monkeypatch.setattr(admission, "inspect_admission", admit)
    return settings, profile, engine, calls


@pytest.mark.asyncio
async def test_service_checks_release_and_unique_worker(candidate):
    settings, profile, engine, calls = candidate
    result = await admission.inspect_docker_service(settings, profile, engine)
    assert calls == [settings.cloud_service_release_sha256]
    assert result["worker_container_id"] == engine.worker["Id"]
    assert result["attempt_membership"] == "NOT_OBSERVED"
    assert result["work_claimed"] is False and result["model_request_sent"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    lambda s, p, e: setattr(s, "cloud_service_release_sha256", ""),
    lambda s, p, e: setattr(s, "cloud_codex_enabled", True),
    lambda s, p, e: e.image["Config"]["Labels"].update({"org.opencontainers.image.revision": "d" * 40}),
    lambda s, p, e: e.volumes["private"].update(Driver="nfs"),
    lambda s, p, e: e.worker["Mounts"][0].update(Source="/engine/private/_data/subpath"),
    lambda s, p, e: e.worker["Mounts"][0].update(RW=False),
    lambda s, p, e: e.members.update({"e" * 64: {"Id": "e" * 64, "Config": {"Labels": {"com.docker.compose.project": "compose", "com.docker.compose.service": "worker"}}, "State": {"Status": "running", "Running": True, "Pid": 43}}}),
    lambda s, p, e: e.members.update({"e" * 64: {"Id": "e" * 64, "Config": {"Labels": {"com.docker.compose.project": "compose", "com.docker.compose.service": "worker"}}, "State": {"Status": "restarting", "Running": False, "Pid": 0}}}),
])
async def test_unconfirmed_service_is_rejected(candidate, change):
    settings, profile, engine, _ = candidate
    change(settings, profile, engine)
    with pytest.raises(CloudBlocked):
        await admission.inspect_docker_service(settings, profile, engine)


@pytest.mark.asyncio
async def test_second_stopped_worker_does_not_claim_running_uniqueness(candidate):
    settings, profile, engine, _ = candidate
    old = deepcopy(engine.worker)
    old["Id"] = "e" * 64
    old["State"] = {"Status": "exited", "Running": False, "Pid": 0}
    engine.members[old["Id"]] = old
    result = await admission.inspect_docker_service(settings, profile, engine)
    assert result["worker_container_id"] == engine.worker["Id"]


def test_profile_loader_requires_readonly_root_owned_file(candidate, tmp_path, monkeypatch):
    import json
    import os
    from dataclasses import asdict
    from types import SimpleNamespace

    _, profile, _, _ = candidate
    path = tmp_path / "docker-service.json"
    document = {"profile": "hypertest-cloud-docker-service/v1", **asdict(profile)}
    path.write_text(json.dumps(document))
    monkeypatch.setattr(admission, "PROFILE_PATH", str(path))
    actual_os = os

    class FakeOS:
        def __getattr__(self, name):
            return getattr(actual_os, name)

        def fstat(self, fd):
            result = actual_os.fstat(fd)
            values = {name: getattr(result, name) for name in ("st_dev", "st_ino", "st_mode", "st_gid", "st_nlink",
                      "st_size", "st_mtime_ns", "st_ctime_ns")}
            return SimpleNamespace(st_uid=0, **values)

        def stat(self, name, **kwargs):
            result = actual_os.stat(name, **kwargs)
            values = {key: getattr(result, key) for key in ("st_dev", "st_ino", "st_mode", "st_gid", "st_nlink",
                      "st_size", "st_mtime_ns", "st_ctime_ns")}
            return SimpleNamespace(st_uid=0, **values)

        def fstatvfs(self, fd):
            return SimpleNamespace(f_flag=actual_os.ST_RDONLY)

    monkeypatch.setattr(admission, "os", FakeOS())
    assert admission.load_docker_service_profile() == profile
    path.write_text('{"profile":"one","profile":"two"}')
    with pytest.raises(CloudBlocked):
        admission.load_docker_service_profile()
    path.write_text(json.dumps(document))
    path.chmod(0o666)
    with pytest.raises(CloudBlocked):
        admission.load_docker_service_profile()


@pytest.mark.asyncio
async def test_docker_startup_is_gated_before_any_claim(monkeypatch, capsys):
    from hypertest.cloud import __main__ as entrypoint

    monkeypatch.setattr(entrypoint, "get_settings", lambda: SimpleNamespace(
        cloud_enabled=True, cloud_worker_enabled=True, cloud_docker_enabled=True))
    assert await entrypoint.run(once=True) == 1
    assert '"code": "CLOUD_DOCKER_NOT_READY"' in capsys.readouterr().out
