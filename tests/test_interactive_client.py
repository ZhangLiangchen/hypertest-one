"""Client trust boundaries and uncertain writes, using explicit boundary fixtures."""
import hashlib
import json
import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from hypertest.interactive_client import PROFILE
from hypertest.interactive_client.api_client import ApiClient, ApiError
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.ipc import LocalClient, LocalServer
from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.service import InteractiveService, public


def private(path, text):
    path.write_text(text)
    path.chmod(0o600)
    return path


@pytest.fixture
def config(tmp_path):
    state = tmp_path / "private"
    token = private(tmp_path / "integration", "never-model-integration-secret")
    device = private(tmp_path / "device", "never-model-device-secret")
    value = ClientConfig(api_url="https://platform.invalid/api/v1", state_dir=state,
                         integration_token_file=token, device_token_file=device)
    value.prepare()
    return value


class UnsupportedHost:
    def capabilities(self):
        return {"interactive_execution": False}

    async def attest(self, **kwargs):
        raise ClientError("TRUSTED_HOST_UNSUPPORTED")

    async def assert_live(self, proof):
        raise ClientError("TRUSTED_HOST_UNSUPPORTED")


class FakeApi:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.fail_post = False

    async def capabilities(self):
        names = ["hypertest_submit_task", "hypertest_get_submission", "hypertest_get_progress",
                 "hypertest_bind_execution", "hypertest_get_execution"]
        return {"profile": PROFILE, "tools": [{"name": name, "description": name,
                "inputSchema": {"type": "object"}} for name in names], "execution_tools": []}

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if method == "POST" and self.fail_post:
            raise ApiError("PLATFORM_UNAVAILABLE")
        value = self.responses.get((method, path), {"status": "NOT_FOUND"})
        if isinstance(value, Exception):
            raise value
        return value


async def test_lost_submission_reply_is_durable_query_only_even_after_restart(config):
    path = config.state_dir / "journal.sqlite3"
    journal = Journal(path)
    api = FakeApi()
    api.fail_post = True
    service = InteractiveService(config, api, journal, UnsupportedHost())
    args = {"project_id": str(uuid4()), "submission_key": "stable-key", "bootstrap": {}}
    first = await service.call("hypertest_submit_task", args)
    assert first["status"] == "UNKNOWN"
    assert journal.get("submission:" + args["project_id"], "stable-key")["state"] == "UNKNOWN"
    journal.close()
    journal = Journal(path)
    service = InteractiveService(config, api, journal, UnsupportedHost())
    second = await service.call("hypertest_submit_task", args)
    assert second["status"] == "NOT_FOUND"
    assert [call[0] for call in api.calls] == ["POST", "GET"]
    assert journal.get("submission:" + args["project_id"], "stable-key")["state"] == "UNKNOWN"
    journal.close()


async def test_same_key_different_input_is_rejected_before_network(config):
    journal, api = Journal(config.state_dir / "journal.sqlite3"), FakeApi()
    service = InteractiveService(config, api, journal, UnsupportedHost())
    args = {"project_id": str(uuid4()), "submission_key": "same"}
    await service.call("hypertest_submit_task", args)
    with pytest.raises(ClientError, match="IDEMPOTENCY_CONFLICT"):
        await service.call("hypertest_submit_task", {**args, "bootstrap": {"commit_sha": "b" * 40}})
    assert len(api.calls) == 1
    journal.close()


async def test_unsupported_host_cannot_bind_and_model_cannot_supply_identity(config):
    journal, api = Journal(config.state_dir / "journal.sqlite3"), FakeApi()
    service = InteractiveService(config, api, journal, UnsupportedHost())
    with pytest.raises(ClientError, match="TRUSTED_HOST_UNSUPPORTED"):
        await service.call("hypertest_bind_execution", {"run_id": str(uuid4()), "attach_key": "k"}, peer_pid=os.getpid())
    assert not api.calls
    journal.close()


async def test_http_auth_headers_never_redirect_or_enter_public_result(config):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://attacker.invalid/steal"})
    api = ApiClient(config, transport=httpx.MockTransport(respond))
    with pytest.raises(ApiError):
        await api.request("GET", "interactive/capabilities", device=True, request_key="original-operation")
    assert len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer never-model-integration-secret"
    assert seen[0].headers["x-hypertest-request-key"] == "original-operation"
    assert "never-model" not in json.dumps(public({"execution_token": "never-model", "status": "BOUND"}))
    await api.close()


def test_private_permissions_and_scheme_are_enforced(config, tmp_path):
    config.integration_token_file.chmod(0o644)
    with pytest.raises(ClientError, match="PRIVATE_FILE_REQUIRED"):
        config.prepare()
    config.integration_token_file.chmod(0o600)
    config.api_url = "http://remote.invalid"
    with pytest.raises(ClientError, match="HTTPS"):
        config.prepare()


