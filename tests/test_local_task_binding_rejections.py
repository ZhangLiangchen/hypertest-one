"""Independent ADR-024 rejection checks using the existing PostgreSQL fixture.

Native root events below are adapter fixtures, never proof of a real host E2E.
"""
import asyncio
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from test_local_sync import configure_artifact_source, full
from test_local_sync import local as local
from test_session_task_mcp import NoExecutionHost
from test_session_tasks import body, sync
from test_session_tasks import context as context

from hypertest.api.schemas import ProjectCreate
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.interactive_client.api_client import ApiError
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.ipc import LocalClient, LocalServer
from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.service import InteractiveService
from hypertest.local_sync.coordinator import LocalSyncCoordinator
from hypertest.local_sync.sources import source_binding
from hypertest.sync_core import FrozenIntent
from hypertest.sync_core.storage import JournalLedger


async def create_local(f, **changes):
    payload = {"idempotency_key": "create-" + uuid4().hex,
               "title": "Explicit Local binding rejection fixture", **changes}
    response = await f["c"].post(f"/api/v1/projects/{f['project_id']}/local-tasks", json=payload)
    assert response.status_code == 200, response.text
    return response.json(), payload


def binding(f, task_id, **changes):
    return {"project_id": f["project_id"], "task_id": task_id, "provider": "codex",
            "session_id": "binding-fixture-" + uuid4().hex, "expected_version": 1,
            "idempotency_key": "bind-" + uuid4().hex, **changes}


async def bind(f, payload, *, headers=None):
    return await f["c"].post("/api/v1/interactive/tasks/bind", json=payload,
                             headers=f["headers"] if headers is None else headers)


async def detail(f, task_id, **params):
    response = await f["c"].get("/api/v1/tasks/" + task_id, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def another_actor(f, *, project_id=None):
    response = await f["c"].post("/api/v1/interactive/registrations", headers={
        "X-Hypertest-Operator-Key": "task-sync-fixture-operator"}, json={
            "actor_ref": "binding-other-" + uuid4().hex, "client_instance_id": str(uuid4()),
            "project_id": project_id or f["project_id"], "scopes": ["task:sync"]})
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["integration_token"]}


async def test_explicit_null_actor_never_becomes_first_claimant_or_fake_sync(context):
    f = context
    created, _ = await create_local(f, intended_actor_ref=None)
    task = created["task"]
    assert task["binding_state"] == "UNBOUND" and task["binding_required"] is True
    assert task["version"] == 1 and task["reported_result"] == "NOT_RUN"
    for key in ("intended_actor_ref", "provider", "session_id", "owner_actor_ref",
                "source", "last_synced_at", "bound_at"):
        assert task[key] is None
    rejected = await bind(f, binding(f, task["id"]))
    assert rejected.status_code == 403 and rejected.json()["detail"] == "TASK_BINDING_ACTOR_REQUIRED"
    unchanged = await detail(f, task["id"])
    assert unchanged["task"] == task
    assert unchanged["binding_history"] == unchanged["sync_history"] == []
    assert unchanged["cases"] == unchanged["reports"] == []


async def test_create_key_conflict_and_later_authorization_do_not_change_frozen_version_one(context):
    f = context
    created, payload = await create_local(f, intended_actor_ref=None)
    task_id = created["task"]["id"]
    actors = await f["c"].get(f"/api/v1/projects/{f['project_id']}/local-task-actors")
    assert actors.status_code == 200 and actors.json()["total"] == 1
    actor_ref = actors.json()["items"][0]["actor_ref"]
    authorized = await f["c"].patch(f"/api/v1/tasks/{task_id}/binding-authorization",
        json={"expected_version": 1, "intended_actor_ref": actor_ref})
    assert authorized.status_code == 200 and authorized.json()["task"]["version"] == 2
    duplicate = await f["c"].post(f"/api/v1/projects/{f['project_id']}/local-tasks", json=payload)
    assert duplicate.status_code == 200 and duplicate.json() == created
    conflict = await f["c"].post(f"/api/v1/projects/{f['project_id']}/local-tasks",
        json={**payload, "intended_actor_ref": actor_ref})
    assert conflict.status_code == 409 and conflict.json()["detail"] == "TASK_OPERATION_KEY_CONFLICT"
    queried = await f["c"].get(f"/api/v1/projects/{f['project_id']}/local-tasks/by-key",
        params={"idempotency_key": payload["idempotency_key"]})
    assert queried.status_code == 200 and queried.json() == created
    assert (await detail(f, task_id, version=1))["task"] == created["task"]
    assert (await detail(f, task_id))["task"]["intended_actor_ref"] == actor_ref


