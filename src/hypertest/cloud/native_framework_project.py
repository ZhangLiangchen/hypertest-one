"""Open Cloud sessions in the framework project, like a local Harness session.

The per-execution directory still holds transport files and frozen input copies;
it is not the Agent's working directory. Reused project files are never reset.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .errors import CloudBlocked
from .native_git import _git, repository_url
from .worker import save_once

PROFILE = "hypertest-framework-project/v1"
RECORD = "framework-project.json"
_PREPARE_LOCKS: dict[str, asyncio.Lock] = {}


def repository_identity(url: str) -> tuple[str, str]:
    """Ignore transport spelling and .git, but never merge different namespaces."""
    url = repository_url(url)
    if "://" not in url:
        host, path = url.split(":", 1)
        host = host.rsplit("@", 1)[-1].lower()
    else:
        parsed = urlsplit(url)
        host = parsed.hostname.lower()
        if parsed.port and parsed.port not in {22, 443}:
            host += ":" + str(parsed.port)
        path = parsed.path
    path = path.strip("/").removesuffix(".git")
    parts = path.split("/")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in {".", ".."} for part in parts):
        raise CloudBlocked("FRAMEWORK_PROJECT_INVALID", "Unsupported framework repository path")
    return host + "/" + path, parts[-1]


async def prepare_framework_project(*, state: Path, attempt_root: Path | None, snapshot: Path,
                                    resolved: dict) -> Path:
    """Seed once from the accepted source; subsequently reuse the user's project.

    Normal Agent edits, branches and worktrees belong to the Agent. Never reset
    the shared checkout to a later task's frozen reference behind its back.
    """
    identity, basename = repository_identity(resolved["url"])
    parent = Path(state).parent / "framework-projects" / hashlib.sha256(identity.encode()).hexdigest()
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    project = parent / basename
    title = "hypervise" if identity == "gitlab.charprotocol.com/zhangliangchen/hypervise_pure" else basename
    record = {"profile": PROFILE, "repository": identity, "path": str(project), "title": title}
    # The Worker normally starts tasks sequentially; use its existing local lock
    # for concurrent slots too. It protects creation only, never Agent execution.
    from .native_worker import worker_lock

    async with _PREPARE_LOCKS.setdefault(identity, asyncio.Lock()):
        with worker_lock(parent):
            if not project.exists():
                await _git(["clone", "--no-hardlinks", "--no-checkout", str(snapshot), str(project)])
                await _git(["remote", "set-url", "origin", repository_url(resolved["url"])], cwd=project)
                await _git(["checkout", "--detach", resolved["commit_sha"]], cwd=project)
            if project.is_symlink() or not project.is_dir():
                raise CloudBlocked("FRAMEWORK_PROJECT_INVALID", "Framework project is not a regular directory")
            origin = await _git(["remote", "get-url", "origin"], cwd=project)
            if repository_identity(origin)[0] != identity:
                raise CloudBlocked("FRAMEWORK_PROJECT_INVALID", "Framework project repository does not match")
            # Read HEAD to reject incomplete clones, without changing existing files.
            await _git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=project)
            if not (parent / "project.json").exists():
                save_once(parent / "project.json", record)
            if json.loads((parent / "project.json").read_bytes()) != record:
                raise CloudBlocked("FRAMEWORK_PROJECT_INVALID", "Framework project registration has changed")
    if attempt_root is not None:
        save_once(Path(attempt_root) / RECORD, record)
    return project


def session_working_directory(workspace: Path) -> Path:
    """Old sessions without a project record keep their original directory."""
    workspace = Path(workspace)
    record_path = workspace.parent / RECORD
    if not record_path.exists():
        return workspace
    try:
        if record_path.is_symlink() or record_path.stat().st_size > 8192:
            raise ValueError
        record = json.loads(record_path.read_bytes())
        path = Path(record["path"])
        if (record.get("profile") != PROFILE or not path.is_absolute() or path.is_symlink()
                or path.resolve(strict=True) != path or not path.is_dir()):
            raise ValueError
        return path
    except (OSError, ValueError, KeyError, TypeError):
        raise CloudBlocked("FRAMEWORK_PROJECT_INVALID", "Original framework project is unavailable") from None
