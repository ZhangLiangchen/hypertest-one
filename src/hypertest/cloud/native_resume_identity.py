"""Freeze non-secret native-session identity before the first SDK prompt.

The caller must anchor the returned digest in an original fenced Worker receipt
*before* submitting the prompt.  A local file alone is not an independent
attestation: native Workers and Agents run as the same OS user.  Recovery must
never create this file, and must compare it to that original server receipt.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import re
import stat
import subprocess
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import yaml

from .errors import CloudBlocked

PROFILE = "hypertest-native-session-identity/v1"
FILENAME = "native-session-identity.json"
_MAX_BYTES = 512 * 1024 * 1024
_MAX_RECORD = 16 * 1024
_HEX = re.compile(r"^[a-f0-9]{64}$")
_COMMIT = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}$")
_WORKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MODELS = frozenset({"deepseek-flash", "deepseek-v4-pro"})
_REASONING = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max"})
_BASE_BUNDLES = ("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-sdk-app")
_EXPERIMENTAL_BUNDLES = frozenset({
    "@deepseek-ai/dsh-experimental-agent-team-profile", "@deepseek-ai/dsh-experimental-tool-worktree",
    "@deepseek-ai/dsh-experimental-terminal-bundle", "@deepseek-ai/dsh-experimental-session-search",
    "@deepseek-ai/dsh-experimental-session-titles-bundle", "@deepseek-ai/dsh-experimental-ralph-bundle",
})
_PROFILE_FILES = frozenset({"package.json", "cordis.yml", "cordis.patch.yml", "pnpm-workspace.yaml"})
_SDK_SOURCE_FILES = frozenset({"__init__.py", "api.py", "client.py", "errors.py", "models.py", "office.py"})
_NONSECRET_ENV = frozenset({"PATH", "HOME", "SHELL", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
                            "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "DSH_PERMISSION_MODE", "DSH_SANDBOX",
                            "DSH_APPROVAL_MODE"})


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _uuid(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("invalid identity")
    return value


def _digest(value: str) -> str:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ValueError("invalid digest")
    return value


def _selection_digest(selection: dict) -> str:
    if (not isinstance(selection, dict) or set(selection) not in
            ({"provider", "model"}, {"provider", "model", "reasoning_effort"})
            or selection.get("provider") != "deepseek-official" or selection.get("model") not in _MODELS
            or ("reasoning_effort" in selection and selection["reasoning_effort"] not in _REASONING)):
        raise ValueError("invalid resolved selection")
    return _sha(_canonical(selection))


def _environment_digest(environment: dict) -> str:
    if not isinstance(environment, dict):
        raise ValueError("invalid native environment")
    selected = {}
    for key in _NONSECRET_ENV:
        if key in environment:
            value = environment[key]
            if not isinstance(value, str) or "\x00" in value or len(value) > 32768:
                raise ValueError("invalid native environment")
            selected[key] = value
    if "DEEPSEEK_BASE_URL" in environment:
        endpoint = environment["DEEPSEEK_BASE_URL"]
        if not isinstance(endpoint, str):
            raise ValueError("invalid provider endpoint")
        url = urlsplit(endpoint)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in {"", "/", "/v1", "/v1/"}):
            # Avoid capturing a possibly secret-bearing endpoint path/query.
            raise ValueError("unsupported provider endpoint")
        selected["DEEPSEEK_BASE_URL"] = endpoint
    # Tokens and credentials are deliberately neither read nor hashed.
    return _sha(_canonical(selected))


def _commit(value: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise ValueError("invalid source commit")
    return value


def _checked_head(path: Path, expected: str) -> str:
    path, _ = _directory(path)
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--verify", "HEAD^{commit}"],
        env={"PATH": "/usr/bin:/bin", "HOME": str(path), "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=10, check=True,
    )
    if result.stdout.decode("ascii").strip() != _commit(expected):
        raise ValueError("source commit does not match frozen input")
    return expected


def _directory(path: Path) -> tuple[Path, dict]:
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("unsafe directory")
    real = path.resolve(strict=True)
    if real != path:
        raise ValueError("noncanonical directory")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("directory unavailable")
    return real, {"path_sha256": _sha(os.fsencode(str(real))), "device": info.st_dev, "inode": info.st_ino}


def _stable_file(path: Path) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_BYTES:
            raise ValueError("unsafe file")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(fd, 128 * 1024):
            size += len(chunk)
            if size > _MAX_BYTES:
                raise ValueError("file too large")
            digest.update(chunk)
        after = os.fstat(fd)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or size != before.st_size):
            raise ValueError("file changed while reading")
        return size, digest.hexdigest()
    finally:
        os.close(fd)


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("duplicate or invalid profile key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate profile key")
        result[key] = value
    return result


def _read_small_profile_file(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 65536:
            raise ValueError("unsafe profile file")
        result = bytearray()
        while chunk := os.read(fd, min(8192, 65537 - len(result))):
            result.extend(chunk)
            if len(result) > 65536:
                raise ValueError("profile file too large")
        after = os.fstat(fd)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or len(result) != before.st_size):
            raise ValueError("profile file changed")
        return bytes(result)
    finally:
        os.close(fd)


def _profile_digest(dsh_home: Path, selection: dict) -> str:
    """Fingerprint only reviewed, structured non-secret SDK profile settings.

    Unknown files/packages/plugins mean this profile cannot be authenticated for
    restoration; they are not read and this is not a general Harness restriction.
    """
    root = dsh_home / "profiles" / "sdk"
    if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root:
        raise ValueError("SDK profile unavailable")
    entries = {entry.name for entry in root.iterdir()}
    if not {"package.json", "cordis.patch.yml"}.issubset(entries) or not entries <= _PROFILE_FILES:
        raise ValueError("unreviewed SDK profile contents")
    for name in entries:
        info = (root / name).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise ValueError("unsafe SDK profile file")

    package = json.loads(_read_small_profile_file(root / "package.json"), object_pairs_hook=_unique_json_pairs)
    if (not isinstance(package, dict) or set(package) != {"name", "private", "dependencies", "dsh"}
            or package["name"] != "dsh-profile-sdk" or package["private"] is not True
            or package["dependencies"] != {} or not isinstance(package["dsh"], dict)
            or set(package["dsh"]) != {"profile"} or not isinstance(package["dsh"]["profile"], dict)
            or set(package["dsh"]["profile"]) != {"bundles"}):
        raise ValueError("unreviewed SDK package")
    bundles = package["dsh"]["profile"]["bundles"]
    if (not isinstance(bundles, list) or not all(isinstance(v, str) for v in bundles)
            or tuple(bundles[:2]) != _BASE_BUNDLES or len(bundles) != len(set(bundles))
            or not set(bundles[2:]) <= _EXPERIMENTAL_BUNDLES):
        raise ValueError("unreviewed SDK bundles")

    patches = yaml.load(_read_small_profile_file(root / "cordis.patch.yml"), Loader=_UniqueLoader)
    if not isinstance(patches, list) or len(patches) > 1:
        raise ValueError("unreviewed SDK patch")
    if patches:
        patch = patches[0]
        if (not isinstance(patch, dict) or not {"id", "config"} <= set(patch)
                or set(patch) - {"id", "name", "config"} or patch["id"] != "agent-default-model"
                or patch.get("name", "@deepseek-ai/dsh-agent-default-model") != "@deepseek-ai/dsh-agent-default-model"
                or not isinstance(patch["config"], dict)
                or set(patch["config"]) - {"provider", "model", "reasoningEffort"}):
            raise ValueError("unreviewed SDK model patch")
        settings = patch["config"]
        for key, expected in (("provider", selection["provider"]), ("model", selection["model"]),
                              ("reasoningEffort", selection.get("reasoning_effort"))):
            if key in settings and settings[key] != expected:
                raise ValueError("SDK patch disagrees with resolved selection")
    cordis = yaml.load(_read_small_profile_file(root / "cordis.yml"), Loader=_UniqueLoader) if "cordis.yml" in entries else []
    if cordis != []:
        raise ValueError("unreviewed SDK root")
    workspace = (yaml.load(_read_small_profile_file(root / "pnpm-workspace.yaml"), Loader=_UniqueLoader)
                 if "pnpm-workspace.yaml" in entries else None)
    if workspace is not None and workspace != {"packages": ["."], "nodeLinker": "hoisted", "autoInstallPeers": False}:
        raise ValueError("unreviewed package manager configuration")
    return _sha(_canonical({"package": package, "patches": patches, "cordis": cordis, "workspace": workspace}))


def _sdk_package_root() -> Path:
    from deepseek_harness import HarnessClient

    spec = importlib.util.find_spec("deepseek_harness")
    locations = None if spec is None else spec.submodule_search_locations
    if locations is None or len(locations) != 1:
        raise ValueError("SDK package unavailable")
    root = Path(next(iter(locations)))
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("unsafe SDK package")
    client = Path(inspect.getfile(HarnessClient)).resolve(strict=True)
    if client != root / "client.py":
        raise ValueError("imported SDK client does not match package")
    return root


def _sdk_package_digest(root: Path) -> str:
    """Hash only the audited SDK source files, excluding generated bytecode."""
    entries = []
    names = {entry.name for entry in root.iterdir()}
    if not _SDK_SOURCE_FILES <= names or not names <= _SDK_SOURCE_FILES | {"__pycache__", "py.typed"}:
        # Do not read or hash unknown package files as they may be credentials.
        raise ValueError("unreviewed SDK package contents")
    if "__pycache__" in names and not stat.S_ISDIR((root / "__pycache__").lstat().st_mode):
        raise ValueError("unsafe SDK bytecode directory")
    total = 0
    for name in sorted(names - {"__pycache__"}):
        path = root / name
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("unsafe SDK source")
        size, file_digest = _stable_file(path)
        total += size
        if total > _MAX_BYTES:
            raise ValueError("SDK package too large")
        entries.append([name, size, file_digest])
    return _sha(json.dumps(entries, ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def _runtime_identity() -> dict:
    from deepseek_harness_runtime import resolve_bundled_launch_args

    launch = resolve_bundled_launch_args()
    if len(launch) != 1:
        raise ValueError("unsupported native SDK launcher")
    runtime = Path(launch[0])
    if not runtime.is_absolute() or runtime.is_symlink() or runtime.resolve(strict=True) != runtime:
        raise ValueError("unsafe SDK runtime")
    sdk_version = version("deepseek-harness-sdk")
    if not _VERSION.fullmatch(sdk_version):
        raise ValueError("invalid SDK version")
    adapter = Path(__file__).parent
    return {"sdk_version": sdk_version, "sdk_package_sha256": _sdk_package_digest(_sdk_package_root()),
            "runtime_sha256": _stable_file(runtime)[1],
            "driver_sha256": _stable_file(adapter / "native_sdk_driver.py")[1],
            "cordis_adapter_sha256": _stable_file(adapter / "native_cordis.py")[1],
            "identity_adapter_sha256": _stable_file(adapter / "native_resume_identity.py")[1]}


def _private_attempt_root(root: Path) -> Path:
    root, _ = _directory(root)
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("unsafe attempt state")
    return root


def _identity(*, project_id: str, task_id: str, attempt_id: str, session_id: str,
              input_digest: str, prompt_sha256: str, title_sha256: str, workspace: Path, dsh_home: Path,
              sut_commit: str, framework_commit: str, selection: dict, environment: dict,
              worker_id: str, original_generation: int) -> dict:
    project_id, task_id, attempt_id = _uuid(project_id), _uuid(task_id), _uuid(attempt_id)
    if session_id != "cloud-" + attempt_id:
        raise ValueError("session does not match original Attempt")
    if (not isinstance(worker_id, str) or not _WORKER.fullmatch(worker_id)
            or type(original_generation) is not int or not 1 <= original_generation <= 9223372036854775807):
        raise ValueError("invalid original Worker identity")
    workspace, workspace_id = _directory(workspace)
    home, home_id = _directory(dsh_home)
    from .native_framework_project import session_working_directory

    session_cwd = session_working_directory(workspace)
    framework_project = {} if session_cwd == workspace else {"session_directory": _directory(session_cwd)[1]}
    return {"profile": PROFILE, "project_id": project_id, "task_id": task_id,
            "attempt_id": attempt_id, "session_id": session_id,
            "worker_id": worker_id, "original_generation": original_generation,
            "input_digest": _digest(input_digest), "prompt_sha256": _digest(prompt_sha256),
            "title_sha256": _digest(title_sha256),
            "source": {"sut": _checked_head(workspace / "sut", sut_commit),
                       "framework": _checked_head(workspace / "framework", framework_commit)},
            "selection_sha256": _selection_digest(selection),
            "nonsecret_environment_sha256": _environment_digest(environment),
            "workspace": workspace_id, "dsh_home": home_id, **framework_project,
            "sdk_profile_sha256": _profile_digest(home, selection), "runtime": _runtime_identity()}


def record_initial_identity(attempt_root: Path, **original) -> str:
    """Create exactly once before prompt intent; caller must anchor digest remotely.

    Existing records are never treated as permission to repeat an initial send.
    """
    try:
        root = _private_attempt_root(Path(attempt_root))
        encoded = _canonical(_identity(**original))
        if len(encoded) > _MAX_RECORD:
            raise ValueError("identity too large")
        fd = os.open(root / FILENAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        dir_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return _sha(encoded)
    except (OSError, ValueError, TypeError, ImportError, subprocess.SubprocessError, yaml.YAMLError):
        raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "Original session identity could not be recorded") from None


def verify_original_identity(attempt_root: Path, *, expected_identity_digest: str, **original) -> dict:
    """Validate a previously anchored identity; never create or repair a record."""
    try:
        _digest(expected_identity_digest)
        root = _private_attempt_root(Path(attempt_root))
        fd = os.open(root / FILENAME, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError("unsafe identity record")
            encoded = stream.read(_MAX_RECORD + 1)
        if len(encoded) > _MAX_RECORD or _sha(encoded) != expected_identity_digest:
            raise ValueError("original receipt mismatch")
        recorded = json.loads(encoded)
        if not isinstance(recorded, dict) or _canonical(recorded) != encoded or recorded != _identity(**original):
            raise ValueError("original session identity mismatch")
        return recorded
    except (OSError, ValueError, TypeError, ImportError, subprocess.SubprocessError, yaml.YAMLError):
        raise CloudBlocked("NATIVE_SESSION_IDENTITY_UNAVAILABLE", "Original session identity is missing or changed") from None
