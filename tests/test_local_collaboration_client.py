"""Collaboration transport fixtures; these do not assert real native host E2E."""
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from test_local_sync import configure_artifact_source, full
from test_local_sync import local as local
from test_session_task_mcp import NoExecutionHost

from hypertest.api.interactive_routes import capabilities
from hypertest.api.task_collaboration_schemas import CollaborationMemberOperation
from hypertest.interactive_client.api_client import ApiError
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.mcp_server import create_server
from hypertest.interactive_client.service import InteractiveService
from hypertest.local_sync.collaboration import PROFILE, namespace
from hypertest.local_sync.coordinator import LocalSyncCoordinator
from hypertest.local_sync.hooks import handle_hook
from hypertest.local_sync.sources import source_binding
from hypertest.sync_core import FrozenIntent, digest
from hypertest.sync_core.storage import JournalLedger


class CollaborationTransport:
    def __init__(self, identity):
        self.identity = identity
        self.actor = "interactive:" + str(uuid4())
        self.participant_id = str(uuid4())
        self.calls, self.receipts = [], {}
        self.lose_response = self.hide_receipt = self.fail_readback = False
        self.receipt_changes = {}
        self.document_changes = None
        self.documents = {4: {"profile": PROFILE, "task": {
            "id": identity["task_id"], "project_id": identity["project_id"], "version": 4,
            "provider": "codex", "session_id": "original-root", "collaboration_enabled": True,
            "title": "Shared task", "objective": "", "status": "IN_PROGRESS",
            "plan_markdown": "Original overall plan", "reported_result": "FAIL"},
            "collaboration": {"enabled": True, "primary_participant_id": self.participant_id,
                "primary_generation": 1, "participants": [{
                    "id": self.participant_id, "actor_ref": self.actor, "provider": "codex",
                    "session_id": identity["session_id"], "status": "AUTHORIZED", "role": "PRIMARY"}],
                "contributions": [], "publications": []}, "operation_history": []}}

    async def capabilities(self):
        return await capabilities()

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, deepcopy(kwargs)))
        selected_path = "interactive/tasks/" + self.identity["task_id"] + "/collaboration"
        if method == "POST":
            assert path == selected_path, "collaboration may never call full sync"
            payload = CollaborationMemberOperation.model_validate(kwargs["payload"]).model_dump(mode="json")
            current_version = max(self.documents)
            if payload["expected_version"] != current_version:
                raise ApiError("VERSION_CONFLICT", 409)
            version = current_version + 1
            document = deepcopy(self.documents[current_version])
            document["task"]["version"] = version
            document["collaboration"]["participants"][0]["status"] = "ACTIVE"
            refs = []
            for item in payload.get("contributions") or []:
                accepted = {"id": str(uuid4()), "participant_id": self.participant_id,
                    "kind": item["kind"], "stable_key": item["stable_key"], "content": item["content"],
                    "revision": item["expected_revision"] + 1, "task_version": version}
                document["collaboration"]["contributions"].append(accepted)
                refs.append({"contribution_id": accepted["id"], "revision": accepted["revision"]})
            if payload["operation"] == "PUBLISH":
                document["task"].update({key: payload["summary"][key] for key in (
                    "title", "objective", "status", "plan_markdown", "reported_result")})
                document["collaboration"]["publications"].append({
                    "id": str(uuid4()), "participant_id": self.participant_id,
                    "task_version": version, "primary_generation": payload["primary_generation"],
                    "summary": payload["summary"]})
            receipt = {"profile": PROFILE, "status": "ACCEPTED", "operation": payload["operation"],
                "idempotency_key": payload["idempotency_key"], "task_id": self.identity["task_id"],
                **{key: payload[key] for key in ("project_id", "provider", "session_id")},
                "actor_ref": self.actor, "participant_id": self.participant_id, "version": version,
                "request_digest": digest(payload), "primary_generation": 1, "contribution_refs": refs}
            document["operation_history"].append({"request_payload": payload, "response": receipt})
            self.documents[version] = document
            self.receipts[payload["idempotency_key"]] = receipt
            if self.lose_response:
                raise ApiError("LOST_COLLABORATION_RESPONSE")
            return {**deepcopy(receipt), **self.receipt_changes}
        params = kwargs["params"]
        if path.endswith("/receipts/by-key"):
            if self.hide_receipt or params["idempotency_key"] not in self.receipts:
                raise ApiError("NOT_FOUND", 404)
            return {**deepcopy(self.receipts[params["idempotency_key"]]), **self.receipt_changes}
        if path != selected_path:
            raise ApiError("COLLABORATION_PROFILE_REQUIRED", 409)
        if self.fail_readback:
            raise ApiError("MISSING_PAGE")
        version = params.get("version", max(self.documents))
        document = deepcopy(self.documents[version])
        if self.document_changes:
            self.document_changes(document)
        content = json.dumps(document, ensure_ascii=False)
        offset = params.get("offset", 0)
        part = content[offset:offset + 251]
        end = offset + len(part)
        return {"task_id": self.identity["task_id"], "version": version,
            "profile": PROFILE, "format": "application/json", "content": part,
            "offset": offset, "total_chars": len(content), "complete": end == len(content),
            "next_offset": None if end == len(content) else end}


