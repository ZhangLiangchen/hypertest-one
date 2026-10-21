"""Session management uses the private MCP channel without execution authority."""
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from hypertest.interactive_client import PROFILE
from hypertest.interactive_client.api_client import ApiError
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.service import InteractiveService


class NoExecutionHost:
    """Any accidental call into the legacy execution host fails the test."""

    async def assert_peer(self, *_args):
        pytest.fail("management sync must not attest an execution host")

    async def attest(self, **_kwargs):
        pytest.fail("management sync must not attest an execution host")


class ManagementApi:
    def __init__(self):
        self.calls = []
        self.fail_post = False
        self.page_changes = {}
        self.task_content = {"task": {"version": 1, "reported_result": "FAIL"},
                             "reports": [{"reported_result": "FAIL", "markdown": "10 PASS, 2 FAIL"}]}
        self.receipt = {"status": "ACCEPTED", "task_id": str(uuid4()), "version": 1,
                        "idempotency_key": "sync-1", "profile": "codex-session-task-sync/v1alpha1",
                        "source": "AGENT_REPORTED"}

    async def capabilities(self):
        from hypertest.api.task_schemas import GET_TASK_SCHEMA, SessionTaskSync

        return {"profile": PROFILE, "tools": [
            {"name": "hypertest_sync_task", "description": "Synchronize management records",
             "inputSchema": SessionTaskSync.model_json_schema()},
            {"name": "hypertest_get_task", "description": "Read task or original sync receipt",
             "inputSchema": GET_TASK_SCHEMA},
        ], "execution_tools": []}

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, deepcopy(kwargs)))
        if method == "POST" and self.fail_post:
            raise ApiError("PLATFORM_UNAVAILABLE")
        if method == "POST":
            for field in ("project_id", "provider", "session_id"):
                self.receipt.setdefault(field, kwargs["payload"][field])
        if path.endswith("by-session"):
            params = kwargs["params"]
            offset, limit = params.get("offset", 0), params.get("limit", 24000)
            serialized = json.dumps(self.task_content, ensure_ascii=False)
            content = serialized[offset:offset + limit]
            end = offset + len(content)
            return {"task_id": self.receipt["task_id"], "version": 1, "format": "application/json",
                    "offset": offset, "total_chars": len(serialized), "content": content,
                    "next_offset": end if end < len(serialized) else None,
                    "complete": end == len(serialized), "source": "AGENT_REPORTED", **self.page_changes}
        if isinstance(self.receipt, Exception):
            raise self.receipt
        return deepcopy(self.receipt)


@pytest.fixture
def management(tmp_path):
    token = tmp_path / "integration-token"
    token.write_text("private-scoped-task-sync-token")
    token.chmod(0o600)
    config = ClientConfig(api_url="https://platform.invalid/api/v1", state_dir=tmp_path / "state",
                          integration_token_file=token)
    config.prepare()
    journal = Journal(config.state_dir / "client.sqlite3")
    api = ManagementApi()
    service = InteractiveService(config, api, journal, NoExecutionHost())
    yield config, api, journal, service
    journal.close()


def payload():
    return {"project_id": str(uuid4()), "provider": "codex", "session_id": "real-session-reference",
            "idempotency_key": "sync-1", "expected_version": 0,
            "title": "Existing SUT test task", "objective": "Save the existing test assets",
            "status": "IN_PROGRESS", "plan_markdown": "Use the project's existing framework.",
            "reported_result": "FAIL", "cases": [{"key": "CASE-001", "title": "Existing case",
                "steps": ["Call the existing test entry"], "expected": "Expected behavior",
                "actual": "Two existing assertions failed", "reported_result": "FAIL"}],
            "reports": [{"key": "automatic", "title": "Existing execution report",
                "markdown": "10 PASS, 2 FAIL", "source_ref": "existing/report.md",
                "reported_result": "FAIL"}]}


