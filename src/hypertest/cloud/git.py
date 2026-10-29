"""Worker-only Git resolution. No model, API request or floating checkout work."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .errors import CloudBlocked

SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
REF = re.compile(r"refs/(?:heads|tags|merge-requests|pull)/[A-Za-z0-9_./-]+")


def require_private_empty_checkout_target(destination: Path) -> None:
    """Accept only an untouched private directory created by the trusted Worker.

    The caller must keep the parent inaccessible to other writers until Git
    preparation finishes; this check does not turn a shared path into one.
    """
    fd = None
    try:
        destination = destination.absolute()
        if destination.resolve(strict=True) != destination:
            raise ValueError
        fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
        path_info = destination.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700 or os.listdir(fd)
                or (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino)):
            raise ValueError
    except (OSError, ValueError):
        raise CloudBlocked("CHECKOUT_TARGET_INVALID", "Checkout requires an untouched private empty directory") from None
    finally:
        if fd is not None:
            os.close(fd)


def repository_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.strip("/")):
        raise CloudBlocked("GIT_URL_INVALID", "Cloud Git requires a credential-free HTTPS repository URL")
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise CloudBlocked("GIT_URL_INVALID", "Git repository URL contains invalid characters")
    return value


@contextmanager
def git_environment(url: str, token: bytes | None = None):
    """Private helper returns a token only for this exact HTTPS host/path.

    No token appears in the URL, argv, environment or returned diagnostics. Git
    redirects, user/system config, hooks, submodules and interactive asks are off.
    """
    repository_url(url)
    with tempfile.TemporaryDirectory(prefix="hypertest-git-") as directory:
        root = Path(directory)
        os.chmod(root, 0o700)
        env = {"PATH": os.defpath, "HOME": str(root), "LANG": "C.UTF-8",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false",
               "GIT_CONFIG_COUNT": "5", "GIT_CONFIG_KEY_0": "http.followRedirects",
               "GIT_CONFIG_VALUE_0": "false", "GIT_CONFIG_KEY_1": "credential.useHttpPath",
               "GIT_CONFIG_VALUE_1": "true", "GIT_CONFIG_KEY_2": "core.hooksPath",
               "GIT_CONFIG_VALUE_2": os.devnull, "GIT_CONFIG_KEY_3": "protocol.allow",
               "GIT_CONFIG_VALUE_3": "never", "GIT_CONFIG_KEY_4": "protocol.https.allow",
               "GIT_CONFIG_VALUE_4": "always"}
        if token is not None:
            if b"\n" in token or b"\r" in token or not token or len(token) > 65536:
                raise CloudBlocked("GIT_TOKEN_INVALID", "Git token is invalid")
            parsed = urlsplit(url)
            secret = root / "credential.json"
            descriptor = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump({"host": parsed.netloc, "path": parsed.path.lstrip("/"),
                           "token": token.decode()}, stream)
            helper = root / "helper.py"
            helper.write_text('''import json,sys
from pathlib import Path
if len(sys.argv) < 2 or sys.argv[-1] != "get": sys.exit(0)
request = dict(line.rstrip("\\n").split("=", 1) for line in sys.stdin if "=" in line)
secret = json.loads(Path(__file__).with_name("credential.json").read_text())
if request.get("protocol") == "https" and request.get("host") == secret["host"] and request.get("path") == secret["path"]:
 print("username=oauth2")
 print("password=" + secret["token"])
''')
            # Shell quoting is only for trusted local executable paths, never a token.
            import shlex
            env["GIT_CONFIG_COUNT"] = "6"
            env["GIT_CONFIG_KEY_5"] = "credential.helper"
            env["GIT_CONFIG_VALUE_5"] = f"!{shlex.quote(sys.executable)} {shlex.quote(str(helper))}"
        yield env


async def _git(args: list[str], *, env: dict[str, str], cwd: Path | None = None,
               timeout: float = 90) -> str:
    executable = shutil.which("git", path=os.defpath)
    if not executable:
        raise CloudBlocked("GIT_UNAVAILABLE", "Git is not installed on the Cloud worker")
    process = await asyncio.create_subprocess_exec(executable, *args, cwd=cwd, env=env,
                                                 stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.DEVNULL,
                                                 start_new_session=True)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        raise
    if process.returncode:
        raise CloudBlocked("GIT_OPERATION_FAILED", "Repository access or fixed commit retrieval failed")
    if len(stdout) > 2 * 1024 * 1024:
        raise CloudBlocked("GIT_OUTPUT_LIMIT", "Git preflight output exceeds its limit")
    return stdout.decode("utf-8", errors="strict").strip()


def _ref(value: str) -> str:
    value = value if value.startswith("refs/") else "refs/heads/" + value
    if (not REF.fullmatch(value) or ".." in value or "//" in value or "@{" in value
            or value.endswith(("/", ".", ".lock"))):
        raise CloudBlocked("GIT_REF_INVALID", "Git selector must be an exact legal ref")
    return value


class GitResolver:
    async def resolve(self, url: str, selector: dict, *, token: bytes | None = None) -> dict:
        url = repository_url(url)
        kind = selector.get("kind", "BRANCH").upper()
        value = selector.get("value", selector.get("ref", ""))
        with git_environment(url, token) as env:
            with tempfile.TemporaryDirectory(prefix="hypertest-resolve-") as directory:
                root = Path(directory)
                await _git(["init", "--bare", str(root)], env=env)
                if kind == "SHA":
                    if not SHA.fullmatch(value):
                        raise CloudBlocked("GIT_SHA_INVALID", "A SHA selector requires a full commit hash")
                    commit = await self._fetch(root, url, value, env)
                    if commit != value:
                        raise CloudBlocked("GIT_SHA_MISMATCH", "Fetched commit differs from the requested SHA")
                    return {"url": url, "selector": selector, "commit_sha": commit,
                            "source": "worker-git-fetch"}
                if kind in {"BRANCH", "REF", "TAG"}:
                    ref = _ref("refs/tags/" + value if kind == "TAG" and not value.startswith("refs/") else value)
                    sha = await self._fetch(root, url, ref, env)
                    return {"url": url, "selector": selector, "commit_sha": sha,
                            "resolved_ref": ref, "source": "worker-git-fetch"}
                if kind != "MR":
                    raise CloudBlocked("GIT_SELECTOR_UNSUPPORTED", "Unsupported Git selector")
                # Require explicit server-exposed MR refs; never infer a merge hash.
                number = selector.get("number")
                if number is None and str(value).isdigit():
                    number = int(value)
                if not isinstance(number, int) or number < 1:
                    raise CloudBlocked("MR_ID_REQUIRED", "MR selector requires a positive number")
                strategy = selector.get("checkout_strategy", "HEAD").upper()
                head_ref = _ref(selector.get("head_ref", f"refs/merge-requests/{number}/head"))
                base_ref = _ref(selector.get("mr_base_ref") or selector.get("base_ref", ""))
                head = await self._fetch(root, url, head_ref, env)
                base = await self._fetch(root, url, base_ref, env)
                if strategy == "HEAD":
                    checkout = head
                elif strategy == "MERGE":
                    merge_ref = _ref(selector.get("merge_ref", f"refs/merge-requests/{number}/merge"))
                    checkout = await self._fetch(root, url, merge_ref, env)
                    parents = (await _git(["rev-list", "--parents", "-n", "1", checkout], env=env, cwd=root)).split()[1:]
                    if len(parents) != 2 or head not in parents or base not in parents:
                        raise CloudBlocked("MR_MERGE_PROVENANCE", "MR merge commit parents do not match the observed base/head")
                    # Re-observe refs after fetch to reject racing source MR changes.
                    if head != await self._fetch(root, url, head_ref, env) or base != await self._fetch(root, url, base_ref, env):
                        raise CloudBlocked("MR_MOVED_DURING_RESOLUTION", "MR changed during input resolution")
                else:
                    raise CloudBlocked("MR_STRATEGY_INVALID", "MR checkout strategy must be HEAD or MERGE")
                return {"url": url, "selector": selector, "commit_sha": checkout,
                        "mr_number": number, "base_sha": base, "head_sha": head,
                        "actual_checkout_sha": checkout,
                        "checkout_strategy": strategy, "source": "worker-git-fetch"}

    async def _fetch(self, root: Path, url: str, ref: str, env: dict[str, str]) -> str:
        await _git(["fetch", "--no-tags", "--no-recurse-submodules", url, ref], env=env, cwd=root)
        commit = await _git(["rev-parse", "--verify", "FETCH_HEAD^{commit}"], env=env, cwd=root)
        if not SHA.fullmatch(commit):
            raise CloudBlocked("GIT_SHA_INVALID", "Git did not resolve a full commit hash")
        return commit

    async def checkout(self, resolved: dict, destination: Path, *, token: bytes | None = None,
                       private_empty: bool = False) -> None:
        sha = resolved["commit_sha"]
        if type(private_empty) is not bool or not SHA.fullmatch(sha):
            raise CloudBlocked("CHECKOUT_TARGET_INVALID", "Checkout requires a new directory and frozen SHA")
        if private_empty:
            require_private_empty_checkout_target(destination)
        elif destination.exists() or destination.is_symlink():
            raise CloudBlocked("CHECKOUT_TARGET_INVALID", "Checkout requires a new directory and frozen SHA")
        url = repository_url(resolved["url"])
        with git_environment(url, token) as env:
            await _git(["init", str(destination)], env=env)
            actual = await self._fetch(destination, url, sha, env)
            if actual != sha:
                raise CloudBlocked("CHECKOUT_SHA_MISMATCH", "Fetched checkout differs from frozen input")
            await _git(["checkout", "--detach", sha], env=env, cwd=destination)