def page(text, **changes):
    value = {"schema_version": "hypertest.interactive-content/v1alpha1", "object_type": "evidence",
             "object_id": "e", "run_id": "r", "object_version": "v", "sha256": hashlib.sha256(text.encode()).hexdigest(),
             "encoding": "utf-8", "total_bytes": len(text.encode()), "offset": 0,
             "content": text, "next_cursor": None, "complete": True, "untrusted": True}
    return {**value, **changes}


def test_content_pages_preserve_version_and_verify_completed_digest(config):
    journal = Journal(config.state_dir / "journal.sqlite3")
    service = InteractiveService(config, FakeApi(), journal, UnsupportedHost())
    full = "可信 evidence"
    first = page(full, content=full[:2], next_cursor="next", complete=False)
    service._verify_content(first, requested_cursor=None)
    with pytest.raises(ClientError, match="VERSION_CONFLICT"):
        service._verify_content(page(full, content=full[2:], object_version="other"), requested_cursor="next")
    with pytest.raises(ClientError, match="INTEGRITY_REJECTED"):
        service._verify_content(page(full, sha256="0" * 64), requested_cursor=None)
    service._verify_content(page(full), requested_cursor=None)
    journal.close()


async def test_private_uds_checks_token_and_passes_kernel_peer_pid(config):
    class Service:
        async def tools(self): return []
        async def call(self, name, arguments, *, peer_pid=None): return {"peer_pid": peer_pid}
    with tempfile.TemporaryDirectory(prefix="hti-", dir="/tmp") as short:
        config.state_dir = Path(short).resolve()
        server = LocalServer(config, Service())
        await server.start()
        try:
            client = LocalClient(config.socket_path, config.local_token_file)
            result = await client.exchange("call", {"name": "test", "arguments": {}})
            assert result["peer_pid"] == os.getpid()
            config.local_token_file.write_text("wrong")
            with pytest.raises(ClientError, match="LOCAL_AUTHORIZATION_REJECTED"):
                await client.exchange("list", {})
        finally:
            await server.close()


async def test_official_sdk_negotiates_lists_and_returns_structured_results():
    from mcp.shared.memory import create_connected_server_and_client_session

    from hypertest.interactive_client.mcp_server import create_server

    class LocalBoundary:
        async def exchange(self, operation, payload):
            if operation == "list":
                return {"tools": [{"name": "hypertest_get_progress", "description": "Read progress",
                                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]}
            return {"status": "WAITING_INPUT", "untrusted": True}

    async with create_connected_server_and_client_session(create_server(LocalBoundary())) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools.tools] == ["hypertest_get_progress"]
        result = await client.call_tool("hypertest_get_progress", {})
        assert result.structuredContent == {"status": "WAITING_INPUT", "untrusted": True}
        invalid = await client.call_tool("hypertest_get_progress", {"host_proof": "forged"})
        assert invalid.isError


async def test_local_execution_needs_live_host_explicit_continue_and_keeps_grant_private(config, tmp_path):
    """A boundary host fixture proves routing, not actual desktop capability."""
    run_id, execution_id, node, transfer = [str(uuid4()) for _ in range(4)]
    workspace_id = uuid4().hex
    config.node_id = node
    config.workspaces = {run_id: {"path": str(tmp_path), "workspace_id": workspace_id,
                                 "commit_sha": "a" * 40, "origin": "git@source:approved/repo",
                                 "source_bundle_transfer_id": transfer}}

    class Host:
        live = True
        async def assert_peer(self, pid):
            if pid != os.getpid() or not self.live:
                raise ClientError("HOST_STDIO_PEER_REJECTED")
        async def attest(self, **kwargs):
            return {"node_id": node, "source_bundle_transfer_id": transfer,
                    "workspace_id": workspace_id, "native_session_id": "boundary-fixture"}
        async def assert_live(self, proof):
            if not self.live:
                raise ClientError("HOST_STDIO_PEER_REJECTED")

    class API(FakeApi):
        async def capabilities(self):
            caps = await super().capabilities()
            caps["execution_tools"] = [{"name": "request_mission", "description": "test boundary",
                "inputSchema": {"type": "object"}}]
            return caps

    journal, api, host = Journal(config.state_dir / "journal.sqlite3"), API(), Host()
    api.responses[("GET", f"interactive/runs/{run_id}/execution-context")] = {
        "project_id": str(uuid4()), "execution_mode": "LOCAL", "execution_driver": "INTERACTIVE_MCP",
        "harness_node_id": node, "source_bundle_transfer_id": transfer,
        "repository_url": "git@source:approved/repo", "commit_sha": "a" * 40}
    api.responses[("POST", "interactive/executions/bind")] = {"execution_id": execution_id, "status": "BOUND"}
    api.responses[("GET", "interactive/executions/by-key")] = {"execution_id": execution_id, "status": "ACTIVE"}
    api.responses[("POST", f"interactive/executions/{execution_id}/continue")] = {
        "execution_id": execution_id, "status": "ACTIVE", "execution_token": "private-runtime-secret",
        "expires_at": (datetime.now(UTC) + timedelta(seconds=60)).isoformat()}
    service = InteractiveService(config, api, journal, host)
    await service.call("hypertest_bind_execution", {"run_id": run_id, "attach_key": "a"}, peer_pid=os.getpid())
    tool = {"execution_id": execution_id, "arguments": {"idempotency_key": "mission", "mission_type": "DESIGN_TESTS"}}
    with pytest.raises(ClientError, match="EXPLICIT_CONTINUATION_REQUIRED"):
        await service.call("request_mission", tool, peer_pid=os.getpid())
    grant = await service.call("hypertest_bind_execution", {
        "run_id": run_id, "attach_key": "a", "action": "continue", "continuation_key": "c"}, peer_pid=os.getpid())
    assert "private-runtime-secret" not in json.dumps(grant)
    api.responses[("POST", f"interactive/executions/{execution_id}/tools/request_mission")] = {"mission_id": "m"}
    assert (await service.call("request_mission", tool, peer_pid=os.getpid()))["mission_id"] == "m"
    assert api.calls[-1][2]["execution_token"] == "private-runtime-secret"
    host.live = False
    with pytest.raises(ClientError, match="HOST_STDIO_PEER_REJECTED"):
        await service.call("request_mission", {**tool, "arguments": {"idempotency_key": "different"}}, peer_pid=os.getpid())
    saved = " ".join(str(row) for row in journal.db.execute("SELECT payload,result FROM intents"))
    assert "private-runtime-secret" not in saved
    journal.close()