async def test_other_authorized_project_actor_cannot_claim_or_read_target(context):
    f = context
    created, _ = await create_local(f)
    task_id = created["task"]["id"]
    other_headers = await another_actor(f)
    rejected = await bind(f, binding(f, task_id), headers=other_headers)
    assert rejected.status_code == 403 and rejected.json()["detail"] == "TASK_BINDING_ACTOR_MISMATCH"
    read = await f["c"].get("/api/v1/interactive/tasks/" + task_id,
        params={"project_id": f["project_id"]}, headers=other_headers)
    assert read.status_code == 403
    assert (await detail(f, task_id))["task"] == created["task"]


async def test_wrong_project_uuid_and_operator_key_do_not_authorize_binding(context):
    f = context
    created, _ = await create_local(f)
    task_id = created["task"]["id"]
    async with AsyncSessionLocal() as db:
        other = await create_project(db, ProjectCreate(key=public_key("BINDOTHER"), name="Other binding Project"))
        other_project = str(other.id)
    payload = binding(f, task_id, project_id=other_project)
    assert (await bind(f, payload)).status_code == 403  # no grant to that Project
    other_headers = await another_actor(f, project_id=other_project)
    assert (await bind(f, payload, headers=other_headers)).status_code == 404  # valid grant, wrong Task
    operator = await bind(f, binding(f, task_id), headers={
        "X-Hypertest-Operator-Key": "task-sync-fixture-operator"})
    assert operator.status_code == 403 and operator.json()["detail"] == "TASK_BINDING_REQUIRES_INTEGRATION_ACTOR"
    assert (await detail(f, task_id))["task"] == created["task"]


async def test_revoked_grant_cannot_bind_or_retrieve_original_binding_receipt(context):
    f = context
    created, _ = await create_local(f)
    payload = binding(f, created["task"]["id"])
    accepted = await bind(f, payload)
    assert accepted.status_code == 200, accepted.text
    revoked = await f["c"].post(f"/api/v1/interactive/grants/{f['auth']['grant_id']}/revoke",
        headers={"X-Hypertest-Operator-Key": "task-sync-fixture-operator"})
    assert revoked.status_code == 200, revoked.text
    assert (await bind(f, payload)).status_code == 403
    queried = await f["c"].get("/api/v1/interactive/tasks/bindings/by-key", params={
        "project_id": f["project_id"], "idempotency_key": payload["idempotency_key"]}, headers=f["headers"])
    assert queried.status_code == 403
    assert (await detail(f, payload["task_id"]))["task"]["version"] == 2


