"""Host Git access with the operator's existing credential helpers and SSH agent.

Only the trusted Worker calls this adapter. Credentials are never accepted in a
repository URL or as a platform token. Git output and errors are not logged.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .errors import CloudBlocked
from .git import SHA, _ref, require_private_empty_checkout_target

_SCP = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*:[A-Za-z0-9_./~-]+\Z")


def repository_url(value: str) -> str:
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise CloudBlocked("GIT_URL_INVALID", "Invalid repository address")
    if _SCP.fullmatch(value) and "://" not in value:
        return value
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"https", "ssh"} or not parsed.hostname or not parsed.path.strip("/")
                or parsed.password is not None or parsed.query or parsed.fragment
                or (parsed.scheme == "https" and parsed.username is not None)
                or (parsed.scheme == "ssh" and parsed.username == "")):
            raise ValueError
        # Accessing port checks malformed and out-of-range ports.
        _ = parsed.port
    except ValueError:
        raise CloudBlocked("GIT_URL_INVALID", "Repository address must not contain credentials") from None
    return value


def _environment() -> dict[str, str]:
    # Do not inherit platform tokens or arbitrary task environment. Git and
    # credential helpers retain the operator's normal configuration and agent.
    allowed = ("HOME", "USER", "LOGNAME", "PATH", "SSH_AUTH_SOCK", "XDG_CONFIG_HOME",
               "GH_CONFIG_DIR", "GLAB_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN",
               "GLAB_TOKEN", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/usr/bin/false",
                "SSH_ASKPASS": "/usr/bin/false", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
                "GCM_INTERACTIVE": "never", "GH_PROMPT_DISABLED": "1", "LC_ALL": "C"})
    return env


async def _git(args: list[str], *, cwd: Path | None = None, timeout: float = 90) -> str:
    env = _environment()
    executable = shutil.which("git", path=env.get("PATH", os.defpath))
    if executable is None:
        raise CloudBlocked("GIT_UNAVAILABLE", "Git is unavailable on the host")
    process = await asyncio.create_subprocess_exec(
        executable, "-c", "core.hooksPath=/dev/null", *args, cwd=cwd, env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        raise
    if process.returncode or len(stdout) > 2 * 1024 * 1024:
        raise CloudBlocked("GIT_OPERATION_FAILED", "Host repository operation failed")
    try:
        return stdout.decode("utf-8", errors="strict").strip()
    except UnicodeError:
        raise CloudBlocked("GIT_OPERATION_FAILED", "Host repository operation failed") from None


class NativeGitResolver:
    """Resolve and fetch exact revisions using the local user's Git identity."""

    @staticmethod
    def _no_token(token: bytes | None) -> None:
        if token is not None:
            raise CloudBlocked("GIT_PLATFORM_TOKEN_UNSUPPORTED", "Host Git uses the operator's configured identity")

    async def _fetch(self, root: Path, url: str, ref: str) -> str:
        await _git(["fetch", "--no-tags", "--no-recurse-submodules", url, ref], cwd=root)
        commit = await _git(["rev-parse", "--verify", "FETCH_HEAD^{commit}"], cwd=root)
        if not SHA.fullmatch(commit):
            raise CloudBlocked("GIT_SHA_INVALID", "Git did not return a full commit hash")
        return commit

    async def resolve(self, url: str, selector: dict, *, token: bytes | None = None) -> dict:
        self._no_token(token)
        url = repository_url(url)
        kind = selector.get("kind", "BRANCH").upper()
        value = selector.get("value", selector.get("ref", ""))
        with tempfile.TemporaryDirectory(prefix="hypertest-host-resolve-") as directory:
            root = Path(directory)
            await _git(["init", "--bare", str(root)])
            if kind == "SHA":
                if not isinstance(value, str) or not SHA.fullmatch(value):
                    raise CloudBlocked("GIT_SHA_INVALID", "A SHA selector requires a full commit hash")
                commit = await self._fetch(root, url, value)
                if commit != value:
                    raise CloudBlocked("GIT_SHA_MISMATCH", "Fetched commit differs from the requested SHA")
                return {"url": url, "selector": selector, "commit_sha": commit, "source": "worker-git-fetch"}
            if kind in {"BRANCH", "REF", "TAG"}:
                ref = _ref("refs/tags/" + value if kind == "TAG" and not value.startswith("refs/") else value)
                sha = await self._fetch(root, url, ref)
                return {"url": url, "selector": selector, "commit_sha": sha,
                        "resolved_ref": ref, "source": "worker-git-fetch"}
            if kind != "MR":
                raise CloudBlocked("GIT_SELECTOR_UNSUPPORTED", "Unsupported Git selector")
            number = selector.get("number")
            if number is None and str(value).isdigit():
                number = int(value)
            if type(number) is not int or number < 1:
                raise CloudBlocked("MR_ID_REQUIRED", "MR selector requires a positive number")
            strategy = selector.get("checkout_strategy", "HEAD").upper()
            head_ref = _ref(selector.get("head_ref", f"refs/merge-requests/{number}/head"))
            base_ref = _ref(selector.get("mr_base_ref") or selector.get("base_ref", ""))
            head = await self._fetch(root, url, head_ref)
            base = await self._fetch(root, url, base_ref)
            if strategy == "HEAD":
                checkout = head
            elif strategy == "MERGE":
                merge_ref = _ref(selector.get("merge_ref", f"refs/merge-requests/{number}/merge"))
                checkout = await self._fetch(root, url, merge_ref)
                parents = (await _git(["rev-list", "--parents", "-n", "1", checkout], cwd=root)).split()[1:]
                if len(parents) != 2 or head not in parents or base not in parents:
                    raise CloudBlocked("MR_MERGE_PROVENANCE", "MR merge parents do not match base/head")
                if head != await self._fetch(root, url, head_ref) or base != await self._fetch(root, url, base_ref):
                    raise CloudBlocked("MR_MOVED_DURING_RESOLUTION", "MR changed during resolution")
            else:
                raise CloudBlocked("MR_STRATEGY_INVALID", "MR checkout strategy must be HEAD or MERGE")
            return {"url": url, "selector": selector, "commit_sha": checkout, "mr_number": number,
                    "base_sha": base, "head_sha": head, "actual_checkout_sha": checkout,
                    "checkout_strategy": strategy, "source": "worker-git-fetch"}

    async def checkout(self, resolved: dict, destination: Path, *, token: bytes | None = None,
                       private_empty: bool = False) -> None:
        self._no_token(token)
        sha = resolved.get("commit_sha")
        if type(private_empty) is not bool or not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise CloudBlocked("CHECKOUT_TARGET_INVALID", "Checkout requires a new directory and frozen SHA")
        if private_empty:
            require_private_empty_checkout_target(destination)
        elif destination.exists() or destination.is_symlink():
            raise CloudBlocked("CHECKOUT_TARGET_INVALID", "Checkout requires a new directory and frozen SHA")
        url = repository_url(resolved.get("url"))
        await _git(["init", str(destination)])
        if await self._fetch(destination, url, sha) != sha:
            raise CloudBlocked("CHECKOUT_SHA_MISMATCH", "Fetched checkout differs from frozen input")
        await _git(["checkout", "--detach", sha], cwd=destination)
        if await _git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=destination) != sha:
            raise CloudBlocked("CHECKOUT_SHA_MISMATCH", "Checked out revision differs from frozen input")
