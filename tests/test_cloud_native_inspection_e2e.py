"""Synthetic API/Worker/fixed-SDK inspection; never uses an external provider or SUT."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import os
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import test_cloud_tasks
from sqlalchemy import select
from test_cloud_native_cordis_sdk import _FakeProvider
from test_cloud_native_session_anchor import _anchor, _payload
from test_cloud_native_session_restore_sdk import _synthetic_git
from test_cloud_tasks import cloud_context as cloud_context
from test_cloud_tasks import dispatched, worker_submit

from hypertest.application import cloud_tasks as service
from hypertest.cloud import native_cordis, native_session_restore, native_worker
from hypertest.cloud.native_resume_identity import record_initial_identity
from hypertest.cloud.native_sdk_adapter import host_environment
from hypertest.cloud.native_selection import read_native_selection
from hypertest.cloud.worker import save_once
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import (
    CloudAttempt,
    CloudNativeSessionRestore,
    CloudRunRecord,
    CloudTask,
)
from hypertest.main import app


@pytest.mark.asyncio
async def test_original_session_inspection_through_api_worker_and_fixed_sdk(cloud_context, monkeypatch, tmp_path):
    sdk = pytest.importorskip("deepseek_harness")
    runtime = pytest.importorskip("deepseek_harness_runtime")
    binary = Path(runtime.resolve_bundled_launch_args()[0])
    with binary.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != native_cordis._RUNTIME_SHA256:
            pytest.skip("the audited native SDK runtime is not installed")
    python = next((p / "bin/python" for p in Path(runtime.__file__).resolve().parents
                   if (p / "bin/python").is_file()), None)
    if python is None:
        pytest.skip("the audited SDK virtual environment is unavailable")

    root = tmp_path.resolve()
    staged = root / "staged"
    staged.mkdir()
    sut_sha = _synthetic_git(staged / "sut")
    framework_sha = _synthetic_git(staged / "framework")
    monkeypatch.setattr(test_cloud_tasks, "SHA", sut_sha)
    settings = get_settings()
    monkeypatch.setattr(settings, "cloud_native_session_inspection_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    worker_id = "e2e-worker-" + uuid4().hex
    token = "synthetic-worker-token-" + uuid4().hex
    token_file = root / "worker-token"
    token_file.write_text(token)
    token_file.chmod(0o600)
    monkeypatch.setattr(settings, "cloud_worker_api_token_file", str(token_file))
    monkeypatch.setattr(settings, "cloud_worker_api_worker_id", worker_id)

    context = cloud_context
    dispatched_receipt = await dispatched(context, framework_sha=framework_sha)
    async with AsyncSessionLocal() as db:
        claim = await service.claim_attempt(db, worker_id, project_id=UUID(context["project_id"]))
    assert claim["attempt"]["id"] == dispatched_receipt["attempt_id"]
    original_writer = service.WorkerIdentity(worker_id, claim["lease_token"], claim["generation"], claim["work_token"])

    state = root / "state"
    state.mkdir(mode=0o700)
    attempt_root = state / ("attempt-" + dispatched_receipt["attempt_id"])
    attempt_root.mkdir(mode=0o700)
    workspace = attempt_root / "workspace"
    workspace.mkdir(mode=0o700)
    shutil.move(staged / "sut", workspace / "sut")
    shutil.move(staged / "framework", workspace / "framework")
    home = root / "synthetic-dsh"
    profile = home / "profiles" / "sdk"
    profile.mkdir(parents=True)
    (profile / "package.json").write_text(json.dumps({"name": "dsh-profile-sdk", "private": True,
        "dependencies": {}, "dsh": {"profile": {"bundles": [*native_session_restore._BASE,
                                                *sorted(native_session_restore._EXPERIMENTAL)]}}}))
    (profile / "cordis.patch.yml").write_text("[]\n")

    provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeProvider)
    provider.request_count = 0
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    fake_env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "LANG": "C.UTF-8",
                "DEEPSEEK_API_KEY": "synthetic-only", "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{provider.server_port}/v1"}
    monkeypatch.setattr(os, "environ", fake_env)
    native_env = host_environment(dict(fake_env))
    session_id = "cloud-" + dispatched_receipt["attempt_id"]
    prompt = "Synthetic session for isolated restoration."
    selection = read_native_selection(dsh_home=str(home), cwd=str(workspace), environment=native_env)
    original = {"project_id": context["project_id"], "task_id": dispatched_receipt["task_id"],
        "attempt_id": dispatched_receipt["attempt_id"], "session_id": session_id,
        "worker_id": worker_id, "original_generation": original_writer.generation,
        "input_digest": dispatched_receipt["input_digest"], "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "title_sha256": hashlib.sha256(claim["task"]["title"].encode()).hexdigest(),
        "workspace": workspace, "dsh_home": home, "sut_commit": sut_sha, "framework_commit": framework_sha,
        "selection": selection, "environment": native_env}
    try:
        snapshot = record_initial_identity(attempt_root, **original)
        anchor = await _anchor(_payload(context, dispatched_receipt, snapshot_sha256=snapshot), original_writer)
        running = await worker_submit(context, original_writer, anchor, "TRANSITION", status="RUNNING", reason="synthetic")
        save_once(attempt_root / "prompt-intent.json", {"state": "SENT", "session_id": session_id,
                  "prompt_sha256": original["prompt_sha256"]})

        # The only model endpoint is a loopback server that returns a synthetic
        # 401. Its response is irrelevant; it creates one persisted SDK session.
        def create_session():
            with sdk.HarnessClient(sdk.HarnessConfig(profile="sdk", dsh_home=str(home), cwd=str(workspace),
                                                     env=fake_env, request_timeout_seconds=10)) as client:
                client.initialize(cwd=str(workspace), **selection)
                client.session_prompt(session_id, [{"type": "text", "text": prompt}])
                deadline = time.monotonic() + 8
                while not provider.request_count and time.monotonic() < deadline:
                    time.sleep(.05)
                assert provider.request_count > 0
        await asyncio.to_thread(create_session)
        provider_before = provider.request_count

        report = b"synthetic existing failure"
        artifact = await worker_submit(context, original_writer, running, "UPLOAD_ARTIFACT", filename="failure.txt",
            media_type="text/plain", content_base64=base64.b64encode(report).decode(), byte_count=len(report),
            sha256=hashlib.sha256(report).hexdigest())
        assets = await worker_submit(context, original_writer, artifact, "SUBMIT_ASSETS", assets=[{
            "kind": "CASE", "key": "fixture-case", "title": "Synthetic case", "reported_result": "FAIL",
            "details": {"steps": ["Synthetic"], "expected": "yes", "actual": "no"}}])
        case_id = assets["assets"][0]["id"]
        now = datetime.now(UTC).isoformat()
        run = await worker_submit(context, original_writer, assets, "SUBMIT_RUN", run_key="original-failure",
            execution={"source": "PROJECT_FRAMEWORK", "actual_sut_build": "UNKNOWN", "framework_sha": framework_sha,
                "test_tree_digest": "3" * 64, "environment_observation": {"source": "synthetic-fixture"},
                "entrypoint": "python -m pytest", "cwd": "framework", "framework_version": "synthetic",
                "started_at": now, "finished_at": now, "exit_code": 1}, reported_result="FAIL",
            report_artifact_ids=[artifact["artifact_id"]],
            cases=[{"case_revision_id": case_id, "actual": "no", "reported_result": "FAIL"}])
        async with AsyncSessionLocal() as db:
            await service.fence_attempt_for_recovery(db, UUID(dispatched_receipt["task_id"]),
                UUID(dispatched_receipt["attempt_id"]), original_writer, "WORKER_INTERRUPTED")

        request = {"project_id": context["project_id"], "task_id": dispatched_receipt["task_id"],
            "attempt_id": dispatched_receipt["attempt_id"], "expected_version": run["version"],
            "operation": "INSPECT_NATIVE_SESSION", "operation_key": "synthetic-inspection-original",
            "anchor_operation_key": "native-anchor-original",
            "reconciliation": {"old_owner_fenced": True, "local_processes_stopped": True,
                "external_operations_reconciled": True, "observations": "Only isolated synthetic processes were used."}}
        accepted = await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"], json=request)
        assert accepted.status_code == 200, accepted.text
        assert (await context["client"].post("/api/v1/cloud/operations", headers=context["operator_headers"],
                                            json=request)).json() == accepted.json()

        # The real Worker calls the real API through ASGI, and a real SDK child
        # opens the persisted session. Simulate a lost *finish* response only
        # after the server commits; the Worker must query the same original key.
        api = native_worker.WorkerAPI("https://localhost", token.encode())
        await api.client.aclose()
        api.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://localhost/",
                                       headers={"Authorization": "Bearer " + token})
        requests = []
        class LostFinish:
            async def request(self, operation, body):
                requests.append(operation)
                result = await api.request(operation, body)
                if operation == "native-session-inspection/finish":
                    raise TimeoutError("synthetic lost finish response")
                return result

        monkeypatch.setattr(native_session_restore, "sys", SimpleNamespace(executable=str(python)))
        args = SimpleNamespace(worker_id=worker_id, dsh_home=str(home), lease_seconds=90, poll_seconds=.05, once=False)
        try:
            assert await native_worker.inspect_next_original_session(LostFinish(), args, state)
        finally:
            await api.close()
        assert requests.count("native-session-inspection/claim") == 1
        assert requests.count("native-session-inspection/finish") == 1
        assert requests.count("native-session-inspection/claim-state") == 1
        assert provider.request_count == provider_before
        assert not (state / "inspection-claim-pending.json").exists()
        async with AsyncSessionLocal() as db:
            task = await db.get(CloudTask, UUID(dispatched_receipt["task_id"]))
            attempt = await db.get(CloudAttempt, UUID(dispatched_receipt["attempt_id"]))
            runs = list(await db.scalars(select(CloudRunRecord).where(CloudRunRecord.attempt_id == attempt.id)))
            observation = await db.scalar(select(CloudNativeSessionRestore).where(
                CloudNativeSessionRestore.attempt_id == attempt.id))
            assert task.latest_attempt_id == attempt.id and task.status == attempt.status == "RECOVERY_REQUIRED"
            assert task.reported_result == attempt.reported_result == "NOT_RUN"
            assert len(runs) == 1 and runs[0].reported_result == "FAIL"
            assert observation.state == "RESTORED" and observation.observation["prompt_sent"] is False
            assert observation.observation["continuation_started"] is False
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=5)