async def test_stale_version_rebind_softdelete_and_key_conflict_preserve_accepted_identity(context):
    f = context
    created, _ = await create_local(f)
    task_id = created["task"]["id"]
    edited = await f["c"].patch("/api/v1/tasks/" + task_id,
                              json={"expected_version": 1, "title": "Managed before bind"})
    assert edited.status_code == 200, edited.text
    payload = binding(f, task_id)
    stale = await bind(f, payload)
    assert stale.status_code == 409 and stale.json()["detail"] == "TASK_VERSION_CONFLICT"
    assert (await detail(f, task_id)) == edited.json()
    payload.update(expected_version=2)
    accepted = await bind(f, payload)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()
    assert receipt["version"] == 3
    changed = await bind(f, {**payload, "session_id": "another-parent"})
    assert changed.status_code == 409 and changed.json()["detail"] == "TASK_OPERATION_KEY_CONFLICT"
    rebind = await bind(f, {**payload, "expected_version": 3, "idempotency_key": "new-bind-key"})
    assert rebind.status_code == 409 and rebind.json()["detail"] == "TASK_ALREADY_BOUND"
    deleted = await f["c"].delete("/api/v1/tasks/" + task_id, params={"expected_version": 3})
    assert deleted.status_code == 200, deleted.text
    rejected = await bind(f, {**payload, "expected_version": 4, "idempotency_key": "after-delete"})
    assert rejected.status_code == 409 and rejected.json()["detail"] == "TASK_BINDING_DELETED"
    assert (await bind(f, payload)).json() == receipt  # original key is checked before current state/version
    queried = await f["c"].get("/api/v1/interactive/tasks/bindings/by-key", params={
        "project_id": f["project_id"], "idempotency_key": payload["idempotency_key"]}, headers=f["headers"])
    assert queried.status_code == 200 and queried.json() == receipt
    restored = await f["c"].post(f"/api/v1/tasks/{task_id}/restore", json={"expected_version": 4})
    assert restored.status_code == 200, restored.text
    task = restored.json()["task"]
    assert task["provider"] == payload["provider"] and task["session_id"] == payload["session_id"]
    assert task["source"] is None and task["last_synced_at"] is None
    assert restored.json()["sync_history"] == []
    assert len(restored.json()["binding_history"]) == 1


async def test_deleted_unbound_task_cannot_be_claimed_and_restore_retains_empty_source(context):
    f = context
    created, _ = await create_local(f)
    task_id = created["task"]["id"]
    deleted = await f["c"].delete("/api/v1/tasks/" + task_id, params={"expected_version": 1})
    assert deleted.status_code == 200, deleted.text
    rejected = await bind(f, binding(f, task_id, expected_version=2))
    assert rejected.status_code == 409 and rejected.json()["detail"] == "TASK_BINDING_DELETED"
    restored = await f["c"].post(f"/api/v1/tasks/{task_id}/restore", json={"expected_version": 2})
    assert restored.status_code == 200, restored.text
    assert restored.json()["task"]["binding_state"] == "UNBOUND"
    assert restored.json()["task"]["session_id"] is None
    assert restored.json()["binding_history"] == restored.json()["sync_history"] == []


async def test_existing_auto_task_conflict_does_not_move_or_overwrite_failure(context):
    f = context
    old_payload = body(f)
    old = await sync(f, old_payload)
    assert old.status_code == 200, old.text
    old_id = old.json()["task_id"]
    old_detail = await detail(f, old_id)
    created, _ = await create_local(f)
    task_id = created["task"]["id"]
    rejected = await bind(f, binding(f, task_id, session_id=old_payload["session_id"]))
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == {"code": "SESSION_ALREADY_HAS_TASK", "existing_task_id": old_id}
    assert await detail(f, old_id) == old_detail
    assert (await detail(f, task_id))["task"] == created["task"]
    resumed = await sync(f, {**old_payload, "idempotency_key": "legacy-resume", "expected_version": 1})
    assert resumed.status_code == 200 and resumed.json()["task_id"] == old_id
    assert (await detail(f, old_id))["reports"][0]["markdown"] == old_payload["reports"][0]["markdown"]


async def test_conflict_does_not_leak_another_actors_existing_task_id(context):
    f = context
    created, _ = await create_local(f)
    other_headers = await another_actor(f)
    old_payload = body(f)
    old = await f["c"].post("/api/v1/interactive/tasks/sync", json=old_payload, headers=other_headers)
    assert old.status_code == 200, old.text
    rejected = await bind(f, binding(f, created["task"]["id"], session_id=old_payload["session_id"]))
    assert rejected.status_code == 409 and rejected.json()["detail"] == {"code": "SESSION_ALREADY_HAS_TASK"}
    assert old.json()["task_id"] not in rejected.text


