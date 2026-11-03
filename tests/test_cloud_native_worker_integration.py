"""Real API/DB Worker fencing against a dedicated synthetic test database."""

import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from test_cloud_tasks import (
    FRAMEWORK_ORIGIN,
    FRAMEWORK_SHA,
    ORIGIN,
    SHA,
    dispatched,
    draft,
    inputs,
    legacy_claimed,
    new_inputs,
    post,
    read_all,
    worker_submit,
)
from test_cloud_tasks import cloud_context as cloud_context

from hypertest.application import cloud_tasks as service
from hypertest.cloud import native_git, native_sdk_adapter, native_worker
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudAttempt, CloudTask
from hypertest.main import app


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

        async def start(self, *, session_id, prompt, interaction_enabled=False):
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


async def native_report_ready(context, monkeypatch, tmp_path, *, reported="NOT_RUN"):
    """Prepare a real Worker API delivery with synthetic report data, never an SDK/SUT."""
    settings = get_settings()
    token = "native-management-" + "z" * 40
    key = tmp_path / "worker-token"
    key.write_text(token)
    key.chmod(0o600)
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_api_token_file", str(key))
    monkeypatch.setattr(settings, "cloud_worker_api_worker_id", "native-management")
    queued = await dispatched(context, task_inputs=new_inputs(expected_outputs=["REPORT"]))
    async with AsyncSessionLocal() as db:
        claim = await service.claim_attempt(db, "native-management", project_id=UUID(context["project_id"]))
    identity = {"worker_id": "native-management", "lease_token": claim["lease_token"],
                "work_token": claim["work_token"], "generation": claim["generation"]}
    common = {"project_id": context["project_id"], "task_id": queued["task_id"], "attempt_id": queued["attempt_id"]}
    state = SimpleNamespace(**common, version=claim["task"]["version"])

    async def submit(operation, **fields):
        response = await context["client"].post("/api/v1/cloud/worker/submit",
            headers={"Authorization": "Bearer " + token}, json={**common, "identity": identity, "payload": {
                **common, "operation": operation, "operation_key": "native-" + uuid4().hex,
                "expected_version": state.version, **fields}})
        if response.status_code == 200:
            state.version = response.json()["version"]
        return response

    running = await submit("TRANSITION", status="RUNNING", reason="Synthetic native lifecycle regression")
    assert running.status_code == 200, running.text
    state.report_bytes = json.dumps({"source": "synthetic-no-SDK-or-SUT", "reported_result": reported}).encode()
    uploaded = await submit("UPLOAD_ARTIFACT", filename="synthetic-report.json", media_type="application/json",
        content_base64=base64.b64encode(state.report_bytes).decode(), byte_count=len(state.report_bytes),
        sha256=hashlib.sha256(state.report_bytes).hexdigest())
    assert uploaded.status_code == 200, uploaded.text
    state.artifact_id = uploaded.json()["artifact_id"]
    assets = await submit("SUBMIT_ASSETS", assets=[{"kind": "REPORT", "key": "final", "title": "Synthetic report",
        "artifact_id": state.artifact_id, "markdown": "API lifecycle fixture; no SDK or SUT", "reported_result": reported}])
    assert assets.status_code == 200, assets.text
    state.report_id = assets.json()["assets"][0]["id"]
    if reported == "FAIL":
        now = datetime.now(UTC).isoformat()
        run = await submit("SUBMIT_RUN", run_key="synthetic-failure", reported_result="FAIL",
            execution={"source": "PROJECT_FRAMEWORK", "actual_sut_build": "SYNTHETIC", "framework_sha": FRAMEWORK_SHA,
                "test_tree_digest": "3" * 64, "environment_observation": {"source": "synthetic-no-SDK-or-SUT"},
                "entrypoint": "python -m pytest", "cwd": "framework", "framework_version": "synthetic-fixture",
                "started_at": now, "finished_at": now, "exit_code": 1}, report_artifact_ids=[state.artifact_id])
        assert run.status_code == 200, run.text
    state.completion = {"final_report_revision": state.report_id, "reported_result": reported,
        "completion_manifest": {"required_asset_ids": [state.report_id],
            "no_tests_reason": "Synthetic lifecycle fixture" if reported == "NOT_RUN" else None,
            "all_local_processes_stopped": False, "external_operations_reconciled": False,
            "pending_operation_keys": [], "scope_and_gaps": "Synthetic API regression only"},
        "usage_seconds": 0, "cost_microunits": 0, "runtime_observation": "DIRECT_SDK_PROCESS_EXITED"}
    state.submit = submit
    return state


