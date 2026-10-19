"""Prepare managed, pinned GitHub checkouts without touching operator work."""

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import ConflictError, get_test_run
from hypertest.application.source_diagnostics import (
    GIT_OUTPUT_LIMIT,
    SourcePreparationError,
    filesystem_failure,
    git_failure,
)
from hypertest.config import get_settings
from hypertest.domain.models import SourceSnapshot
from hypertest.runner.backends import run_process
from hypertest.runner.source import SourceGitError, SourceValidationError, validate_checkout


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
    stage = "validate_input"
    staging = None

    def resolve_workspace_path(path: Path) -> Path:
        try:
            return path.resolve()
        except RuntimeError:
            # Python 3.12 reports symlink loops as RuntimeError with the full
            # path. Only this filesystem operation is translated, not arbitrary
            # RuntimeErrors from preparation or validation implementations.
            raise SourcePreparationError(stage=stage, category="storage") from None

    async def verify_checkout(path: Path) -> None:
        await validate_checkout(path, snapshot.commit_sha, snapshot.repository_url,
                                include_files=False, output_limit=GIT_OUTPUT_LIMIT)

    try:
        try:
            github_repository_url(snapshot.repository_url)
        except ValueError:
            raise SourcePreparationError(stage=stage, category="invalid_source") from None
        if not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", snapshot.commit_sha):
            raise SourcePreparationError(stage=stage, category="invalid_source")
        if not shutil.which("git"):
            raise SourcePreparationError(stage=stage, category="git_unavailable")
        stage = "create_workspace"
        root = resolve_workspace_path(Path(get_settings().workspace_root))
        parent = root / ".hypertest-checkouts" / str(snapshot.id)
        if not resolve_workspace_path(parent).is_relative_to(root):
            raise SourcePreparationError(stage=stage, category="checkout_integrity")
        parent.mkdir(parents=True, exist_ok=True)
        destination = parent / "repo"
        if destination.exists() or destination.is_symlink():
            stage = "validate_checkout"
            await verify_checkout(resolve_workspace_path(destination))
            return {
                "workspace": str(destination),
                "repository_url": snapshot.repository_url,
                "commit_sha": snapshot.commit_sha,
            }
        staging = Path(tempfile.mkdtemp(prefix="checkout-", dir=parent))
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        commands = [
            ("git_init", ["git", "init", str(staging)]),
            ("configure_remote", ["git", "-C", str(staging), "remote", "add", "origin", snapshot.repository_url]),
            ("fetch_commit", ["git", "-C", str(staging), "fetch", "--depth=1", "origin", snapshot.commit_sha]),
            ("checkout_commit", ["git", "-C", str(staging), "checkout", "--detach", snapshot.commit_sha]),
        ]
        for stage, command in commands:
            try:
                result = await run_process(command, cwd=parent, timeout=120, env=environment,
                                           output_limit=GIT_OUTPUT_LIMIT)
            except OSError as exc:
                raise filesystem_failure(stage, exc, spawning_git=True) from None
            if result.exit_code != 0 or result.timed_out:
                raise git_failure(stage, result)
        stage = "validate_checkout"
        await verify_checkout(staging)
        stage = "publish_workspace"
        try:
            staging.rename(destination)
        except OSError:
            if not destination.exists():
                raise
            stage = "validate_checkout"
            await verify_checkout(resolve_workspace_path(destination))
    except SourceGitError as exc:
        raise git_failure(stage, exc.result) from None
    except SourceValidationError:
        raise SourcePreparationError(stage=stage, category="checkout_integrity") from None
    except OSError as exc:
        raise filesystem_failure(stage, exc, spawning_git=stage == "validate_checkout") from None
    finally:
        # Cleanup must not replace a preparation failure or cancellation with
        # an unsafe filesystem exception containing operator paths.
        failed = sys.exception() is not None
        if staging is not None:
            try:
                if staging.exists():
                    shutil.rmtree(staging)
            except OSError as exc:
                if not failed:
                    raise filesystem_failure("publish_workspace", exc) from None
    return {
        "workspace": str(destination),
        "repository_url": snapshot.repository_url,
        "commit_sha": snapshot.commit_sha,
    }
