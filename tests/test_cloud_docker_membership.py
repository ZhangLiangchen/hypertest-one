"""Single-Worker lock and original-container membership contracts."""
from copy import deepcopy
from uuid import UUID

import pytest
from test_cloud_docker_attempt_spec import candidate, inspect_fixture

from hypertest.cloud.docker_attempt_spec import ResourceLimit
from hypertest.cloud.docker_membership import DockerWorkerLock, _closed_originals, admit_members
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


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    lambda raw: raw["State"].update(Status="running", Running=True, Pid=123),
    lambda raw: raw.update(Id="f" * 64),
    lambda raw: raw["HostConfig"].update(Privileged=True),
    lambda raw: raw["State"].update(Status="created", Running=False, Pid=0),
])
async def test_closed_ledger_requires_matching_stopped_engine_identity(tmp_path, change):
    spec, rows = closed_rows()
    raw = inspect_fixture(spec)
    worker_id = spec["envelope"]["worker_id"]
    limit = ResourceLimit(1 << 30, 1 << 30, 80)
    calls = []

    class Result:
        def __init__(self, data):
            self.data = data

        def all(self):
            return self.data

    class DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def execute(self, _query):
            calls.append(True)
            if len(calls) % 3 == 1:
                return Result([])
            if len(calls) % 3 == 2:
                return Result([(rows[0][0], rows[0][1], UUID(spec["scope"]["attempt_id"]))])
            return Result(rows[1:])

    class Engine:
        async def list_attempts(self):
            return ["e" * 64]

        async def list_volume_containers(self, _volume):
            return ["e" * 64]

        async def inspect_container(self, cid):
            assert cid == "e" * 64
            return deepcopy(raw)

    tmp_path.chmod(0o700)
    with DockerWorkerLock(tmp_path) as lock:
        kwargs = {"engine": Engine(), "sessions": DB, "lock": lock, "worker_id": worker_id,
                  "volume_name": spec["mounts"][0]["Source"], "worker_limit": limit, "attempt_limit": limit}
        assert await admit_members(**kwargs) == {worker_id: limit}
        change(raw)
        with pytest.raises(CloudBlocked):
            await admit_members(**kwargs)


@pytest.mark.asyncio
async def test_unlabeled_volume_container_cannot_escape_membership(tmp_path):
    worker_id, unknown_id = "a" * 64, "f" * 64
    limit = ResourceLimit(1 << 30, 1 << 30, 80)

    class Result:
        def all(self):
            return []

    class DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def execute(self, _query):
            return Result()

    class Engine:
        async def list_attempts(self):
            return []

        async def list_volume_containers(self, volume):
            assert volume == "shared"
            return [worker_id, unknown_id]

        async def inspect_container(self, cid):
            assert cid == unknown_id
            return {"Config": {"Labels": {}}, "HostConfig": {"Mounts": [{"Type": "volume", "Source": "shared"}]}}

    tmp_path.chmod(0o700)
    with DockerWorkerLock(tmp_path) as lock:
        with pytest.raises(CloudBlocked):
            await admit_members(engine=Engine(), sessions=DB, lock=lock, worker_id=worker_id,
                                volume_name="shared", worker_limit=limit, attempt_limit=limit)


@pytest.mark.asyncio
async def test_never_started_observation_still_requires_zero_engine_timestamps(tmp_path):
    spec, rows = closed_rows()
    rows[2][1]["container_observation"]["state"] = "NEVER_STARTED"
    rows[2] = ("OBSERVE_CONTAINER_NEVER_STARTED", rows[2][1])
    raw = inspect_fixture(spec)
    raw["State"].update(Status="created", Running=False, Pid=0,
                        StartedAt="0001-01-01T00:00:00Z", FinishedAt="0001-01-01T00:00:00Z")
    raw["RestartCount"] = 0
    worker_id = spec["envelope"]["worker_id"]
    limit = ResourceLimit(1 << 30, 1 << 30, 80)

    class Result:
        def __init__(self, data):
            self.data = data

        def all(self):
            return self.data

    class DB:
        def __init__(self):
            self.count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def execute(self, _query):
            self.count += 1
            return Result([] if self.count == 1 else
                          [(rows[0][0], rows[0][1], UUID(spec["scope"]["attempt_id"]))] if self.count == 2 else rows[1:])

    class Engine:
        async def list_attempts(self):
            return ["e" * 64]

        async def list_volume_containers(self, _volume):
            return ["e" * 64]

        async def inspect_container(self, _cid):
            return deepcopy(raw)

    tmp_path.chmod(0o700)
    with DockerWorkerLock(tmp_path) as lock:
        kwargs = {"engine": Engine(), "sessions": DB, "lock": lock, "worker_id": worker_id,
                  "volume_name": spec["mounts"][0]["Source"], "worker_limit": limit, "attempt_limit": limit}
        assert await admit_members(**kwargs) == {worker_id: limit}
        raw["State"]["StartedAt"] = "2026-10-29T00:00:00Z"
        with pytest.raises(CloudBlocked):
            await admit_members(**kwargs)
