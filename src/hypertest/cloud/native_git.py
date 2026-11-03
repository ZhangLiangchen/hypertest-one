"""Host Git access with the operator's existing credential helpers and SSH agent.

Only the trusted Worker calls this adapter. Credentials are never accepted in a
repository URL or as a platform token. Raw Git errors are never logged; bounded
stderr is used only to select fixed diagnostic codes and read-only fetch retries.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from .errors import CloudBlocked
from .git import SHA, _ref, require_private_empty_checkout_target

_SCP = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*:[A-Za-z0-9_./~-]+\Z")
_FETCH_TIMEOUT = 90.0
_FETCH_ATTEMPTS = 3
_TRANSIENT = {"GIT_DNS_FAILED", "GIT_CONNECT_FAILED", "GIT_CONNECTION_RESET", "GIT_HTTP2_FAILED",
              "GIT_SERVER_UNAVAILABLE", "GIT_TIMEOUT"}


class GitOperationFailure(CloudBlocked):
    """Finite diagnostics only: no URL, ref, command output or environment."""

    def __init__(self, code: str, operation: str, exit_code: int | None = None):
        self.operation = operation if operation in {"init", "fetch", "rev-parse", "checkout", "rev-list"} else "git"
        self.exit_code = exit_code
        super().__init__(code, f"Host Git {self.operation} failed ({code})")


def _failure_code(stderr: bytes) -> str:
    value = stderr.lower()
    # Permanent authorization, identity and source failures take precedence.
    for code, markers in (
        ("GIT_AUTH_FAILED", (b"authentication failed", b"could not read username", b"permission denied (publickey",
                              b"returned error: 401", b"returned error: 403")),
        ("GIT_HOST_KEY_FAILED", (b"host key verification failed", b"remote host identification has changed")),
        ("GIT_TLS_VERIFICATION_FAILED", (b"ssl certificate problem", b"certificate verification failed",
                                          b"server certificate verification failed", b"certificate verify failed",
                                          b"peer certificate cannot be authenticated",
                                          b"no alternative certificate subject name matches")),
        ("GIT_REVISION_NOT_FOUND", (b"couldn't find remote ref", b"not our ref", b"unadvertised object")),
        ("GIT_REPOSITORY_NOT_FOUND", (b"repository not found", b"does not appear to be a git repository")),
        ("GIT_DNS_FAILED", (b"could not resolve host", b"could not resolve proxy", b"temporary failure in name resolution",
                             b"could not resolve hostname")),
        ("GIT_CONNECT_FAILED", (b"failed to connect", b"connection refused", b"network is unreachable", b"no route to host")),
        ("GIT_HTTP2_FAILED", (b"http/2 stream", b"http2 framing", b"curl 92")),
        ("GIT_CONNECTION_RESET", (b"connection reset", b"recv failure", b"send failure",
                                  b"remote end hung up unexpectedly", b"unexpected disconnect",
                                  b"tls connection was non-properly terminated", b"early eof",
                                  b"ssl_error_syscall")),
        ("GIT_TIMEOUT", (b"connection timed out", b"operation timed out", b"curl 28")),
    ):
        if any(marker in value for marker in markers):
            return code
    # libcurl transport failures can omit the usual Git disconnect wording.
    # Keep permanent checks above; index-pack errors alone are not transport proof.
    if re.search(rb"\bcurl\s+35\b", value):
        return "GIT_CONNECT_FAILED"
    if re.search(rb"\bcurl\s+56\b", value):
        return "GIT_CONNECTION_RESET"
    if re.search(rb"(?:returned error:|http(?:/[0-9.]+)?)[ \t]+(?:500|502|503|504)\b", value):
        return "GIT_SERVER_UNAVAILABLE"
    return "GIT_OPERATION_FAILED"


async def _bounded_output(stream, limit: int, *, tail: bool = False) -> tuple[bytes, bool]:
    retained = bytearray()
    exceeded = False
    while chunk := await stream.read(65536):
        if len(retained) + len(chunk) > limit:
            exceeded = True
        if tail:
            retained.extend(chunk)
            if len(retained) > limit:
                del retained[:-limit]
        elif len(retained) < limit:
            retained.extend(chunk[:limit - len(retained)])
    return bytes(retained), exceeded


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
    operation = args[0] if args else "git"
    try:
        process = await asyncio.create_subprocess_exec(
            executable, "-c", "core.hooksPath=/dev/null", *args, cwd=cwd, env=env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True,
        )
    except OSError:
        raise GitOperationFailure("GIT_START_FAILED", operation) from None
    output = asyncio.gather(_bounded_output(process.stdout, 2 * 1024 * 1024),
        _bounded_output(process.stderr, 65536, tail=True), process.wait())
    try:
        # Timeout must not cancel the bounded readers: a paused pipe can keep
        # process.wait() pending even after the process group has been killed.
        stdout_result, stderr_result, _ = await asyncio.wait_for(asyncio.shield(output), timeout)
    except (TimeoutError, asyncio.CancelledError) as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await output
        if isinstance(error, TimeoutError):
            raise GitOperationFailure("GIT_TIMEOUT", operation) from None
        raise
    stdout, stdout_exceeded = stdout_result
    stderr, _ = stderr_result
    if process.returncode:
        code = "GIT_PROCESS_INTERRUPTED" if process.returncode < 0 else _failure_code(stderr)
        raise GitOperationFailure(code, operation, process.returncode)
    if stdout_exceeded:
        raise GitOperationFailure("GIT_OUTPUT_LIMIT", operation, process.returncode)
    try:
        return stdout.decode("utf-8", errors="strict").strip()
    except UnicodeError:
        raise GitOperationFailure("GIT_OUTPUT_INVALID", operation, process.returncode) from None


class NativeGitResolver:
    """Resolve and fetch exact revisions using the local user's Git identity."""

    @staticmethod
    def _no_token(token: bytes | None) -> None:
        if token is not None:
            raise CloudBlocked("GIT_PLATFORM_TOKEN_UNSUPPORTED", "Host Git uses the operator's configured identity")

    async def _fetch(self, root: Path, url: str, ref: str, *, identity_only: bool = False) -> str:
        # Fetch only reads the remote and writes this private Git object store.
        # Never retry checkout, source validation, SDK work or external actions.
        # Plain input resolution needs only the selected commit's identity.
        # Keep complete history for MR parent verification and SDK workspaces.
        options = ["--depth=1", "--filter=tree:0"] if identity_only else []
        deadline = time.monotonic() + _FETCH_TIMEOUT
        for attempt in range(_FETCH_ATTEMPTS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitOperationFailure("GIT_TIMEOUT", "fetch")
            try:
                await _git(["fetch", "--no-tags", "--no-recurse-submodules", *options, url, ref], cwd=root, timeout=remaining)
                break
            except GitOperationFailure as error:
                delay = float(attempt + 1)
                if (error.code not in _TRANSIENT or attempt + 1 >= _FETCH_ATTEMPTS
                        or deadline - time.monotonic() <= delay):
                    raise
                await asyncio.sleep(delay)
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
                commit = await self._fetch(root, url, value, identity_only=True)
                if commit != value:
                    raise CloudBlocked("GIT_SHA_MISMATCH", "Fetched commit differs from the requested SHA")
                return {"url": url, "selector": selector, "commit_sha": commit, "source": "worker-git-fetch"}
            if kind in {"BRANCH", "REF", "TAG"}:
                ref = _ref("refs/tags/" + value if kind == "TAG" and not value.startswith("refs/") else value)
                sha = await self._fetch(root, url, ref, identity_only=True)
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
