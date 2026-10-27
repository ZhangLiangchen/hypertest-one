"""Owned-fragment removal and exact old-key recovery without daemon or POST."""
import copy
import json
import os
import sqlite3
from uuid import uuid4

import pytest

from hypertest.cli import legacy
from hypertest.cli.state import CLIError
from hypertest.sync_core import canonical_json, digest


def private(path, content):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else canonical_json(content).encode())
    path.chmod(0o600)
    return path


def installation(tmp_path, host):
    directory = tmp_path / "install"
    directory.mkdir(mode=0o700)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    token = private(tmp_path / "token", b"private-legacy-token")
    journal = private(state / "client.sqlite3", b"original-pending-journal")
    source = private(tmp_path / "report.md", b"# FAIL\noriginal source\n")
    client = private(tmp_path / "client.json", {"api_url": "https://archive.example/api/v1",
        "state_dir": str(state), "integration_token_file": str(token), "local_sync": {"enabled": True, "hooks_enabled": True}})
    group = {"hooks": [{"type": "command", "command": "/private/hypertest-local hook", "timeout": 15}]}
    other = {"hooks": [{"type": "command", "command": "unrelated-tool", "timeout": 15}]}
    hooks = private(tmp_path / "hooks.json", {"hooks": {"Stop": [group, other]}, "unrelated": "preserve"})
    if host == "claude-code":
        entry = {"command": "/private/python", "args": ["-m", "hypertest.interactive_client", "stdio"]}
        config = private(tmp_path / "host.json", {"mcpServers": {"hypertest-local": entry, "other": {"command": "other"}}, "permission": True})
        owned = {"entry": entry}
    else:
        body = ('[mcp_servers.hypertest_local]\ncommand = "/private/python"\n' if host == "codex"
            else '- insert:\n    - {"id":"hypertest-local-mcp"}\n    - {"id":"hypertest-local-hook-bridge"}\n')
        block = legacy.BEGIN + body + legacy.END
        config = private(tmp_path / "host.conf", ("# Unrelated comment\n" + block).encode())
        owned = {"block": block}
    receipt = private(directory / f"installed-{host}.json", {"profile": "hypertest.local-install/v1", "host": host,
        "configuration": "WRITTEN", "host_config": str(config), "hook_config": str(hooks),
        "client_config": str(client), "python": "/private/python", "owned": owned,
        "hooks_owned": {"groups": {"Stop": group}}, "version": "local-v0.1.1-rc.2"})
    return {"directory": directory, "state": state, "token": token, "journal": journal, "source": source,
        "client": client, "host": config, "hooks": hooks, "receipt": receipt, "other": other}


@pytest.mark.parametrize("host", ["codex", "claude-code", "deepseek-harness"])
async def test_retire_preserves_unowned_configuration_and_all_private_history(tmp_path, host):
    f = installation(tmp_path, host)
    before = {name: f[name].read_bytes() for name in ("token", "journal", "source")}
    result, code = legacy.retire(str(f["directory"]), host)
    assert code == 0 and result["status"] == "RETIRED" and result["runtime"] == "NOT_RUNNING"
    assert "hypertest-local" not in f["host"].read_text() and "hypertest_local" not in f["host"].read_text()
    if host == "claude-code":
        host_config = json.loads(f["host"].read_text())
        assert host_config["mcpServers"]["other"] == {"command": "other"} and host_config["permission"]
    else:
        assert f["host"].read_text() == "# Unrelated comment\n"
    assert json.loads(f["hooks"].read_text()) == {"hooks": {"Stop": [f["other"]]}, "unrelated": "preserve"}
    assert json.loads(f["client"].read_text())["local_sync"] == {"enabled": False, "hooks_enabled": False}
    assert {name: f[name].read_bytes() for name in before} == before
    assert len(list((f["directory"] / "legacy-retire").glob("*/committed.json"))) == 1
    assert legacy.retire(str(f["directory"]), host)[0]["status"] == "RETIRED"


@pytest.mark.parametrize("changed", ["host", "hooks"])
async def test_drift_rejects_before_runtime_stop_or_partial_configuration_write(tmp_path, monkeypatch, changed):
    f = installation(tmp_path, "codex")
    if changed == "host":
        f["host"].write_text(f["host"].read_text().replace('/private/python', '/user/custom/python'))
    else:
        f["hooks"].write_text(f["hooks"].read_text().replace('hypertest-local hook', 'user-modified-command'))
    before = {name: f[name].read_bytes() for name in ("host", "hooks", "client", "receipt")}
    monkeypatch.setattr(legacy, "_stop_owned", lambda *args: pytest.fail("drift must be rejected before stopping"))
    with pytest.raises(CLIError, match="PRESERVED"):
        legacy.retire(str(f["directory"]), "codex")
    assert {name: f[name].read_bytes() for name in before} == before