async def test_two_sessions_cannot_both_bind_one_precreated_task(context):
    f = context
    created, _ = await create_local(f)
    task_id = created["task"]["id"]
    requests = [binding(f, task_id), binding(f, task_id)]
    results = await asyncio.gather(*(bind(f, payload) for payload in requests))
    assert sorted(response.status_code for response in results) == [200, 409]
    accepted_index = next(index for index, response in enumerate(results) if response.status_code == 200)
    current = await detail(f, task_id)
    assert current["task"]["session_id"] == requests[accepted_index]["session_id"]
    assert current["task"]["version"] == 2 and current["task"]["last_synced_at"] is None
    assert len(current["binding_history"]) == 1 and current["sync_history"] == []


@pytest.mark.parametrize("mutation", ["missing-task", "wrong-task", "wrong-session", "wrong-provider", "stale", "other-actor", "operator"])
async def test_manual_bound_sync_rejections_never_create_replacement_or_assets(context, mutation):
    f = context
    created, _ = await create_local(f)
    task_id = created["task"]["id"]
    request = binding(f, task_id)
    accepted = await bind(f, request)
    assert accepted.status_code == 200, accepted.text
    before = await detail(f, task_id)
    payload = body(f, task_id=task_id, session_id=request["session_id"], expected_version=2)
    headers = f["headers"]
    if mutation == "missing-task":
        payload.pop("task_id")
    elif mutation == "wrong-task":
        payload["task_id"] = str(uuid4())
    elif mutation == "wrong-session":
        payload["session_id"] = "different-" + uuid4().hex
    elif mutation == "wrong-provider":
        payload["provider"] = "claude_code"
    elif mutation == "stale":
        payload["expected_version"] = 1
    elif mutation == "other-actor":
        headers = await another_actor(f)
    elif mutation == "operator":
        headers = {"X-Hypertest-Operator-Key": "task-sync-fixture-operator"}
    rejected = await f["c"].post("/api/v1/interactive/tasks/sync", json=payload, headers=headers)
    assert rejected.status_code == ({"wrong-task": 404, "operator": 403, "other-actor": 403}.get(mutation, 409)), rejected.text
    assert await detail(f, task_id) == before
    listing = await f["c"].get("/api/v1/tasks", params={"project_id": f["project_id"]})
    assert listing.status_code == 200 and listing.json()["total"] == 1


class BindingTransport:
    """Protocol fault injector, without native-host or execution claims."""

    def __init__(self):
        self.calls = []
        self.receipt = None
        self.document = None
        self.lose_response = False
        self.hide_receipt = False
        self.receipt_changes = {}

    async def capabilities(self):
        from hypertest.api.task_schemas import (
            GET_TASK_SCHEMA,
            TASK_BINDING_QUERY_SCHEMA,
            SessionTaskSync,
            TaskBind,
        )
        from hypertest.interactive_client import PROFILE

        return {"profile": PROFILE, "tools": [
            {"name": "hypertest_bind_task", "description": "Bind the selected fixture Task",
             "inputSchema": TaskBind.model_json_schema()},
            {"name": "hypertest_get_task_binding", "description": "Query the original fixture key",
             "inputSchema": TASK_BINDING_QUERY_SCHEMA},
            {"name": "hypertest_sync_task", "description": "Sync existing fixture assets",
             "inputSchema": SessionTaskSync.model_json_schema()},
            {"name": "hypertest_get_task", "description": "Read the fixture Task",
             "inputSchema": GET_TASK_SCHEMA},
        ], "execution_tools": []}

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, deepcopy(kwargs)))
        if method == "POST":
            assert path == "interactive/tasks/bind", "An unbound fixture must never sync assets"
            payload = kwargs["payload"]
            self.receipt = {"status": "ACCEPTED", "operation": "BIND",
                "profile": "codex-session-task-sync/v1alpha1", "binding_state": "BOUND",
                "source": None, "actor_ref": "interactive:" + str(uuid4()),
                "version": payload["expected_version"] + 1,
                **{key: payload[key] for key in ("project_id", "task_id", "provider", "session_id", "idempotency_key")}}
            self.document = {"task": {"id": payload["task_id"], "version": self.receipt["version"],
                "binding_state": "BOUND", "binding_required": True, "source": None,
                "last_synced_at": None, "bound_at": "2026-10-23T00:00:00+00:00",
                "owner_actor_ref": self.receipt["actor_ref"],
                **{key: payload[key] for key in ("project_id", "provider", "session_id")}},
                "cases": [], "reports": []}
            if self.lose_response:
                raise ApiError("LOST_BINDING_RESPONSE")
            return {**deepcopy(self.receipt), **self.receipt_changes}
        if path == "interactive/tasks/bindings/by-key":
            if self.hide_receipt or self.receipt is None:
                raise ApiError("NOT_FOUND", 404)
            return {**deepcopy(self.receipt), **self.receipt_changes}
        if path == "interactive/tasks/by-session":
            raise ApiError("NOT_FOUND", 404)
        assert self.document is not None
        assert path == "interactive/tasks/" + self.document["task"]["id"]
        params = kwargs["params"]
        selected_version = params.get("version", self.document["task"]["version"])
        assert selected_version == self.document["task"]["version"]
        content = json.dumps(self.document)
        offset = params.get("offset", 0)
        fragment = content[offset:offset + 137]
        end = offset + len(fragment)
        return {"task_id": self.document["task"]["id"], "version": selected_version,
            "source": None, "format": "application/json", "content": fragment,
            "offset": offset, "total_chars": len(content), "complete": end == len(content),
            "next_offset": None if end == len(content) else end}


