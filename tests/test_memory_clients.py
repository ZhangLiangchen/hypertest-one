"""Optional memory transport failures never become task-sync operations."""
import asyncio
import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.memory import HANDOFF_PROFILE, CloudMemoryBridge, CloudMemoryTransport
from hypertest.interactive_client.api_client import ApiError
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.ipc import LocalServer
from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.memory import PROFILE, MemoryClient
from hypertest.interactive_client.service import InteractiveService


def payload():
    return {"project_id": str(uuid4()), "operation_key": "memory-original", "operation": "CREATE_CANDIDATE",
        "expected_version": 0, "title": "Approved reusable method", "content": "Use the existing API fixture with a bounded timeout.",
        "source": {"mode": "LOCAL", "task_id": str(uuid4()), "task_version": 3, "report_id": str(uuid4())}}


class Gateway:
    def __init__(self, body):
        self.calls = []
        self.lose_ack = False
        self.missing = False
        self.entry = {"id": str(uuid4()), "project_id": body["project_id"], "version": 1,
            "status": "CANDIDATE", "title": body["title"], "content": body["content"],
            "source": {**body["source"], "report_sha256": "a" * 64}}
        self.receipt = {"profile": PROFILE, **{k: body[k] for k in ("project_id", "operation_key", "operation", "expected_version")},
            "status": "ACCEPTED", "entry_id": self.entry["id"], "accepted_version": 1}

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, deepcopy(kwargs)))
        if method == "POST" and self.lose_ack:
            raise ApiError("MEMORY_UNAVAILABLE")
        if path.endswith("by-key") and self.missing:
            raise ApiError("NOT_FOUND", 404)
        return deepcopy(self.entry if path.startswith("memory/entries/") else self.receipt)


async def test_lost_ack_restart_and_not_found_only_original_key_get(tmp_path):
    body = payload()
    gateway = Gateway(body)
    gateway.lose_ack = True
    path = tmp_path / "memory.sqlite3"
    client = MemoryClient(gateway.request, path)
    assert (await client.propose(body))["status"] == "UNKNOWN"
    client.close()
    gateway.lose_ack = False
    gateway.missing = True
    client = MemoryClient(gateway.request, path)
    assert (await client.propose(body))["status"] == "UNKNOWN"
    gateway.missing = False
    result = await client.propose(body)
    assert result["readback_complete"]
    assert [method for method, _, _ in gateway.calls] == ["POST", "GET", "GET", "GET"]
    assert gateway.calls[-1][2]["params"]["version"] == 1
    record = client.journal.get("memory:" + body["project_id"], body["operation_key"])
    assert record["state"] == "READBACK_COMPLETE"
    assert body["content"] not in json.dumps(record) and body["title"] not in json.dumps(record)
    client.close()


async def test_two_clients_one_sent_claim_and_changed_input_conflicts(tmp_path):
    body = payload()
    gateway = Gateway(body)
    first = MemoryClient(gateway.request, tmp_path / "memory.sqlite3")
    second = MemoryClient(gateway.request, tmp_path / "memory.sqlite3")
    results = await asyncio.gather(first.propose(body), second.propose(body))
    assert all(result["readback_complete"] for result in results)
    assert [method for method, _, _ in gateway.calls].count("POST") == 1
    with pytest.raises(ClientError, match="IDEMPOTENCY_CONFLICT"):
        await second.propose({**body, "content": "changed input under same original key"})
    first.close()
    second.close()


async def test_late_failed_recovery_cannot_downgrade_completed_delivery(tmp_path):
    body = payload()
    gateway = Gateway(body)
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed_missing(method, path, **kwargs):
        entered.set()
        await release.wait()
        raise ApiError("NOT_FOUND", 404)
    first = MemoryClient(gateway.request, tmp_path / "memory.sqlite3")
    second = MemoryClient(delayed_missing, tmp_path / "memory.sqlite3")
    late = asyncio.create_task(second.recover(body["project_id"], body["operation_key"]))
    await entered.wait()
    assert (await first.propose(body))["readback_complete"]
    release.set()
    assert (await late)["status"] == "UNKNOWN"
    assert second.journal.get("memory:" + body["project_id"], body["operation_key"])["state"] == "READBACK_COMPLETE"
    first.close()
    second.close()


