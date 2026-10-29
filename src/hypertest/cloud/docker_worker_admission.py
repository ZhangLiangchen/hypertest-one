"""Validate the trusted Worker's Engine identity and shared volume binding.

All expectations are fixed, trusted deployment configuration. The caller must
resolve the hostname against a trusted local Engine, reject ambiguous Compose
membership, and serialize enumeration/admission; inspect alone cannot prove
that no sibling Attempt exists or independently observe kernel cgroups.
"""
from __future__ import annotations

import os
import re
import socket
import stat
from dataclasses import dataclass

from .docker_attempt_spec import ResourceLimit
from .docker_workspace import _open_root
from .errors import CloudBlocked

_HEX = re.compile(r"[a-f0-9]{64}\Z")
_VOLUME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _blocked() -> CloudBlocked:
    return CloudBlocked("DOCKER_WORKER_UNCONFIRMED", "Cloud Worker identity or volume binding is unconfirmed")


def _path(value: object) -> bool:
    return (isinstance(value, str) and value.startswith("/") and value != "/"
            and os.path.normpath(value) == value and "\x00" not in value)


def _overlaps(a: str, b: str) -> bool:
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _socket_info(path: str) -> os.stat_result:
    """Inspect the socket without traversing symlinked parent directories."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        parts = path.split("/")[1:]
        for name in parts[:-1]:
            next_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class WorkerMount:
    """Expected Engine mount; source is volume name or exact bind source."""
    kind: str
    source: str
    target: str
    writable: bool


def verify_worker(*, observed: dict, volume_inspect: dict, worker_hint: str,
                  expected_project: str, expected_service: str, expected_image_id: str,
                  expected_volume: str, volume_target: str, docker_socket_source: str,
                  docker_socket_target: str, expected_mounts: tuple[WorkerMount, ...]) -> tuple[str, ResourceLimit]:
    """Return exact Engine ID and configured limits or fail closed.

    ``volume_inspect`` is the same trusted Engine's GET /volumes/<name>. The
    caller must verify that this Compose service has exactly one member; the
    current process hostname is only a lookup hint, not standalone proof.
    Configured limits are Engine observations, not independent cgroup readings.
    """
    try:
        if (not isinstance(observed, dict) or not isinstance(volume_inspect, dict)
                or not isinstance(worker_hint, str) or re.fullmatch(r"[a-f0-9]{12,64}", worker_hint) is None
                or not isinstance(expected_project, str) or not expected_project
                or not isinstance(expected_service, str) or not expected_service
                or not isinstance(expected_image_id, str)
                or re.fullmatch(r"sha256:[a-f0-9]{64}", expected_image_id) is None
                or not isinstance(expected_volume, str) or _VOLUME.fullmatch(expected_volume) is None
                or not all(_path(p) for p in (volume_target, docker_socket_source, docker_socket_target))
                or not isinstance(expected_mounts, tuple) or not expected_mounts
                or any(not isinstance(m, WorkerMount) for m in expected_mounts)):
            raise ValueError
        worker_id = observed["Id"]
        config, host, state = observed["Config"], observed["HostConfig"], observed["State"]
        labels = config["Labels"]
        if (not isinstance(worker_id, str) or _HEX.fullmatch(worker_id) is None or not worker_id.startswith(worker_hint)
                or socket.gethostname() != worker_hint or config["Hostname"] != worker_hint or observed["Image"] != expected_image_id
                or labels.get("com.docker.compose.project") != expected_project
                or labels.get("com.docker.compose.service") != expected_service
                or labels.get("com.docker.compose.oneoff") != "False"
                or state["Status"] != "running" or state["Running"] is not True
                or type(state["Pid"]) is not int or state["Pid"] <= 0
                or os.geteuid() == 0 or config["User"] != f"{os.geteuid()}:{os.getegid()}"
                or host["Privileged"] is not False or host.get("PidMode") == "host"
                or host.get("IpcMode") == "host" or host.get("CapAdd") not in (None, [])):
            raise ValueError
        limits = ResourceLimit(host["Memory"], host["MemorySwap"], host["PidsLimit"])
        limits.validate()
        mountpoint = volume_inspect["Mountpoint"]
        if (volume_inspect["Name"] != expected_volume or volume_inspect["Driver"] != "local"
                or volume_inspect.get("Options") not in (None, {}) or not _path(mountpoint)):
            raise ValueError
        targets = set()
        for item in expected_mounts:
            if (item.kind not in ("volume", "bind") or type(item.writable) is not bool
                    or not _path(item.target) or item.target in targets
                    or (item.kind == "volume" and _VOLUME.fullmatch(item.source) is None)
                    or (item.kind == "bind" and not _path(item.source))):
                raise ValueError
            targets.add(item.target)
        volume = WorkerMount("volume", expected_volume, volume_target, True)
        sock = WorkerMount("bind", docker_socket_source, docker_socket_target, True)
        if expected_mounts.count(volume) != 1 or expected_mounts.count(sock) != 1:
            raise ValueError
        if any(_overlaps(m.target, volume_target) or _overlaps(m.target, docker_socket_target)
               for m in expected_mounts if m not in (volume, sock)) or _overlaps(volume_target, docker_socket_target):
            raise ValueError
        mounts = observed["Mounts"]
        if not isinstance(mounts, list) or len(mounts) != len(expected_mounts):
            raise ValueError
        found = []
        for mount in mounts:
            kind = mount["Type"]
            if type(mount["RW"]) is not bool:
                raise ValueError
            source = mount["Name"] if kind == "volume" else mount["Source"]
            item = WorkerMount(kind, source, mount["Destination"], mount["RW"])
            if item not in expected_mounts or item in found:
                raise ValueError
            if item == volume and mount["Source"] != mountpoint:
                raise ValueError
            found.append(item)
        # A same-path socket/volume mount is only useful if the current process
        # actually sees the expected kind; no symlink final component accepted.
        volume_fd = _open_root(volume_target)
        os.close(volume_fd)
        if not stat.S_ISSOCK(_socket_info(docker_socket_target).st_mode):
            raise ValueError
        return worker_id, limits
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        raise _blocked() from None