@pytest.fixture
def native_binding(local):
    config, _, journal, _, identity = local
    event = configure_artifact_source(config, identity)
    # This creates the same private record used by SessionStart handling. It is
    # a unit fixture and cannot establish a real Codex/Claude/DeepSeek session.
    source_binding(config, event, create=True)
    api = BindingTransport()
    coordinator = LocalSyncCoordinator(config, api, journal)
    payload = {**identity, "task_id": str(uuid4()), "expected_version": 1, "idempotency_key": "binding-one"}
    return config, api, journal, coordinator, payload, event


def native_caller(payload):
    """Synthetic transport metadata; never a real native-host assertion."""
    return {"provider": "codex", "session_id": payload["session_id"],
            "transport": "codex-mcp-thread-id/v1"}


@pytest.mark.parametrize("mutation", ["missing-root", "project", "provider", "child", "workspace", "policy", "host"])
async def test_bind_rejects_missing_forged_or_changed_native_root_before_network(native_binding, mutation):
    config, api, _, coordinator, payload, _ = native_binding
    if mutation == "missing-root":
        for path in (config.state_dir / "local-sync" / "native-sources").glob("*.json"):
            path.unlink()  # only this test's temporary private record
    elif mutation == "project":
        payload["project_id"] = str(uuid4())
    elif mutation == "provider":
        payload["provider"] = "claude_code"
    elif mutation == "child":
        payload["session_id"] = "synthetic-child-without-root"
    elif mutation == "workspace":
        config.local_sync["artifact_source"]["workspace"] = str(config.state_dir / "other-workspace")
    elif mutation == "policy":
        config.local_sync["artifact_source"]["initial"]["title"] = "Changed policy after root admission"
    elif mutation == "host":
        config.local_sync["host"] = "unsupported-host"
    with pytest.raises(ClientError):
        await coordinator.bind_task(payload, native_caller_context=native_caller(payload))
    assert api.calls == []


async def test_unbound_new_root_keeps_artifact_and_never_posts_sync(native_binding):
    config, api, _, coordinator, payload, event = native_binding
    from hypertest.local_sync.hooks import handle_hook

    directory = source_binding(config, event)[2]
    original = "Approved analysis retained while binding is required"
    artifact = directory / "analysis.md"
    artifact.write_text(original)
    post = {**event, "hook_event_name": "PostToolUse", "tool_name": "write_file"}
    # Hook processing and explicit MCP share the same missing-target decision.
    with pytest.raises(ClientError, match="TASK_BINDING_REQUIRED"):
        await handle_hook(config, coordinator, {"event": post})
    identity = {key: payload[key] for key in ("project_id", "provider", "session_id")}
    with pytest.raises(ClientError, match="TASK_BINDING_REQUIRED"):
        await coordinator.submit_full(full(identity))
    assert artifact.read_text() == original
    assert api.calls and all(call[0] == "GET" for call in api.calls)


