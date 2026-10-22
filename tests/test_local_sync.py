"""Local coordinator invariants against a versioned management transport."""
import asyncio
import json
import stat
from copy import deepcopy
from uuid import uuid4

import pytest

from hypertest.api.task_schemas import SessionTaskSync
from hypertest.interactive_client.api_client import ApiError
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.journal import Journal
from hypertest.local_sync.coordinator import LocalSyncCoordinator
from hypertest.local_sync.hosts import parse_trigger


class VersionedApi:
    def __init__(self):
        self.calls = []
        self.documents = {}
        self.receipts = {}
        self.task_id = str(uuid4())
        self.lose_post = False
        self.hide_receipt = False
        self.readback_fails = False

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, deepcopy(kwargs)))
        await asyncio.sleep(0)
        if method == "POST":
            payload = SessionTaskSync.model_validate(kwargs["payload"]).model_dump(mode="json")
            expected = len(self.documents)
            if payload["expected_version"] != expected:
                raise ApiError("VERSION_CONFLICT", 409)
            version = expected + 1
            baseline = deepcopy(self.documents.get(expected, {"cases": [], "reports": []}))
            baseline["task"] = {key: value for key, value in payload.items()
                                if key not in {"cases", "reports", "idempotency_key", "expected_version"}}
            baseline["task"].update(id=self.task_id, version=version, source="AGENT_REPORTED")
            for group in ("cases", "reports"):
                items = {item["key"]: item for item in baseline[group]}
                items.update({item["key"]: item for item in payload[group]})
                baseline[group] = list(items.values())
            self.documents[version] = baseline
            receipt = {"status": "ACCEPTED", "task_id": self.task_id, "version": version,
                "profile": "codex-session-task-sync/v1alpha1", "source": "AGENT_REPORTED",
                "idempotency_key": payload["idempotency_key"],
                **{field: payload[field] for field in ("project_id", "provider", "session_id")}}
            self.receipts[payload["idempotency_key"]] = receipt
            if self.lose_post:
                raise ApiError("LOST_POST_RESPONSE")
            return deepcopy(receipt)
        params = kwargs["params"]
        if path.endswith("by-key"):
            if self.hide_receipt:
                raise ApiError("NOT_FOUND", 404)
            return deepcopy(self.receipts[params["idempotency_key"]])
        if self.readback_fails:
            raise ApiError("MISSING_PAGE")
        if not self.documents:
            raise ApiError("NOT_FOUND", 404)
        selected = params.get("version", len(self.documents))
        document = self.documents[selected]
        content = json.dumps(document, ensure_ascii=False)
        # Small independent slices ensure that the coordinator must pin all
        # continuation pages rather than accidentally relying on one page.
        offset = params.get("offset", 0)
        part = content[offset:offset + 73]
        end = offset + len(part)
        return {"task_id": self.task_id, "version": selected, "content": part,
                "format": "application/json", "source": "AGENT_REPORTED",
                "total_chars": len(content), "offset": offset,
                "next_offset": end if end < len(content) else None, "complete": end == len(content)}


@pytest.fixture
def local(tmp_path):
    token = tmp_path / "token"
    token.write_text("private-token")
    token.chmod(0o600)
    config = ClientConfig(api_url="https://platform.invalid/api/v1", state_dir=tmp_path / "state",
                          integration_token_file=token, local_sync={"enabled": True})
    config.prepare()
    journal = Journal(config.state_dir / "client.sqlite3")
    api = VersionedApi()
    coordinator = LocalSyncCoordinator(config, api, journal)
    identity = {"project_id": str(uuid4()), "provider": "codex", "session_id": "real-parent"}
    yield config, api, journal, coordinator, identity
    journal.close()


def full(identity):
    return {**identity, "idempotency_key": "explicit-first", "expected_version": 0,
            "title": "Test existing framework", "objective": "Original objective",
            "status": "IN_PROGRESS", "plan_markdown": "Original plan",
            "reported_result": "FAIL", "cases": [], "reports": [{"key": "run-one",
                "title": "Actual failed run", "markdown": "Original complete failure report",
                "reported_result": "FAIL"}]}


