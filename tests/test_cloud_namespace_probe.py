"""Worker startup namespace checks use no model, network or project data."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from hypertest.cloud import sandbox, worker
from hypertest.cloud.errors import CloudBlocked


@pytest.fixture
def namespace_commands(monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(sandbox, "require_readonly_shell", lambda: None)


async def test_probe_executes_isolated_setup_without_workspace_or_secrets(namespace_commands, monkeypatch):
    calls = []

    async def start(*args, **kwargs):
        calls.append((args, kwargs))

        async def wait():
            return 0

        return SimpleNamespace(wait=wait)

    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", start)
    await sandbox.probe_namespace()
    args, options = calls[0]
    assert {"--unshare-all", "--clearenv", "--die-with-parent", "--proc", "--dev", "--tmpfs"} <= set(args)
    assert args[-2:] == ("/", "/usr/bin/true")
    assert "/workspace" not in args and "/run/model.sock" not in args
    assert options["env"] == {"PATH": sandbox.os.defpath}
    assert options["stdin"] == options["stdout"] == options["stderr"] == asyncio.subprocess.DEVNULL


@pytest.mark.parametrize("outcome", ["rejected", "timeout"])
async def test_probe_failure_is_bounded_and_terminates_process(namespace_commands, monkeypatch, outcome):
    class Process:
        pid = 1234
        killed = False

        async def wait(self):
            if outcome == "rejected":
                return 1
            if not self.killed:
                await asyncio.Event().wait()
            return -9

        def kill(self):
            self.killed = True

    process = Process()

    def killpg(pid, sig):
        assert pid == process.pid and sig == sandbox.signal.SIGKILL
        process.killed = True

    async def start(*args, **kwargs):
        return process

    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", start)
    monkeypatch.setattr(sandbox.os, "killpg", killpg)
    with pytest.raises(CloudBlocked) as error:
        await sandbox.probe_namespace(timeout_seconds=0.01)
    assert error.value.code == "NAMESPACE_SETUP_FAILED"
    assert process.killed is (outcome == "timeout")


async def test_cancelled_probe_terminates_and_reaps(namespace_commands, monkeypatch):
    entered = asyncio.Event()

    class Process:
        pid = 1234
        killed = False

        async def wait(self):
            if not self.killed:
                entered.set()
                await asyncio.Event().wait()
            return -9

        def kill(self):
            self.killed = True

    process = Process()

    def killpg(pid, sig):
        assert pid == process.pid and sig == sandbox.signal.SIGKILL
        process.killed = True

    async def start(*args, **kwargs):
        return process

    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", start)
    monkeypatch.setattr(sandbox.os, "killpg", killpg)
    task = asyncio.create_task(sandbox.probe_namespace())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed


@pytest.mark.parametrize("fail", [False, True])
async def test_worker_expires_leases_then_probes_before_claim_and_caches_result(monkeypatch, fail):
    counts = {"probe": 0, "database": 0}
    events = []
    monkeypatch.setattr(worker, "inspect_resource_envelope", lambda: None)

    async def probe():
        counts["probe"] += 1
        events.append("probe")
        if fail:
            raise CloudBlocked("NAMESPACE_SETUP_FAILED", "fixture refusal")

    monkeypatch.setattr(worker, "probe_namespace", probe)

    class Session:
        async def __aenter__(self):
            counts["database"] += 1
            return object()

        async def __aexit__(self, *_):
            return False

    async def expire(*args, **kwargs):
        events.append("expire")

    async def no_work(*args, **kwargs):
        events.append("claim")
        return None

    monkeypatch.setattr(worker.service, "expire_leases", expire)
    for name in ("claim_resolution", "claim_attempt"):
        monkeypatch.setattr(worker.service, name, no_work)
    instance = worker.CloudWorker(Session, SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True,
        cloud_worker_lease_seconds=30), "fixture")
    for _ in range(2):
        if fail:
            with pytest.raises(CloudBlocked) as error:
                await instance.run_once()
            assert error.value.code == "NAMESPACE_SETUP_FAILED"
        else:
            assert await instance.run_once() is False
    assert counts == {"probe": 1, "database": 2 if fail else 6}
    assert events == (["expire", "probe", "expire"] if fail else
                      ["expire", "probe", "claim", "claim", "expire", "claim", "claim"])


async def test_cli_stops_after_namespace_failure_without_polling(monkeypatch, capsys):
    from hypertest.cloud import __main__ as cli

    events = []
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(
        cloud_enabled=True, cloud_worker_enabled=True, cloud_service_release_sha256=""))
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *_: None)

    class Engine:
        async def dispose(self):
            events.append("dispose")

    class FailedWorker:
        _namespace_failure = None

        def __init__(self, *_):
            pass

        async def run_once(self):
            events.append("run")
            self._namespace_failure = "NAMESPACE_SETUP_FAILED"
            raise CloudBlocked(self._namespace_failure, "private canary")

    monkeypatch.setattr(worker, "CloudWorker", FailedWorker)
    monkeypatch.setitem(sys.modules, "hypertest.db.session", SimpleNamespace(AsyncSessionLocal=object(), engine=Engine()))
    assert await cli.run(once=False) == 1
    assert events == ["run", "dispose"]
    output = capsys.readouterr().out
    assert json.loads(output)["code"] == "NAMESPACE_SETUP_FAILED"
    assert "private canary" not in output
