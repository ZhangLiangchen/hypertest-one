"""Private shared-volume layout for one Cloud Attempt.

Only the workspace, read-only SUT, home and broker socket directory may be
mounted into an Agent container. This first layout supports a DeepSeek root
only: the read-only /run cannot host the native delegation observer. The
Worker must place admitted SSH/HTTPS sockets under their sandbox names in the
broker directory, rather than assume its existing outer socket names match.
This module does not create Docker volumes, start containers, establish Engine
trust or authorize an Attempt. The caller must independently verify that
``volume_root`` is the named volume mounted into the trusted Worker and
compare the resulting spec with Engine inspect.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from .errors import CloudBlocked

PROFILE = "hypertest-cloud-docker-workspace/v1"
_VOLUME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_SOCKETS = frozenset({"model.sock", "hypertest-ssh.sock", "hypertest-https.sock"})


def _blocked(code: str = "DOCKER_WORKSPACE_INVALID") -> CloudBlocked:
    return CloudBlocked(code, "Docker Attempt workspace is unavailable or outside its private layout")


def _uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
        return value
    except (ValueError, TypeError, AttributeError):
        raise _blocked() from None


def _identity(volume: str, project_id: str, task_id: str, attempt_id: str, input_digest: str) -> dict:
    if (not isinstance(volume, str) or not _VOLUME.fullmatch(volume)
            or not isinstance(input_digest, str) or not _DIGEST.fullmatch(input_digest)):
        raise _blocked()
    return {"profile": PROFILE, "volume_name": volume, "project_id": _uuid(project_id),
            "task_id": _uuid(task_id), "attempt_id": _uuid(attempt_id), "input_digest": input_digest}


def _open_dir(parent: int, name: str) -> int:
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise _blocked()
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_root(root: Path) -> int:
    """Walk every absolute component without following symlinks."""
    raw = os.fspath(root)
    if (not isinstance(raw, str) or not raw.startswith("/") or os.path.normpath(raw) != raw
            or raw == "/" or os.geteuid() == 0):
        raise _blocked()
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for name in Path(raw).parts[1:]:
            next_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise _blocked()
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_identity(parent: int) -> bytes:
    fd = os.open("identity.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 < before.st_size <= 4096):
            raise _blocked()
        data = os.read(fd, 4097)
        after = os.fstat(fd)
        if (len(data) != before.st_size or len(data) > 4096
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise _blocked()
        return data
    finally:
        os.close(fd)


def _encoded(identity: dict) -> bytes:
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


@dataclass(frozen=True)
class DockerWorkspace:
    volume_root: Path
    volume_name: str
    project_id: str
    task_id: str
    attempt_id: str
    input_digest: str

    @property
    def _name(self) -> str:
        return "attempt-" + self.attempt_id

    @property
    def workspace(self) -> Path:
        return self.volume_root / self._name / "workspace"

    @property
    def sut(self) -> Path:
        return self.workspace / "sut"

    @property
    def framework(self) -> Path:
        return self.workspace / "framework"

    @property
    def dsh_home(self) -> Path:
        return self.volume_root / self._name / "dsh-home"

    @property
    def broker(self) -> Path:
        return self.volume_root / self._name / "broker"

    @classmethod
    def create(cls, volume_root: Path, volume_name: str, *, project_id: str, task_id: str,
               attempt_id: str, input_digest: str) -> DockerWorkspace:
        identity = _identity(volume_name, project_id, task_id, attempt_id, input_digest)
        instance = cls(Path(volume_root), volume_name, project_id, task_id, attempt_id, input_digest)
        root_fd = attempt_fd = workspace_fd = None
        try:
            root_fd = _open_root(instance.volume_root)
            try:
                os.mkdir(instance._name, 0o700, dir_fd=root_fd)
            except FileExistsError:
                # Existing or partial state is reconciled explicitly, never overwritten.
                raise _blocked("DOCKER_WORKSPACE_EXISTS") from None
            attempt_fd = _open_dir(root_fd, instance._name)
            for name in ("workspace", "dsh-home", "broker"):
                os.mkdir(name, 0o700, dir_fd=attempt_fd)
            workspace_fd = _open_dir(attempt_fd, "workspace")
            for name in ("sut", "framework"):
                os.mkdir(name, 0o700, dir_fd=workspace_fd)
            data = _encoded(identity)
            fd = os.open("identity.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=attempt_fd)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("identity write failed")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(workspace_fd)
            os.fsync(attempt_fd)
            os.fsync(root_fd)
        except CloudBlocked:
            raise
        except (OSError, ValueError):
            raise _blocked() from None
        finally:
            for fd in (workspace_fd, attempt_fd, root_fd):
                if fd is not None:
                    os.close(fd)
        instance.validate()
        return instance

    @classmethod
    def load(cls, volume_root: Path, volume_name: str, *, project_id: str, task_id: str,
             attempt_id: str, input_digest: str) -> DockerWorkspace:
        _identity(volume_name, project_id, task_id, attempt_id, input_digest)
        instance = cls(Path(volume_root), volume_name, project_id, task_id, attempt_id, input_digest)
        instance.validate()
        return instance

    def validate(self, *, expected_sockets: tuple[str, ...] | None = None) -> None:
        """Recheck fixed identity, distinct private directories, and optional socket set."""
        identity = _identity(self.volume_name, self.project_id, self.task_id, self.attempt_id, self.input_digest)
        descriptors: list[int] = []
        try:
            root = _open_root(self.volume_root)
            descriptors.append(root)
            attempt = _open_dir(root, self._name)
            descriptors.append(attempt)
            if _read_identity(attempt) != _encoded(identity):
                raise _blocked("DOCKER_WORKSPACE_IDENTITY_MISMATCH")
            workspace = _open_dir(attempt, "workspace")
            descriptors.append(workspace)
            for parent, name in ((workspace, "sut"), (workspace, "framework"),
                                 (attempt, "dsh-home"), (attempt, "broker")):
                descriptors.append(_open_dir(parent, name))
            ids = [(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in descriptors]
            if len(set(ids)) != len(ids):
                raise _blocked()
            if expected_sockets is not None:
                if (not isinstance(expected_sockets, tuple) or not expected_sockets
                        or len(expected_sockets) != len(set(expected_sockets))
                        or not set(expected_sockets) <= _SOCKETS or "model.sock" not in expected_sockets):
                    raise _blocked("DOCKER_BROKER_SOCKET_INVALID")
                broker = descriptors[-1]
                if set(os.listdir(broker)) != set(expected_sockets):
                    raise _blocked("DOCKER_BROKER_SOCKET_INVALID")
                for name in expected_sockets:
                    info = os.stat(name, dir_fd=broker, follow_symlinks=False)
                    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid()
                            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                        raise _blocked("DOCKER_BROKER_SOCKET_INVALID")
        except CloudBlocked:
            raise
        except (OSError, ValueError, TypeError):
            raise _blocked() from None
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def mount_specs(self, *, expected_sockets: tuple[str, ...]) -> list[dict]:
        """Return ordered Docker Engine mount specs after rechecking the layout.

        Volume identity, Engine mount enforcement and container inspection are
        independent caller responsibilities. The parent Attempt directory and
        identity manifest are never mounted into the Agent.
        """
        self.validate(expected_sockets=expected_sockets)
        return [{"Type": "volume", "Source": self.volume_name, "Target": target, "ReadOnly": readonly,
                 "VolumeOptions": {"Subpath": f"{self._name}/{subpath}"}}
                for subpath, target, readonly in (
                    ("workspace", "/workspace", False), ("workspace/sut", "/workspace/sut", True),
                    ("dsh-home", "/home/agent", False), ("broker", "/run", True))]