@pytest.fixture
def collaboration(local):
    config, _, journal, _, identity = local
    identity = {**identity, "task_id": str(uuid4())}
    event = configure_artifact_source(config, identity)
    source_binding(config, event, create=True)
    api = CollaborationTransport(identity)
    coordinator = LocalSyncCoordinator(config, api, journal)
    return config, api, journal, coordinator, identity, event


def caller(identity):
    return {"provider": "codex", "session_id": identity["session_id"], "transport": "codex-mcp-thread-id/v1"}


def request(identity, operation="JOIN", **changes):
    extras = {}
    if operation == "CONTRIBUTE":
        extras = {"contributions": [{"kind": "REPORT", "stable_key": "same-name", "expected_revision": 0,
            "content": {"title": "Original failure", "markdown": "失败报告\n", "reported_result": "FAIL"}}]}
    if operation == "PUBLISH":
        extras = {"primary_generation": 1, "summary": {"title": "Shared task", "objective": "",
            "status": "COMPLETED", "plan_markdown": "Consolidated plan", "reported_result": "FAIL",
            "contribution_refs": [], "completion_basis": "All scoped checks reported; failure retained",
            "unresolved_items": ["Known defect"]}}
    return {**identity, "expected_version": 4, "idempotency_key": operation.lower() + "-original", **extras, **changes}


async def accepted_join(fixture):
    _, _, _, coordinator, identity, _ = fixture
    result = await coordinator.submit_collaboration(request(identity), operation="JOIN", native_caller_context=caller(identity))
    assert result["_sync"]["readback_complete"] is True
    return result


async def test_join_contribute_publish_pin_exact_versions_and_keep_original_failure(collaboration):
    _, api, journal, coordinator, identity, _ = collaboration
    await accepted_join(collaboration)
    contribution = await coordinator.submit_collaboration(request(identity, "CONTRIBUTE", expected_version=5),
        operation="CONTRIBUTE", native_caller_context=caller(identity))
    assert contribution["_sync"]["readback_complete"]
    ref = {**contribution["contribution_refs"][0], "disposition": "DIVERGENCE"}
    publication = request(identity, "PUBLISH", expected_version=6)
    publication["summary"]["contribution_refs"] = [ref]
    published = await coordinator.submit_collaboration(publication, operation="PUBLISH", native_caller_context=caller(identity))
    assert published["_sync"]["readback_complete"]
    assert api.documents[7]["task"]["reported_result"] == "FAIL"
    assert api.documents[6]["task"]["plan_markdown"] == "Original overall plan"
    assert api.documents[7]["collaboration"]["contributions"][0]["content"]["markdown"] == "失败报告\n"
    assert [item[2]["payload"]["operation"] for item in api.calls if item[0] == "POST"] == ["JOIN", "CONTRIBUTE", "PUBLISH"]
    for version in (5, 6, 7):
        pages = [item for item in api.calls if item[0] == "GET" and item[2]["params"].get("version") == version]
        assert len(pages) > 1
    assert {row[0] for row in journal.db.execute("SELECT state FROM intents")} == {"READBACK_COMPLETE"}