async def test_runtime_requires_authenticated_identity_and_never_signals_pid(tmp_path, monkeypatch):
    f = installation(tmp_path, "codex")
    calls = []

    def foreign(config, operation):
        calls.append(operation)
        return {"runtime": {"profile": "another-service", "python": "/private/python"}, "pid": os.getpid()}

    monkeypatch.setattr(legacy, "_rpc", foreign)
    monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("must not signal arbitrary process"))
    with pytest.raises(CLIError, match="IDENTITY_MISMATCH"):
        legacy.retire(str(f["directory"]), "codex")
    assert calls == ["runtime-info"]
    assert json.loads(f["receipt"].read_text())["configuration"] == "WRITTEN"


def recovery(tmp_path, kind="SYNC", *, compact=False, status="UNKNOWN"):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    project, task = str(uuid4()), str(uuid4())
    key = "original-key"
    namespace = {"SYNC": "session-task:", "BIND": "task-bind:", "JOIN": "task-collaboration:"}[kind] + project
    target = {"project_id": project, "task_id": task, "provider": "codex", "session_id": "original-session"}
    payload = {**target, "idempotency_key": key, "expected_version": 1}
    task_snapshot = {"id": task, "project_id": project, "provider": "codex", "session_id": "original-session", "version": 2}
    receipt = {"profile": legacy.SYNC_PROFILE, "status": "ACCEPTED", **target, "idempotency_key": key, "version": 2}
    if kind == "SYNC":
        payload.update(title="Exact task", objective="Test", status="COMPLETED", plan_markdown="# Original plan", reported_result="FAIL", cases=[], reports=[{
            "key": "raw", "title": "Raw", "markdown": "原文\r\nFAIL\n", "reported_result": "FAIL", "artifact_uri": None, "source_ref": None}])
        task_snapshot.update({k: payload[k] for k in ("title", "objective", "status", "plan_markdown", "reported_result")})
        receipt["source"] = task_snapshot["source"] = "AGENT_REPORTED"
        document = {"task": task_snapshot, "cases": [], "reports": payload["reports"]}
    elif kind == "BIND":
        receipt.update(operation="BIND", binding_state="BOUND", source=None, actor_ref="interactive:" + str(uuid4()))
        task_snapshot.update(binding_state="BOUND", binding_required=True, bound_at="2026-10-27T01:00:00+00:00",
            owner_actor_ref=receipt["actor_ref"], source=None, last_synced_at=None)
        document = {"task": task_snapshot, "cases": [], "reports": []}
    else:
        participant_id, actor = str(uuid4()), "interactive:" + str(uuid4())
        payload["operation"] = "JOIN"
        wire = {k: v for k, v in payload.items() if k != "task_id"}
        receipt.update(profile=legacy.COLLAB_PROFILE, operation="JOIN", actor_ref=actor, participant_id=participant_id,
            primary_generation=1, contribution_refs=[], request_digest=digest(wire))
        document = {"profile": legacy.COLLAB_PROFILE, "task": task_snapshot, "collaboration": {"enabled": True,
            "participants": [{"id": participant_id, "actor_ref": actor, "status": "ACTIVE", "provider": "codex", "session_id": "original-session"}],
            "contributions": [], "publications": []}, "operation_history": [{"request_payload": wire, "response": receipt}]}
    frozen = {"namespace": namespace, "key": key, "target": target, "payload": payload, "expected_version": 1, "request_digest": digest(payload)}
    compact_row = {**target, "idempotency_key": key, "expected_version": 1}
    if not compact:
        compact_row["snapshot_schema"] = "hypertest.sync-snapshot/v1"
        private(state / "local-sync" / "approved-snapshots" / (digest([namespace, key]) + ".json"), frozen)
    journal = state / "client.sqlite3"
    with sqlite3.connect(journal) as db:
        db.execute("CREATE TABLE intents(kind TEXT,key TEXT,digest TEXT,payload TEXT,state TEXT,result TEXT,PRIMARY KEY(kind,key))")
        db.execute("INSERT INTO intents VALUES(?,?,?,?,?,?)", (namespace,key,digest(payload),canonical_json(compact_row),status,None))
    journal.chmod(0o600)
    token = private(tmp_path / "token", b"private-token")
    config = private(tmp_path / "config.json", {"api_url": "https://example.test/api/v1", "state_dir": str(state), "integration_token_file": str(token)})
    return {"config": config, "state": state, "key": key, "namespace": namespace, "journal": journal, "receipt": receipt, "document": document}


