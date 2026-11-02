"""Real API/DB Worker fencing against a dedicated synthetic test database."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
from test_cloud_tasks import FRAMEWORK_ORIGIN, FRAMEWORK_SHA, ORIGIN, SHA, dispatched, draft, post

from hypertest.cloud import native_git, native_sdk_adapter, native_worker
from hypertest.config import get_settings
from hypertest.main import app

pytest_plugins = ("test_cloud_tasks",)


async def test_host_worker_claim_resolution_and_original_read_after_fence(cloud_context, monkeypatch, tmp_path):
    context = cloud_context
    token = "worker-integration-" + "x" * 40
    key = tmp_path / "worker-token"
    key.write_text(token)
    key.chmod(0o600)
    settings = get_settings()
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_api_token_file", str(key))
    monkeypatch.setattr(settings, "cloud_worker_api_worker_id", "fixture-host-worker")
    client = context["client"]
    headers = {"Authorization": "Bearer " + token}
    created = await draft(context)
    task_id, project_id = created["task_id"], context["project_id"]
    requested = await post(context, "RESOLVE_INPUTS", 1, task_id=task_id)
    assert requested.status_code == 200
    response = await client.post("/api/v1/cloud/worker/claim", headers=headers,
                                 json={"worker_id": "fixture-host-worker", "lease_seconds": 90})
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "RESOLUTION"
    claimed = response.json()["claim"]
    identity = {"worker_id": "fixture-host-worker", "lease_token": claimed["lease_token"],
                "work_token": claimed["work_token"], "generation": claimed["generation"]}
    target = {"project_id": project_id, "task_id": task_id, "resolution_id": claimed["resolution"]["id"],
              "identity": identity}
    assert (await client.post("/api/v1/cloud/worker/resolution/assert", headers=headers, json=target)).status_code == 200
    wrong = {**target, "identity": {**identity, "work_token": "z" * 43}}
    assert (await client.post("/api/v1/cloud/worker/resolution/assert", headers=headers, json=wrong)).status_code == 409
    result = {"repositories": {
        "sut": {"url": ORIGIN, "commit_sha": SHA, "selector": claimed["task"]["inputs"]["sut_selector"]},
        "framework": {"url": FRAMEWORK_ORIGIN, "commit_sha": FRAMEWORK_SHA,
                      "selector": claimed["task"]["inputs"]["framework_selector"]}},
        "environment_observation": {"state": "UNOBSERVED"},
        "observed_at": datetime.now(UTC).isoformat(), "source": "synthetic-no-git"}
    resolved = await client.post("/api/v1/cloud/worker/resolution/accept", headers=headers, json={**target, "result": result})
    assert resolved.status_code == 200, resolved.text
    sent = await post(context, "DISPATCH", resolved.json()["version"], task_id=task_id,
                      resolution_id=requested.json()["resolution_id"])
    assert sent.status_code == 200, sent.text
    attempt_claim = await client.post("/api/v1/cloud/worker/claim", headers=headers,
                                      json={"worker_id": "fixture-host-worker", "lease_seconds": 90})
    assert attempt_claim.status_code == 200 and attempt_claim.json()["kind"] == "ATTEMPT"
    claim = attempt_claim.json()["claim"]
    identity = {"worker_id": "fixture-host-worker", "lease_token": claim["lease_token"],
                "work_token": claim["work_token"], "generation": claim["generation"]}
    body = {"project_id": project_id, "task_id": task_id, "attempt_id": claim["attempt"]["id"], "identity": identity}
    payload = {"profile": "cloud-harness-task/v1alpha1", "project_id": project_id, "task_id": task_id,
               "attempt_id": body["attempt_id"], "operation": "TRANSITION", "operation_key": "worker:" + uuid4().hex,
               "expected_version": claim["task"]["version"], "status": "RUNNING", "reason": "synthetic"}
    submitted = await client.post("/api/v1/cloud/worker/submit", headers=headers, json={**body, "payload": payload})
    assert submitted.status_code == 200, submitted.text
    receipt = submitted.json()
    assert (await client.post("/api/v1/cloud/worker/page", headers=headers,
                              json={**body, "version": receipt["version"]})).status_code == 200
    fenced = await client.post("/api/v1/cloud/worker/fence", headers=headers, json={**body, "reason": "WORKER_INTERRUPTED"})
    assert fenced.status_code == 200, fenced.text
    assert (await client.post("/api/v1/cloud/worker/assert", headers=headers, json=body)).status_code == 409
    original = await client.post("/api/v1/cloud/worker/receipt", headers=headers,
                                 json={**body, "operation_key": payload["operation_key"]})
    assert original.status_code == 200 and original.json() == receipt
    wrong = {**body, "identity": {**identity, "work_token": "z" * 43}, "operation_key": payload["operation_key"]}
    assert (await client.post("/api/v1/cloud/worker/receipt", headers=headers, json=wrong)).status_code == 403


async def test_host_worker_synthetic_handoff_roundtrip(cloud_context, monkeypatch, tmp_path):
    """Exercise real API + Worker reporting with a fake SDK, never a model or SUT."""
    context = cloud_context
    settings = get_settings()
    token = "worker-integration-" + "y" * 40
    key = tmp_path / "worker-token"
    key.write_text(token)
    key.chmod(0o600)
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_api_token_file", str(key))
    monkeypatch.setattr(settings, "cloud_worker_api_worker_id", "fixture-host-worker")
    queued = await dispatched(context)
    claim_response = await context["client"].post("/api/v1/cloud/worker/claim",
        headers={"Authorization": "Bearer " + token}, json={"worker_id": "fixture-host-worker", "lease_seconds": 90})
    assert claim_response.status_code == 200 and claim_response.json()["kind"] == "ATTEMPT"
    claim = claim_response.json()["claim"]

    async def checkout(_self, _repository, path):
        path.mkdir()

    class FakeProcess:
        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.returncode = None
            self.done = asyncio.Event()

        async def wait(self):
            await self.done.wait()
            return self.returncode

    class FakeAdapter:
        def __init__(self, *, workspace, dsh_home):
            self.workspace = workspace

        async def start(self, *, session_id, prompt):
            process = FakeProcess()
            envelope = json.loads(prompt)
            task_id, attempt_id = envelope["task_id"], envelope["attempt_id"]
            ready = self.workspace / ".hypertest-cloud" / "ready"
            ready.mkdir(parents=True)

            async def produce():
                assets = [
                    {"kind": "ANALYSIS", "key": "analysis", "title": "Synthetic", "markdown": "Fixture only"},
                    {"kind": "DESIGN", "key": "design", "title": "Synthetic", "markdown": "Fixture only"},
                    {"kind": "CASE", "key": "case", "title": "Synthetic", "reported_result": "NOT_RUN",
                     "details": {"steps": ["None"], "expected": "None", "actual": "Not run"}},
                    {"kind": "IMPLEMENTATION", "key": "impl", "title": "Synthetic", "markdown": "No changes",
                     "details": {"framework_sha": FRAMEWORK_SHA, "cwd": "framework", "dirty_files": [],
                                 "untracked_files": [], "test_tree_digest": "3" * 64}},
                    {"kind": "REPORT", "key": "report", "title": "Synthetic", "markdown": "No model or SUT",
                     "reported_result": "NOT_RUN"},
                ]

                def emit(key, operation, payload):
                    document = {"profile": "hypertest-cloud-handoff/v1alpha1", "task_id": task_id,
                                "attempt_id": attempt_id, "key": key, "operation": operation, "payload": payload}
                    (ready / (key + ".json")).write_text(json.dumps(document))

                emit("assets", "SUBMIT_ASSETS", {"assets": assets})
                receipt = self.workspace / ".hypertest-cloud" / "receipts" / "assets.json"
                for _ in range(100):
                    if receipt.exists():
                        break
                    await asyncio.sleep(0.05)
                if not receipt.exists():
                    process.returncode = 1
                else:
                    data = json.loads(receipt.read_text())
                    report_id = next(row["id"] for row in data["assets"] if row["kind"] == "REPORT")
                    emit("finish", "COMPLETE_ATTEMPT", {"final_report_revision": report_id,
                        "reported_result": "NOT_RUN", "completion_manifest": {
                            "required_asset_ids": [row["id"] for row in data["assets"]],
                            "no_tests_reason": "Synthetic protocol test", "scope_and_gaps": "No model or SUT"}})
                    process.returncode = 0
                process.stdout.feed_eof()
                process.done.set()

            asyncio.create_task(produce())
            return process

        async def stop(self):
            return {"direct_process_stopped": True}

    monkeypatch.setattr(native_git.NativeGitResolver, "checkout", checkout)
    monkeypatch.setattr(native_sdk_adapter, "NativeSdkAdapter", FakeAdapter)
    api = native_worker.WorkerAPI("https://localhost", token.encode())
    await api.client.aclose()
    api.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://localhost/",
                                   headers={"Authorization": "Bearer " + token})
    state = tmp_path / "worker-state"
    state.mkdir(mode=0o700)
    args = SimpleNamespace(worker_id="fixture-host-worker", dsh_home=str(tmp_path), lease_seconds=90)
    try:
        await native_worker.execute(api, args, state, claim)
    finally:
        await api.close()
    detail = await context["client"].get(f"/api/v1/cloud/tasks/{queued['task_id']}",
        headers=context["headers"], params={"project_id": context["project_id"]})
    assert detail.status_code == 200
    assert detail.json()["complete"]
    data = json.loads(detail.json()["content"])
    assert data["task"]["status"] == "COMPLETED" and data["task"]["reported_result"] == "NOT_RUN"
    checkpoint = data["attempts"][0]["checkpoint"]
    assert checkpoint["native_completion_observation"] == {"runtime": "DIRECT_SDK_PROCESS_EXITED",
        "other_local_processes": "UNKNOWN", "external_operations": "NOT_OBSERVED"}
    assert checkpoint["external_operations_reconciled"] is False
