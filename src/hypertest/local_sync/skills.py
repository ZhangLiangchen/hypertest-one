"""Explicitly export the bundled onboarding guide; never configure a host."""
from __future__ import annotations

import hashlib
import json
import os
import re
from importlib import resources
from pathlib import Path

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_read
from hypertest.local_sync import installer
from hypertest.sync_core import canonical_json

SKILL_NAME = "hypertest-local-task-onboarding"
SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/setup.md",
    "references/sync-contract.md",
    "references/troubleshooting.md",
)
PROFILE = "hypertest.local-skill-install/v1"


def bundled_skill() -> dict[str, bytes]:
    root = resources.files("hypertest.local_sync").joinpath("assets", "skills", SKILL_NAME)
    try:
        return {name: root.joinpath(*name.split("/")).read_bytes() for name in SKILL_FILES}
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ClientError("LOCAL_BUNDLED_SKILL_MISSING") from exc


def _checked_path(path: Path, *, directory: bool) -> Path:
    path = path.expanduser().absolute()
    if ".." in path.parts:
        raise ClientError("INSTALL_SKILL_PATH_REJECTED")
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise ClientError("INSTALL_SYMLINK_REJECTED")
        if parent.exists() and (parent != path or directory) and not parent.is_dir():
            raise ClientError("INSTALL_SKILL_PATH_REJECTED")
    if directory and path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ClientError("INSTALL_SKILL_DIRECTORY_REJECTED")
    return path


def _empty_destination(target: Path) -> bool:
    # A recovered first installation can leave these empty parent directories.
    # No unowned file, including an identical copy of this guide, is replaced.
    for child in target.iterdir():
        if (child.name not in {"agents", "references"} or not child.is_dir()
                or child.is_symlink() or any(child.iterdir())):
            return False
    return True


def install_skill(*, directory: Path, skills_directory: Path) -> dict:
    directory = _checked_path(directory, directory=True)
    selected = _checked_path(skills_directory, directory=True)
    target = _checked_path(selected / SKILL_NAME, directory=True)
    payload = bundled_skill()
    hashes = {name: hashlib.sha256(payload[name]).hexdigest() for name in SKILL_FILES}
    receipt = {
        "profile": PROFILE, "skill": SKILL_NAME, "skill_directory": str(target),
        "files": hashes, "content_sha256": hashlib.sha256(canonical_json(hashes).encode()).hexdigest(),
    }
    receipt_file = directory / ("installed-skill-" + hashlib.sha256(str(target).encode()).hexdigest() + ".json")
    with installer.install_lock(directory):
        if installer._pending_transactions(directory):
            raise ClientError("INSTALL_RECOVERY_REQUIRED")
        _checked_path(target, directory=True)
        _checked_path(receipt_file, directory=False)
        old_bytes = private_read(receipt_file) if receipt_file.exists() else b""
        old = json.loads(old_bytes) if old_bytes else None
        if old is not None:
            if (not isinstance(old, dict) or old.get("profile") != PROFILE or old.get("skill") != SKILL_NAME
                    or old.get("skill_directory") != str(target)
                    or not isinstance(old.get("files"), dict) or set(old["files"]) != set(SKILL_FILES)
                    or any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
                           for value in old["files"].values())):
                raise ClientError("INSTALL_SKILL_RECEIPT_INVALID")
        elif target.exists() and not _empty_destination(target):
            raise ClientError("INSTALL_UNOWNED_SKILL_CONFLICT")
        changes = []
        for name in SKILL_FILES:
            path = _checked_path(target / name, directory=False)
            _checked_path(path.parent, directory=True)
            before = installer.read_host(path)
            if old is None and path.exists():
                raise ClientError("INSTALL_UNOWNED_SKILL_CONFLICT")
            if old is not None and (not path.exists() or hashlib.sha256(before).hexdigest() != old["files"][name]):
                raise ClientError("MANAGED_SKILL_CHANGED")
            if before != payload[name]:
                changes.append((path, before, payload[name]))
        after = canonical_json(receipt).encode()
        if old_bytes != after:
            changes.append((receipt_file, old_bytes, after))
        if changes:
            installer._commit_changes(directory, changes)
    return {"configuration": "WRITTEN" if changes else "UNCHANGED", "skill": SKILL_NAME,
            "skill_directory": str(target), "receipt_file": str(receipt_file), "files": len(SKILL_FILES)}
