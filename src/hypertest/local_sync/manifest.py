"""Read only a selected main-session manifest and allowlisted testing artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_read
from hypertest.local_sync import LOCAL_PROFILE
from hypertest.sync_core import digest


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SourceIdentity(StrictModel):
    project_id: UUID
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    parent_session_id: str = Field(min_length=1, max_length=512)


class ApprovedArtifact(StrictModel):
    kind: Literal["TEST_PLAN", "TEST_REPORT"]
    path: Path
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    title: str | None = Field(default=None, min_length=1, max_length=512)
    reported_result: Literal["NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"] | None = None
    source_ref: str | None = Field(default=None, max_length=2048)


class ArtifactManifest(StrictModel):
    profile: Literal["hypertest.local-manifest/v1alpha1"] = LOCAL_PROFILE
    identity: SourceIdentity
    base_version: int = Field(ge=0)
    set: dict = Field(default_factory=dict)
    clear: list[Literal["objective", "plan_markdown"]] = Field(default_factory=list)
    artifacts: list[ApprovedArtifact] = Field(default_factory=list, max_length=17)


def reject_secrets(value: str) -> None:
    if (re.search(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", value)
            or re.search(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_.=-]{16,}", value)
            or re.search(r"https?://[^\s/@:]+:[^\s/@]+@", value)
            or re.search(r'"(?:integration_token|device_token|execution_token|operator_key)"\s*:\s*"[^\"]+"', value)):
        raise ClientError("SECRET_MATERIAL_REJECTED")


def artifact_read(path: Path, roots: list[Path]) -> bytes:
    if not path.is_absolute():
        raise ClientError("ABSOLUTE_APPROVED_ARTIFACT_REQUIRED")
    if path.suffix.lower() not in {".md", ".markdown"}:
        raise ClientError("ONLY_APPROVED_MARKDOWN_ARTIFACTS_SUPPORTED")
    roots = [root.expanduser() for root in roots]
    if any(not root.is_absolute() or ".." in root.parts for root in roots):
        raise ClientError("ABSOLUTE_APPROVED_ROOT_REQUIRED")
    root = next((root for root in roots if path.is_relative_to(root)), None)
    if root is None or root == Path("/"):
        raise ClientError("ARTIFACT_OUTSIDE_ALLOWLIST")
    parts = path.relative_to(root).parts
    if (not parts or any(part in {".", ".."} or part.startswith(".")
                         or part.lower() in {"transcripts", "rollouts", "sessions"}
                         or "transcript" in part.lower() for part in parts)):
        raise ClientError("ARTIFACT_SOURCE_REJECTED")
    # Hold every directory FD while traversing relative to it. Replacing a path
    # or symlink during a hook cannot redirect the final read outside this root.
    directory_fds = []
    try:
        directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory_fds.append(directory)
        for part in root.parts[1:]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
            directory_fds.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
            directory_fds.append(directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    except OSError as exc:
        raise ClientError("APPROVED_ARTIFACT_FILE_REJECTED") from exc
    finally:
        for directory in reversed(directory_fds):
            os.close(directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_size > 2 * 1024 * 1024):
            raise ClientError("APPROVED_ARTIFACT_FILE_REJECTED")
        data = bytearray()
        while len(data) <= 2 * 1024 * 1024:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data.extend(chunk)
    finally:
        os.close(fd)
    if len(data) > 2 * 1024 * 1024:
        raise ClientError("ARTIFACT_SIZE_EXCEEDED")
    return bytes(data)


def load_manifest(path: Path, roots: list[Path], *, expected_identity: dict):
    raw = private_read(path, max_bytes=2 * 1024 * 1024)
    reject_secrets(raw.decode("utf-8"))
    try:
        manifest = ArtifactManifest.model_validate_json(raw)
    except ValidationError as exc:
        raise ClientError("INVALID_APPROVED_MANIFEST") from exc
    identity = {"project_id": str(manifest.identity.project_id),
                "provider": manifest.identity.provider,
                "session_id": manifest.identity.parent_session_id}
    if identity != expected_identity:
        raise ClientError("MANIFEST_PARENT_PROJECT_MISMATCH")
    changes = json.loads(json.dumps(manifest.set))
    if "plan_markdown" in changes and any(a.kind == "TEST_PLAN" for a in manifest.artifacts):
        raise ClientError("DUPLICATE_PLAN_SOURCE")
    seen_plan = False
    for artifact in manifest.artifacts:
        data = artifact_read(artifact.path, roots)
        if hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise ClientError("APPROVED_ARTIFACT_DIGEST_MISMATCH")
        text = data.decode("utf-8")
        reject_secrets(text)
        if len(text) > 262144:
            raise ClientError("ARTIFACT_SIZE_EXCEEDED")
        if artifact.kind == "TEST_PLAN":
            if seen_plan:
                raise ClientError("DUPLICATE_PLAN_SOURCE")
            seen_plan = True
            changes["plan_markdown"] = text
        else:
            if artifact.key is None or artifact.title is None or artifact.reported_result is None:
                raise ClientError("REPORT_REQUIRES_EXPLICIT_KEY_TITLE_RESULT")
            changes.setdefault("reports", []).append({"key": artifact.key, "title": artifact.title,
                "markdown": text, "reported_result": artifact.reported_result,
                "source_ref": artifact.source_ref, "artifact_uri": None})
    return manifest, identity, changes, digest({"manifest": json.loads(raw), "changes": changes})