async def test_partial_status_preserves_plan_failure_original_report_and_duplicate_checkpoint(local):
    _, api, journal, coordinator, identity = local
    assert (await coordinator.submit_full(full(identity)))["_sync"]["readback_complete"]
    updated = await coordinator.submit_partial(identity, {"status": "BLOCKED"},
                                               base_version=1, checkpoint_digest="checkpoint-one")
    assert updated["version"] == 2 and updated["_sync"]["readback_complete"]
    current = api.documents[2]
    assert current["task"]["plan_markdown"] == "Original plan"
    assert current["task"]["reported_result"] == "FAIL"
    assert current["reports"][0]["markdown"] == "Original complete failure report"
    before = len(api.calls)
    duplicate = await coordinator.submit_partial(identity, {"status": "BLOCKED"},
                                                base_version=1, checkpoint_digest="checkpoint-one")
    assert duplicate["status"] == "UNCHANGED" and len(api.calls) == before
    rows = journal.db.execute("SELECT payload,state FROM intents").fetchall()
    assert all("Original plan" not in row[0] and "failure report" not in row[0] for row in rows)
    assert all(row[1] == "READBACK_COMPLETE" for row in rows)
    pages = [call[2]["params"] for call in api.calls if call[1].endswith("by-session")]
    assert all("version" in page for page in pages if page.get("offset", 0))


async def test_explicit_complete_empty_values_and_new_key_noop_still_create_versions(local):
    _, api, _, coordinator, identity = local
    original = full(identity)
    await coordinator.submit_full(original)
    empty = {**original, "idempotency_key": "explicit-empty", "expected_version": 1,
             "plan_markdown": "", "objective": ""}
    await coordinator.submit_full(empty)
    assert api.documents[2]["task"]["plan_markdown"] == ""
    await coordinator.submit_full({**empty, "idempotency_key": "explicit-noop", "expected_version": 2})
    assert len(api.documents) == 3


async def test_lost_send_blocks_new_key_not_found_never_reposts_after_restart(local):
    config, api, journal, coordinator, identity = local
    api.lose_post = True
    first = await coordinator.submit_full(full(identity))
    assert first["status"] == "UNKNOWN"
    api.hide_receipt = True
    restarted = LocalSyncCoordinator(config, api, journal)
    second = await restarted.submit_partial(identity, {"status": "BLOCKED"},
                                           base_version=1, checkpoint_digest="later")
    assert second["status"] == "UNKNOWN"
    third = await restarted.submit_full({**full(identity), "idempotency_key": "do-not-bypass"})
    assert third["status"] == "UNKNOWN"
    assert [call[0] for call in api.calls] == ["POST", "GET", "GET"]


async def test_accepted_readback_failure_never_reposts_and_clear_is_explicit(local):
    _, api, _, coordinator, identity = local
    api.readback_fails = True
    first = await coordinator.submit_full(full(identity))
    assert first["status"] == "ACCEPTED" and not first["_sync"]["readback_complete"]
    api.readback_fails = False
    await coordinator.submit_partial(identity, {}, clear_fields=["plan_markdown"],
                                     base_version=1, checkpoint_digest="explicit-clear")
    assert api.documents[2]["task"]["plan_markdown"] == ""
    assert api.documents[2]["task"]["reported_result"] == "FAIL"
    assert len([call for call in api.calls if call[0] == "POST"]) == 2


async def test_source_lock_rejects_cross_project_and_serializes_two_new_partial_intents(local):
    _, api, _, coordinator, identity = local
    await coordinator.submit_full(full(identity))
    results = await asyncio.gather(
        coordinator.submit_partial(identity, {"status": "BLOCKED"}, base_version=1, checkpoint_digest="A"),
        coordinator.submit_partial(identity, {"objective": "later"}, base_version=1, checkpoint_digest="B"),
        return_exceptions=True)
    assert len(api.documents) == 2
    assert len([value for value in results if isinstance(value, ClientError)]) == 1
    with pytest.raises(ClientError, match="LOCAL_SOURCE_PROJECT_CONFLICT"):
        await coordinator.submit_full({**full(identity), "project_id": str(uuid4())})


def test_native_source_mapping_and_deepseek_child_bridge_are_separate():
    event = {"session_id": "parent", "hook_event_name": "SubagentStop", "agent_id": "child"}
    assert parse_trigger("codex", event, selected_parent="parent").provider == "codex"
    assert parse_trigger("claude-code", event, selected_parent="parent").provider == "claude_code"
    with pytest.raises(ClientError, match="LOCAL_EVENT_UNSUPPORTED"):
        parse_trigger("deepseek-harness", event, selected_parent="parent", bridge="claude-code")
    with pytest.raises(ClientError, match="REAL_PARENT_SESSION_REQUIRED"):
        parse_trigger("codex", {**event, "session_id": "child"}, selected_parent="parent")
    assert parse_trigger("claude-code", {**event, "tool_name": "mcp__hypertest__hypertest_sync_task"},
                         selected_parent="parent") is None


