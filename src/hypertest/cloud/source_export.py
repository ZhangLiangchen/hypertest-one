"""Frozen, explicitly selected source files for an untrusted Cloud Agent.

The complete Git checkout remains in the Worker-only runtime directory.  The
Agent receives only the operator-selected file bytes, never a Git object store.
This is not a credential vault or a way to execute an authenticated request.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path, PurePosixPath

from .errors import CloudBlocked

PROFILE = "cloud-agent-source-export/v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 4096
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_DENIED_COMPONENTS = frozenset({".git", ".hg", ".svn", ".ssh", ".aws", ".gnupg"})
_DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")


def _blocked(code: str = "SOURCE_EXPORT_INVALID") -> CloudBlocked:
    return CloudBlocked(code, "Cloud Agent source export failed closed")


def _path(value: object) -> str:
    if (not isinstance(value, str) or not value or len(value) > 512 or "\\" in value
            or "\x00" in value or any(ord(char) < 32 for char in value)):
        raise _blocked()
    path = PurePosixPath(value)
    if (path.is_absolute() or value != str(path) or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(part.lower() in _DENIED_COMPONENTS for part in path.parts)):
        raise _blocked()
    name = path.name.lower()
    if (name in {".env", "env_password", "env_info", "secrets.yaml", "secrets.yml", "secrets.json"}
            or name.endswith(_DENIED_SUFFIXES) or name.startswith(".env.")
            or "api_key" in name or "apikey" in name or "private_key" in name):
        raise _blocked("SOURCE_EXPORT_SENSITIVE_PATH")
    return value


def validate_export(value: object) -> dict:
    """Validate a strict, complete list frozen in Task inputs before dispatch."""
    if not isinstance(value, dict) or set(value) != {"profile", "sut", "framework"} or value["profile"] != PROFILE:
        raise _blocked()
    result = {"profile": PROFILE}
    total = 0
    for role in ("sut", "framework"):
        entries = value[role]
        if not isinstance(entries, list) or not entries:
            raise _blocked()
        paths = set()
        result[role] = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                raise _blocked()
            path = _path(entry["path"])
            digest = entry["sha256"]
            if path in paths or not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
                raise _blocked()
            paths.add(path)
            result[role].append({"path": path, "sha256": digest})
            total += 1
        if any(a.startswith(b + "/") or b.startswith(a + "/") for a, b in zip(sorted(paths), sorted(paths)[1:], strict=False)):
            raise _blocked()
    if total > MAX_FILES:
        raise _blocked()
    return result


def _open_root(path: Path) -> int:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise _blocked()
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(descriptor)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(descriptor)
        raise _blocked()
    return descriptor


def _read(root: int, path: str, expected: str, remaining: int) -> tuple[bytes, bool]:
    descriptors = []
    try:
        parent = root
        parts = path.split("/")
        for component in parts[:-1]:
            parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            descriptors.append(parent)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        descriptors.append(fd)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1
                or before.st_size > remaining or before.st_mode & (stat.S_ISUID | stat.S_ISGID)):
            raise _blocked()
        chunks = []
        left = before.st_size
        while left:
            chunk = os.read(fd, min(left, 65536))
            if not chunk:
                raise _blocked()
            chunks.append(chunk)
            left -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or hashlib.sha256(raw).hexdigest() != expected):
            raise _blocked("SOURCE_EXPORT_DIGEST_MISMATCH")
        return raw, bool(before.st_mode & stat.S_IXUSR)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _write(root: int, path: str, raw: bytes, executable: bool) -> None:
    descriptors = []
    try:
        parent = root
        parts = path.split("/")
        for component in parts[:-1]:
            try:
                os.mkdir(component, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            descriptors.append(parent)
            info = os.fstat(parent)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise _blocked()
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o700 if executable else 0o600, dir_fd=parent)
        descriptors.append(fd)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise _blocked()
            view = view[count:]
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


async def export_sources(*, policy: dict, sources: dict[str, Path], destinations: dict[str, Path], validate_payload,
                         private_framework: Path | None = None) -> None:
    """Validate both complete exports before releasing any bytes to the Agent.

    The private Agent container must not yet have started and no other writer
    may access either destination. A failed scan or copy prevents admission.
    """
    policy = validate_export(policy)
    if set(sources) != {"sut", "framework"} or set(destinations) != {"sut", "framework"}:
        raise _blocked()
    descriptors = []
    try:
        contents = []
        roots = {}
        signer_root = None
        if private_framework is not None:
            signer_root = _open_root(Path(private_framework))
            descriptors.append(signer_root)
            if os.listdir(signer_root):
                raise _blocked()
        total = 0
        for role in ("sut", "framework"):
            src = _open_root(Path(sources[role]))
            dst = _open_root(Path(destinations[role]))
            descriptors.extend((src, dst))
            if os.listdir(dst):
                raise _blocked()
            roots[role] = dst
            for entry in policy[role]:
                raw, executable = _read(src, entry["path"], entry["sha256"], MAX_BYTES - total)
                total += len(raw)
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    raise _blocked("SOURCE_EXPORT_NON_TEXT") from None
                contents.append((role, entry["path"], raw, executable, text))
        await validate_payload({"source_export": [{"path": path, "content": text}
                           for _, path, _, _, text in contents]})
        for role, path, raw, executable, _ in contents:
            _write(roots[role], path, raw, executable)
            if role == "framework" and signer_root is not None:
                _write(signer_root, path, raw, executable)
    except CloudBlocked:
        raise
    except (OSError, ValueError, TypeError):
        raise _blocked() from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