class FakeReadOnlyAPI:
    def __init__(self, fixture):
        self.fixture, self.calls = fixture, []

    def get(self, path, query):
        self.calls.append((path, query))
        if path.endswith("by-key"):
            return copy.deepcopy(self.fixture["receipt"])
        content = canonical_json(self.fixture["document"])
        offset = query["offset"]
        end = min(offset + 67, len(content))
        receipt = self.fixture["receipt"]
        return {"task_id": receipt["task_id"], "version": receipt["version"], "profile": receipt["profile"],
            "source": receipt.get("source"), "format": "application/json", "offset": offset, "total_chars": len(content),
            "content": content[offset:end], "complete": end == len(content), "next_offset": None if end == len(content) else end}


@pytest.mark.parametrize("kind", ["SYNC", "BIND", "JOIN"])
async def test_reconcile_only_original_key_and_complete_fixed_version_without_modifying_old_journal(tmp_path, monkeypatch, kind):
    f = recovery(tmp_path, kind)
    before = f["journal"].read_bytes()
    api = FakeReadOnlyAPI(f)
    monkeypatch.setattr(legacy, "ReadOnlyAPI", lambda config: api)
    result, code = legacy.reconcile(str(f["config"]), f["key"])
    assert code == 0 and result["status"] == "LEGACY_RECOVERED" and result["readback_complete"]
    assert result["original_request_verified"] and not result["replay_allowed"]
    assert api.calls[0][1]["idempotency_key"] == f["key"]
    assert all(query["version"] == 2 for _, query in api.calls[1:])
    assert f["journal"].read_bytes() == before
    assert len(list((f["state"] / "legacy-readbacks").glob("*.json"))) == 1


async def test_legacy_compact_record_does_not_claim_original_content_comparison(tmp_path, monkeypatch):
    f = recovery(tmp_path, compact=True)
    api = FakeReadOnlyAPI(f)
    monkeypatch.setattr(legacy, "ReadOnlyAPI", lambda config: api)
    result, code = legacy.reconcile(str(f["config"]), f["key"])
    assert code == 0 and result["status"] == "LEGACY_ACCEPTED_READBACK"
    assert result["original_request_verified"] is False
    assert result["code"] == "ORIGINAL_REQUEST_COMPARISON_UNAVAILABLE_LEGACY_COMPACT"


async def test_not_found_and_unsent_never_repost_or_replace_key(tmp_path, monkeypatch):
    f = recovery(tmp_path, status="PENDING")
    monkeypatch.setattr(legacy, "ReadOnlyAPI", lambda config: pytest.fail("unsent intent must not access network"))
    result, code = legacy.reconcile(str(f["config"]), f["key"])
    assert code == 4 and result["code"] == "LEGACY_ORIGINAL_REQUEST_NOT_SENT"
    with sqlite3.connect(f["journal"]) as db:
        db.execute("UPDATE intents SET state='UNKNOWN'")
    api = FakeReadOnlyAPI(f)
    calls = []

    def absent(path, query):
        calls.append((path, query))
        raise CLIError("LEGACY_ORIGINAL_KEY_NOT_FOUND", 4, status=404)

    api.get = absent
    monkeypatch.setattr(legacy, "ReadOnlyAPI", lambda config: api)
    with pytest.raises(CLIError, match="ORIGINAL_KEY_NOT_FOUND"):
        legacy.reconcile(str(f["config"]), f["key"])
    assert len(calls) == 1 and calls[0][1]["idempotency_key"] == f["key"]
    assert not (f["state"] / "legacy-readbacks").exists()


async def test_mismatched_original_content_is_not_marked_recovered(tmp_path, monkeypatch):
    f = recovery(tmp_path)
    f["document"]["reports"][0]["markdown"] = "Changed raw report"
    api = FakeReadOnlyAPI(f)
    monkeypatch.setattr(legacy, "ReadOnlyAPI", lambda config: api)
    with pytest.raises(CLIError, match="ORIGINAL_CONTENT_MISMATCH"):
        legacy.reconcile(str(f["config"]), f["key"])
    assert not (f["state"] / "legacy-readbacks").exists()


async def test_runtime_from_another_configuration_is_preserved(tmp_path, monkeypatch):
    f = installation(tmp_path, "codex")
    calls = []

    def different_configuration(config, operation):
        calls.append(operation)
        return {"runtime": {"profile": "hypertest.local-runtime/v1", "python": "/private/python",
            "runtime_sha256": "a" * 64, "configuration_sha256": "b" * 64}, "state": "READY"}

    monkeypatch.setattr(legacy, "_rpc", different_configuration)
    with pytest.raises(CLIError, match="IDENTITY_MISMATCH"):
        legacy.retire(str(f["directory"]), "codex")
    assert calls == ["runtime-info"]
    assert json.loads(f["receipt"].read_text())["configuration"] == "WRITTEN"