def configure_artifact_source(config, identity):
    workspace = config.state_dir.parent / "workspace"
    workspace.mkdir()
    config.local_sync.update(host="codex", harness_version="0.144.6", hooks_enabled=True,
        project_id=identity["project_id"], artifact_source={"workspace": str(workspace),
        "initial": {"title": "Approved local analysis", "objective": "Analyze the fixture",
                    "status": "IN_PROGRESS", "plan_markdown": "", "reported_result": "NOT_RUN"},
        "artifacts": [{"kind": "TEST_PLAN", "path": "analysis.md"}]})
    return {"session_id": identity["session_id"], "hook_event_name": "SessionStart", "cwd": str(workspace)}


async def test_native_start_binds_two_real_sources_without_post_or_shared_manifest(local):
    from hypertest.local_sync.hooks import handle_hook
    from hypertest.local_sync.sources import source_binding

    config, api, _, coordinator, identity = local
    event = configure_artifact_source(config, identity)
    first = await handle_hook(config, coordinator, {"event": event})
    second_event = {**event, "session_id": "another-native-parent"}
    second = await handle_hook(config, coordinator, {"event": second_event})
    assert first["status"] == second["status"] == "BOUND" and not api.calls
    assert source_binding(config, event)[2] != source_binding(config, second_event)[2]
    with pytest.raises(ClientError, match="NATIVE_SESSION_START_REQUIRED"):
        await handle_hook(config, coordinator, {"event": {**event, "session_id": "never-started",
                                                    "hook_event_name": "PostToolUse"}})
    with pytest.raises(ClientError, match="LOCAL_SOURCE_WORKSPACE_MISMATCH"):
        await handle_hook(config, coordinator, {"event": {**event, "cwd": "/another/workspace"}})


async def test_native_file_events_hash_without_manifest_and_preserve_reported_failure(local):
    from hypertest.local_sync.hooks import handle_hook
    from hypertest.local_sync.sources import source_binding

    config, api, _, coordinator, identity = local
    event = configure_artifact_source(config, identity)
    await handle_hook(config, coordinator, {"event": event})
    post = {**event, "hook_event_name": "PostToolUse", "tool_name": "write_file"}
    empty = await handle_hook(config, coordinator, {"event": post})
    assert empty["code"] == "NO_APPROVED_ARTIFACTS" and not api.calls
    _, _, directory = source_binding(config, event)
    artifact = directory / "analysis.md"
    artifact.write_text("Formal approved analysis A")
    accepted = await handle_hook(config, coordinator, {"event": post})
    assert accepted["_sync"]["readback_complete"] and api.documents[1]["task"]["plan_markdown"].endswith("A")
    failed = full(identity)
    failed.update(expected_version=1, idempotency_key="explicit-failure")
    await coordinator.submit_full(failed)
    artifact.write_text("Formal approved analysis B")
    updated = await handle_hook(config, coordinator, {"event": post})
    assert updated["version"] == 3 and updated["_sync"]["readback_complete"]
    assert api.documents[3]["task"]["reported_result"] == "FAIL"
    assert api.documents[3]["reports"][0]["markdown"] == "Original complete failure report"
    duplicate = await handle_hook(config, coordinator, {"event": {**post, "hook_event_name": "Stop"}})
    assert duplicate["status"] == "UNCHANGED" and len(api.documents) == 3
    artifact.write_text("Formal approved analysis A")
    reverted = await handle_hook(config, coordinator, {"event": post})
    assert reverted["version"] == 4 and api.documents[4]["task"]["plan_markdown"].endswith("A")
    assert not list((config.state_dir / "local-sync" / "pending-events").glob("*.json"))


async def test_native_auto_source_lost_send_keeps_original_key_and_pending_event(local):
    from hypertest.local_sync.hooks import handle_hook
    from hypertest.local_sync.sources import source_binding

    config, api, _, coordinator, identity = local
    event = configure_artifact_source(config, identity)
    await handle_hook(config, coordinator, {"event": event})
    artifact = source_binding(config, event)[2] / "analysis.md"
    artifact.write_text("approved before loss")
    api.lose_post = True
    post = {**event, "hook_event_name": "PostToolUse"}
    assert (await handle_hook(config, coordinator, {"event": post}))["status"] == "UNKNOWN"
    original_key = api.calls[-1][2]["payload"]["idempotency_key"]
    api.hide_receipt = True
    artifact.write_text("later approved content")
    await handle_hook(config, coordinator, {"event": post})
    assert [call[0] for call in api.calls].count("POST") == 1
    assert api.calls[-1][2]["params"]["idempotency_key"] == original_key
    assert list((config.state_dir / "local-sync" / "pending-events").glob("*.json"))


