"""CLI/API contract integration using synthetic data only in the dedicated test DB."""
import asyncio
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from hypertest.api.schemas import ProjectCreate
from hypertest.application.services import create_project
from hypertest.cli import AUTH_PREFIX, PREFIX, PROFILE, archive, auth
from hypertest.cli.state import CLIError, State
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.main import app


@pytest.mark.parametrize("child_target", [False, True])
async def test_cli_web_pairing_to_root_or_subtask_archive(tmp_path, monkeypatch, child_target):
    monkeypatch.setattr(get_settings(), "connector_operator_key", "cli-contract-operator")
    monkeypatch.setattr(get_settings(), "connector_operator_identity", "cli-contract-" + uuid4().hex)
    operator = {"X-Hypertest-Operator-Key": "cli-contract-operator"}
    async with AsyncSessionLocal() as db:
        projects = [str((await create_project(db, ProjectCreate(
            key=public_key("CLIWIRE"), name="Synthetic CLI wire fixture"))).id) for _ in range(2)]
    loop = asyncio.get_running_loop()
    calls, readback_pages = [], []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        class ASGIHTTP:
            def __init__(self, server, *, token=None, proof=None):
                assert server == "https://localhost"
                self.headers = {}
                if token:
                    self.headers["Authorization"] = "Bearer " + token
                if proof:
                    self.headers["X-Hypertest-Pairing-Proof"] = proof

            def call(self, method, path, *, query=None, body=None):
                async def request():
                    calls.append((method, path))
                    response = await client.request(method, path, params={k: v for k, v in (query or {}).items()
                                                     if v is not None}, json=body, headers=self.headers)
                    if response.status_code >= 400:
                        raise CLIError("ASGI_HTTP_" + str(response.status_code), 3,
                                       status=response.status_code)
                    value = response.json()
                    if method == "GET" and path.startswith(PREFIX + "/submissions/") and "content" in value:
                        readback_pages.append(value)
                    if method == "POST" and path == AUTH_PREFIX + "/requests":
                        # The synthetic operator represents the single explicit Web confirmation.
                        approved = await client.post(path + "/" + value["request_id"] + "/approve",
                            headers=operator, json={"idempotency_key": str(uuid4()),
                                "project_ids": projects,
                                "scopes": ["archive:read", "archive:write"],
                                "expires_in_days": 30, "short_code": value["short_code"]})
                        assert approved.status_code == 200, approved.text
                    return value
                return asyncio.run_coroutine_threadsafe(request(), loop).result(timeout=20)

        state = State(tmp_path / "private-cli")
        bound, code = await asyncio.to_thread(auth.bind, state, server="https://localhost",
            wait_seconds=1, open_browser=False, sleep=lambda _: None, http_factory=ASGIHTTP)
        assert code == 0 and bound["profile_saved"], bound
        assert len(state.safe_profiles()[0]["grants"]) == 2
        project = projects[1]
        actor_ref = state.profile("default", project_id=project)["actor_ref"]
        created = await client.post(PREFIX + "/tasks", headers=operator, json={
            "project_id": project, "idempotency_key": str(uuid4()), "title": "CLI fixture task",
            "owner_uploader_actor_ref": actor_ref})
        assert created.status_code == 200, created.text
        task_id = created.json()["task"]["id"]
        child_id = None
        if child_target:
            child = await client.post(PREFIX + f"/tasks/{task_id}/subtasks", headers=operator,
                json={"project_id": project, "idempotency_key": str(uuid4()),
                      "expected_task_version": 1, "title": "CLI fixture child"})
            assert child.status_code == 200, child.text
            child_id = child.json()["subtasks"][0]["id"]
        original = "# Original FAIL\r\n保留原文与来源\n" + ("Observed failed assertion.\n" * 1100)
        (tmp_path / "report.txt").write_bytes(original.encode())
        (tmp_path / "plan.txt").write_text("# Test plan\nSynthetic CLI contract check\n")
        (tmp_path / "summary.txt").write_text("# Summary\nObserved FAIL\n")
        (tmp_path / "details.txt").write_text("# Details\nAssertion failure\n")
        manifest = {"profile": PROFILE, "project_id": project, "task_id": task_id,
            "assets": [{"kind": "PLAN", "stable_key": "test-plan", "title": "Test plan", "path": "plan.txt"},
                       {"kind": "REPORT", "stable_key": "original", "title": "Original failure",
                        "path": "report.txt", "reported_result": "FAIL",
                        "origin": {"origin_provider": "codex", "origin_session_ref": "declared-session",
                                   "report_created_at": "2026-10-27T01:02:00+00:00"}},
                       {"kind": "REPORT", "stable_key": "summary", "title": "Summary",
                        "path": "summary.txt", "reported_result": "FAIL"},
                       {"kind": "REPORT", "stable_key": "details", "title": "Details",
                        "path": "details.txt", "reported_result": "FAIL"}]}
        if child_id:
            manifest.update(subtask_id=child_id, subtask_update={"status": "COMPLETED", "reported_result": "FAIL"})
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(manifest))
        result, code = await asyncio.to_thread(archive.archive, state, profile_name="default",
            project_id=project, task_id=task_id, subtask_id=child_id, manifest=path, http_factory=ASGIHTTP)
        assert code == 0 and result["readback_complete"], result
        assert result["target_kind"] == ("SUBTASK" if child_id else "TASK")
        assert result["task_url"].endswith(f"/archives/{task_id}?projectId={project}")
        submission_reads = [path for method, path in calls if method == "GET"
                            and path == PREFIX + "/submissions/" + result["submission_id"]]
        assert len(submission_reads) >= 2  # Actual server pagination is fully reassembled.
        snapshot = json.loads("".join(page["content"] for page in readback_pages))
        assets = {(asset["kind"], asset["stable_key"]): asset for asset in snapshot["assets"]}
        assert set(assets) == {("PLAN", "test-plan"), ("REPORT", "original"),
                               ("REPORT", "summary"), ("REPORT", "details")}
        assert assets[("REPORT", "original")]["markdown"] == original
        assert assets[("REPORT", "original")]["origin"]["report_created_at"] == "2026-10-27T01:02:00+00:00"
        details = await client.get(PREFIX + f"/tasks/{task_id}", headers=operator, params={"project_id": project})
        assert details.status_code == 200
        assert details.json()["task"]["reported_result"] == "NOT_RUN"
        assert len(details.json()["subtasks"]) == int(child_target)
        followup, code = await asyncio.to_thread(archive.archive, state, profile_name="default",
            project_id=project, task_id=task_id, subtask_id=child_id, manifest=path, http_factory=ASGIHTTP)
        assert code == 0 and followup["status"] == "UNCHANGED", followup
        assert followup["accepted_version"] == result["accepted_version"]
