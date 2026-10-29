"""Read-only service startup admission for the dedicated Docker Cloud Worker.

The profile must come from trusted fixed deployment configuration, never an
Agent or Engine inspect. This validates the Worker and its two volume roots;
it does not claim work, contact a model, or establish global Attempt admission.
The caller must complete serialized Engine/DB member admission separately.
"""
from __future__ import annotations

import json
import os
import re
import socket
import stat
from dataclasses import dataclass

from .docker_worker_admission import WorkerMount, verify_worker
from .docker_workspace import _open_root
from .errors import CloudBlocked
from .worker_admission import RUNTIME_ROOT, inspect_admission

_HEX40 = re.compile(r"[a-f0-9]{40}\Z")
PROFILE_PATH = "/etc/hypertest-cloud/docker-service.json"
_VOLUME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def _blocked() -> CloudBlocked:
    return CloudBlocked("DOCKER_SERVICE_ADMISSION_FAILED", "Docker Cloud service identity or deployment is unconfirmed")


@dataclass(frozen=True)
class DockerServiceProfile:
    """Nonsecret immutable expectations from the trusted Compose deployment."""
    compose_project: str
    compose_service: str
    image_id: str
    source_commit: str
    shared_volume: str
    shared_root: str
    private_volume: str
    private_root: str
    docker_socket_source: str
    docker_socket_target: str
    mounts: tuple[WorkerMount, ...]


def load_docker_service_profile() -> DockerServiceProfile:
    """Read only the fixed root-owned, readonly deployment profile, never Agent data."""
    parent = descriptor = None
    try:
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        parts = PROFILE_PATH.split("/")[1:]
        for component in parts[:-1]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            os.close(parent)
            parent = next_fd
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_mode & 0o022
                or before.st_nlink != 1 or not 0 < before.st_size <= 32768
                or not os.fstatvfs(descriptor).f_flag & os.ST_RDONLY):
            raise ValueError
        raw = os.read(descriptor, 32769)
        after = os.fstat(descriptor)
        named = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(raw) != before.st_size or any(getattr(before, name) != getattr(after, name)
                or getattr(before, name) != getattr(named, name) for name in fields)):
            raise ValueError
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        data = json.loads(raw, object_pairs_hook=unique)
        expected = {"profile", "compose_project", "compose_service", "image_id", "source_commit", "shared_volume",
                    "shared_root", "private_volume", "private_root", "docker_socket_source", "docker_socket_target", "mounts"}
        if not isinstance(data, dict) or set(data) != expected or data.pop("profile") != "hypertest-cloud-docker-service/v1":
            raise ValueError
        entries = data.pop("mounts")
        if not isinstance(entries, list) or not entries or len(entries) > 32:
            raise ValueError
        mounts = []
        for item in entries:
            if not isinstance(item, dict) or set(item) != {"kind", "source", "target", "writable"}:
                raise ValueError
            mounts.append(WorkerMount(**item))
        if any(not isinstance(value, str) or not value or len(value) > 2048 or "\x00" in value for value in data.values()):
            raise ValueError
        return DockerServiceProfile(**data, mounts=tuple(mounts))
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        raise _blocked() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)