async def test_storage_failure_before_post_and_fixed_revision_mismatch(tmp_path, monkeypatch):
    body = payload()
    gateway = Gateway(body)
    client = MemoryClient(gateway.request, tmp_path / "memory.sqlite3")
    with monkeypatch.context() as context:
        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("disk full")
        context.setattr(client.journal, "intent", fail)
        result = await client.propose(body)
    assert result["code"] == "MEMORY_STORAGE_UNAVAILABLE" and not gateway.calls
    gateway.entry["version"] = 2
    result = await client.propose(body)
    assert result["status"] == "UNKNOWN" and result["code"] == "MEMORY_READBACK_MISMATCH"
    assert gateway.calls[-1][2]["params"]["version"] == 1
    client.close()


async def test_optional_timeout_is_bounded_and_memory_not_in_task_journal(tmp_path):
    body = payload()
    async def hanging(*args, **kwargs):
        await asyncio.Event().wait()
    client = MemoryClient(hanging, tmp_path / "memory.sqlite3", timeout_seconds=0.01)
    task_journal = Journal(tmp_path / "tasks.sqlite3")
    task_journal.intent("session-task:project", "pending-task", {"version": 4})
    task_journal.mark("session-task:project", "pending-task", "UNKNOWN")
    assert (await client.propose(body))["status"] == "UNKNOWN"
    assert task_journal.get("session-task:project", "pending-task")["state"] == "UNKNOWN"
    assert not task_journal.get("memory:" + body["project_id"], body["operation_key"])
    assert (await client.query({"query": "minimal"}))["status"] == "UNAVAILABLE"
    client.close()
    task_journal.close()


async def test_memory_ipc_does_not_hold_task_transport_lock(tmp_path):
    config = ClientConfig(api_url="https://platform.invalid/api/v1", state_dir=tmp_path / "state",
        integration_token_file=tmp_path / "unused-integration")
    server = LocalServer(config, None)
    async with server._lock:
        async with asyncio.timeout(0.05):
            async with server._request_lock({"operation": "call", "payload": {"name": "hypertest_query_memory"}}):
                pass
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                async with server._request_lock({"operation": "call", "payload": {"name": "hypertest_sync_task"}}):
                    pytest.fail("task synchronization should retain its existing ordering")


async def test_local_memory_requires_opt_in_and_native_parent_before_post(tmp_path):
    body = payload()
    token = tmp_path / "integration"
    token.write_text("existing-private-integration")
    token.chmod(0o600)
    config = ClientConfig(api_url="https://platform.invalid/api/v1", state_dir=tmp_path / "state",
        integration_token_file=token)
    config.prepare()
    gateway = Gateway(body)
    async def capabilities():
        return {"tools": [], "execution_tools": []}
    gateway.capabilities = capabilities
    journal = Journal(config.state_dir / "tasks.sqlite3")
    service = InteractiveService(config, gateway, journal, None)
    assert await service.tools() == []
    config.memory_enabled = True
    assert {item["name"] for item in await service.tools()} == {"hypertest_query_memory", "hypertest_propose_memory", "hypertest_get_memory_operation"}
    arguments = {"project_id": body["project_id"], "provider": "codex", "session_id": "actual-root",
        **{k: body["source"][k] for k in ("task_id", "task_version", "report_id")},
        **{k: body[k] for k in ("operation_key", "title", "content")}}
    with pytest.raises(ClientError, match="LOCAL_COORDINATOR_REQUIRED"):
        await service.call("hypertest_propose_memory", arguments)
    assert not gateway.calls
    class NativeRoot:
        def _require_native_caller(self, identity, context):
            if context != {"session_id": "actual-root"}:
                raise ClientError("NATIVE_CALLER_CONTEXT_MISMATCH")
        async def _target(self, identity, **kwargs):
            return {"task_id": arguments["task_id"]}
    service.coordinator = NativeRoot()
    with pytest.raises(ClientError, match="NATIVE_CALLER_CONTEXT_MISMATCH"):
        await service.call("hypertest_propose_memory", arguments, native_caller_context={"session_id": "child"})
    result = await service.call("hypertest_propose_memory", arguments, native_caller_context={"session_id": "actual-root"})
    assert result["readback_complete"] and not journal.get("memory:" + body["project_id"], body["operation_key"])
    query = {k: arguments[k] for k in ("project_id", "provider", "session_id", "task_id")}
    query["query"] = "Existing fixture behavior"
    await service.call("hypertest_query_memory", query, native_caller_context={"session_id": "actual-root"})
    assert gateway.calls[-1][1] == "memory/query"
    assert gateway.calls[-1][2]["payload"] == {"project_id": body["project_id"], "query": query["query"], "limit": 5}
    with pytest.raises(ClientError, match="NATIVE_CALLER_CONTEXT_MISMATCH"):
        await service.call("hypertest_query_memory", query, native_caller_context={"session_id": "child"})
    service.close_memory()
    journal.close()