@pytest.mark.parametrize("operation", ["JOIN", "CONTRIBUTE", "PUBLISH"])
@pytest.mark.parametrize("bad_caller", [None, {"provider": "codex", "session_id": "actual-child", "transport": "codex-mcp-thread-id/v1"}])
async def test_new_writes_reject_missing_or_child_caller_before_files_journal_or_network(collaboration, operation, bad_caller):
    _, api, journal, coordinator, identity, _ = collaboration
    with pytest.raises(ClientError, match="NATIVE_CALLER_CONTEXT"):
        await coordinator.submit_collaboration(request(identity, operation), operation=operation, native_caller_context=bad_caller)
    assert api.calls == [] and journal.db.execute("SELECT count(*) FROM intents").fetchone()[0] == 0
    assert list(coordinator.snapshots.directory.glob("*.json")) == []


@pytest.mark.parametrize("host,provider", [("claude-code", "claude_code"), ("deepseek-harness", "deepseek_harness")])
async def test_unsupported_host_rejects_new_collaboration_but_original_key_get_is_read_only(collaboration, host, provider):
    config, api, _, coordinator, identity, _ = collaboration
    config.local_sync["host"] = host
    foreign = {**identity, "provider": provider}
    with pytest.raises(ClientError, match="NATIVE_CALLER_CONTEXT_UNSUPPORTED"):
        await coordinator.submit_collaboration(request(foreign), operation="JOIN", native_caller_context=caller(identity))
    assert api.calls == []
    unknown = await coordinator.get_collaboration({**foreign, "idempotency_key": "never-sent"})
    assert unknown["status"] == "UNKNOWN" and [item[0] for item in api.calls] == ["GET"]


async def test_lost_join_restart_not_found_blocks_new_key_and_never_reposts(collaboration):
    config, api, _, coordinator, identity, _ = collaboration
    api.lose_response = True
    first = await coordinator.submit_collaboration(request(identity), operation="JOIN", native_caller_context=caller(identity))
    assert first["status"] == "UNKNOWN"
    api.hide_receipt = True
    reopened = Journal(config.state_dir / "client.sqlite3")
    try:
        restarted = LocalSyncCoordinator(config, api, reopened)
        query = await restarted.get_collaboration({**identity, "idempotency_key": "join-original"})
        assert query["status"] == "UNKNOWN"
        blocked = await restarted.submit_collaboration(request(identity, "CONTRIBUTE", expected_version=5),
            operation="CONTRIBUTE", native_caller_context=caller(identity))
        assert blocked["status"] == "UNKNOWN" and blocked["idempotency_key"] == "join-original"
        assert [item[0] for item in api.calls] == ["POST", "GET", "GET"]
        api.hide_receipt = False
        recovered = await restarted.get_collaboration({**identity, "idempotency_key": "join-original"})
        assert recovered["_sync"]["readback_complete"]
        assert sum(item[0] == "POST" for item in api.calls) == 1
    finally:
        reopened.close()


@pytest.mark.parametrize("change", [{"session_id": "other-root"}, {"task_id": str(uuid4())}, {"expected_version": 5}])
async def test_original_key_cannot_change_root_target_or_payload(collaboration, change):
    _, api, _, coordinator, identity, _ = collaboration
    api.lose_response = True
    await coordinator.submit_collaboration(request(identity), operation="JOIN", native_caller_context=caller(identity))
    before = len(api.calls)
    with pytest.raises(ClientError, match="IDEMPOTENCY_CONFLICT"):
        await coordinator.submit_collaboration({**request(identity), **change}, operation="JOIN", native_caller_context=caller(identity))
    assert len(api.calls) == before


