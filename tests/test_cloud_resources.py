"""Kernel resource-envelope admission with controlled filesystem fixtures."""

import pytest

from hypertest.cloud import worker as worker_module
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.resources import inspect_resource_envelope
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy


def hierarchy(tmp_path, *, memory="2147483648", swap="0", pids="256", member="/", proc="101"):
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.controllers").write_text("cpu memory pids")
    (root / "cgroup.procs").write_text(proc + "\n")
    for key, value in (("memory.max", memory), ("memory.swap.max", swap), ("pids.max", pids)):
        (root / key).write_text(value)
    membership = tmp_path / "membership"
    membership.write_text("0::" + member + "\n")
    return root, membership


def test_finite_aggregate_limits_are_observed_without_modification(tmp_path):
    root, membership = hierarchy(tmp_path)
    observed = inspect_resource_envelope(root=root, membership=membership, pid=101)
    assert observed == {"kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024 ** 3,
        "swap_max_bytes": 0, "pids_max": 256}
    assert (root / "memory.max").read_text() == "2147483648"


def test_runtime_resource_metadata_separates_virtual_ceiling_and_actual_cgroup():
    observed = {"kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024**3,
        "swap_max_bytes": 0, "pids_max": 256, "path": "private-cgroup-canary", "environment": {"key": "private-canary"}}
    metadata = SandboxPolicy(30, 1, 1024, memory_bytes=16 * 1024**3).resource_metadata(observed)
    assert metadata == {"address_space_rlimit_bytes": 16 * 1024**3,
        "aggregate_memory_ceiling_bytes": 4 * 1024**3, "aggregate_processes_ceiling": 256,
        "observed_cgroup": {"kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024**3,
            "swap_max_bytes": 0, "pids_max": 256}}


@pytest.mark.parametrize("field,value", [
    ("kind", "private-cgroup-canary"), ("memory_max_bytes", True),
    ("memory_max_bytes", "2147483648"), ("swap_max_bytes", -1), ("pids_max", None),
])
def test_runtime_resource_metadata_rejects_untyped_or_noncanonical_observation(field, value):
    observed = {"kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024**3, "swap_max_bytes": 0, "pids_max": 256}
    observed[field] = value
    with pytest.raises(CloudBlocked) as error:
        SandboxPolicy(30, 1, 1024).resource_metadata(observed)
    assert error.value.code == "CGROUP_RESOURCE_LIMIT_UNAVAILABLE"
    assert "private-cgroup-canary" not in str(error.value)


@pytest.mark.parametrize("address_space_gib", [4, 16])
async def test_production_start_preexec_applies_finite_virtual_limit_without_changing_other_limits(tmp_path, monkeypatch, address_space_gib):
    import resource
    from types import SimpleNamespace

    from hypertest.cloud import sandbox as sandbox_module

    applied = []
    monkeypatch.setattr(resource, "setrlimit", lambda kind, bounds: applied.append((kind, bounds)))

    class Stdin:
        def write(self, value):
            assert value == b"{}"

        async def drain(self):
            pass

        def close(self):
            pass

    process = SimpleNamespace(stdin=Stdin())

    async def create_subprocess(*command, **kwargs):
        assert command == ("inert-not-executed",)
        assert kwargs["start_new_session"] is True
        kwargs["preexec_fn"]()
        return process

    monkeypatch.setattr(sandbox_module.asyncio, "create_subprocess_exec", create_subprocess)
    sandbox = BubblewrapSandbox(workspace=tmp_path / "workspace", dsh_home=tmp_path / "home",
        broker_socket=tmp_path / "unused.sock",
        policy=SandboxPolicy(30, 1, 1024, memory_bytes=address_space_gib * 1024**3))
    monkeypatch.setattr(sandbox, "command", lambda: ["inert-not-executed"])
    assert await sandbox.start({}) is process
    assert applied == [(resource.RLIMIT_CORE, (0, 0)),
        (resource.RLIMIT_FSIZE, (128 * 1024**2,) * 2),
        (resource.RLIMIT_NOFILE, (256, 256)),
        (resource.RLIMIT_AS, (address_space_gib * 1024**3,) * 2),
        (resource.RLIMIT_CPU, (40, 40))]


@pytest.mark.parametrize("field,value,code", [
    ("memory", "max", "CGROUP_RESOURCE_LIMIT_UNBOUNDED"),
    ("swap", "max", "CGROUP_RESOURCE_LIMIT_UNBOUNDED"),
    ("pids", "max", "CGROUP_RESOURCE_LIMIT_UNBOUNDED"),
    ("memory", str(5 * 1024 ** 3), "CGROUP_RESOURCE_LIMIT_EXCEEDED"),
    ("pids", "257", "CGROUP_RESOURCE_LIMIT_EXCEEDED"),
    ("swap", str(3 * 1024 ** 3), "CGROUP_RESOURCE_LIMIT_EXCEEDED"),
])
def test_unbounded_or_excessive_scope_rejects_without_changing_limits(tmp_path, field, value, code):
    root, membership = hierarchy(tmp_path, **{field: value})
    with pytest.raises(CloudBlocked) as error:
        inspect_resource_envelope(root=root, membership=membership, pid=101)
    assert error.value.code == code


def test_inherited_finite_parent_limits_cover_unlimited_leaf(tmp_path):
    root, membership = hierarchy(tmp_path, member="/worker", proc="999")
    leaf = root / "worker"
    leaf.mkdir()
    (leaf / "cgroup.procs").write_text("101\n")
    for name in ("memory.max", "memory.swap.max", "pids.max"):
        (leaf / name).write_text("max")
    observed = inspect_resource_envelope(root=root, membership=membership, pid=101)
    assert observed["memory_max_bytes"] == 2 * 1024 ** 3 and observed["pids_max"] == 256


def test_unrelated_finite_cgroup_is_not_accepted_as_worker_scope(tmp_path):
    root, membership = hierarchy(tmp_path, member="/some-other-cgroup", proc="999")
    with pytest.raises(CloudBlocked) as error:
        inspect_resource_envelope(root=root, membership=membership, pid=101)
    assert error.value.code == "CGROUP_SCOPE_UNVERIFIED"


async def test_unbounded_worker_envelope_rejects_before_claim_or_database(monkeypatch):
    from types import SimpleNamespace

    def reject_unbounded():
        raise CloudBlocked("CGROUP_RESOURCE_LIMIT_UNBOUNDED", "Finite resource limits are required")

    monkeypatch.setattr(worker_module, "inspect_resource_envelope", reject_unbounded)
    worker = worker_module.CloudWorker(lambda: pytest.fail("database/claim reached before resource admission"),
        SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True), "fixture")
    with pytest.raises(CloudBlocked) as error:
        await worker.run_once()
    assert error.value.code == "CGROUP_RESOURCE_LIMIT_UNBOUNDED"
