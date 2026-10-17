from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from hypertest.config import get_settings

if TYPE_CHECKING:
    from hypertest.domain.models import Evidence


class ArtifactIntegrityError(RuntimeError):
    pass


def artifact_root() -> Path:
    return Path(get_settings().artifact_root).expanduser().resolve()


def _path(sha256: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise ArtifactIntegrityError("invalid artifact digest")
    root = artifact_root()
    path = root / "sha256" / sha256[:2] / sha256
    if not path.resolve().is_relative_to(root):
        raise ArtifactIntegrityError("artifact path escapes content store")
    return path


def store_content(content: bytes) -> tuple[str, str]:
    """Write immutable content; a conflicting/missing artifact is never trusted."""
    digest = hashlib.sha256(content).hexdigest()
    path = _path(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ArtifactIntegrityError("artifact content does not match its digest")
    return digest, f"sha256:{digest}"


def read_evidence_content(evidence: Evidence) -> bytes:
    if evidence.artifact_uri != f"sha256:{evidence.sha256}":
        raise ArtifactIntegrityError("evidence URI does not match its content address")
    path = _path(evidence.sha256)
    try:
        if path.is_symlink():
            raise ArtifactIntegrityError("artifact cannot be a symbolic link")
        content = path.read_bytes()
    except OSError as exc:
        raise ArtifactIntegrityError("evidence artifact is unavailable") from exc
    if hashlib.sha256(content).hexdigest() != evidence.sha256:
        raise ArtifactIntegrityError("evidence artifact checksum mismatch")
    if evidence.size_bytes is not None and len(content) != evidence.size_bytes:
        raise ArtifactIntegrityError("evidence artifact size mismatch")
    return content
