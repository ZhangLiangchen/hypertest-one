"""Private original-container recovery capability, never a cloud:work token.

The caller supplies an existing Worker-only private root and must independently
verify it is not mounted into any Agent or project framework container. This
module never creates that root, removes a file, or restarts an operation.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from .errors import CloudBlocked

PROFILE = "hypertest-cloud-container-recovery/v1"
_FILE = "container-recovery.json"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_WORKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_FIELDS = {"profile", "project_id", "task_id", "attempt_id", "create_key", "generation", "worker_id", "secret_base64"}


def _blocked(code: str = "CONTAINER_RECOVERY_UNAVAILABLE") -> CloudBlocked:
    return CloudBlocked(code, "Original container recovery capability is unavailable or unsafe")


def _uuid(value: str) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


@dataclass(frozen=True)
class RecoveryIdentity:
    project_id: str
    task_id: str
    attempt_id: str
    create_key: str
    generation: int
    worker_id: str

    def document(self) -> dict:
        if (not all(_uuid(item) for item in (self.project_id, self.task_id, self.attempt_id))
                or not isinstance(self.create_key, str) or not _SAFE_ID.fullmatch(self.create_key)
                or type(self.generation) is not int or not 1 <= self.generation <= 2**63 - 1
                or not isinstance(self.worker_id, str) or not _WORKER.fullmatch(self.worker_id)):
            raise _blocked("CONTAINER_RECOVERY_IDENTITY_INVALID")
        return {"profile": PROFILE, "project_id": self.project_id, "task_id": self.task_id,
                "attempt_id": self.attempt_id, "create_key": self.create_key,
                "generation": self.generation, "worker_id": self.worker_id}


@dataclass(frozen=True)
class RecoveryCapability:
    identity: RecoveryIdentity
    secret: bytes = field(repr=False)

    def __post_init__(self):
        self.identity.document()
        if not isinstance(self.secret, bytes) or len(self.secret) != 32:
            raise _blocked("CONTAINER_RECOVERY_SECRET_INVALID")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.secret).hexdigest()


def _open_private_root(private_root: Path) -> int:
    raw = os.fspath(private_root)
    if (not isinstance(raw, str) or not raw.startswith("/") or os.path.normpath(raw) != raw
            or raw == "/" or os.geteuid() == 0):
        raise _blocked()
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in Path(raw).parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise _blocked()
        return fd
    except BaseException:
        os.close(fd)
        raise


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def create_recovery_capability(private_root: Path, identity: RecoveryIdentity) -> RecoveryCapability:
    """Persist one random capability without replacing existing or partial state."""
    document = identity.document()
    secret = secrets.token_bytes(32)
    document["secret_base64"] = base64.b64encode(secret).decode("ascii")
    data = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    root = fd = None
    try:
        root = _open_private_root(private_root)
        try:
            fd = os.open(_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=root)
        except FileExistsError:
            raise _blocked("CONTAINER_RECOVERY_EXISTS") from None
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise _blocked()
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("short private write")
            view = view[count:]
        os.fsync(fd)
        os.fsync(root)
        return RecoveryCapability(identity, secret)
    except CloudBlocked:
        raise
    except (OSError, ValueError, TypeError):
        # A partial file is deliberately left in place for explicit recovery.
        raise _blocked() from None
    finally:
        if fd is not None:
            os.close(fd)
        if root is not None:
            os.close(root)


def load_recovery_capability(private_root: Path, identity: RecoveryIdentity,
                             expected_sha256: str) -> RecoveryCapability:
    """Reopen the original capability and match trusted identity and digest."""
    expected = identity.document()
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        raise _blocked("CONTAINER_RECOVERY_DIGEST_INVALID")
    root = fd = None
    try:
        root = _open_private_root(private_root)
        fd = os.open(_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=root)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 < before.st_size <= 4096):
            raise _blocked()
        data = os.read(fd, 4097)
        after = os.fstat(fd)
        named = os.stat(_FILE, dir_fd=root, follow_symlinks=False)
        def identity_of(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
        if len(data) != before.st_size or identity_of(before) != identity_of(after) or identity_of(before) != identity_of(named):
            raise _blocked()
        document = json.loads(data, object_pairs_hook=_json_pairs)
        if not isinstance(document, dict) or set(document) != _FIELDS:
            raise ValueError("unexpected document")
        encoded = document.pop("secret_base64")
        if document != expected or type(document.get("generation")) is not int or not isinstance(encoded, str):
            raise ValueError("identity mismatch")
        secret = base64.b64decode(encoded, validate=True)
        if (len(secret) != 32 or base64.b64encode(secret).decode("ascii") != encoded
                or not hmac.compare_digest(hashlib.sha256(secret).hexdigest(), expected_sha256)):
            raise ValueError("digest mismatch")
        return RecoveryCapability(identity, secret)
    except CloudBlocked:
        raise
    except (OSError, ValueError, TypeError, UnicodeDecodeError, binascii.Error):
        raise _blocked() from None
    finally:
        if fd is not None:
            os.close(fd)
        if root is not None:
            os.close(root)
