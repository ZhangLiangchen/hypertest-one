"""Local manifest → real typed HTTPS adapter → ASGI/DB → fixed-version readback.

This uses an isolated synthetic management identity. It does not exercise a
native Harness, install hooks, call a model, or execute the system under test.
"""
import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid4

from httpx import ASGITransport
from sqlalchemy import func, select
from test_session_tasks import context as context
from test_session_tasks import counts

from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.session_tasks import SyncReceipt
from hypertest.interactive_client.api_client import ApiClient
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.journal import Journal
from hypertest.interactive_client.security import private_create
from hypertest.local_sync.coordinator import LocalSyncCoordinator
from hypertest.local_sync.hooks import submit_manifest
from hypertest.main import app


class RecordingApi(ApiClient):
    def __init__(self, config):
        super().__init__(config, transport=ASGITransport(app=app))
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, deepcopy(kwargs)))
        return await super().request(method, path, **kwargs)


async def test_approved_manifest_real_api_preserves_failure_and_assets_across_partial_checkpoint(context, tmp_path):
    f = context
    execution_before = await counts()
    token_file = tmp_path / "integration-token"
    private_create(token_file, f["auth"]["integration_token"].encode())
    artifacts = tmp_path / "approved-testing-artifacts"
    artifacts.mkdir(mode=0o700)
    raw_report = "# Original execution failure\n" + "原始失败证据与全部观察，不能截断。\n" * 4000
    report_file = artifacts / "original-report.md"
    report_file.write_text(raw_report)
    source = {"project_id": f["project_id"], "provider": "codex",
              "parent_session_id": "synthetic-integration-parent-" + uuid4().hex}
    manifest_file = tmp_path / "approved-manifest.json"
    first_manifest = {"profile": "hypertest.local-manifest/v1alpha1", "identity": source,
        "base_version": 2, "set": {"title": "Isolated Local integration fixture",
            "objective": "Preserve official test assets through the existing management API",
            "status": "IN_PROGRESS", "plan_markdown": "# Original plan\nAnalyze and design before execution.",
            "reported_result": "FAIL", "cases": [{"key": "UC-INTEGRATION-1",
                "title": "Original case whose failure must survive", "steps": ["Read existing failure"],
                "expected": "Expected original behavior", "actual": "Original actual mismatch",
                "reported_result": "FAIL", "implementation_ref": "tests/existing_case.py::test_original"}]},
        "artifacts": [{"kind": "TEST_REPORT", "path": str(report_file),
            "sha256": hashlib.sha256(report_file.read_bytes()).hexdigest(), "key": "original-run",
            "title": "Full original failure report", "reported_result": "FAIL",
            "source_ref": "test-fixture:original-report.md"}]}
    private_create(manifest_file, json.dumps(first_manifest, ensure_ascii=False).encode())
    config = ClientConfig(api_url="https://localhost/api/v1", state_dir=tmp_path / "state",
        integration_token_file=token_file, local_sync={"enabled": True, "host": "codex",
            "hooks_enabled": False, "harness_version": "0.144.6", "project_id": f["project_id"],
            "manifest_file": str(manifest_file), "allowed_roots": [str(artifacts)]})
    config.prepare()
    api = RecordingApi(config)
    journal = Journal(config.state_dir / "client.sqlite3")
    coordinator = LocalSyncCoordinator(config, api, journal)
    try:
        # Explicit synthetic SessionStart fixture, not real-host acceptance.
        from hypertest.local_sync.sources import manifest_root
        manifest_root(config, {"session_id": source["parent_session_id"],
            "cwd": str(artifacts), "hook_event_name": "SessionStart"}, create=True)
        created = await f["c"].post(f"/api/v1/projects/{f['project_id']}/local-tasks", json={
            "idempotency_key": "integration-create", "title": "Isolated precreated Local task"})
        assert created.status_code == 200, created.text
        task_id = created.json()["task"]["id"]
        bound = await coordinator.bind_task({"project_id": f["project_id"], "task_id": task_id,
            "provider": "codex", "session_id": source["parent_session_id"],
            "expected_version": 1, "idempotency_key": "integration-bind"}, native_caller_context={
                "provider": "codex", "session_id": source["parent_session_id"],
                "transport": "codex-mcp-thread-id/v1"})
        assert bound["version"] == 2 and bound["_sync"]["readback_complete"]
        accepted = await submit_manifest(config, coordinator)
        assert accepted["status"] == "ACCEPTED" and accepted["version"] == 3
        assert accepted["_sync"] == {"state": "READBACK_COMPLETE", "readback_complete": True, "code": None}
        task_id = accepted["task_id"]
        pinned_pages = [options["params"] for method, path, options in api.calls
                        if method == "GET" and path.endswith(task_id)
                        and options["params"].get("version") == 3]
        assert len(pinned_pages) > 2 and pinned_pages[0]["offset"] == 0
        assert [page["offset"] for page in pinned_pages] == sorted(page["offset"] for page in pinned_pages)
        assert all(page["version"] == 3 and page["limit"] == 24000 for page in pinned_pages)
        original = (await f["c"].get("/api/v1/tasks/" + task_id, params={"version": 3})).json()
        assert original["reports"][0]["markdown"] == raw_report
        assert original["cases"][0]["actual"] == "Original actual mismatch"
        assert original["task"]["reported_result"] == "FAIL"

        # A new explicitly approved partial status contains neither a plan,
        # result, case nor report. The coordinator must preserve every one.
        second_manifest = {"profile": first_manifest["profile"], "identity": source,
                           "base_version": 3, "set": {"status": "BLOCKED"}}
        manifest_file.write_text(json.dumps(second_manifest))
        updated = await submit_manifest(config, coordinator)
        assert updated["version"] == 4 and updated["_sync"]["readback_complete"]
        latest = (await f["c"].get("/api/v1/tasks/" + task_id)).json()
        assert latest["task"]["status"] == "BLOCKED"
        assert latest["task"]["reported_result"] == "FAIL"
        assert latest["task"]["plan_markdown"] == first_manifest["set"]["plan_markdown"]
        assert latest["reports"][0]["markdown"] == raw_report
        assert latest["reports"][0]["reported_result"] == "FAIL"
        assert latest["cases"][0]["reported_result"] == "FAIL"
        assert latest["cases"][0]["implementation_ref"] == first_manifest["set"]["cases"][0]["implementation_ref"]
        assert len(latest["case_history"]) == len(latest["report_history"]) == 1

        posts_before = sum(method == "POST" for method, _, _ in api.calls)
        assert (await submit_manifest(config, coordinator))["status"] == "UNCHANGED"
        # Different manifest digest / current baseline, same semantic contents:
        # this must also suppress a write, independent of duplicate-event cache.
        manifest_file.write_text(json.dumps({**second_manifest, "base_version": 4}))
        no_change = await submit_manifest(config, coordinator)
        assert no_change == {"status": "UNCHANGED", "version": 4, "readback_complete": True}
        assert sum(method == "POST" for method, _, _ in api.calls) == posts_before == 3
        async with AsyncSessionLocal() as db:
            assert await db.scalar(select(func.count()).select_from(SyncReceipt).where(
                SyncReceipt.task_id == UUID(task_id))) == 2
        rows = journal.db.execute("SELECT payload,state FROM intents").fetchall()
        assert len(rows) == 3 and all(state == "READBACK_COMPLETE" for _, state in rows)
        assert all("原始失败" not in compact and "Original actual mismatch" not in compact
                   for compact, _ in rows)
        assert await counts() == execution_before
    finally:
        journal.close()
        await api.close()
