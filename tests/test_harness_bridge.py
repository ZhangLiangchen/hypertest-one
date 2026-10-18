"""Bridge tests exercise real UDS transport and process-independent journals.

The provider below is a deterministic boundary fixture; these are not claimed
as a real-model workflow acceptance run.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from hypertest.agent.bridge import BridgeClient
from hypertest.harness_bridge.protocol import BridgeError, ExecutionContext, canonical
from hypertest.harness_bridge.provider import provider_environment
from hypertest.harness_bridge.server import BridgeServer

EXECUTION_KEY = b"e" * 32
MANAGEMENT_KEY = b"m" * 32


class BoundaryProvider:
    def __init__(self):
        self.native = set()
        self.invocations = []
        self.events = {}
        self.tool_result = None

    def session_exists(self, reference):
        return reference in self.native

    async def run(self, *, call_id, workspace, native_session, contract, relay_socket, relay_token, started):
        reference = native_session or str(uuid4())
        self.native.add(reference)
        self.invocations.append((call_id, reference, str(workspace)))
        self.events[call_id] = asyncio.Event()
        started(1000000, None)
        yield {"type": "SESSION_STARTED", "payload": {"provider_session_id": reference}}
        if contract["prompt"] == "tool":
            reader, writer = await asyncio.open_unix_connection(relay_socket)
            writer.write(canonical({"call_id": call_id, "token": relay_token, "operation": "call",
                                    "payload": {"name": "get_state", "arguments": {}, "tool_call_id": "tool-1"}}) + b"\n")
            await writer.drain()
            self.tool_result = json.loads(await reader.readline())
            writer.close()
            await writer.wait_closed()
        elif contract["prompt"] == "wait":
            await self.events[call_id].wait()
        yield {"type": "TURN_FINISHED", "payload": {"return_code": 0}}

    async def interrupt(self, call_id):
        if event := self.events.get(call_id):
            event.set()
        return True


@pytest.fixture
async def bridge():
    # UNIX socket paths have a small OS limit, independent of pytest's long path.
    with tempfile.TemporaryDirectory(prefix="htb-", dir="/tmp") as temporary:
        root = Path(temporary).resolve()
        provider = BoundaryProvider()
        server = BridgeServer(socket_path=root / "b.sock", tool_socket_path=root / "t.sock",
                              state_dir=root / "state", workspace_root=root / "workspaces",
                              host_id="host-test", execution_key=EXECUTION_KEY,
                              management_key=MANAGEMENT_KEY, provider=provider)
        await server.start()
        client = BridgeClient(str(server.socket_path), EXECUTION_KEY, MANAGEMENT_KEY)
        yield server, client, provider
        await server.shutdown()


def context(server, **changes):
    workspace_id = uuid4().hex
    (server.workspace_root / workspace_id / "repo").mkdir(parents=True)
    result = ExecutionContext(run_id=uuid4().hex, binding_id=uuid4().hex,
                              logical_worker_id=uuid4().hex, session_id=uuid4().hex,
                              workspace_id=workspace_id, harness_host_id="host-test",
                              job_id=uuid4().hex, claim_token=uuid4().hex,
                              binding_epoch=1, expires_at=time.time() + 30)
    return replace(result, **changes)


def contract(prompt="done", tools=None):
    return {"prompt": prompt, "tools": tools or [{"name": "get_state", "description": "Read state",
                                                  "inputSchema": {"type": "object"}}],
            "timeout_seconds": 30}


async def until_call(client, ctx, call_id, predicate):
    for _ in range(100):
        result = await client.get_call(ctx, call_id, management=True)
        if predicate(result):
            return result
        await asyncio.sleep(0.01)
    raise AssertionError("call did not reach expected state")


async def test_bridge_negotiates_and_reuses_native_session_across_turns(bridge):
    server, client, provider = bridge
    capabilities = await client.capabilities()
    assert capabilities["profile"] == "run-persistent-harness/v1"
    assert capabilities["protocol"] == "hypertest.tmp/v1alpha2"
    assert capabilities["native_shell"] is False
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract(), call_id="first")
    first = await until_call(client, ctx, "first", lambda call: call["stopped"])
    assert first["status"] == "COMPLETED"
    await client.start_call(ctx, contract(), call_id="second", resume=True)
    second = await until_call(client, ctx, "second", lambda call: call["stopped"])
    assert first["provider_session_id"] == second["provider_session_id"]
    assert len(provider.invocations) == 2
    assert all(item[1] == first["provider_session_id"] for item in provider.invocations)
    assert await client.restore_session(ctx) == server.session_view(server.sessions[ctx.session_id])
    await client.close(ctx, "second", terminal=True)
    with pytest.raises(BridgeError, match="SESSION_UNAVAILABLE"):
        await client.start_call(ctx, contract(), call_id="third", resume=True)


async def test_same_call_is_reconciled_without_provider_replay_and_conflicts_rejected(bridge):
    server, client, provider = bridge
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("wait"), call_id="same")
    await until_call(client, ctx, "same", lambda call: bool(call["provider_session_id"]))
    repeated = await client.start_call(ctx, contract("wait"), call_id="same")
    assert repeated["call_id"] == "same"
    assert len(provider.invocations) == 1
    with pytest.raises(BridgeError, match="IDEMPOTENCY_CONFLICT"):
        await client.start_call(ctx, contract("different"), call_id="same")
    with pytest.raises(BridgeError, match="SESSION_BUSY"):
        await client.start_call(ctx, contract(), call_id="parallel", resume=True)


async def test_management_stops_after_claim_revocation_without_new_execution_authority(bridge):
    server, client, _ = bridge
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("wait"), call_id="cancelled")
    await until_call(client, ctx, "cancelled", lambda call: bool(call["provider_session_id"]))
    management = replace(ctx, claim_token="management", expires_at=0)
    assert (await client.interrupt(management, "cancelled"))["stopped"]
    assert (await client.get_call(management, "cancelled", management=True))["status"] == "INTERRUPTED"
    with pytest.raises(BridgeError, match="STALE_CLAIM"):
        await client.start_call(ctx, contract(), call_id="late-old-owner", resume=True)
    with pytest.raises(BridgeError, match="AUTHORIZATION_REJECTED"):
        await client.request("resume", {"context": management.to_dict()}, management=True)
    fresh = replace(ctx, claim_token=uuid4().hex, expires_at=time.time() + 30)
    await client.start_call(fresh, contract(), call_id="answered", resume=True)
    resumed = await until_call(client, fresh, "answered", lambda call: call["stopped"])
    assert resumed["binding_epoch"] == 1
    assert resumed["status"] == "COMPLETED"


async def test_call_elapsed_time_is_durable_and_does_not_grow_after_confirmed_stop(bridge):
    server, client, _ = bridge
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("wait"), call_id="timed")
    active = await until_call(client, ctx, "timed", lambda call: bool(call["provider_session_id"]))
    assert active["finished_at"] is None and active["elapsed_seconds"] >= 0
    await client.interrupt(ctx, "timed")
    stopped = await client.get_call(ctx, "timed", management=True)
    assert stopped["stopped"] and stopped["finished_at"] >= stopped["created_at"]
    assert stopped["elapsed_seconds"] == stopped["finished_at"] - stopped["created_at"]
    await asyncio.sleep(0.02)
    await client.interrupt(ctx, "timed")
    repeated = await client.get_call(ctx, "timed", management=True)
    assert repeated["elapsed_seconds"] == stopped["elapsed_seconds"]
    saved = json.loads((server.state_dir / "call-timed.json").read_text())
    assert saved["finished_at"] == stopped["finished_at"]


async def test_expired_grant_stops_and_requires_explicit_recovery(bridge):
    server, client, _ = bridge
    ctx = context(server, expires_at=time.time() + 0.4)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("wait"), call_id="expired")
    final = await until_call(client, ctx, "expired", lambda call: call["stopped"])
    assert final["status"] == "OUTCOME_UNKNOWN"
    assert final["error_code"] == "EXECUTION_GRANT_EXPIRED"
    assert server.sessions[ctx.session_id]["recovery_required"]
    management = replace(ctx, claim_token="management", expires_at=0)
    await client.restore_session(management)
    recovered = await client.recover(management, "expired", new_epoch=2)
    assert recovered["binding_epoch"] == 2
    fresh = replace(ctx, binding_epoch=2, claim_token=uuid4().hex, expires_at=time.time() + 30)
    await client.start_call(fresh, contract("wait"), call_id="recovered", resume=True)
    await until_call(client, fresh, "recovered", lambda call: bool(call["provider_session_id"]))
    assert (await client.interrupt(management, "expired"))["stopped"]
    assert (await client.get_call(fresh, "recovered"))["status"] == "RUNNING"
    with pytest.raises(BridgeError, match="CLOSE_REJECTED"):
        await client.close(management, "expired", terminal=True)


async def test_tool_relay_is_call_scoped_and_worker_result_is_returned(bridge):
    server, client, provider = bridge
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("tool"), call_id="tools")
    ready = await until_call(client, ctx, "tools", lambda call: bool(call["pending_tools"]))
    assert ready["pending_tools"] == [{"tool_call_id": "tool-1", "name": "get_state", "arguments": {}}]
    result = {"requirements": ["REQ-1"]}
    await client.respond_tool(ctx, "tools", "tool-1", result)
    await until_call(client, ctx, "tools", lambda call: call["stopped"])
    assert provider.tool_result == {"ok": True, "result": result}
    journal = (server.state_dir / "call-tools.json").read_text()
    assert ctx.claim_token not in journal
    assert EXECUTION_KEY.decode() not in journal


async def test_workspace_and_tool_allowlists_and_identity_are_enforced(bridge):
    server, client, _ = bridge
    ctx = context(server)
    unsafe = replace(ctx, workspace_id="../../outside")
    with pytest.raises(BridgeError, match="INVALID_CONTEXT"):
        await client.create_session(unsafe)
    target = server.workspace_root / ctx.workspace_id / "repo"
    target.rmdir()
    target.symlink_to(server.state_dir, target_is_directory=True)
    with pytest.raises(BridgeError, match="WORKSPACE_UNAVAILABLE"):
        await client.create_session(ctx)
    target.unlink()
    target.mkdir()
    await client.create_session(ctx)
    with pytest.raises(BridgeError, match="INVALID_TOOLS"):
        await client.start_call(ctx, contract(tools=[{"name": "shell", "inputSchema": {"type": "object"}}]), call_id="bad-tool")
    with pytest.raises(BridgeError, match="SESSION_UNAVAILABLE"):
        await client.restore_session(replace(ctx, run_id=uuid4().hex))
    with pytest.raises(BridgeError, match="INVALID_CONTRACT"):
        await client.start_call(ctx, {**contract(), "executable": "/bin/sh"}, call_id="bad-command")


async def test_host_capacity_is_global_but_distinct_runs_can_execute_concurrently(bridge):
    server, client, _ = bridge
    contexts = [context(server) for _ in range(3)]
    for ctx in contexts:
        await client.create_session(ctx)
    for index, ctx in enumerate(contexts[:2]):
        await client.start_call(ctx, contract("wait"), call_id=f"parallel-{index}")
    with pytest.raises(BridgeError, match="HOST_CAPACITY_EXCEEDED"):
        await client.start_call(contexts[2], contract("wait"), call_id="third-run")
    for index, ctx in enumerate(contexts[:2]):
        await client.interrupt(ctx, f"parallel-{index}")
    await client.start_call(contexts[2], contract(), call_id="third-run")
    await until_call(client, contexts[2], "third-run", lambda call: call["stopped"])


async def test_bad_keys_and_cross_call_context_are_rejected(bridge):
    server, client, _ = bridge
    attacker = BridgeClient(str(server.socket_path), b"x" * 32, b"y" * 32)
    with pytest.raises(BridgeError, match="AUTHORIZATION_REJECTED"):
        await attacker.capabilities()
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("wait"), call_id="one")
    with pytest.raises(BridgeError, match="CALL_NOT_FOUND"):
        await client.get_call(replace(ctx, job_id=uuid4().hex), "one", management=True)
    with pytest.raises(BridgeError, match="STALE_CLAIM"):
        await client.renew(replace(ctx, claim_token=secrets.token_hex(16)), "one")


async def test_journal_restore_preserves_session_and_never_replays_calls(bridge):
    server, client, provider = bridge
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract(), call_id="finished-before-restart")
    first = await until_call(client, ctx, "finished-before-restart", lambda call: call["stopped"])
    restored = BridgeServer(socket_path=server.socket_path, tool_socket_path=server.tool_socket_path,
                            state_dir=server.state_dir, workspace_root=server.workspace_root,
                            host_id=server.host_id, execution_key=EXECUTION_KEY,
                            management_key=MANAGEMENT_KEY, provider=provider)
    assert restored.sessions[ctx.session_id]["provider_session_id"] == first["provider_session_id"]
    assert restored.calls["finished-before-restart"]["status"] == "COMPLETED"
    assert len(provider.invocations) == 1
    # Simulated crash after registration. No automatic resumption or synthetic success.
    pending = dict(restored.calls["finished-before-restart"])
    pending.update(id="crash", status="RUNNING", stopped=False)
    restored._save("call", pending)
    recovered = BridgeServer(socket_path=server.socket_path, tool_socket_path=server.tool_socket_path,
                             state_dir=server.state_dir, workspace_root=server.workspace_root,
                             host_id=server.host_id, execution_key=EXECUTION_KEY,
                             management_key=MANAGEMENT_KEY, provider=provider)
    assert recovered.calls["crash"]["status"] == "OUTCOME_UNKNOWN"
    assert recovered.sessions[ctx.session_id]["recovery_required"]
    assert len(provider.invocations) == 1


def test_provider_environment_drops_platform_and_interpreter_secrets():
    environment = provider_environment({"HOME": "/provider", "PATH": "/usr/bin", "CODEX_HOME": "/auth",
                                        "OPENAI_API_KEY": "provider-only", "HYPERTEST_DATABASE_URL": "secret",
                                        "DATABASE_URL": "secret", "HYPERTEST_BRIDGE_EXECUTION_KEY": "secret",
                                        "GITLAB_TOKEN": "secret", "PYTHONPATH": "/evil", "LD_PRELOAD": "/evil"})
    assert environment == {"HOME": "/provider", "PATH": "/usr/bin", "CODEX_HOME": "/auth",
                           "OPENAI_API_KEY": "provider-only"}


async def test_grant_renewal_keeps_live_call_and_expired_grant_cannot_be_revived(bridge):
    server, client, _ = bridge
    ctx = context(server, expires_at=time.time() + 0.4)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("wait"), call_id="renewable")
    renewed = replace(ctx, expires_at=time.time() + 10)
    assert (await client.renew(renewed, "renewable"))["expires_at"] == renewed.expires_at
    await asyncio.sleep(0.5)
    assert (await client.get_call(renewed, "renewable"))["status"] == "RUNNING"
    # A stopped grant is a recovery decision, not a refreshable token.
    await client.interrupt(replace(ctx, expires_at=0), "renewable")
    with pytest.raises(BridgeError, match="CALL_FINISHED"):
        await client.renew(renewed, "renewable")


async def test_native_session_loss_fails_closed_without_new_thread(bridge):
    server, client, provider = bridge
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract(), call_id="original")
    await until_call(client, ctx, "original", lambda call: call["stopped"])
    provider.native.clear()
    with pytest.raises(BridgeError, match="SESSION_UNAVAILABLE"):
        await client.restore_session(ctx)
    with pytest.raises(BridgeError, match="SESSION_UNAVAILABLE"):
        await client.start_call(ctx, contract(), call_id="missing", resume=True)
    with pytest.raises(BridgeError, match="SESSION_ALREADY_STARTED"):
        await client.start_call(ctx, contract(), call_id="new-thread", resume=False)
    assert len(provider.invocations) == 1


async def test_relay_token_is_not_a_bridge_execution_credential(bridge):
    server, client, _ = bridge
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("wait"), call_id="scoped")
    token = server.relay_tokens["scoped"]
    reader, writer = await asyncio.open_unix_connection(str(server.tool_socket_path))
    writer.write(canonical({"call_id": "scoped", "token": token, "operation": "execute", "payload": {}}) + b"\n")
    await writer.drain()
    assert json.loads(await reader.readline())["error"] == "TOOL_OPERATION_REJECTED"
    writer.close()
    await writer.wait_closed()
    reader, writer = await asyncio.open_unix_connection(str(server.tool_socket_path))
    writer.write(canonical({"call_id": "other", "token": token, "operation": "list", "payload": {}}) + b"\n")
    await writer.drain()
    assert json.loads(await reader.readline())["error"] == "TOOL_AUTHORIZATION_REJECTED"
    writer.close()
    await writer.wait_closed()


async def test_signed_nonce_cannot_be_replayed(bridge):
    from hypertest.harness_bridge.protocol import PROFILE, PROTOCOL, TRANSPORT, sign

    server, _, _ = bridge
    message = {"transport": TRANSPORT, "protocol": PROTOCOL, "profile": PROFILE,
               "operation": "capabilities", "authority": "management", "issued_at": time.time(),
               "nonce": "repeat-nonce", "payload": {}}
    message["signature"] = sign(message, MANAGEMENT_KEY)

    async def send():
        reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
        writer.write(canonical(message) + b"\n")
        await writer.drain()
        result = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()
        return result

    assert (await send())["ok"]
    assert (await send())["error"] == "AUTHORIZATION_REPLAY"


async def test_persistent_provider_uses_fixed_mcp_configuration_and_filtered_env(tmp_path):
    import sys

    from hypertest.harness_bridge.provider import PersistentCodex

    script = tmp_path / "codex-fixture.py"
    native = str(uuid4())
    script.write_text(f'''#!{sys.executable}
import json,os,pathlib,sys,tomllib
args=sys.argv[1:]
assert "--ignore-user-config" in args and "--ignore-rules" in args
assert args[args.index("--sandbox")+1] == "read-only"
for feature in ("shell_tool","unified_exec","multi_agent","apps","plugins","browser_use","computer_use"):
    assert any(args[i:i+2] == ["--disable",feature] for i in range(len(args)))
assert "DATABASE_URL" not in os.environ and "GITLAB_TOKEN" not in os.environ
assert "PYTHONPATH" not in os.environ and "HYPERTEST_BRIDGE_EXECUTION_KEY" not in os.environ
configuration=tomllib.loads(next(x for x in args if x.startswith("mcp_servers.hypertest=")))
mcp=configuration["mcp_servers"]["hypertest"]
assert mcp["required"] and mcp["default_tools_approval_mode"] == "approve"
assert mcp["args"][0] == "-I" and mcp["args"][1].endswith("harness_bridge/relay.py")
assert set(mcp["env"]) == {{"HYPERTEST_RELAY_SOCKET","HYPERTEST_RELAY_TOKEN","HYPERTEST_RELAY_CALL_ID"}}
assert sys.stdin.read().endswith("safe immutable contract")
root=pathlib.Path(os.environ["CODEX_HOME"])/"sessions"
root.mkdir(parents=True,exist_ok=True)
(root/"rollout-{native}.jsonl").write_text("session record")
if "resume" in args:
    assert args[args.index("resume")+1] == {native!r}
    assert args.index("resume") < args.index("--json")
print(json.dumps({{"type":"thread.started","thread_id":{native!r}}}))
print(json.dumps({{"type":"turn.completed"}}))
''')
    script.chmod(0o700)
    provider = PersistentCodex(str(script), environment={"HOME": str(tmp_path), "CODEX_HOME": str(tmp_path / "auth"),
                                                         "PATH": "/usr/bin:/bin", "DATABASE_URL": "secret",
                                                         "GITLAB_TOKEN": "secret", "PYTHONPATH": "/evil",
                                                         "HYPERTEST_BRIDGE_EXECUTION_KEY": "secret"})
    for index in range(2):
        events = [item async for item in provider.run(call_id=f"turn-{index}", workspace=tmp_path,
                                                      native_session=native if index else None,
                                                      contract=contract("safe immutable contract"),
                                                      relay_socket="/tmp/relay.sock", relay_token="scoped-only",
                                                      started=lambda pid, identity: None)]
        assert next(item for item in events if item["type"] == "SESSION_STARTED")["payload"]["provider_session_id"] == native
        assert events[-1]["type"] == "TURN_FINISHED"
        assert provider.session_exists(native)


async def test_management_recovery_after_explicit_fence_without_watchdog_flag(bridge):
    server, client, _ = bridge
    ctx = context(server)
    await client.create_session(ctx)
    await client.start_call(ctx, contract("wait"), call_id="owner-failed")
    await until_call(client, ctx, "owner-failed", lambda call: bool(call["provider_session_id"]))
    with pytest.raises(BridgeError, match="RECOVERY_REJECTED"):
        await client.recover(ctx, "owner-failed", new_epoch=2)
    assert (await client.interrupt(ctx, "owner-failed"))["stopped"]
    assert not server.sessions[ctx.session_id]["recovery_required"]
    recovered = await client.recover(ctx, "owner-failed", new_epoch=2)
    assert recovered["binding_epoch"] == 2
    assert await client.recover(ctx, "owner-failed", new_epoch=2) == recovered
