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


def github_repository_url(repository_url: str) -> str:
    """Only the existing managed-checkout GitHub transport may contact a host."""
    value = repository_url.strip()
    try:
        url = urlsplit(value)
        supported = (
            url.scheme == "https"
            and url.hostname == "github.com"
            and url.port is None
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?", url.path)
        )
    except ValueError:
        # urllib diagnostics can include a submitted authority or invalid port.
        supported = False
    if not supported:
        raise ValueError(
            "automatic checkout supports credential-free HTTPS github.com owner/repository URLs; use an existing workspace for other hosts"
        ) from None
    return f"https://github.com{url.path.rstrip('/')}"


async def resolve_source(repository_url: str, revision: str) -> dict[str, str]:
    """Resolve a branch/tag before creating immutable input; never edit a checkout."""
    repository = github_repository_url(repository_url)
    revision = revision.strip()
    if not revision or revision.startswith("-"):
        raise ValueError("choose a valid branch or tag, or enter a full commit SHA")
    if re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", revision):
        return {"repository_url": repository, "commit_sha": revision.lower(), "revision": revision}
    if revision.startswith("refs/"):
        if not revision.startswith(("refs/heads/", "refs/tags/")):
            raise ValueError("choose a branch, tag, or full commit SHA")
        refs = [revision]
    else:
        refs = [f"refs/heads/{revision}", f"refs/tags/{revision}"]
    if not shutil.which("git"):
        raise ConflictError("Git is unavailable on the HyperTest host")
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    root = Path(tempfile.gettempdir()).resolve()
    for ref in refs:
        checked = await run_process(
            ["git", "check-ref-format", ref], cwd=root, timeout=5, env=environment,
        )
        if checked.exit_code != 0 or checked.timed_out:
            raise ValueError("choose a valid branch or tag, or enter a full commit SHA")
    patterns = [item for ref in refs for item in (ref, f"{ref}^{{}}")]
    resolved = await run_process(
        ["git", "ls-remote", "--exit-code", "--", repository, *patterns],
        cwd=root, timeout=30, env=environment, output_limit=256 * 1024,
    )
    if resolved.exit_code != 0 or resolved.timed_out:
        raise ConflictError(
            "cannot resolve repository revision; verify the branch/tag, configured Git access and network availability"
        )
    matches = {}
    for line in resolved.stdout.decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] in patterns and re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", fields[0]):
            matches[fields[1]] = fields[0]
    tips = [(ref, matches.get(f"{ref}^{{}}", matches.get(ref))) for ref in refs if ref in matches]
    if len(tips) != 1:
        raise ConflictError(
            "revision is missing or ambiguous; use an explicit refs/heads/branch or refs/tags/tag"
        )
    return {"repository_url": repository, "commit_sha": tips[0][1], "revision": revision}


async def prepare_workspace(session: AsyncSession, run_id: UUID) -> dict[str, str]:
    run = await get_test_run(session, run_id)
    snapshot = await session.get(SourceSnapshot, run.source_snapshot_id)
    assert snapshot is not None
    github_repository_url(snapshot.repository_url)
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