def cloud_broker():
    class Broker:
        task_id, attempt_id, project_id = str(uuid4()), str(uuid4()), str(uuid4())
        version = 2
        identity = SimpleNamespace(worker_id="dedicated", lease_token="private-lease", generation=4, work_token="private-work")
        fenced = False
        async def assert_current(self):
            if self.fenced:
                raise CloudBlocked("WORKER_WRITES_SUSPENDED", "fenced")
    return Broker()


async def test_cloud_http_proof_is_private_and_fenced_owner_cannot_query(tmp_path):
    broker = cloud_broker()
    token = tmp_path / "memory-token"
    token.write_text("memory-only-bearer")
    token.chmod(0o600)
    settings = SimpleNamespace(cloud_memory_api_url="https://gateway.invalid/api/v1", cloud_memory_allow_insecure_loopback=False,
        cloud_memory_token_file=token, cloud_memory_ca_file=None, cloud_memory_timeout_seconds=0.1)
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "AVAILABLE", "entries": []})
    transport = CloudMemoryTransport(broker, settings, transport=httpx.MockTransport(handler))
    await transport.request("POST", "memory/query", payload={"project_id": broker.project_id, "query": "minimal"})
    assert calls[0].headers["authorization"] == "Bearer memory-only-bearer"
    assert calls[0].headers["x-hypertest-memory-work-token"] == "private-work"
    assert "private-work" not in calls[0].content.decode() and "private-lease" not in calls[0].content.decode()
    broker.fenced = True
    with pytest.raises(CloudBlocked, match="fenced"):
        await transport.request("POST", "memory/query", payload={"query": "must not send"})
    assert len(calls) == 1
    await transport.close()
    settings.cloud_memory_api_url = "http://remote.invalid/api/v1"
    with pytest.raises(CloudBlocked, match="HTTPS"):
        CloudMemoryTransport(broker, settings)


async def test_cloud_memory_selects_only_private_canonical_project_token(tmp_path):
    directory = tmp_path / "project-grants"
    directory.mkdir(mode=0o700)
    brokers = [cloud_broker(), cloud_broker(), cloud_broker()]
    for index, broker in enumerate(brokers[:2]):
        token = directory / (broker.project_id + ".token")
        token.write_text("project-memory-grant-" + str(index))
        token.chmod(0o600)
    settings = SimpleNamespace(cloud_memory_api_url="https://gateway.invalid/api/v1", cloud_memory_allow_insecure_loopback=False,
        cloud_memory_token_directory=directory, cloud_memory_token_file=tmp_path / "must-not-fallback",
        cloud_memory_ca_file=None, cloud_memory_timeout_seconds=0.1)
    seen = []
    async def handler(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"results": []})
    for broker in brokers[:2]:
        transport = CloudMemoryTransport(broker, settings, transport=httpx.MockTransport(handler))
        await transport.request("POST", "memory/query", payload={"project_id": broker.project_id, "query": "explicit"})
        await transport.close()
    assert seen == ["Bearer project-memory-grant-0", "Bearer project-memory-grant-1"]
    with pytest.raises(CloudBlocked):
        CloudMemoryTransport(brokers[2], settings)
    link = directory / (brokers[2].project_id + ".token")
    link.symlink_to(directory / (brokers[0].project_id + ".token"))
    with pytest.raises(CloudBlocked):
        CloudMemoryTransport(brokers[2], settings)
    link.unlink()
    bad_directory = tmp_path / "aliased-grants"
    bad_directory.symlink_to(directory, target_is_directory=True)
    settings.cloud_memory_token_directory = bad_directory
    with pytest.raises(CloudBlocked):
        CloudMemoryTransport(brokers[0], settings)
    settings.cloud_memory_token_directory = directory
    directory.chmod(0o755)
    with pytest.raises(CloudBlocked):
        CloudMemoryTransport(brokers[0], settings)
    assert len(seen) == 2