def test_native_source_binding_does_not_silently_reassign_policy(local):
    from hypertest.local_sync.sources import source_binding

    config, _, _, _, identity = local
    event = configure_artifact_source(config, identity)
    source_binding(config, event, create=True)
    config.local_sync["artifact_source"]["initial"]["objective"] = "different selection"
    with pytest.raises(ClientError, match="LOCAL_SOURCE_BINDING_CONFLICT"):
        source_binding(config, event, create=True)


async def test_native_report_file_edit_preserves_later_explicit_result_title_and_source(local):
    from hypertest.local_sync.hooks import handle_hook
    from hypertest.local_sync.sources import source_binding

    config, api, _, coordinator, identity = local
    event = configure_artifact_source(config, identity)
    config.local_sync["artifact_source"]["artifacts"] = [{"kind": "TEST_REPORT", "path": "report.md",
        "key": "run-one", "title": "Install-time title", "reported_result": "NOT_RUN"}]
    await handle_hook(config, coordinator, {"event": event})
    artifact = source_binding(config, event)[2] / "report.md"
    artifact.write_text("Initial approved report")
    post = {**event, "hook_event_name": "PostToolUse"}
    await handle_hook(config, coordinator, {"event": post})
    explicit = full(identity)
    explicit.update(expected_version=1, idempotency_key="explicit-failed-report")
    explicit["reports"][0].update(title="Later explicit failure title", source_ref="explicit-failure-source",
                                  artifact_uri="https://artifact.invalid/failure")
    await coordinator.submit_full(explicit)
    artifact.write_text("New formal report Markdown")
    await handle_hook(config, coordinator, {"event": post})
    actual = api.documents[3]["reports"][0]
    assert actual["markdown"] == "New formal report Markdown"
    assert actual["reported_result"] == "FAIL" and actual["title"] == "Later explicit failure title"
    assert actual["source_ref"] == "explicit-failure-source"
    assert actual["artifact_uri"] == "https://artifact.invalid/failure"
    assert api.documents[2]["reports"][0]["markdown"] == "Original complete failure report"


async def test_hook_event_reference_uses_one_durable_record_and_drain_recovers_a_full_queue(local):
    from hypertest.local_sync.hooks import drain_source, handle_hook, persist_trigger
    from hypertest.local_sync.hosts import parse_trigger
    from hypertest.local_sync.sources import source_binding

    config, api, _, coordinator, identity = local
    event = configure_artifact_source(config, identity)
    await handle_hook(config, coordinator, {"event": event})
    artifact = source_binding(config, event)[2] / "analysis.md"
    artifact.write_text("Approved artifact")
    post = {**event, "hook_event_name": "PostToolUse"}
    trigger = parse_trigger("codex", post, selected_parent=identity["session_id"])
    pending = persist_trigger(config, trigger)
    api.lose_post = True
    result = await handle_hook(config, coordinator, {"event": post, "event_id": pending.stem})
    assert result["status"] == "UNKNOWN"
    queue = pending.parent
    assert len(list(queue.glob("*.json"))) == 1
    while len(list(queue.glob("*.json"))) < 1024:
        persist_trigger(config, trigger)
    with pytest.raises(ClientError, match="LOCAL_EVENT_QUEUE_FULL"):
        persist_trigger(config, trigger)
    api.hide_receipt = True
    before = len(api.calls)
    blocked = await drain_source(config, coordinator, identity["session_id"])
    assert blocked["status"] in {"UNKNOWN", "BLOCKED"}
    assert [call[0] for call in api.calls[before:]] == ["GET"]
    assert len(list(queue.glob("*.json"))) == 1024
    # Recover the original accepted snapshot even when the live file is gone.
    artifact.unlink()
    api.hide_receipt = api.lose_post = False
    settled = await drain_source(config, coordinator, identity["session_id"])
    assert settled["code"] == "NO_APPROVED_ARTIFACTS"
    assert not list(queue.glob("*.json"))
    assert [call[0] for call in api.calls].count("POST") == 1
    with pytest.raises(ClientError, match="NATIVE_SESSION_START_REQUIRED"):
        await drain_source(config, coordinator, "unbound-session")


