"""Immutable, content-addressed Cloud objects with no arbitrary path/URL reads."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

from .errors import CloudBlocked

_HASH = re.compile(r"[0-9a-f]{64}")


def write_workspace_receipt(root: Path, key: str, receipt: dict) -> None:
    """Create a bounded receipt without following Agent-controlled symlinks."""
    _write_workspace_metadata(root, "receipts", key, receipt, "RECEIPT")


def write_workspace_rejection(root: Path, key_sha256: str, rejection: dict) -> None:
    """A LOCAL_REJECTED proposal is never an accepted platform receipt."""
    if not _HASH.fullmatch(key_sha256) or rejection.get("status") != "LOCAL_REJECTED":
        raise CloudBlocked("LOCAL_REJECTION_INVALID", "Local feedback requires a digest and fixed status")
    _write_workspace_metadata(root, "rejections", key_sha256, rejection, "LOCAL_REJECTION")


def _write_workspace_metadata(root: Path, directory: str, key: str, document: dict, prefix: str) -> None:
    import json
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", key):
        raise CloudBlocked(prefix + "_KEY_INVALID", "Runtime metadata requires a stable key")
    content = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    if len(content) > 65536:
        raise CloudBlocked(prefix + "_SIZE", "Runtime metadata exceeds its bound")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in (".hypertest-cloud", directory):
            try:
                os.mkdir(component, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        try:
            leaf = os.open(key + ".json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=fd)
        except FileExistsError:
            if read_workspace_file(root, f".hypertest-cloud/{directory}/{key}.json", max_bytes=65536) != content:
                raise CloudBlocked(prefix + "_CONFLICT", "Existing runtime metadata differs from its original") from None
        else:
            with os.fdopen(leaf, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(fd)
    except OSError:
        raise CloudBlocked(prefix + "_PATH_UNSAFE", "Runtime metadata directory is missing or unsafe") from None
    finally:
        os.close(fd)


def read_workspace_file(root: Path, relative: str, *, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    """Open each component with NOFOLLOW; a symlink swap cannot escape the root."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {".", ".."} for p in parts):
        raise CloudBlocked("ARTIFACT_PATH_INVALID", "Artifact must be a contained relative regular file")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in parts[:-1]:
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(leaf, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                raise CloudBlocked("ARTIFACT_SIZE", "Artifact must be a bounded regular file")
            content = stream.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise CloudBlocked("ARTIFACT_SIZE", "Artifact exceeds its byte limit")
            return content
    except OSError as exc:
        raise CloudBlocked("ARTIFACT_PATH_UNAVAILABLE", "Artifact path is missing or unsafe") from exc
    finally:
        os.close(fd)


class ArtifactStore:
    def __init__(self, root: str | Path, max_bytes: int = 8 * 1024 * 1024):
        self.root = Path(root).absolute()
        self.max_bytes = max_bytes
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise CloudBlocked("ARTIFACT_ROOT_INVALID", "Artifact root must not contain symlinks")

    def put(self, content: bytes) -> dict[str, str | int]:
        if not isinstance(content, bytes) or len(content) > self.max_bytes:
            raise CloudBlocked("ARTIFACT_SIZE", "Artifact exceeds the upload byte limit")
        digest = hashlib.sha256(content).hexdigest()
        destination = self.root / digest
        fd, tmp = tempfile.mkstemp(prefix=".pending-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(tmp, destination, follow_symlinks=False)
            except FileExistsError:
                pass  # Validate the existing immutable object; never overwrite it.
            actual = self.read(digest, sha256=digest, byte_length=len(content))
            if actual != content:
                raise CloudBlocked("ARTIFACT_INTEGRITY", "Persisted artifact differs from submitted bytes")
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(tmp)
        return {"storage_key": digest, "sha256": digest, "byte_length": len(content)}

    def read(self, storage_key: str, *, sha256: str | None = None,
             byte_length: int | None = None) -> bytes:
        if not _HASH.fullmatch(storage_key):
            raise CloudBlocked("ARTIFACT_KEY_INVALID", "Only controlled object identities may be read")
        content = read_workspace_file(self.root, storage_key, max_bytes=self.max_bytes)
        if hashlib.sha256(content).hexdigest() != (sha256 or storage_key):
            raise CloudBlocked("ARTIFACT_INTEGRITY", "Persisted artifact digest mismatch")
        if byte_length is not None and len(content) != byte_length:
            raise CloudBlocked("ARTIFACT_INTEGRITY", "Persisted artifact byte length mismatch")
        return content