async def test_sync_without_device_workspace_or_host_preserves_reported_failure(management):
    config, api, journal, service = management
    args = payload()
    result = await service.call("hypertest_sync_task", args)
    assert result["status"] == "ACCEPTED"
    assert config.device_token_file is None and not config.workspaces
    assert api.calls == [("POST", "interactive/tasks/sync", {"payload": args,
                           "device": False, "execution_token": None, "request_key": None})]
    assert journal.get("session-task:" + args["project_id"], "sync-1")["state"] == "ACKED"
    intent = journal.get("session-task:" + args["project_id"], "sync-1")
    assert set(intent["payload"]) == {"project_id", "idempotency_key", "provider", "session_id", "expected_version"}
    assert "markdown" not in str(intent["payload"])
    assert api.calls[0][2]["payload"]["reports"][0]["reported_result"] == "FAIL"


async def test_sync_replay_queries_receipt_and_conflicting_input_never_reaches_network(management):
    _, api, _, service = management
    args = payload()
    await service.call("hypertest_sync_task", args)
    await service.call("hypertest_sync_task", args)
    assert [call[:2] for call in api.calls] == [
        ("POST", "interactive/tasks/sync"), ("GET", "interactive/tasks/syncs/by-key")]
    with pytest.raises(ClientError, match="IDEMPOTENCY_CONFLICT"):
        await service.call("hypertest_sync_task", {**args, "reported_result": "PASS"})
    assert len(api.calls) == 2


async def test_uncertain_sync_survives_restart_and_not_found_never_reposts(management):
    config, api, journal, service = management
    args = payload()
    api.fail_post = True
    result = await service.call("hypertest_sync_task", args)
    assert result["status"] == "UNKNOWN" and result["query_required"]
    assert args["reported_result"] == "FAIL"
    journal.close()
    restarted = Journal(config.state_dir / "client.sqlite3")
    try:
        api.receipt = {"status": "NOT_FOUND"}
        service = InteractiveService(config, api, restarted, NoExecutionHost())
        result = await service.call("hypertest_sync_task", args)
        assert result["status"] == "UNKNOWN" and result["code"] == "INVALID_SYNC_RECEIPT"
        assert restarted.get("session-task:" + args["project_id"], "sync-1")["state"] == "UNKNOWN"
        assert [call[0] for call in api.calls] == ["POST", "GET"]
        api.receipt = ApiError("PLATFORM_REQUEST_REJECTED", 404)
        result = await service.call("hypertest_sync_task", args)
        assert result["status"] == "UNKNOWN" and result["query_required"]
        assert [call[0] for call in api.calls] == ["POST", "GET", "GET"]
        api.receipt = {"status": "ACCEPTED", "task_id": str(uuid4()), "version": 1, "idempotency_key": "sync-1",
                       "profile": "codex-session-task-sync/v1alpha1", "source": "AGENT_REPORTED",
                       **{field: args[field] for field in ("project_id", "provider", "session_id")}}
        found = await service.call("hypertest_get_task", {
            "project_id": args["project_id"], "idempotency_key": "sync-1"})
        assert found["version"] == 1
        assert restarted.get("session-task:" + args["project_id"], "sync-1")["state"] == "ACKED"
    finally:
        restarted.close()


async def test_get_session_task_reads_only_and_preserves_original_markdown(management):
    _, api, _, service = management
    args = {"project_id": str(uuid4()), "provider": "codex", "session_id": "existing-session"}
    page = await service.call("hypertest_get_task", args)
    found = json.loads(page["content"])
    assert found["task"]["reported_result"] == "FAIL"
    assert found["reports"][0]["markdown"] == "10 PASS, 2 FAIL"
    assert api.calls == [("GET", "interactive/tasks/by-session", {"params": args})]


async def test_task_lookup_rejects_mixed_identity_and_sync_uses_declared_default(management):
    _, api, _, service = management
    args = payload()
    with pytest.raises(ClientError, match="INVALID_TOOL_ARGUMENTS"):
        await service.call("hypertest_get_task", {"project_id": args["project_id"],
            "provider": "codex", "session_id": args["session_id"], "idempotency_key": "sync-1"})
    assert not api.calls
    args.pop("provider")
    await service.call("hypertest_sync_task", args)
    assert api.calls[0][2]["payload"]["provider"] == "codex"