@pytest.mark.parametrize("scenario", ["no-start", "child-id", "random-id", "wrong-project", "wrong-provider",
    "record-identity", "record-workspace", "record-policy", "record-directory", "changed-policy"])
async def test_artifact_source_explicit_mcp_rejects_unbound_or_foreign_sources_before_admission(local, scenario):
    from hypertest.local_sync.hooks import handle_hook

    config, api, journal, coordinator, identity = local
    event = configure_artifact_source(config, identity)
    payload = full(identity)
    if scenario != "no-start":
        await handle_hook(config, coordinator, {"event": event})
    if scenario in {"child-id", "random-id"}:
        payload["session_id"] = "actual-child-session" if scenario == "child-id" else str(uuid4())
    elif scenario == "wrong-project":
        payload["project_id"] = str(uuid4())
    elif scenario == "wrong-provider":
        payload["provider"] = "claude_code"
    elif scenario.startswith("record-"):
        path = next((config.state_dir / "local-sync" / "native-sources").glob("*.json"))
        record = json.loads(path.read_text())
        field = {"record-identity": "identity", "record-workspace": "workspace",
                 "record-policy": "policy_digest", "record-directory": "artifact_directory"}[scenario]
        record[field] = {**identity, "session_id": "another-source"} if field == "identity" else "foreign-value"
        path.write_text(json.dumps(record))
    elif scenario == "changed-policy":
        config.local_sync["artifact_source"]["initial"]["objective"] = "another selection"
    with pytest.raises(ClientError):
        await coordinator.submit_full(payload)
    assert not api.calls and journal.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
    assert not list(coordinator.directory.glob("*.binding.json"))
    assert not list(coordinator.snapshots.directory.glob("*.json"))


async def test_artifact_source_explicit_mcp_accepts_existing_root_complete_snapshot(local):
    from hypertest.local_sync.hooks import handle_hook

    config, api, _, coordinator, identity = local
    event = configure_artifact_source(config, identity)
    await handle_hook(config, coordinator, {"event": event})
    payload = {**full(identity), "plan_markdown": "", "objective": ""}
    result = await coordinator.submit_full(payload)
    assert result["_sync"]["readback_complete"]
    assert api.documents[1]["task"]["plan_markdown"] == ""
    assert api.documents[1]["task"]["reported_result"] == "FAIL"
    assert [call[0] for call in api.calls].count("POST") == 1


@pytest.mark.parametrize("first_entry", ["native-start", "event-queue"])
def test_hook_cold_start_creates_private_parent_before_coordinator(tmp_path, first_entry):
    from hypertest.interactive_client.security import private_create
    from hypertest.local_sync.hooks import persist_trigger
    from hypertest.local_sync.hosts import parse_trigger
    from hypertest.local_sync.sources import source_binding

    token = tmp_path / "token"
    private_create(token, b"synthetic-private-token")
    config = ClientConfig(api_url="https://platform.invalid/api/v1", state_dir=tmp_path / "state",
                          integration_token_file=token, local_sync={"enabled": True})
    config.prepare()
    identity = {"project_id": str(uuid4()), "provider": "codex", "session_id": "cold-start-parent"}
    event = configure_artifact_source(config, identity)
    directory = config.state_dir / "local-sync"
    assert not directory.exists()
    if first_entry == "native-start":
        source_binding(config, event, create=True)
    else:
        persist_trigger(config, parse_trigger("codex", event, selected_parent=identity["session_id"]))
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    journal = Journal(config.state_dir / "client.sqlite3")
    try:
        LocalSyncCoordinator(config, VersionedApi(), journal)
        assert journal.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
    finally:
        journal.close()


@pytest.mark.parametrize("first_entry", ["native-start", "event-queue"])
def test_hook_cold_start_refuses_existing_non_private_parent(tmp_path, first_entry):
    from hypertest.interactive_client.security import private_create
    from hypertest.local_sync.hooks import persist_trigger
    from hypertest.local_sync.hosts import parse_trigger
    from hypertest.local_sync.sources import source_binding

    token = tmp_path / "token"
    private_create(token, b"synthetic-private-token")
    config = ClientConfig(api_url="https://platform.invalid/api/v1", state_dir=tmp_path / "state",
                          integration_token_file=token, local_sync={"enabled": True})
    config.prepare()
    identity = {"project_id": str(uuid4()), "provider": "codex", "session_id": "cold-start-parent"}
    event = configure_artifact_source(config, identity)
    directory = config.state_dir / "local-sync"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    with pytest.raises(ClientError, match="PRIVATE_DIRECTORY_REQUIRED"):
        if first_entry == "native-start":
            source_binding(config, event, create=True)
        else:
            persist_trigger(config, parse_trigger("codex", event, selected_parent=identity["session_id"]))
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755
    assert not list(directory.iterdir())