async def test_unknown_bound_tool_can_only_query_after_restart_or_grant_expiry(config):
    execution_id = str(uuid4())
    journal, api = Journal(config.state_dir / "journal.sqlite3"), FakeApi()
    kind = "tool:" + execution_id + ":request_mission"
    business = {"idempotency_key": "original", "mission_type": "DESIGN_TESTS"}
    journal.intent(kind, "original", {"arguments": business})
    journal.mark(kind, "original", "UNKNOWN")
    service = InteractiveService(config, api, journal, UnsupportedHost())
    # Private execution token has intentionally been lost; no POST may happen.
    await service._execute("request_mission", {"execution_id": execution_id, "arguments": business}, None)
    assert [call[0] for call in api.calls] == ["GET"]
    journal.close()


@pytest.mark.parametrize("reply", [
    ApiError("PLATFORM_UNAVAILABLE", 408),
    {"status": "RUNNING", "result": None, "request_id": "mailbox-request"},
])
async def test_mailbox_read_intent_is_durable_and_only_queries_after_lost_or_pending_reply(config, reply):
    """Read transport identities survive daemon loss without another POST."""
    class Host:
        async def assert_peer(self, pid):
            assert pid == os.getpid()
        async def assert_live(self, proof):
            pass

    execution_id = str(uuid4())
    path = config.state_dir / "journal.sqlite3"
    journal, api = Journal(path), FakeApi()
    post_path = f"interactive/executions/{execution_id}/tools/get_state"
    query_path = f"interactive/executions/{execution_id}/tools/by-key"
    api.responses[("POST", post_path)] = reply
    service = InteractiveService(config, api, journal, Host())
    service._grants[execution_id] = {"token": "private-execution", "proof": {},
                                      "deadline": time.monotonic() + 60}
    args = {"execution_id": execution_id, "arguments": {"resource": "state"}}
    pending = await service._execute("get_state", args, os.getpid())
    key = pending["request_key"]
    assert api.calls[0][2]["request_key"] == key
    assert journal.get("tool:" + execution_id + ":get_state", key)
    journal.close()

    journal = Journal(path)
    service = InteractiveService(config, api, journal, UnsupportedHost())
    api.responses[("GET", query_path)] = {"status": "RUNNING", "result": None}
    assert (await service._execute("get_state", {**args, "request_key": key}, None))["status"] == "RUNNING"
    api.responses[("GET", query_path)] = {"status": "SUCCEEDED", "request_id": "mailbox-request",
                                          "result": {"status": "REJECTED", "reason": "domain decision"}}
    result = await service._execute("get_state", {**args, "request_key": key}, None)
    assert result["status"] == "REJECTED"
    assert result["_transport"] == {"request_key": key, "request_id": "mailbox-request",
                                     "tool_call_id": None, "status": "SUCCEEDED"}
    assert [call[0] for call in api.calls] == ["POST", "GET", "GET"]
    journal.close()


async def test_mailbox_write_cannot_change_business_idempotency_identity(config):
    journal, api = Journal(config.state_dir / "journal.sqlite3"), FakeApi()
    service = InteractiveService(config, api, journal, UnsupportedHost())
    with pytest.raises(ClientError, match="IDEMPOTENCY_CONFLICT"):
        await service._execute("request_execution", {"execution_id": str(uuid4()),
            "request_key": "replacement", "arguments": {"idempotency_key": "original"}}, None)
    assert not api.calls
    journal.close()