async def manage_terminal(context, receipt, operation):
    fields = {"task_id": receipt["task_id"]}
    if operation == "DISPATCH":
        fields.update(retry_of_attempt_id=receipt["attempt_id"], retry_scope_confirmed=True,
            retry_authorization_confirmed=True, reason="Review synthetic result and start a new attempt",
            retry_inputs={"objective": "Retest synthetic scope", "test_scope": "Fixture only", "basic_flow": "Read fixture",
                "framework_entrypoints": ["python -m pytest"], "authorization": inputs()["authorization"]})
    return await post(context, operation, receipt["version"], **fields)


@pytest.mark.parametrize("reported,operation", [("NOT_RUN", "DISPATCH"), ("FAIL", "DISPATCH"), ("FAIL", "DELETE_TASK")])
async def test_native_completion_allows_management_without_rewriting_observations(
    cloud_context, monkeypatch, tmp_path, reported, operation,
):
    context = cloud_context
    ready = await native_report_ready(context, monkeypatch, tmp_path, reported=reported)
    completed = await ready.submit("COMPLETE_NATIVE_ATTEMPT", **ready.completion)
    assert completed.status_code == 200, completed.text
    receipt = completed.json()
    original = await read_all(context, ready.task_id, receipt["version"])
    old_attempt = original["attempts"][0]
    assert original["task"]["status"] == "COMPLETED" and original["task"]["reported_result"] == reported
    assert old_attempt["checkpoint"]["external_operations_reconciled"] is False
    assert old_attempt["checkpoint"]["native_completion_observation"] == {
        "runtime": "DIRECT_SDK_PROCESS_EXITED", "other_local_processes": "UNKNOWN", "external_operations": "NOT_OBSERVED"}
    summary = await context["client"].get(f"/api/v1/cloud/tasks/{ready.task_id}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert summary.status_code == 200, summary.text
    assert summary.json()["management"] == {"can_retry": True, "retry_blocking_reasons": [],
        "can_delete": True, "delete_blocking_reasons": [], "native_scope_unobserved": True}
    accepted = await manage_terminal(context, receipt, operation)
    assert accepted.status_code == 200, accepted.text
    current = await read_all(context, ready.task_id, accepted.json()["version"])
    assert current["attempts"][0] == old_attempt
    assert current["assets"] == original["assets"] and current["runs"] == original["runs"]
    if operation == "DISPATCH":
        assert accepted.json()["attempt_id"] != ready.attempt_id
        assert current["attempts"][1]["status"] == "QUEUED"
        assert current["attempts"][1]["execution_manifest"]["retry_of_attempt_id"] == ready.attempt_id
        assert current["task"]["frozen_manifest"] == original["task"]["frozen_manifest"]
    else:
        assert current["task"]["deleted_at"] and current["task"]["status"] == "COMPLETED"
    assert await read_all(context, ready.task_id, receipt["version"]) == original
    raw = await context["client"].get(f"/api/v1/cloud/tasks/{ready.task_id}/artifacts/{ready.artifact_id}",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert raw.status_code == 200 and base64.b64decode(raw.json()["content_base64"]) == ready.report_bytes


async def test_native_completion_still_rejects_known_pending_operation(cloud_context, monkeypatch, tmp_path):
    context = cloud_context
    ready = await native_report_ready(context, monkeypatch, tmp_path)
    # Only the dedicated synthetic database is changed; no external request is sent.
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(ready.attempt_id))
        attempt.checkpoint = {**attempt.checkpoint, "pending_operation_keys": ["original-unknown-key"],
                              "external_operations_reconciled": False}
        await db.commit()
    denied = await ready.submit("COMPLETE_NATIVE_ATTEMPT", **ready.completion)
    assert denied.status_code == 409 and denied.json()["detail"] == "Runtime checkpoint still contains unresolved operation keys"
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(ready.attempt_id))
        assert attempt.status == "RUNNING" and attempt.checkpoint["pending_operation_keys"] == ["original-unknown-key"]