@pytest.mark.parametrize("old_state", ["ACKED", "UNKNOWN"])
async def test_upgrade_old_compact_receipt_without_snapshot_reconciles_original_key(local, old_state):
    _, api, journal, coordinator, identity = local
    original = full(identity)
    receipt = await api.request("POST", "interactive/tasks/sync", payload=original)
    compact = {**identity, "expected_version": 0, "idempotency_key": original["idempotency_key"]}
    namespace = "session-task:" + identity["project_id"]
    journal.intent(namespace, original["idempotency_key"], compact, identity=original)
    journal.mark(namespace, original["idempotency_key"], old_state,
                 receipt if old_state == "ACKED" else None)
    api.calls.clear()
    result = await coordinator.submit_partial(identity, {"status": "BLOCKED"},
                                               base_version=1, checkpoint_digest="after-upgrade")
    assert result["_sync"]["readback_complete"]
    assert journal.get(namespace, original["idempotency_key"])["state"] == "LEGACY_ACCEPTED_READBACK"
    assert api.calls[0][0] == "GET" and api.calls[0][1].endswith("by-key")
    assert len([call for call in api.calls if call[0] == "POST"]) == 1


async def test_old_unknown_receipt_not_found_stays_blocked_without_reposting(local):
    _, api, journal, coordinator, identity = local
    original = full(identity)
    namespace = "session-task:" + identity["project_id"]
    journal.intent(namespace, original["idempotency_key"], {**identity, "expected_version": 0,
                   "idempotency_key": original["idempotency_key"]}, identity=original)
    journal.mark(namespace, original["idempotency_key"], "UNKNOWN")
    api.hide_receipt = True
    for _ in range(2):
        result = await coordinator.submit_partial(identity, {"status": "BLOCKED"},
                                                 base_version=0, checkpoint_digest="later")
        assert result["status"] == "BLOCKED" and result["code"] == "NOT_FOUND"
    assert [call[0] for call in api.calls] == ["GET", "GET"]


async def test_new_frozen_missing_snapshot_never_downgrades_to_legacy_or_bypasses_unknown(local):
    _, api, _, coordinator, identity = local
    api.lose_post = True
    await coordinator.submit_full(full(identity))
    for path in coordinator.snapshots.directory.glob("*.json"):
        path.unlink()
    before = len(api.calls)
    result = await coordinator.submit_full({**full(identity), "idempotency_key": "replacement"})
    assert result["status"] == "BLOCKED" and result["code"] == "ORIGINAL_APPROVED_SNAPSHOT_REQUIRED"
    assert len(api.calls) == before


async def test_later_queued_observation_survives_first_checkpoint_completion(local):
    from hypertest.interactive_client.security import private_create
    from hypertest.local_sync.hooks import persist_trigger, submit_manifest
    from hypertest.local_sync.hosts import Trigger
    config, _, _, coordinator, identity = local
    manifest_path = config.state_dir / "approved-manifest.json"
    private_create(manifest_path, json.dumps({"identity": {"project_id": identity["project_id"],
        "provider": "codex", "parent_session_id": identity["session_id"]}, "base_version": 0,
        "set": {key: full(identity)[key] for key in ("title", "objective", "status", "plan_markdown", "reported_result")}}).encode())
    config.local_sync.update(host="codex", project_id=identity["project_id"],
                             manifest_file=str(manifest_path), allowed_roots=[])
    trigger = Trigger("codex", "codex", identity["session_id"], "Stop")
    first = persist_trigger(config, trigger)
    original_submit = coordinator.submit_partial
    later = []

    async def interleaved(*args, **kwargs):
        later.append(persist_trigger(config, trigger))
        return await original_submit(*args, **kwargs)

    coordinator.submit_partial = interleaved
    result = await submit_manifest(config, coordinator)
    assert result["_sync"]["readback_complete"]
    assert not first.exists() and later[0].exists()