@pytest.mark.parametrize("change", [{"version": 99}, {"participant_id": str(uuid4())}, {"request_digest": "a" * 64}, {"session_id": "child"}])
async def test_invalid_receipt_stays_unknown_without_reposting(collaboration, change):
    _, api, _, coordinator, identity, _ = collaboration
    api.receipt_changes = change
    first = await coordinator.submit_collaboration(request(identity), operation="JOIN", native_caller_context=caller(identity))
    assert first["status"] in {"UNKNOWN", "ACCEPTED"}
    assert not first.get("_sync", {}).get("readback_complete")
    await coordinator.get_collaboration({**identity, "idempotency_key": "join-original"})
    assert sum(item[0] == "POST" for item in api.calls) == 1


async def test_ack_with_changed_raw_contribution_cannot_confirm_and_only_reads_fixed_version(collaboration):
    _, api, _, coordinator, identity, _ = collaboration
    await accepted_join(collaboration)
    api.document_changes = lambda doc: doc["collaboration"]["contributions"][0]["content"].update(markdown="Changed bytes")
    first = await coordinator.submit_collaboration(request(identity, "CONTRIBUTE", expected_version=5),
        operation="CONTRIBUTE", native_caller_context=caller(identity))
    assert first["status"] == "ACCEPTED" and first["_sync"]["readback_complete"] is False
    queried = await coordinator.get_collaboration({**identity, "idempotency_key": "contribute-original"})
    assert queried["_sync"]["readback_complete"] is False
    assert sum(item[0] == "POST" for item in api.calls) == 2


async def test_prepared_intent_requires_current_caller_and_get_never_sends(collaboration):
    _, api, journal, coordinator, identity, _ = collaboration
    payload = CollaborationMemberOperation.model_validate({key: value for key, value in request(identity).items()
        if key != "task_id"} | {"operation": "JOIN"}).model_dump(mode="json") | {"task_id": identity["task_id"]}
    frozen = FrozenIntent(namespace(payload), payload["idempotency_key"], identity, payload, 4)
    coordinator.snapshots.save(frozen)
    JournalLedger(journal).prepare(frozen)
    with pytest.raises(ClientError, match="NATIVE_CALLER_CONTEXT_REQUIRED"):
        await coordinator.submit_collaboration(request(identity), operation="JOIN")
    assert api.calls == []
    result = await coordinator.get_collaboration({**identity, "idempotency_key": "join-original"})
    assert result["status"] == "UNKNOWN" and [item[0] for item in api.calls] == ["GET"]


async def test_hook_never_promotes_a_prepared_explicit_publication(collaboration):
    config, api, journal, coordinator, identity, event = collaboration
    await accepted_join(collaboration)
    publication = request(identity, "PUBLISH", expected_version=5)
    payload = CollaborationMemberOperation.model_validate({key: value for key, value in publication.items()
        if key != "task_id"} | {"operation": "PUBLISH"}).model_dump(mode="json") | {"task_id": identity["task_id"]}
    frozen = FrozenIntent(namespace(payload), payload["idempotency_key"], identity, payload, 5)
    coordinator.snapshots.save(frozen)
    JournalLedger(journal).prepare(frozen)
    (source_binding(config, event)[2] / "analysis.md").write_text("Independent new plan")
    result = await handle_hook(config, coordinator, {"event": {
        **event, "hook_event_name": "PostToolUse", "tool_name": "write_file"}})
    assert result["status"] == "BLOCKED" and result["code"] == "ORIGINAL_REQUEST_NOT_SENT"
    assert journal.get(frozen.namespace, frozen.key)["state"] == "PENDING"
    assert [item[2]["payload"]["operation"] for item in api.calls if item[0] == "POST"] == ["JOIN"]


async def test_hooks_contribute_approved_root_files_without_publishing_or_changing_result(collaboration):
    config, api, _, coordinator, identity, event = collaboration
    await accepted_join(collaboration)
    directory = source_binding(config, event)[2]
    (directory / "analysis.md").write_text("Member's parallel plan\n")
    post = {**event, "hook_event_name": "PostToolUse", "tool_name": "write_file"}
    result = await handle_hook(config, coordinator, {"event": post})
    assert result["_sync"]["readback_complete"]
    assert api.documents[6]["task"]["plan_markdown"] == "Original overall plan"
    assert api.documents[6]["task"]["reported_result"] == "FAIL"
    assert api.documents[6]["collaboration"]["contributions"][0]["content"] == {"markdown": "Member's parallel plan\n"}
    unchanged = await handle_hook(config, coordinator, {"event": post})
    assert unchanged["status"] == "UNCHANGED"
    with pytest.raises(ClientError, match="COLLABORATION_PROFILE_REQUIRED"):
        await coordinator.submit_full({**full(identity), "expected_version": 6}, native_caller_context=caller(identity))
    assert [item[2]["payload"]["operation"] for item in api.calls if item[0] == "POST"] == ["JOIN", "CONTRIBUTE"]


