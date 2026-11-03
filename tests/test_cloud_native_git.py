"""Synthetic host Git failures; no remote repository, credentials or SDK calls."""

import asyncio
import sys
import time
from types import SimpleNamespace

import pytest

from hypertest.cloud import native_git
from hypertest.cloud.native_git import GitOperationFailure, NativeGitResolver

SHA = "a" * 40
URL = "https://example.invalid/project.git"


def stream(value=b""):
    result = asyncio.StreamReader()
    result.feed_data(value)
    result.feed_eof()
    return result


@pytest.mark.parametrize("stderr,expected", [
    (b"fatal: Could not resolve host: example.invalid", "GIT_DNS_FAILED"),
    (b"fatal: unable to access: Recv failure: Connection reset by peer", "GIT_CONNECTION_RESET"),
    (b"error: RPC failed; curl 92 HTTP/2 stream 3 was not closed cleanly", "GIT_HTTP2_FAILED"),
    (b"fatal: The requested URL returned error: 503", "GIT_SERVER_UNAVAILABLE"),
    (b"fatal: Authentication failed", "GIT_AUTH_FAILED"),
    (b"fatal: SSL certificate problem: certificate has expired", "GIT_TLS_VERIFICATION_FAILED"),
    (b"fatal: couldn't find remote ref missing", "GIT_REVISION_NOT_FOUND"),
    (b"fatal: unknown synthetic failure", "GIT_OPERATION_FAILED"),
])
async def test_git_failure_exposes_only_fixed_category(monkeypatch, stderr, expected):
    canary = b"https://synthetic-user:synthetic-secret@example.invalid/private?token=synthetic-token"
    process = SimpleNamespace(returncode=128, stdout=stream(), stderr=stream(canary + b"\n" + stderr))

    async def wait():
        return process.returncode

    async def spawn(*args, **kwargs):
        assert kwargs["stderr"] == asyncio.subprocess.PIPE
        process.wait = wait
        return process

    monkeypatch.setattr(native_git.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(native_git.shutil, "which", lambda *args, **kwargs: "/synthetic/git")
    with pytest.raises(GitOperationFailure) as failure:
        await native_git._git(["fetch", URL, SHA])
    assert failure.value.code == expected
    assert failure.value.operation == "fetch" and failure.value.exit_code == 128
    assert "synthetic-secret" not in str(failure.value) and "example.invalid" not in str(failure.value)
    assert set(vars(failure.value)) == {"code", "operation", "exit_code"}


async def test_transient_fetch_retries_same_read_and_keeps_frozen_sha(monkeypatch, tmp_path):
    calls, delays = [], []

    async def git(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "fetch" and len(calls) < 3:
            raise GitOperationFailure("GIT_CONNECTION_RESET", "fetch", 128)
        return SHA if args[0] == "rev-parse" else ""

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(native_git, "_git", git)
    monkeypatch.setattr(native_git.asyncio, "sleep", sleep)
    assert await NativeGitResolver()._fetch(tmp_path, URL, SHA) == SHA
    fetches = [(args, kwargs) for args, kwargs in calls if args[0] == "fetch"]
    assert len(fetches) == 3
    assert all(args == ["fetch", "--no-tags", "--no-recurse-submodules", URL, SHA] for args, _ in fetches)
    assert all(kwargs["cwd"] == tmp_path and 0 < kwargs["timeout"] <= 90 for _, kwargs in fetches)
    assert delays == [1.0, 2.0]
    assert [args[0] for args, _ in calls] == ["fetch", "fetch", "fetch", "rev-parse"]


async def test_fetch_stops_after_bounded_transient_retries(monkeypatch, tmp_path):
    calls = []

    async def git(args, **kwargs):
        calls.append(args)
        raise GitOperationFailure("GIT_SERVER_UNAVAILABLE", "fetch", 128)

    async def sleep(_delay):
        pass

    monkeypatch.setattr(native_git, "_git", git)
    monkeypatch.setattr(native_git.asyncio, "sleep", sleep)
    with pytest.raises(GitOperationFailure) as failure:
        await NativeGitResolver()._fetch(tmp_path, URL, SHA)
    assert failure.value.code == "GIT_SERVER_UNAVAILABLE" and len(calls) == 3
    assert all(args[0] == "fetch" for args in calls)


@pytest.mark.parametrize("code", ["GIT_AUTH_FAILED", "GIT_TLS_VERIFICATION_FAILED", "GIT_REVISION_NOT_FOUND", "GIT_OPERATION_FAILED"])
async def test_fetch_does_not_retry_permanent_or_unknown_failure(monkeypatch, tmp_path, code):
    calls = []

    async def git(args, **kwargs):
        calls.append(args)
        raise GitOperationFailure(code, "fetch", 128)

    monkeypatch.setattr(native_git, "_git", git)
    with pytest.raises(GitOperationFailure) as failure:
        await NativeGitResolver()._fetch(tmp_path, URL, SHA)
    assert failure.value.code == code and len(calls) == 1


async def test_fetch_cancellation_is_not_retried(monkeypatch, tmp_path):
    calls = []

    async def git(args, **kwargs):
        calls.append(args)
        raise asyncio.CancelledError()

    monkeypatch.setattr(native_git, "_git", git)
    with pytest.raises(asyncio.CancelledError):
        await NativeGitResolver()._fetch(tmp_path, URL, SHA)
    assert len(calls) == 1


async def test_fetch_does_not_retry_past_original_time_budget(monkeypatch, tmp_path):
    clock = iter((0, 0, 89.5))
    calls = []

    async def git(args, **kwargs):
        calls.append(args)
        raise GitOperationFailure("GIT_CONNECTION_RESET", "fetch", 128)

    monkeypatch.setattr(native_git, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(native_git, "_git", git)
    with pytest.raises(GitOperationFailure) as failure:
        await NativeGitResolver()._fetch(tmp_path, URL, SHA)
    assert failure.value.code == "GIT_CONNECTION_RESET" and len(calls) == 1


async def test_git_timeout_stops_process_group_and_returns_safe_code(monkeypatch):
    stopped = asyncio.Event()
    process = SimpleNamespace(pid=12345, returncode=None, stdout=stream(), stderr=stream())
    signals = []

    async def wait():
        await stopped.wait()
        return process.returncode

    async def spawn(*args, **kwargs):
        process.wait = wait
        return process

    def killpg(pid, sig):
        signals.append((pid, sig))
        process.returncode = -9
        stopped.set()

    monkeypatch.setattr(native_git.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(native_git.shutil, "which", lambda *args, **kwargs: "/synthetic/git")
    monkeypatch.setattr(native_git.os, "killpg", killpg)
    with pytest.raises(GitOperationFailure) as failure:
        await native_git._git(["fetch", URL, SHA], timeout=0.01)
    assert failure.value.code == "GIT_TIMEOUT" and signals == [(12345, native_git.signal.SIGKILL)]


async def test_git_output_capture_is_bounded_and_retains_error_tail():
    data, exceeded = await native_git._bounded_output(stream(b"progress\n" * 20000 + b"fatal: Connection reset\n"), 65536, tail=True)
    assert exceeded and len(data) == 65536
    assert native_git._failure_code(data) == "GIT_CONNECTION_RESET"
    data, exceeded = await native_git._bounded_output(stream(b"x" * 100), 64)
    assert exceeded and data == b"x" * 64


async def test_noisy_real_process_timeout_drains_pipes_and_exits(monkeypatch, capsys):
    spawn = asyncio.create_subprocess_exec
    processes = []

    async def noisy_process(*args, **kwargs):
        process = await spawn(sys.executable, "-c",
            "import os\nchunk=b'synthetic-raw-noise'*8192\nwhile True:\n os.write(1,chunk)\n os.write(2,chunk)",
            **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(native_git.asyncio, "create_subprocess_exec", noisy_process)
    monkeypatch.setattr(native_git.shutil, "which", lambda *args, **kwargs: "/synthetic/git")
    started = time.monotonic()
    with pytest.raises(GitOperationFailure) as failure:
        await native_git._git(["fetch", URL, SHA], timeout=0.1)
    assert failure.value.code == "GIT_TIMEOUT"
    assert time.monotonic() - started < 3
    assert len(processes) == 1 and processes[0].returncode is not None
    assert processes[0].stdout.at_eof() and processes[0].stderr.at_eof()
    captured = capsys.readouterr()
    assert "synthetic-raw-noise" not in captured.out + captured.err + str(failure.value)
