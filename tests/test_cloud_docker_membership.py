"""Single-Worker lock and original-container membership contracts."""
from copy import deepcopy

import pytest
from test_cloud_docker_attempt_spec import candidate

from hypertest.cloud.docker_membership import DockerWorkerLock, _closed_originals
from hypertest.cloud.errors import CloudBlocked


def closed_rows():
    spec = candidate()
    scope = spec["scope"]
    intent = {"operation_key": "original-create", "project_id": scope["project_id"], "task_id": scope["task_id"], "attempt_id": scope["attempt_id"],
              "generation": scope["generation"], "spec_sha256": spec["spec_sha256"], "spec": spec}
    common = {"create_operation_key": "original-create", "project_id": scope["project_id"], "task_id": scope["task_id"], "attempt_id": scope["attempt_id"], "source": "DOCKER_ENGINE_INSPECT",
              "generation": scope["generation"], "spec_sha256": spec["spec_sha256"], "container_id": "e" * 64}
    return spec, [("PREPARE_CONTAINER_CREATE", {"container_create_intent": intent}),
                  ("CONFIRM_CONTAINER_ID", {"container_observation": common | {"state": "CONFIRMED"}}),
                  ("OBSERVE_CONTAINER_STOP", {"container_observation": common | {"state": "STOPPED"}})]


def test_worker_lock_excludes_a_second_owner_and_releases(tmp_path):
    tmp_path.chmod(0o700)
    first = DockerWorkerLock(tmp_path)
    try:
        with pytest.raises(CloudBlocked):
            DockerWorkerLock(tmp_path)
    finally:
        first.close()
    with DockerWorkerLock(tmp_path) as second:
        assert second.fd is not None
    assert second.fd is None


def test_membership_requires_exact_original_confirmation_and_terminal():
    spec, rows = closed_rows()
    worker_id = spec["envelope"]["worker_id"]
    volume = spec["mounts"][0]["Source"]
    assert _closed_originals(rows, worker_id=worker_id, volume_name=volume)["e" * 64] == (spec, "STOPPED")
    for changed in (rows[:1], rows[:2], rows + [rows[1]], rows + [rows[2]]):
        with pytest.raises(CloudBlocked):
            _closed_originals(changed, worker_id=worker_id, volume_name=volume)
    changed = deepcopy(rows)
    changed[2][1]["container_observation"]["container_id"] = "f" * 64
    with pytest.raises(CloudBlocked):
        _closed_originals(changed, worker_id=worker_id, volume_name=volume)
    changed = deepcopy(rows)
    changed[0][1]["container_create_intent"]["spec"]["runtime"]["network"] = "host"
    with pytest.raises(CloudBlocked):
        _closed_originals(changed, worker_id=worker_id, volume_name=volume)
