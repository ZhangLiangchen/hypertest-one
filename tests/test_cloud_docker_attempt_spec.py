"""Synthetic fixed-spec and rejection contracts; no business Engine calls."""
from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from hypertest.cloud import docker_attempt_spec as docker_spec


def candidate():
    attempt = str(uuid4())
    volume = "hypertest-test-volume"
    root = "attempt-" + attempt
    mounts = [{"Type": "volume", "Source": volume, "Target": target, "ReadOnly": readonly,
               "VolumeOptions": {"Subpath": root + "/" + path}}
              for target, readonly, path in (("/workspace", False, "workspace"), ("/workspace/sut", True, "workspace/sut"),
                  ("/home/agent", False, "dsh-home"), ("/run", True, "broker"))]
    worker = "a" * 64
    existing = {worker: docker_spec.ResourceLimit(1 << 30, 1 << 30, 80)}
    return docker_spec.build_spec(project_id=str(uuid4()), task_id=str(uuid4()), attempt_id=attempt, generation=1,
        container_name="hypertest-attempt-" + UUID(attempt).hex + "-" + uuid4().hex,
        image_id="sha256:" + "b" * 64, image_revision="c" * 40, image_environment={"PATH": "/usr/bin"},
        volume_name=volume, mounts=mounts, key_sha256="d" * 64, clock_sha256="f" * 64, deadline_epoch=2000000000,
        attempt_limit=docker_spec.ResourceLimit(1 << 30, 1 << 30, 80), worker_id=worker, existing_limits=existing)


def inspect_fixture(spec):
    body = docker_spec.create_body(spec)
    host = body.pop("HostConfig")
    body["Labels"]["org.opencontainers.image.revision"] = spec["image_revision"]
    host.update(Privileged=False, PidMode="", CapAdd=None, PublishAllPorts=False,
                MaskedPaths=sorted(docker_spec._MASKED), ReadonlyPaths=sorted(docker_spec._READONLY))
    return {"Id": "e" * 64, "Name": "/" + spec["container_name"], "Image": spec["image_id"],
            "Config": body, "HostConfig": host,
            "State": {"Status": "exited", "Running": False, "Pid": 0, "ExitCode": 0}}


def test_spec_engine_projection_and_rejection_paths():
    spec = candidate()
    raw = inspect_fixture(spec)
    result = docker_spec.verify_inspect(spec, container_id="e" * 64, observed=raw)
    assert result == {"container_id": "e" * 64, "status": "exited", "running": False, "pid": 0,
                      "exit_code": 0, "source": "DOCKER_ENGINE_INSPECT", "cgroup_independently_observed": False}
    for change in (
        lambda r: r.update(Id="f" * 64), lambda r: r.update(Image="sha256:" + "f" * 64),
        lambda r: r["Config"].update(User="0:0"), lambda r: r["Config"]["Env"].append("API_KEY=secret"),
        lambda r: r["HostConfig"].update(Privileged=True), lambda r: r["HostConfig"].update(PidMode="host"),
        lambda r: r["HostConfig"].update(MemorySwap=0), lambda r: r["HostConfig"].update(CapDrop=[]),
        lambda r: r["HostConfig"]["Mounts"][1].update(ReadOnly=False),
        lambda r: r["HostConfig"].update(SecurityOpt=["seccomp=unconfined"]),
        lambda r: r["HostConfig"].update(MaskedPaths=[]),
    ):
        bad = deepcopy(raw)
        change(bad)
        with pytest.raises(ValueError):
            docker_spec.verify_inspect(spec, container_id="e" * 64, observed=bad)
    changed_spec = deepcopy(spec)
    changed_spec["runtime"]["network"] = "host"
    with pytest.raises(ValueError):
        docker_spec.create_body(changed_spec)


def test_envelope_checks_combined_memory_swap_and_each_member():
    spec = candidate()
    worker = spec["envelope"]["worker_id"]
    worker_limit = docker_spec.ResourceLimit(1 << 30, 1 << 30, 80)
    docker_spec.verify_envelope(spec, {worker: worker_limit})
    with pytest.raises(ValueError):
        docker_spec.verify_envelope(spec, {worker: docker_spec.ResourceLimit(1 << 30, 2 << 30, 80)})
    with pytest.raises(ValueError):
        docker_spec.check_aggregate(worker_id=worker, existing={worker: worker_limit},
            attempt=docker_spec.ResourceLimit(3 << 30, 4 << 30, 80))
    with pytest.raises(ValueError):
        docker_spec.check_aggregate(worker_id=worker, existing={worker: worker_limit},
            attempt=docker_spec.ResourceLimit(1 << 30, 1 << 30, 200))
