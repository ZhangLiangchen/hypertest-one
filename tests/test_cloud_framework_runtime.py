"""Frozen framework inspection does not install dependencies or run test code."""
import hashlib
import os
import platform
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from hypertest.cloud import framework_runtime as runtime
from hypertest.cloud.errors import CloudBlocked


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def spec():
    return {"profile": runtime.PROFILE,
        "lockfiles": [{"path": "requirements.lock", "sha256": sha256(b"pytest==8.4.2\n")}],
        "tools": [{"name": "python", "version": platform.python_version(),
            "sha256": runtime._hash_executable(Path(sys.executable).resolve())}],
        "entrypoints": [{"key": "python -m pytest", "argv": ["python", "-m", "pytest", "-q"]}]}


@pytest.fixture
def trusted_python(monkeypatch, tmp_path):
    # setup-python's hosted tool cache is not a trusted Worker installation.
    # Inspect the fixed system interpreter through the unchanged trust checks.
    executable = Path("/usr/bin/python3").resolve(strict=True)
    monkeypatch.setattr(runtime, "sys", SimpleNamespace(executable=str(executable)))
    assert runtime._runtime_executable("python", tmp_path) == executable
    observed = subprocess.run([str(executable), "--version"], check=True, timeout=5,
        capture_output=True, text=True, cwd="/",
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
    assert observed.stdout.startswith("Python ")
    return {"name": "python", "version": observed.stdout.removeprefix("Python ").strip(),
        "sha256": runtime._hash_executable(executable)}


@pytest.mark.parametrize("path", ["../requirements.lock", "/tmp/requirements.lock", "./requirements.lock",
    "nested/../requirements.lock", "nested//requirements.lock", "nested\\requirements.lock",
    ".git/config", ".ssh/config", "configs/dev/env_password", "secrets/requirements.lock",
    "nested/.env", "credentials.json", "identity.pem", "auth/token.lock", "https://repo.invalid/lock"])
def test_runtime_spec_rejects_escape_and_secret_paths_without_io(path, monkeypatch):
    selected = spec()
    selected["lockfiles"][0]["path"] = path
    def forbidden(*args, **kwargs):
        pytest.fail("pure validation must not inspect filesystem or start any process")
    monkeypatch.setattr(runtime.os, "open", forbidden)
    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", forbidden)
    with pytest.raises(CloudBlocked, match="strict frozen"):
        runtime.validate_runtime_spec(selected)


@pytest.mark.parametrize("mutation", ["unknown-field", "duplicate-lock", "duplicate-tool", "duplicate-entrypoint", "too-many-locks", "unsupported-tool", "control-argv", "empty-argv"])
def test_runtime_spec_rejects_ambiguous_or_unbounded_selection(mutation):
    selected = spec()
    if mutation == "unknown-field":
        selected["install"] = "pip install -r requirements.lock"
    elif mutation.startswith("duplicate-"):
        field = {"duplicate-lock": "lockfiles", "duplicate-tool": "tools", "duplicate-entrypoint": "entrypoints"}[mutation]
        selected[field].append(deepcopy(selected[field][0]))
    elif mutation == "too-many-locks":
        selected["lockfiles"] = [{"path": f"lock-{index}.lock", "sha256": "a" * 64} for index in range(17)]
    elif mutation == "unsupported-tool":
        selected["tools"][0]["name"] = "bash"
    elif mutation == "control-argv":
        selected["entrypoints"][0]["argv"] = ["python", "argument\nsecond-line"]
    else:
        selected["entrypoints"][0]["argv"] = []
    with pytest.raises(CloudBlocked):
        runtime.validate_runtime_spec(selected)


async def test_absent_spec_preserves_legacy_no_inspection(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("legacy tasks without runtime spec must retain original behavior")
    monkeypatch.setattr(runtime, "_runtime_executable", forbidden)
    monkeypatch.setattr(runtime.os, "open", forbidden)
    assert runtime.validate_runtime_spec(None) is None
    assert await runtime.inspect_framework_runtime(tmp_path / "absent", None, ["old entrypoint"]) is None


async def test_real_fixed_python_and_locks_observed_without_running_entrypoint(tmp_path, trusted_python):
    selected = spec()
    selected["tools"] = [trusted_python]
    (tmp_path / "requirements.lock").write_bytes(b"pytest==8.4.2\n")
    marker = tmp_path / "must-not-exist"
    selected["entrypoints"][0]["argv"] = ["python", "-c", f"open({str(marker)!r}, 'w').write('executed')"]
    result = await runtime.inspect_framework_runtime(tmp_path, selected, ["python -m pytest"])
    assert result["lockfile_total_bytes"] == 14
    assert result["tools"][0]["sha256"] == selected["tools"][0]["sha256"]
    assert result["entrypoints"] == selected["entrypoints"]
    assert result["entrypoint_execution"] == result["dependency_installation"] == result["network_access"] == "NOT_RUN"
    assert not marker.exists()


@pytest.mark.parametrize("kind", ["file-link", "directory-link", "hardlink", "missing", "digest", "aggregate-size"])
async def test_unsafe_or_changed_lock_fails_before_any_tool_version(tmp_path, monkeypatch, kind):
    selected = spec()
    lock = tmp_path / "requirements.lock"
    lock.write_bytes(b"pytest==8.4.2\n")
    async def forbidden(*args, **kwargs):
        pytest.fail("a rejected frozen lock must not start even a version command")
    monkeypatch.setattr(runtime, "_version", forbidden)
    if kind == "file-link":
        target = tmp_path / "actual.lock"
        lock.rename(target)
        lock.symlink_to(target)
    elif kind == "directory-link":
        target = tmp_path / "actual"
        target.mkdir()
        lock.rename(target / "requirements.lock")
        (tmp_path / "alias").symlink_to(target, target_is_directory=True)
        selected["lockfiles"][0]["path"] = "alias/requirements.lock"
    elif kind == "hardlink":
        os.link(lock, tmp_path / "alias.lock")
    elif kind == "missing":
        lock.unlink()
    elif kind == "digest":
        lock.write_bytes(b"changed dependency\n")
    else:
        content = b"x" * (runtime.MAX_LOCK_BYTES // 2 + 1)
        lock.write_bytes(content)
        (tmp_path / "second.lock").write_bytes(content)
        selected["lockfiles"] = [{"path": path, "sha256": sha256(content)} for path in ("requirements.lock", "second.lock")]
    with pytest.raises(CloudBlocked):
        await runtime.inspect_framework_runtime(tmp_path, selected, ["python -m pytest"])


async def test_entrypoint_set_must_match_original_inputs_before_filesystem(tmp_path, monkeypatch):
    selected = spec()
    def forbidden(*args, **kwargs):
        pytest.fail("entrypoint mismatch must be rejected before opening any repository file")
    monkeypatch.setattr(runtime.os, "open", forbidden)
    with pytest.raises(CloudBlocked, match="exactly match"):
        await runtime.inspect_framework_runtime(tmp_path, selected, ["new unauthorized entrypoint"])


async def test_executable_digest_precedes_version_and_repository_path_is_not_used(tmp_path, monkeypatch, trusted_python):
    selected = spec()
    selected["tools"] = [trusted_python]
    (tmp_path / "requirements.lock").write_bytes(b"pytest==8.4.2\n")
    selected["tools"][0]["sha256"] = "0" * 64
    async def forbidden(*args, **kwargs):
        pytest.fail("unmatched executable digest must prohibit version execution")
    monkeypatch.setattr(runtime, "_version", forbidden)
    with pytest.raises(CloudBlocked, match="toolchain digest"):
        await runtime.inspect_framework_runtime(tmp_path, selected, ["python -m pytest"])
    executable = tmp_path / "node"
    executable.write_text("#!/bin/sh\nexit 99\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    try:
        actual = runtime._runtime_executable("node", tmp_path)
    except CloudBlocked:
        pass  # Images without the fixed Node runtime refuse this tool.
    else:
        assert actual != executable and not actual.is_relative_to(tmp_path)


async def test_matching_binary_with_wrong_version_is_refused(tmp_path, trusted_python):
    selected = spec()
    selected["tools"] = [trusted_python]
    (tmp_path / "requirements.lock").write_bytes(b"pytest==8.4.2\n")
    selected["tools"][0]["version"] = "0.0.0"
    with pytest.raises(CloudBlocked, match="version differs"):
        await runtime.inspect_framework_runtime(tmp_path, selected, ["python -m pytest"])


async def test_version_subprocess_uses_fixed_argv_clean_environment_and_cwd(monkeypatch):
    seen = []
    class Output:
        async def read(self, limit):
            assert limit == 4097
            return b"Python 3.13.5\n"
    class Process:
        stdout, returncode = Output(), 0
        async def wait(self):
            return 0
    async def spawn(*args, **kwargs):
        seen.append((args, kwargs))
        return Process()
    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    assert await runtime._version(Path("/fixed/python"), "python", "3.13.5") == "3.13.5"
    assert seen[0][0] == ("/fixed/python", "--version")
    assert seen[0][1]["cwd"] == "/"
    assert seen[0][1]["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