async def test_lost_binding_restart_not_found_and_new_target_only_reconcile_original_key(native_binding):
    config, api, _, coordinator, payload, _ = native_binding
    api.lose_response = True
    first = await coordinator.bind_task(payload, native_caller_context=native_caller(payload))
    assert first["status"] == "UNKNOWN" and first["query_required"]
    api.hide_receipt = True
    reopened = Journal(config.state_dir / "client.sqlite3")
    try:
        restarted = LocalSyncCoordinator(config, api, reopened)
        queried = await restarted.get_binding({"project_id": payload["project_id"],
                                               "idempotency_key": payload["idempotency_key"]})
        assert queried["status"] == "UNKNOWN"
        new_target = {**payload, "task_id": str(uuid4()), "idempotency_key": "do-not-create-another-binding"}
        blocked = await restarted.bind_task(new_target, native_caller_context=native_caller(payload))
        assert blocked["status"] == "UNKNOWN" and blocked["idempotency_key"] == payload["idempotency_key"]
        identity = {key: payload[key] for key in ("project_id", "provider", "session_id")}
        colliding_sync = {**full(identity), "idempotency_key": payload["idempotency_key"]}
        blocked_sync = await restarted.submit_full(colliding_sync, native_caller_context=native_caller(payload))
        assert blocked_sync["status"] == "UNKNOWN" and blocked_sync["idempotency_key"] == payload["idempotency_key"]
        assert [call[:2] for call in api.calls] == [
            ("POST", "interactive/tasks/bind"), ("GET", "interactive/tasks/bindings/by-key"),
            ("GET", "interactive/tasks/bindings/by-key"), ("GET", "interactive/tasks/bindings/by-key")]
        assert all(call[2]["params"]["idempotency_key"] == payload["idempotency_key"] for call in api.calls[1:])
        assert reopened.get("task-bind:" + payload["project_id"], new_target["idempotency_key"]) is None
        assert reopened.get("session-task:" + payload["project_id"], payload["idempotency_key"]) is None
    finally:
        reopened.close()


async def test_binding_only_confirms_after_complete_fixed_version_readback(native_binding):
    _, api, journal, coordinator, payload, _ = native_binding
    accepted = await coordinator.bind_task(payload, native_caller_context=native_caller(payload))
    assert accepted["status"] == "ACCEPTED" and accepted["source"] is None
    assert accepted["_sync"]["readback_complete"] is True
    assert journal.get("task-bind:" + payload["project_id"], payload["idempotency_key"])["state"] == "READBACK_COMPLETE"
    pages = [call for call in api.calls if call[0] == "GET"]
    assert len(pages) > 1 and all(call[2]["params"]["version"] == 2 for call in pages)
    assert all(call[1] == "interactive/tasks/" + payload["task_id"] for call in pages)
    assert [call[1] for call in api.calls if call[0] == "POST"] == ["interactive/tasks/bind"]


@pytest.mark.parametrize("changes", [
    {"task_id": str(uuid4())}, {"project_id": str(uuid4())}, {"session_id": "different-parent"},
    {"provider": "claude_code"}, {"version": True}, {"version": 9}, {"operation": "SYNC"},
    {"idempotency_key": "wrong-original-key"}, {"source": "AGENT_REPORTED"},
])
async def test_binding_receipt_mismatch_stays_unknown_and_never_resends(native_binding, changes):
    _, api, journal, coordinator, payload, _ = native_binding
    api.receipt_changes = changes
    first = await coordinator.bind_task(payload, native_caller_context=native_caller(payload))
    assert first["status"] == "UNKNOWN" and first["query_required"]
    repeat = await coordinator.bind_task(payload, native_caller_context=native_caller(payload))
    assert repeat["status"] == "UNKNOWN"
    queried = await coordinator.get_binding({"project_id": payload["project_id"],
                                            "idempotency_key": payload["idempotency_key"]})
    assert queried["status"] == "UNKNOWN"
    assert [call[0] for call in api.calls] == ["POST", "GET", "GET"]
    assert journal.get("task-bind:" + payload["project_id"], payload["idempotency_key"])["state"] == "UNKNOWN"


