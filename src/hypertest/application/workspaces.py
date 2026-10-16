"""Prepare managed, pinned GitHub checkouts without touching operator work."""

import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import ConflictError, get_test_run
from hypertest.config import get_settings
from hypertest.domain.models import SourceSnapshot
from hypertest.runner.backends import run_process
from hypertest.runner.source import validate_checkout


async def prepare_workspace(session: AsyncSession, run_id: UUID) -> dict[str, str]:
    run = await get_test_run(session, run_id)
    snapshot = await session.get(SourceSnapshot, run.source_snapshot_id)
    assert snapshot is not None
    url = urlsplit(snapshot.repository_url)
    if (
        url.scheme != "https"
        or url.hostname != "github.com"
        or url.port is not None
        or url.username
        or url.password
        or url.query
        or url.fragment
        or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?", url.path)
    ):
        raise ValueError(
            "automatic checkout supports credential-free HTTPS github.com owner/repository URLs; use an existing workspace for other hosts"
        )
    if not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", snapshot.commit_sha):
        raise ValueError("automatic checkout requires a full pinned commit SHA")
    root = Path(get_settings().workspace_root).resolve()
    parent = root / ".hypertest-checkouts" / str(snapshot.id)
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.resolve().is_relative_to(root):
        raise ConflictError("managed checkout directory must remain inside the workspace root")
    destination = parent / "repo"
    if destination.exists():
        await validate_checkout(destination.resolve(), snapshot.commit_sha, snapshot.repository_url)
        return {
            "workspace": str(destination),
            "repository_url": snapshot.repository_url,
            "commit_sha": snapshot.commit_sha,
        }
    staging = Path(tempfile.mkdtemp(prefix="checkout-", dir=parent))
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        commands = [
            ["git", "init", str(staging)],
            ["git", "-C", str(staging), "remote", "add", "origin", snapshot.repository_url],
            ["git", "-C", str(staging), "fetch", "--depth=1", "origin", snapshot.commit_sha],
            ["git", "-C", str(staging), "checkout", "--detach", snapshot.commit_sha],
        ]
        for command in commands:
            result = await run_process(command, cwd=parent, timeout=120, env=environment)
            if result.exit_code != 0 or result.timed_out:
                raise ConflictError(
                    "cannot prepare pinned source using configured Git access; verify repository access, commit SHA and network availability"
                )
        await validate_checkout(staging, snapshot.commit_sha, snapshot.repository_url)
        try:
            staging.rename(destination)
        except OSError:
            if not destination.exists():
                raise
            await validate_checkout(
                destination.resolve(), snapshot.commit_sha, snapshot.repository_url
            )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "workspace": str(destination),
        "repository_url": snapshot.repository_url,
        "commit_sha": snapshot.commit_sha,
    }