@pytest.mark.parametrize("changes", [
    {"idempotency_key": "another-original-key"}, {"task_id": "not-a-uuid"},
    {"version": True}, {"version": 3}, {"status": "SUCCEEDED"},
    {"profile": "another-contract"}, {"source": "VERIFIED"},
    {"project_id": str(uuid4())}, {"provider": "different-provider"}, {"session_id": "another-session"},
])
async def test_invalid_sync_receipt_never_acknowledges_and_only_queries_afterward(management, changes):
    _, api, journal, service = management
    args = payload()
    api.receipt.update(changes)
    first = await service.call("hypertest_sync_task", args)
    assert first == {"status": "UNKNOWN", "code": "INVALID_SYNC_RECEIPT", "query_required": True}
    assert journal.get("session-task:" + args["project_id"], "sync-1")["state"] == "UNKNOWN"
    again = await service.call("hypertest_sync_task", args)
    assert again["status"] == "UNKNOWN"
    queried = await service.call("hypertest_get_task", {
        "project_id": args["project_id"], "idempotency_key": "sync-1"})
    assert queried["status"] == "UNKNOWN"
    assert [call[0] for call in api.calls] == ["POST", "GET", "GET"]


async def test_fixed_version_pages_reconstruct_original_report_without_history_or_truncation(management):
    _, api, _, service = management
    api.task_content["reports"][0]["markdown"] = "原始失败报告，保留全部内容。" * 30
    identity = {"project_id": str(uuid4()), "provider": "codex", "session_id": "existing-session"}
    chunks, version, offset = [], None, 0
    while True:
        args = {**identity, "offset": offset, "limit": 64}
        if version:
            args["version"] = version
        page = await service.call("hypertest_get_task", args)
        version = page["version"]
        chunks.append(page["content"])
        if page["complete"]:
            break
        offset = page["next_offset"]
    result = json.loads("".join(chunks))
    assert result == api.task_content and len(chunks) > 1
    assert all(call[0] == "GET" for call in api.calls)
    assert all(call[2]["params"]["version"] == 1 for call in api.calls[1:])


@pytest.mark.parametrize("changes", [
    {"version": 2}, {"offset": 1}, {"next_offset": 0},
    {"source": "VERIFIED"}, {"format": "text/plain"}, {"complete": False},
])
async def test_page_metadata_cannot_mix_versions_or_claim_truncated_complete_content(management, changes):
    _, api, _, service = management
    api.page_changes = changes
    with pytest.raises(ClientError, match="INVALID_TASK_PAGE"):
        await service.call("hypertest_get_task", {"project_id": str(uuid4()), "provider": "codex",
            "session_id": "existing-session", "version": 1})


async def test_accepted_receipt_cannot_change_original_task_id(management):
    _, api, journal, service = management
    args = payload()
    original = await service.call("hypertest_sync_task", args)
    api.receipt["task_id"] = str(uuid4())
    for _ in range(2):
        result = await service.call("hypertest_get_task", {
            "project_id": args["project_id"], "idempotency_key": "sync-1"})
        assert result["status"] == "UNKNOWN" and result["code"] == "INVALID_SYNC_RECEIPT"
    assert original["task_id"] != api.receipt["task_id"]
    assert journal.get("session-task:" + args["project_id"], "sync-1")["state"] == "UNKNOWN"


async def test_official_mcp_sdk_exposes_management_tools_without_binding(management):
    from mcp.shared.memory import create_connected_server_and_client_session

    from hypertest.interactive_client.mcp_server import create_server

    _, api, _, service = management

    class LocalBoundary:
        async def exchange(self, operation, data):
            if operation == "list":
                return {"tools": await service.tools()}
            return await service.call(data["name"], data["arguments"])

    async with create_connected_server_and_client_session(create_server(LocalBoundary())) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {"hypertest_sync_task", "hypertest_get_task"}
        result = await client.call_tool("hypertest_sync_task", payload())
        assert result.structuredContent["status"] == "ACCEPTED" and not result.isError
    assert [call[1] for call in api.calls] == ["interactive/tasks/sync"]
