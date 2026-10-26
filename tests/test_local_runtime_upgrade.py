"""Upgrades verify the live transport without platform requests or journal replay."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from hypertest.interactive_client import __main__ as entry
from hypertest.interactive_client import ipc
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.ipc import LocalClient, LocalServer
from hypertest.interactive_client.runtime import runtime_identity
from hypertest.interactive_client.security import private_create


@pytest.fixture
def runtime_config(tmp_path):
    # A short path also fits Darwin's AF_UNIX limit in the same regression.
    token = tmp_path / "integration"
    private_create(token, b"private-project-authorization")
    config = ClientConfig(api_url="https://must-not-be-contacted.invalid/api/v1",
        state_dir=tmp_path / "state", integration_token_file=token,
        local_sync={"enabled": True, "host": "codex"})
    config.prepare(validate_credentials=False)
    return config


class NoNetworkService:
    async def tools(self):
        pytest.fail("runtime verification must not query platform capabilities")

    async def call(self, *args, **kwargs):
        pytest.fail("runtime verification must not execute a task operation")


async def test_live_provenance_matches_selected_runtime_without_start_or_network(runtime_config, monkeypatch):
    server = LocalServer(runtime_config, NoNetworkService())
    await server.start()
    launch = Mock(side_effect=AssertionError("matching runtime should be reused"))
    monkeypatch.setattr(entry.subprocess, "Popen", launch)
    try:
        result = await entry.ensure_daemon(runtime_config, Path("/private/client.json"))
        assert result["status"] == "MATCH" and result["restarted"] is False
        assert result["observed"] == runtime_identity(runtime_config)
        assert "private-project-authorization" not in json.dumps(result)
        assert not launch.called
    finally:
        await server.close()


async def test_mismatch_stops_and_restarts_authenticated_daemon_preserving_frozen_state(runtime_config, monkeypatch):
    frozen = runtime_config.state_dir / "original-request.json"
    private_create(frozen, b'{"state":"UNKNOWN","key":"original-only","request":"frozen"}')
    stopping = asyncio.Event()
    old = LocalServer(runtime_config, NoNetworkService(), stopping=stopping)
    old.runtime = {**old.runtime, "source_commit": "old-loaded-source"}
    await old.start()
    new = LocalServer(runtime_config, NoNetworkService())
    spawned = []
    async def close_old():
        await stopping.wait()
        await old.close()
    closer = asyncio.create_task(close_old())
    def start_selected(command, **kwargs):
        spawned.append(command)
        asyncio.create_task(new.start())
        return Mock()
    monkeypatch.setattr(entry.subprocess, "Popen", start_selected)
    try:
        result = await entry.ensure_daemon(runtime_config, Path("/private/client.json"))
        assert result["status"] == "MATCH" and result["restarted"] is True
        assert result["observed"]["source_commit"] != "old-loaded-source"
        assert len(spawned) == 1 and "-I" in spawned[0]
        assert frozen.read_bytes() == b'{"state":"UNKNOWN","key":"original-only","request":"frozen"}'
    finally:
        await closer
        await new.close()


async def test_busy_runtime_refuses_upgrade_without_stopping_or_replaying(runtime_config, monkeypatch):
    entered, release, stopping = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class BusyService:
        async def call(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return {"status": "UNKNOWN"}
    server = LocalServer(runtime_config, BusyService(), stopping=stopping)
    server.runtime = {**server.runtime, "python": "/old/python"}
    await server.start()
    client = LocalClient(runtime_config.socket_path, runtime_config.local_token_file)
    operation = asyncio.create_task(client.exchange("call", {"name": "test", "arguments": {}}))
    launch = Mock()
    monkeypatch.setattr(entry.subprocess, "Popen", launch)
    try:
        await entered.wait()
        with pytest.raises(ClientError, match="LOCAL_RUNTIME_BUSY"):
            await entry.ensure_daemon(runtime_config, Path("/private/client.json"))
        assert not stopping.is_set() and not launch.called
        release.set()
        assert await operation == {"status": "UNKNOWN"}
    finally:
        release.set()
        await operation
        await server.close()


async def test_legacy_stop_requires_authenticated_reply_before_same_peer_signal(runtime_config, monkeypatch):
    # Simulate a prior daemon that only understands the original private RPC.
    token = "legacy-private-ipc-token"
    private_create(runtime_config.local_token_file, token.encode())
    async def handle(reader, writer):
        request = json.loads(await reader.readline())
        code = "LOCAL_OPERATION_UNSUPPORTED" if request["token"] == token else "LOCAL_AUTHORIZATION_REJECTED"
        writer.write(json.dumps({"ok": False, "error": code}).encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_unix_server(handle, path=runtime_config.socket_path)
    runtime_config.socket_path.chmod(0o600)
    kill = Mock()
    monkeypatch.setattr(ipc.os, "kill", kill)
    client = LocalClient(runtime_config.socket_path, runtime_config.local_token_file)
    try:
        runtime_config.local_token_file.write_text("wrong-token")
        with pytest.raises(ClientError, match="LOCAL_AUTHORIZATION_REJECTED"):
            await client.stop()
        assert not kill.called
        runtime_config.local_token_file.write_text(token)
        result = await client.stop()
        assert result == {"state": "STOPPING", "legacy": True}
        kill.assert_called_once_with(os.getpid(), ipc.signal.SIGTERM)
    finally:
        server.close()
        await server.wait_closed()
        runtime_config.socket_path.unlink(missing_ok=True)


async def test_private_runtime_token_failure_does_not_start_or_stop(runtime_config, monkeypatch):
    stopping = asyncio.Event()
    server = LocalServer(runtime_config, NoNetworkService(), stopping=stopping)
    await server.start()
    runtime_config.local_token_file.write_text("wrong-token")
    launch = Mock()
    monkeypatch.setattr(entry.subprocess, "Popen", launch)
    try:
        with pytest.raises(ClientError, match="LOCAL_AUTHORIZATION_REJECTED"):
            await entry.ensure_daemon(runtime_config, Path("/private/client.json"))
        assert not stopping.is_set() and not launch.called
    finally:
        await server.close()
