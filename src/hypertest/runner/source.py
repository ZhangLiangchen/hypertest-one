from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from hypertest.runner.artifacts import ArtifactIntegrityError, artifact_root
from hypertest.runner.backends import ProcessResult, run_process


class SourceValidationError(RuntimeError):
    pass


class SourceGitError(SourceValidationError):
    """A failed bounded process observation, distinct from a proven mismatch."""

    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        # The process result stays in memory for trusted error classification;
        # ordinary error consumers see no command, path or subprocess output.
        super().__init__("repository validation Git operation failed")


def safe_nodeid(file_path: str, symbol: str) -> str:
    path = PurePosixPath(file_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.parts[0] != "tests"
        or path.suffix != ".py"
        or str(path) != file_path
        or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path.parts)
    ):
        raise SourceValidationError("implementations require a safe relative tests/*.py path")
    if not re.fullmatch(r"(?:[A-Za-z_]\w*::)*test_\w+", symbol):
        raise SourceValidationError("implementation symbol must identify a pytest test function")
    return f"{file_path}::{symbol}"


def _repo_identity(value: str) -> str:
    value = value.strip().removesuffix("/").removesuffix(".git")
    if value.startswith("git@") and ":" in value:
        hostname, path = value[4:].split(":", 1)
        return f"{hostname.lower()}/{path}"
    parsed = urlsplit(value)
    if parsed.hostname:
        return f"{parsed.hostname.lower()}/{parsed.path.lstrip('/')}"
    return str(Path(value).resolve())


async def git(source: Path, *args: str, output_limit: int = 8 * 1024 * 1024) -> bytes:
    result = await run_process(["git", "-C", str(source), *args], cwd=source, timeout=30,
                               output_limit=output_limit)
    if result.exit_code != 0 or result.timed_out:
        raise SourceGitError(result)
    return result.stdout


async def validate_checkout(source: Path, commit: str, repository_url: str, *,
                            include_files: bool = True, output_limit: int = 8 * 1024 * 1024) -> list[str]:
    if (await git(source, "rev-parse", "--show-toplevel", output_limit=output_limit)).decode().strip() != str(source):
        raise SourceValidationError("workspace must be the repository root")
    if not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", commit):
        raise SourceValidationError("official source snapshot requires a full Git commit SHA")
    if (await git(source, "rev-parse", "HEAD", output_limit=output_limit)).decode().strip() != commit.lower():
        raise SourceValidationError("workspace HEAD differs from the canonical source snapshot")
    if (await git(source, "status", "--porcelain", "--untracked-files=no", output_limit=output_limit)).strip():
        raise SourceValidationError("tracked repository content must match the source snapshot")
    remote = (await git(source, "remote", "get-url", "origin", output_limit=output_limit)).decode().strip()
    if _repo_identity(remote) != _repo_identity(repository_url):
        raise SourceValidationError("workspace origin differs from the canonical repository")
    if not include_files:
        return []
    return [item.decode() for item in (await git(source, "ls-files", "-z", output_limit=output_limit)).split(b"\0") if item]


def copy_tracked_source(source: Path, target: Path, files: list[str]) -> None:
    """Only tracked snapshot content crosses the runner boundary; never .git or host .env."""
    target.mkdir(parents=True)
    for relative in files:
        path = source / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(source)
            or ".git" in PurePosixPath(relative).parts
        ):
            raise SourceValidationError("snapshot contains unsupported symlink/submodule content")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        destination.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)


def implementation_content(implementation) -> bytes:
    digest = implementation.source_sha256
    uri = implementation.artifact_uri
    if not digest or not re.fullmatch(r"[a-f0-9]{64}", digest) or not uri:
        raise ArtifactIntegrityError("generated implementation requires a verified source digest")
    root = artifact_root()
    if uri == f"sha256:{digest}":
        path = root / "sha256" / digest[:2] / digest
    else:
        path = Path(uri.removeprefix("file://"))
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ArtifactIntegrityError("implementation artifact escapes content store")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ArtifactIntegrityError("implementation artifact is unavailable") from exc
    if hashlib.sha256(content).hexdigest() != digest:
        raise ArtifactIntegrityError("implementation artifact checksum mismatch")
    return content