@pytest.mark.parametrize("operation", ["JOIN", "CONTRIBUTE", "PUBLISH"])
async def test_mcp_host_metadata_fences_child_and_passes_parent_context(collaboration, operation):
    from mcp.shared.memory import create_connected_server_and_client_session

    config, api, journal, _, identity, _ = collaboration
    service = InteractiveService(config, api, journal, NoExecutionHost())

    class DaemonClient:
        async def exchange(self, kind, payload):
            if kind == "list":
                return {"tools": await service.tools()}
            return await service.call(payload["name"], payload["arguments"],
                native_caller_context=payload.get("native_caller_context"))

    name = {"JOIN": "hypertest_join_task", "CONTRIBUTE": "hypertest_contribute_task", "PUBLISH": "hypertest_publish_task"}[operation]
    async with create_connected_server_and_client_session(create_server(DaemonClient(), local_host="codex")) as client:
        rejected = await client.call_tool(name, request(identity, operation), meta={"threadId": "real-child"})
        assert rejected.isError and rejected.content[0].text == "NATIVE_CALLER_CONTEXT_MISMATCH"
        assert api.calls == []
        accepted = await client.call_tool(name, request(identity, operation), meta={"threadId": identity["session_id"]})
        assert not accepted.isError and accepted.structuredContent["_sync"]["readback_complete"]


@pytest.mark.parametrize("operation", ["JOIN", "CONTRIBUTE", "PUBLISH"])
@pytest.mark.parametrize("spoof", ["missing-meta", "argument-meta", "argument-context", "forged-source"])
async def test_new_mcp_tools_cannot_inject_native_caller_through_arguments(collaboration, operation, spoof):
    from mcp.shared.memory import create_connected_server_and_client_session

    config, api, journal, _, identity, _ = collaboration
    service = InteractiveService(config, api, journal, NoExecutionHost())

    class DaemonClient:
        async def exchange(self, kind, payload):
            if kind == "list":
                return {"tools": await service.tools()}
            return await service.call(payload["name"], payload["arguments"],
                native_caller_context=payload.get("native_caller_context"))

    arguments = request(identity, operation)
    meta = {"threadId": identity["session_id"]}
    if spoof == "missing-meta":
        meta = None
    elif spoof == "argument-meta":
        arguments["_meta"] = meta
        meta = {"threadId": "actual-child"}
    elif spoof == "argument-context":
        arguments["native_caller_context"] = caller(identity)
        meta = {"threadId": "actual-child"}
    else:
        arguments["session_id"] = "arbitrary-root-reference"
    name = {"JOIN": "hypertest_join_task", "CONTRIBUTE": "hypertest_contribute_task", "PUBLISH": "hypertest_publish_task"}[operation]
    async with create_connected_server_and_client_session(create_server(DaemonClient(), local_host="codex")) as client:
        result = await client.call_tool(name, arguments, meta=meta)
        assert result.isError
    assert api.calls == []
    assert journal.db.execute("SELECT count(*) FROM intents").fetchone()[0] == 0


@pytest.mark.parametrize("arguments", [
    {"idempotency_key": "key", "version": 5}, {"offset": 1}, {"task_id": "../invalid-path"},
])
async def test_collaboration_get_rejects_mixed_selectors_and_unfixed_pages_before_network(collaboration, arguments):
    config, api, journal, _, identity, _ = collaboration
    service = InteractiveService(config, api, journal, NoExecutionHost())
    with pytest.raises(ClientError, match="INVALID_TOOL_ARGUMENTS"):
        await service.call("hypertest_get_task_collaboration", {**identity, **arguments})
    assert api.calls == []