async def test_cloud_explicit_candidate_unknown_keeps_original_key_and_source(tmp_path):
    broker = cloud_broker()
    body = payload()
    source = {"mode": "CLOUD", "task_id": broker.task_id, "attempt_id": broker.attempt_id,
        "task_version": 7, "asset_revision_id": str(uuid4())}
    body.update(project_id=broker.project_id, source=source)
    from hypertest.sync_core import digest
    body["operation_key"] = "m:" + digest([broker.attempt_id, "approved"])
    gateway = Gateway(body)
    gateway.lose_ack = True
    async def close():
        pass
    gateway.close = close
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bridge = CloudMemoryBridge(broker, gateway, tmp_path / "private", workspace)
    document = {"profile": HANDOFF_PROFILE, "task_id": broker.task_id, "attempt_id": broker.attempt_id,
        "key": "approved", "operation": "CREATE_CANDIDATE", "payload": {"task_version": 7,
            "asset_revision_id": source["asset_revision_id"], "title": body["title"], "content": body["content"]}}
    ready = workspace / ".hypertest-cloud" / "memory-ready"
    ready.mkdir(parents=True)
    (ready / "approved.json").write_text(json.dumps(document))
    await bridge.collect_once()
    response = json.loads((workspace / ".hypertest-cloud" / "memory-responses" / "approved.json").read_text())
    assert response["status"] == "UNKNOWN" and response["operation_key"] == body["operation_key"]
    await bridge.collect_once()
    assert len(gateway.calls) == 1
    gateway.lose_ack = False
    recovery = {**document, "key": "recover", "operation": "GET_OPERATION", "payload": {"operation_key": body["operation_key"]}}
    result = await bridge.handle(recovery, "recover")
    assert result["readback_complete"]
    assert gateway.calls[0][2]["payload"]["source"] == source
    assert all("work_token" not in json.dumps(call[2]) for call in gateway.calls)
    wrong_parent = {**document, "task_id": str(uuid4())}
    with pytest.raises(CloudBlocked, match="parent"):
        await bridge.handle(wrong_parent, "approved")
    await bridge.close()


async def test_cloud_query_before_reports_uses_host_fixed_claim_context(tmp_path):
    broker = cloud_broker()
    gateway = Gateway(payload())
    async def close():
        pass
    gateway.close = close
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bridge = CloudMemoryBridge(broker, gateway, tmp_path / "private", workspace)
    document = {"profile": HANDOFF_PROFILE, "task_id": broker.task_id, "attempt_id": broker.attempt_id,
        "key": "query", "operation": "QUERY", "payload": {"query": "Existing project fixture method"}}
    # A later report version cannot change this original dispatch context.
    broker.version = 9
    await bridge.handle(document, "query")
    body = gateway.calls[-1][2]["payload"]
    assert body["context"] == {"task_id": broker.task_id, "attempt_id": broker.attempt_id, "task_version": 2}
    assert "source" not in body and "asset_revision_id" not in json.dumps(body)
    assert not list((tmp_path / "private").glob("*report*"))
    with pytest.raises(CloudBlocked):
        await bridge.handle({**document, "payload": {"query": "override context", "task_version": 9}}, "query")
    candidate = {**document, "operation": "CREATE_CANDIDATE", "payload": {"title": "Missing source", "content": "Still requires fixed accepted asset"}}
    with pytest.raises(CloudBlocked):
        await bridge.handle(candidate, "query")
    await bridge.close()
