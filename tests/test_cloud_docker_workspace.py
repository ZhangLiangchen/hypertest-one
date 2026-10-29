"""Private Docker Attempt volume boundaries without a running Agent or model."""

import os
import socket
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from hypertest.cloud.docker_workspace import DockerWorkspace
from hypertest.cloud.errors import CloudBlocked


@pytest.fixture
def parameters():
    # A real Unix socket must fit Darwin's sun_path limit; keep the owned test
    # directory short independently of pytest's descriptive test directory.
    with tempfile.TemporaryDirectory(prefix="hc-", dir=Path("/tmp").resolve()) as base:
        root = Path(base) / "v"
        root.mkdir(mode=0o700)
        yield {"volume_root": root, "volume_name": "cloud-fixture",
               "project_id": str(uuid4()), "task_id": str(uuid4()), "attempt_id": str(uuid4()),
               "input_digest": "a" * 64}


@pytest.fixture
def workspace(parameters):
    return DockerWorkspace.create(**parameters)


def socket_at(path: Path):
    result = socket.socket(socket.AF_UNIX)
    result.bind(str(path))
    path.chmod(0o600)
    return result


def test_created_volume_has_only_explicit_mounts_and_original_identity(workspace, parameters):
    assert all(path.stat().st_mode & 0o777 == 0o700 for path in
               (workspace.workspace, workspace.sut, workspace.framework, workspace.dsh_home, workspace.broker))
    reopened = DockerWorkspace.load(**parameters)
    with socket_at(workspace.broker / "model.sock"):
        mounts = reopened.mount_specs(expected_sockets=("model.sock",))
    prefix = "attempt-" + parameters["attempt_id"]
    assert mounts == [{"Type": "volume", "Source": "cloud-fixture", "Target": target,
                       "ReadOnly": readonly, "VolumeOptions": {"Subpath": f"{prefix}/{subpath}"}}
                      for subpath, target, readonly in (
                          ("workspace", "/workspace", False), ("workspace/sut", "/workspace/sut", True),
                          ("dsh-home", "/home/agent", False), ("broker", "/run", True))]
    assert all("identity.json" not in repr(item) for item in mounts)


def test_existing_attempt_is_not_recreated_or_overwritten(workspace, parameters):
    before = (workspace.volume_root / workspace._name / "identity.json").read_bytes()
    with pytest.raises(CloudBlocked) as error:
        DockerWorkspace.create(**parameters)
    assert error.value.code == "DOCKER_WORKSPACE_EXISTS"
    assert (workspace.volume_root / workspace._name / "identity.json").read_bytes() == before


def test_load_requires_exact_attempt_task_project_volume_and_input(workspace, parameters):
    for field, value in (("project_id", str(uuid4())), ("task_id", str(uuid4())),
                         ("input_digest", "b" * 64), ("volume_name", "other-volume")):
        with pytest.raises(CloudBlocked, match="Docker Attempt"):
            DockerWorkspace.load(**{**parameters, field: value})


@pytest.mark.parametrize("part", ["sut", "framework", "dsh_home", "broker"])
def test_symlink_or_insecure_directory_is_rejected(workspace, part):
    path = getattr(workspace, part)
    path.rmdir()
    path.symlink_to(workspace.volume_root, target_is_directory=True)
    with pytest.raises(CloudBlocked):
        workspace.validate()


def test_insecure_root_and_metadata_hardlink_are_rejected(workspace, parameters, tmp_path):
    workspace.volume_root.chmod(0o755)
    with pytest.raises(CloudBlocked):
        workspace.validate()
    workspace.volume_root.chmod(0o700)
    metadata = workspace.volume_root / workspace._name / "identity.json"
    os.link(metadata, tmp_path / "identity-alias")
    with pytest.raises(CloudBlocked):
        DockerWorkspace.load(**parameters)


def test_broker_allows_only_exact_private_unix_sockets(workspace):
    with pytest.raises(CloudBlocked) as error:
        workspace.mount_specs(expected_sockets=("model.sock",))
    assert error.value.code == "DOCKER_BROKER_SOCKET_INVALID"
    with socket_at(workspace.broker / "model.sock"):
        workspace.mount_specs(expected_sockets=("model.sock",))
        (workspace.broker / "unexpected").write_text("not a socket")
        with pytest.raises(CloudBlocked):
            workspace.mount_specs(expected_sockets=("model.sock",))
        (workspace.broker / "unexpected").unlink()
        (workspace.broker / "model.sock").chmod(0o666)
        with pytest.raises(CloudBlocked):
            workspace.mount_specs(expected_sockets=("model.sock",))


def test_bad_identity_and_unsafe_socket_names_are_rejected(workspace, parameters):
    for field, value in (("volume_name", "bad,source=/tmp"), ("attempt_id", "../other"),
                         ("input_digest", "not-a-hash")):
        with pytest.raises(CloudBlocked):
            DockerWorkspace.create(**{**parameters, field: value})
    with pytest.raises(CloudBlocked):
        workspace.mount_specs(expected_sockets=("model.sock", "../../outside"))
    with pytest.raises(CloudBlocked):
        workspace.mount_specs(expected_sockets=("model.sock", "codex.sock"))