async def test_native_completion_marker_without_accepted_delivery_cannot_unlock_management(
    cloud_context, monkeypatch, tmp_path,
):
    context = cloud_context
    ready = await native_report_ready(context, monkeypatch, tmp_path)
    # Adversarial legacy fixture: a marker and report exist, but no native completion
    # was accepted. Fence before the synthetic terminal transition, never edit history.
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(ready.attempt_id))
        task = await db.get(CloudTask, UUID(ready.task_id))
        await service._fence(db, attempt)
        attempt.checkpoint = {"completion_manifest": ready.completion["completion_manifest"],
            "final_report_revision": ready.report_id, "external_operations_reconciled": False,
            "native_completion_observation": {"runtime": "DIRECT_SDK_PROCESS_EXITED",
                "other_local_processes": "UNKNOWN", "external_operations": "NOT_OBSERVED"}}
        attempt.status = task.status = "COMPLETED"
        attempt.ended_at = datetime.now(UTC)
        await db.commit()
    receipt = {"task_id": ready.task_id, "attempt_id": ready.attempt_id, "version": ready.version}
    for operation in ("DISPATCH", "DELETE_TASK"):
        assert (await manage_terminal(context, receipt, operation)).status_code == 409


async def test_native_completion_requires_fenced_owner_for_management(cloud_context, monkeypatch, tmp_path):
    context = cloud_context
    ready = await native_report_ready(context, monkeypatch, tmp_path)
    completed = await ready.submit("COMPLETE_NATIVE_ATTEMPT", **ready.completion)
    assert completed.status_code == 200, completed.text
    original = await read_all(context, ready.task_id, completed.json()["version"])

    async def owner_not_fenced(_db, _attempt):
        return False

    monkeypatch.setattr(service, "_owner_fenced", owner_not_fenced)
    for operation in ("DISPATCH", "DELETE_TASK"):
        assert (await manage_terminal(context, completed.json(), operation)).status_code == 409
    summary = await context["client"].get(f"/api/v1/cloud/tasks/{ready.task_id}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert summary.status_code == 200, summary.text
    controls = summary.json()["management"]
    assert controls["can_retry"] is controls["can_delete"] is False
    assert "OLD_OWNER_NOT_FENCED" in controls["retry_blocking_reasons"]
    assert "OLD_OWNER_NOT_FENCED" in controls["delete_blocking_reasons"]
    assert await read_all(context, ready.task_id, completed.json()["version"]) == original


@pytest.mark.parametrize("blocker", ["CLOUD_ACTION_BUSINESS_UNRECONCILED", "CLOUD_CONTAINER_UNRECONCILED"])
async def test_native_completion_does_not_bypass_known_operation_or_container(
    cloud_context, monkeypatch, tmp_path, blocker,
):
    from hypertest.application import cloud_ssh

    context = cloud_context
    ready = await native_report_ready(context, monkeypatch, tmp_path)
    completed = await ready.submit("COMPLETE_NATIVE_ATTEMPT", **ready.completion)
    assert completed.status_code == 200, completed.text
    original = await read_all(context, ready.task_id, completed.json()["version"])

    async def unresolved(_db, task_id):
        assert task_id == UUID(ready.task_id)
        raise HTTPException(409, blocker)

    if blocker == "CLOUD_CONTAINER_UNRECONCILED":
        monkeypatch.setattr(service, "_ensure_container_closed", unresolved)
    else:
        monkeypatch.setattr(cloud_ssh, "ensure_remote_closed", unresolved)
    for operation in ("DISPATCH", "DELETE_TASK"):
        denied = await manage_terminal(context, completed.json(), operation)
        assert denied.status_code == 409 and denied.json()["detail"] == blocker
    summary = await context["client"].get(f"/api/v1/cloud/tasks/{ready.task_id}/summary",
        params={"project_id": context["project_id"]}, headers=context["headers"])
    assert summary.status_code == 200, summary.text
    controls = summary.json()["management"]
    assert controls["can_retry"] is controls["can_delete"] is False
    assert blocker in controls["retry_blocking_reasons"] and blocker in controls["delete_blocking_reasons"]
    assert await read_all(context, ready.task_id, completed.json()["version"]) == original


async def test_legacy_unreconciled_terminal_is_not_unlocked_by_native_management(cloud_context):
    context = cloud_context
    receipt, _, identity = await legacy_claimed(context)
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(receipt["attempt_id"]))
        attempt.checkpoint = {**attempt.checkpoint, "external_operations_reconciled": False}
        await db.commit()
    terminal = await worker_submit(context, identity, receipt, "TRANSITION", status="FAILED",
        reason="Synthetic legacy external scope remains unobserved")
    original = await read_all(context, receipt["task_id"], terminal["version"])
    assert original["attempts"][0]["runtime_metadata"]["preparation_budget_reservation"]["state"] == "HELD"
    for operation in ("DISPATCH", "DELETE_TASK"):
        assert (await manage_terminal(context, terminal, operation)).status_code == 409
    assert await read_all(context, receipt["task_id"], terminal["version"]) == original
