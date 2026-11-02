"""Worker auth observation stays independent of task scheduling."""
import asyncio
from types import SimpleNamespace

from hypertest.cloud import agent_auth_monitor


async def test_monitor_probes_and_records_in_background(monkeypatch):
    calls = []
    recorded = asyncio.Event()

    def probe(path):
        calls.append(("probe", path))
        return "VALID"

    async def record(sessions, worker_id, status):
        calls.append(("record", sessions, worker_id, status))
        recorded.set()

    monkeypatch.setattr(agent_auth_monitor, "probe_deepseek_auth", probe)
    monkeypatch.setattr(agent_auth_monitor, "record_worker_auth_status", record)
    task = asyncio.create_task(agent_auth_monitor.monitor_agent_auth("sessions", SimpleNamespace(cloud_model_key_file="private-path"), "worker-id"))
    await asyncio.wait_for(recorded.wait(), 2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls == [("probe", "private-path"), ("record", "sessions", "worker-id", "VALID")]


async def test_monitor_swallows_storage_error_without_logging_secret(monkeypatch, capsys):
    called = asyncio.Event()
    monkeypatch.setattr(agent_auth_monitor, "probe_deepseek_auth", lambda path: "UNKNOWN")

    async def record(*args):
        called.set()
        raise RuntimeError("synthetic-secret")

    monkeypatch.setattr(agent_auth_monitor, "record_worker_auth_status", record)
    task = asyncio.create_task(agent_auth_monitor.monitor_agent_auth(None, SimpleNamespace(cloud_model_key_file="private-path"), "worker-id"))
    await asyncio.wait_for(called.wait(), 2)
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert "synthetic-secret" not in capsys.readouterr().out