async def test_unknown_binding_query_without_local_intent_is_read_only(native_binding):
    _, api, journal, coordinator, payload, _ = native_binding
    result = await coordinator.get_binding({"project_id": payload["project_id"],
                                           "idempotency_key": "never-posted"})
    assert result["status"] == "UNKNOWN" and result["query_required"]
    assert [call[:2] for call in api.calls] == [("GET", "interactive/tasks/bindings/by-key")]
    assert journal.get("task-bind:" + payload["project_id"], "never-posted") is None


def write_state(coordinator, journal):
    """Only target, frozen requests and intent rows; excludes advisory locks."""
    paths = list(coordinator.directory.glob("*.task.json"))
    paths += list((coordinator.directory / "approved-snapshots").glob("*.json"))
    return ({str(path.relative_to(coordinator.directory)): path.read_bytes() for path in paths},
            journal.db.execute("SELECT * FROM intents ORDER BY rowid").fetchall())


@pytest.fixture
async def mcp_binding_boundary(native_binding):
    """Official SDK memory transport → real UDS → service/coordinator fixture.

    The test supplies MCP metadata itself; this is deliberately not a native
    Codex process or proof that an installed host injects the right metadata.
    """
    config, api, _, _, payload, event = native_binding
    with tempfile.TemporaryDirectory(prefix="ht-caller-", dir="/tmp") as short:
        selected = config.model_copy(deep=True, update={"state_dir": Path(short).resolve()})
        selected.prepare()
        source_binding(selected, event, create=True)
        journal = Journal(selected.state_dir / "client.sqlite3")
        service = InteractiveService(selected, api, journal, NoExecutionHost())
        server = LocalServer(selected, service)
        await server.start()
        try:
            client = LocalClient(selected.socket_path, selected.local_token_file)
            yield selected, api, journal, service, client, payload, event
        finally:
            await server.close()
            journal.close()


@pytest.mark.parametrize("operation", ["bind", "manual-sync", "manual-sync-old-target"])
async def test_retired_mcp_rejects_writes_to_known_parent_without_changing_history(mcp_binding_boundary, operation):
    from mcp.shared.memory import create_connected_server_and_client_session

    from hypertest.interactive_client.mcp_server import create_server

    _, api, journal, service, ipc_client, payload, _ = mcp_binding_boundary
    async with create_connected_server_and_client_session(create_server(ipc_client, local_host="codex")) as client:
        if operation.startswith("manual-sync"):
            # Establish a historical bound record directly; the current MCP entry cannot bind.
            parent = await service.coordinator.bind_task(payload, native_caller_context=native_caller(payload))
            assert parent["_sync"]["readback_complete"]
            if operation == "manual-sync-old-target":
                # A's private target files predate the local manual/auto flag.
                path = service.coordinator._target_path(payload)
                old = json.loads(path.read_text())
                old.pop("binding_required")
                path.write_text(json.dumps(old))
            identity = {key: payload[key] for key in ("project_id", "provider", "session_id")}
            arguments = {**full(identity), "task_id": payload["task_id"], "expected_version": 2}
            tool = "hypertest_sync_task"
        else:
            arguments, tool = payload, "hypertest_bind_task"
        before = write_state(service.coordinator, journal)
        posts = sum(call[0] == "POST" for call in api.calls)
        result = await client.call_tool(tool, arguments, meta={"threadId": "actual-child-thread"})
        assert result.isError and result.content[0].text == "LOCAL_SYNC_RETIRED_USE_HYPERTEST_CLI"
        assert sum(call[0] == "POST" for call in api.calls) == posts
        assert write_state(service.coordinator, journal) == before


