"""Offline inspection of an explicitly frozen framework/toolchain baseline.

This profile installs nothing, accesses no network and executes no repository
entrypoint. It does not claim to restrict every shell command an SDK may run.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import CloudBlocked

PROFILE = "FRAMEWORK_LOCKED_V1"
MAX_LOCK_BYTES = 1024 * 1024
_HASH = r"^[a-f0-9]{64}$"
_SECRET = re.compile(r"(?:^|[._-])(?:secrets?|password|credentials?|tokens?|api[_-]?key|private[_-]?key|auth)(?:[._-]|$)", re.I)


def _relative_path(value):
    path = PurePosixPath(value)
    if (not value or len(value) > 512 or path.is_absolute() or "\\" in value or ":" in value
            or value != str(path) or len(path.parts) > 32 or any(ord(char) < 32 for char in value)
            or any(part in {".", "..", ".git"} for part in path.parts)):
        raise ValueError("Framework lock paths must be canonical contained relative paths")
    if any(part.lower().startswith(".env") or part.lower() in {
            ".ssh", ".aws", ".azure", ".kube", ".config", "id_rsa", "id_ed25519",
            "env_password"} or _SECRET.search(part) or PurePosixPath(part).suffix.lower() in {
                ".pem", ".key", ".p12", ".pfx"} for part in path.parts):
        raise ValueError("Secret and authentication paths are not framework lock inputs")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Lockfile(StrictModel):
    path: str
    sha256: str = Field(pattern=_HASH)
    _path = field_validator("path")(_relative_path)


class Tool(StrictModel):
    name: Literal["python", "node"]
    version: str = Field(min_length=1, max_length=128, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+-]*$")
    sha256: str = Field(pattern=_HASH)


class Entrypoint(StrictModel):
    key: str = Field(min_length=1, max_length=512)
    argv: list[str] = Field(min_length=1, max_length=64)

    @field_validator("key")
    @classmethod
    def key_value(cls, value):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Entrypoint requires a nonempty single-line identifier")
        return value

    @field_validator("argv")
    @classmethod
    def argv_values(cls, values):
        if any(not value or len(value) > 4096 or any(ord(char) < 32 for char in value) for value in values):
            raise ValueError("Entrypoint argv must contain bounded literal arguments")
        return values


class RuntimeSpec(StrictModel):
    profile: Literal["FRAMEWORK_LOCKED_V1"]
    lockfiles: list[Lockfile] = Field(min_length=1, max_length=16)
    tools: list[Tool] = Field(min_length=1, max_length=2)
    entrypoints: list[Entrypoint] = Field(min_length=1, max_length=32)


def validate_runtime_spec(value: dict | None) -> dict | None:
    """Pure schema validation; no filesystem, process, credential or network IO."""
    if value is None:
        return None
    try:
        spec = RuntimeSpec.model_validate(value)
        for items, field in ((spec.lockfiles, "path"), (spec.tools, "name"), (spec.entrypoints, "key")):
            if len({getattr(item, field) for item in items}) != len(items):
                raise ValueError("Duplicate framework runtime selection")
        return spec.model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        raise CloudBlocked("FRAMEWORK_RUNTIME_SPEC_INVALID", "Framework runtime must use the strict frozen offline profile") from None


def _read_lock(root: Path, relative: str, remaining: int) -> bytes:
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    leaf = None
    try:
        parts = PurePosixPath(relative).parts
        for component in parts[:-1]:
            next_parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = next_parent
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        before = os.fstat(leaf)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= remaining:
            raise CloudBlocked("FRAMEWORK_LOCK_SIZE", "Framework lockfiles must be regular files within the aggregate byte limit")
        with os.fdopen(leaf, "rb") as stream:
            leaf = None
            content = stream.read(remaining + 1)
            after = os.fstat(stream.fileno())
        if (len(content) != before.st_size or len(content) > remaining
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                   (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise CloudBlocked("FRAMEWORK_LOCK_CHANGED", "Framework lockfile changed during its bounded inspection")
        return content
    except OSError:
        raise CloudBlocked("FRAMEWORK_LOCK_UNAVAILABLE", "Frozen framework lockfile is absent or unsafe") from None
    finally:
        if leaf is not None:
            os.close(leaf)
        os.close(parent)


def _runtime_executable(name: str, framework: Path) -> Path:
    if name == "python":
        candidates = [Path(sys.executable)]
    else:
        # Never consult a repository-modified PATH, shell shim or node_modules.
        candidates = [Path("/usr/local/bin/node"), Path("/usr/bin/node"), Path("/bin/node")]
    for candidate in candidates:
        try:
            executable = candidate.resolve(strict=True)
            info = executable.stat()
            if (not executable.is_absolute() or executable.is_relative_to(framework)
                    or not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                    or not os.access(executable, os.X_OK)):
                continue
            # A root-owned binary under a writable parent is replaceable too.
            if any(parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022 for parent in executable.parents):
                continue
            return executable
        except (OSError, RuntimeError):
            continue
    raise CloudBlocked("FRAMEWORK_TOOL_UNAVAILABLE", "Frozen tool requires a trusted fixed host executable")


def _hash_executable(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _version(executable: Path, name: str, expected: str) -> str:
    process = await asyncio.create_subprocess_exec(str(executable), "--version", stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}, cwd="/")
    try:
        async with asyncio.timeout(5):
            output = await process.stdout.read(4097)
            if len(output) > 4096:
                raise CloudBlocked("FRAMEWORK_TOOL_VERSION_INVALID", "Frozen tool version output exceeds its fixed bound")
            await process.wait()
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    prefix = "Python " if name == "python" else "v"
    if process.returncode != 0 or output.decode("ascii", errors="replace").strip() != prefix + expected:
        raise CloudBlocked("FRAMEWORK_TOOL_VERSION_MISMATCH", "Fixed executable version differs from the frozen toolchain")
    return expected


async def inspect_framework_runtime(framework: Path, spec: dict | None, framework_entrypoints: list[str]) -> dict | None:
    """Check frozen hashes/version only; argv remains a declaration, never run."""
    spec = validate_runtime_spec(spec)
    if spec is None:
        return None
    if (len(framework_entrypoints) != len(set(framework_entrypoints))
            or {item["key"] for item in spec["entrypoints"]} != set(framework_entrypoints)):
        raise CloudBlocked("FRAMEWORK_ENTRYPOINT_MISMATCH", "Frozen entrypoints must exactly match the task's original entrypoint set")
    framework = Path(framework).absolute()
    if not framework.is_dir() or framework.resolve() != framework:
        raise CloudBlocked("FRAMEWORK_ROOT_UNSAFE", "Frozen framework root must be a canonical directory")
    locks, total, tools = [], 0, []
    for selected in spec["lockfiles"]:
        content = _read_lock(framework, selected["path"], MAX_LOCK_BYTES - total)
        sha256 = hashlib.sha256(content).hexdigest()
        if sha256 != selected["sha256"]:
            raise CloudBlocked("FRAMEWORK_LOCK_DIGEST_MISMATCH", "Framework lockfile differs from its frozen digest")
        total += len(content)
        locks.append({**selected, "byte_count": len(content)})
    for selected in spec["tools"]:
        executable = _runtime_executable(selected["name"], framework)
        try:
            # Hash matching precedes even the fixed version command.
            sha256 = await asyncio.to_thread(_hash_executable, executable)
            if sha256 != selected["sha256"]:
                raise CloudBlocked("FRAMEWORK_TOOL_DIGEST_MISMATCH", "Fixed executable differs from its frozen toolchain digest")
            version = await _version(executable, selected["name"], selected["version"])
        except (OSError, TimeoutError):
            raise CloudBlocked("FRAMEWORK_TOOL_INSPECTION_FAILED", "Frozen tool inspection failed within its fixed bound") from None
        tools.append({"name": selected["name"], "version": version, "sha256": sha256})
    return {"profile": PROFILE, "source": "HOST_OFFLINE_FROZEN_BASELINE", "lockfiles": locks,
        "lockfile_total_bytes": total, "tools": tools, "entrypoints": spec["entrypoints"],
        "entrypoint_execution": "NOT_RUN", "dependency_installation": "NOT_RUN", "network_access": "NOT_RUN"}