async def inspect_docker_service(settings, profile: DockerServiceProfile, engine) -> dict:
    """Inspect a single trusted Worker without starting SDK, model, or work.

    No caller may supply expectations from Agent input or observed Engine data.
    The private volume is Worker-only; Agent subpath mounts must separately
    come from the checked shared volume. Engine socket authenticity and the
    fixed Compose configuration are deployment trust assumptions.
    """
    try:
        if (not isinstance(profile, DockerServiceProfile) or os.geteuid() != 997 or os.getegid() != 0
                or getattr(settings, "cloud_codex_enabled", True) is not False
                or not isinstance(profile.source_commit, str) or _HEX40.fullmatch(profile.source_commit) is None
                or not isinstance(profile.private_volume, str) or _VOLUME.fullmatch(profile.private_volume) is None
                or profile.private_volume == profile.shared_volume
                or profile.private_root != str(RUNTIME_ROOT)
                or profile.docker_socket_target != engine.socket_path
                or not isinstance(profile.mounts, tuple)
                or profile.mounts.count(WorkerMount("volume", profile.private_volume, profile.private_root, True)) != 1
                or sum(m.kind == "volume" and m.source == profile.private_volume for m in profile.mounts) != 1
                or sum(m.kind == "volume" and m.source == profile.shared_volume for m in profile.mounts) != 1):
            raise ValueError
        # Keep the prior release, credential, SDK and outer-profile checks;
        # an empty release digest must never bypass them for this profile.
        release_digest = settings.cloud_service_release_sha256
        if not release_digest:
            raise ValueError
        admitted = inspect_admission(settings, release_sha256=release_digest)
        if (admitted["status"] != "ADMITTED" or admitted["release"]["source_commit"] != profile.source_commit
                or "sha256:" + admitted["release"]["rootfs_image_sha256"] != profile.image_id):
            raise ValueError
        image = await engine.inspect_image(profile.image_id)
        if (image.get("Id") != profile.image_id
                or image["Config"]["Labels"].get("org.opencontainers.image.revision") != profile.source_commit):
            raise ValueError
        hint = socket.gethostname()
        worker = await engine.inspect_container(hint)
        worker_id, limits = verify_worker(observed=worker, volume_inspect=await engine.inspect_volume(profile.shared_volume),
            worker_hint=hint, expected_project=profile.compose_project, expected_service=profile.compose_service,
            expected_image_id=profile.image_id, expected_volume=profile.shared_volume, volume_target=profile.shared_root,
            docker_socket_source=profile.docker_socket_source, docker_socket_target=profile.docker_socket_target,
            expected_mounts=profile.mounts)
        actual = admitted["outer_profile"]["resource_envelope"]
        if (actual["memory_max_bytes"] != limits.memory or actual["swap_max_bytes"] != 0
                or limits.memory_swap != limits.memory or actual["pids_max"] != limits.pids):
            raise ValueError
        private = await engine.inspect_volume(profile.private_volume)
        if (private.get("Name") != profile.private_volume or private.get("Driver") != "local"
                or private.get("Options") not in (None, {}) or not isinstance(private.get("Mountpoint"), str)
                or not private["Mountpoint"].startswith("/")
                or os.path.normpath(private["Mountpoint"]) != private["Mountpoint"]):
            raise ValueError
        private_mounts = [m for m in worker["Mounts"] if m.get("Destination") == profile.private_root]
        if (len(private_mounts) != 1 or private_mounts[0].get("Type") != "volume"
                or private_mounts[0].get("Name") != profile.private_volume
                or private_mounts[0].get("Source") != private["Mountpoint"] or private_mounts[0].get("RW") is not True):
            raise ValueError
        for mount in profile.mounts:
            if mount.target != profile.private_root and (mount.target.startswith(profile.private_root + "/")
                    or profile.private_root.startswith(mount.target + "/")):
                raise ValueError
        fd = _open_root(profile.private_root)
        os.close(fd)
        ids = await engine.list_workers(profile.compose_project, profile.compose_service)
        if worker_id not in ids:
            raise ValueError
        running = []
        for identity in ids:
            observed = worker if identity == worker_id else await engine.inspect_container(identity)
            labels = observed["Config"]["Labels"]
            state = observed["State"]
            if (observed["Id"] != identity or labels.get("com.docker.compose.project") != profile.compose_project
                    or labels.get("com.docker.compose.service") != profile.compose_service
                    or type(state["Running"]) is not bool or type(state["Pid"]) is not int):
                raise ValueError
            if state["Running"]:
                if state["Status"] != "running" or state["Pid"] <= 0:
                    raise ValueError
                running.append(identity)
            elif state["Status"] not in {"created", "exited", "dead"} or state["Pid"] != 0:
                raise ValueError
        if running != [worker_id]:
            raise ValueError
        return {"status": "ADMITTED", "scope": "DOCKER_SERVICE_STARTUP_ONLY", "worker_container_id": worker_id,
                "worker_limit": limits, "release": admitted["release"], "shared_volume": profile.shared_volume,
                "private_volume": profile.private_volume, "attempt_membership": "NOT_OBSERVED",
                "work_claimed": False, "model_request_sent": False, "worker_cgroup_observed": True,
                "attempt_cgroup_independently_observed": False}
    except CloudBlocked:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        raise _blocked() from None