@pytest.mark.parametrize("spoof", ["no-metadata", "argument-meta", "argument-caller-context"])
async def test_bind_arguments_cannot_supply_or_override_mcp_native_caller(mcp_binding_boundary, spoof):
    from mcp.shared.memory import create_connected_server_and_client_session

    from hypertest.interactive_client.mcp_server import create_server

    _, api, journal, service, ipc_client, payload, _ = mcp_binding_boundary
    arguments = deepcopy(payload)
    if spoof == "argument-meta":
        arguments["_meta"] = {"threadId": payload["session_id"]}
    elif spoof == "argument-caller-context":
        arguments["native_caller_context"] = native_caller(payload)
    before = write_state(service.coordinator, journal)
    async with create_connected_server_and_client_session(create_server(ipc_client, local_host="codex")) as client:
        result = await client.call_tool("hypertest_bind_task", arguments)
        assert result.isError and result.content[0].text == "LOCAL_SYNC_RETIRED_USE_HYPERTEST_CLI"
    assert api.calls == [] and write_state(service.coordinator, journal) == before


@pytest.mark.parametrize("host,provider,metadata", [
    ("claude-code", "claude_code", {"claudecode/toolUseId": "tool-call-is-not-root-proof"}),
    ("deepseek-harness", "deepseek_harness", {"threadId": "not-a-supported-host-adapter"}),
])
async def test_unsupported_host_mcp_binding_fails_closed_but_original_key_get_remains_available(
        mcp_binding_boundary, host, provider, metadata):
    from mcp.shared.memory import create_connected_server_and_client_session

    from hypertest.interactive_client.mcp_server import create_server

    config, api, journal, service, ipc_client, payload, event = mcp_binding_boundary
    config.local_sync.update(host=host, event_bridge="native-root")
    source_binding(config, event, create=True)
    arguments = {**payload, "provider": provider}
    before = write_state(service.coordinator, journal)
    async with create_connected_server_and_client_session(create_server(ipc_client, local_host=host)) as client:
        result = await client.call_tool("hypertest_bind_task", arguments, meta=metadata)
        assert result.isError and result.content[0].text == "LOCAL_SYNC_RETIRED_USE_HYPERTEST_CLI"
        assert api.calls == [] and write_state(service.coordinator, journal) == before
        queried = await client.call_tool("hypertest_get_task_binding", {
            "project_id": payload["project_id"], "idempotency_key": "unknown-original-key"})
        assert not queried.isError and queried.structuredContent["status"] == "UNKNOWN"
    assert [call[:2] for call in api.calls] == [("GET", "interactive/tasks/bindings/by-key")]


@pytest.mark.parametrize("operation", ["bind", "manual-sync"])
async def test_missing_caller_cannot_promote_prepared_intent_or_send_it(native_binding, operation):
    _, api, journal, coordinator, payload, _ = native_binding
    target = {key: payload[key] for key in ("project_id", "provider", "session_id", "task_id")}
    if operation == "bind":
        namespace, arguments = "task-bind:" + payload["project_id"], payload
    else:
        accepted = await coordinator.bind_task(payload, native_caller_context=native_caller(payload))
        assert accepted["_sync"]["readback_complete"]
        identity = {key: payload[key] for key in ("project_id", "provider", "session_id")}
        arguments = {**full(identity), "task_id": payload["task_id"], "expected_version": 2}
        namespace = "session-task:" + payload["project_id"]
    intent = FrozenIntent(namespace, arguments["idempotency_key"], target, arguments, arguments["expected_version"])
    coordinator.snapshots.save(intent)
    JournalLedger(journal).prepare(intent)
    before = write_state(coordinator, journal)
    posts = sum(call[0] == "POST" for call in api.calls)
    with pytest.raises(ClientError, match="NATIVE_CALLER_CONTEXT_REQUIRED"):
        if operation == "bind":
            await coordinator.bind_task(arguments)
        else:
            await coordinator.submit_full(arguments)
    assert sum(call[0] == "POST" for call in api.calls) == posts
    assert write_state(coordinator, journal) == before
    assert journal.get(namespace, intent.key)["state"] == "PENDING"
