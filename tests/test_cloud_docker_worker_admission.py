"""Worker identity and fixed volume mounts must fail closed."""
import os
import socket
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest

from hypertest.cloud.docker_attempt_spec import ResourceLimit
from hypertest.cloud.docker_worker_admission import WorkerMount, verify_worker
from hypertest.cloud.errors import CloudBlocked


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    worker = "a" * 64
    hint = worker[:12]
    monkeypatch.setattr(socket, "gethostname", lambda: hint)
    volume = tmp_path / "volume"
    volume.mkdir(mode=0o700)
    short_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="ht-")
    sockpath = Path(short_dir.name).resolve() / "docker.sock"
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(sockpath))
    expected = (WorkerMount("volume", "test-volume", str(volume), True),
                WorkerMount("bind", "/engine/docker.sock", str(sockpath), True))
    observed = {"Id": worker, "Image": "sha256:" + "b" * 64,
        "Config": {"Hostname": hint, "User": f"{os.geteuid()}:{os.getegid()}",
                   "Labels": {"com.docker.compose.project": "test-project",
                              "com.docker.compose.service": "cloud-worker", "com.docker.compose.oneoff": "False"}},
        "State": {"Status": "running", "Running": True, "Pid": 101},
        "HostConfig": {"Privileged": False, "PidMode": "", "IpcMode": "private", "CapAdd": None,
                       "Memory": 1024**3, "MemorySwap": 2 * 1024**3, "PidsLimit": 100},
        "Mounts": [{"Type": "volume", "Name": "test-volume", "Source": "/engine/volume/_data",
                    "Destination": str(volume), "RW": True},
                   {"Type": "bind", "Source": "/engine/docker.sock", "Destination": str(sockpath), "RW": True}]}
    kwargs = dict(observed=observed, volume_inspect={"Name": "test-volume", "Driver": "local",
                  "Mountpoint": "/engine/volume/_data", "Options": None}, worker_hint=hint,
                  expected_project="test-project", expected_service="cloud-worker",
                  expected_image_id="sha256:" + "b" * 64, expected_volume="test-volume", volume_target=str(volume),
                  docker_socket_source="/engine/docker.sock", docker_socket_target=str(sockpath), expected_mounts=expected)
    yield kwargs
    sock.close()
    short_dir.cleanup()


def test_worker_identity_and_volume_binding(candidate):
    worker, limits = verify_worker(**candidate)
    assert worker == "a" * 64
    assert limits == ResourceLimit(1024**3, 2 * 1024**3, 100)


@pytest.mark.parametrize("change", [
    lambda k: k["observed"].update(Id="b" * 64),
    lambda k: k["observed"].update(Image="sha256:" + "c" * 64),
    lambda k: k["observed"]["Config"].update(Hostname="b" * 12),
    lambda k: k["observed"]["Config"].update(User="0:0"),
    lambda k: k["observed"]["Config"]["Labels"].update({"com.docker.compose.project": "other"}),
    lambda k: k["observed"]["Config"]["Labels"].update({"com.docker.compose.oneoff": "True"}),
    lambda k: k["observed"]["State"].update(Running=False),
    lambda k: k["observed"]["HostConfig"].update(Privileged=True),
    lambda k: k["observed"]["HostConfig"].update(PidMode="host"),
    lambda k: k["observed"]["HostConfig"].update(CapAdd=["SYS_ADMIN"]),
    lambda k: k["observed"]["HostConfig"].update(MemorySwap=0),
    lambda k: k["observed"]["HostConfig"].update(PidsLimit=-1),
    lambda k: k["observed"]["Mounts"][0].update(Source="/engine/volume/_data/subpath"),
    lambda k: k["observed"]["Mounts"][0].update(RW=False),
    lambda k: k["observed"]["Mounts"][1].update(Source="/evil/docker.sock"),
    lambda k: k["observed"]["Mounts"].append(k["observed"]["Mounts"][0]),
    lambda k: k["volume_inspect"].update(Driver="nfs"),
    lambda k: k["volume_inspect"].update(Options={"device": "/etc"}),
    lambda k: k.update(expected_mounts=k["expected_mounts"] + (WorkerMount("bind", "/evil", k["volume_target"] + "/sub", True),)),
])
def test_wrong_identity_mount_or_limit_denied(candidate, change):
    changed = deepcopy(candidate)
    change(changed)
    with pytest.raises(CloudBlocked):
        verify_worker(**changed)


def test_private_volume_and_socket_required(candidate):
    os.chmod(candidate["volume_target"], 0o755)
    with pytest.raises(CloudBlocked):
        verify_worker(**candidate)
