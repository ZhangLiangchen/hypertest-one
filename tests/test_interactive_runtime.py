"""Real current-Agent HTTP binding and Worker coordination, without a shadow CLI."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_harness_tools import result_input
from test_source_transfer_api import authorize
from test_source_transfer_api import repository as _repository
from test_source_transfer_api import transfer_fixture as _transfer_fixture

from hypertest.application.jobs import cancel_job, claim_job, finish_job
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.bindings import RunExecutionBinding
from hypertest.domain.interactive import InteractiveExecutionBinding, InteractiveExecutionGrant
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob, JobStatus
from hypertest.domain.models import AgentSessionRecord, SourceSnapshot
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app
from hypertest.worker import run_claimed_job

repository = _repository
transfer_fixture = _transfer_fixture


@pytest.fixture
async def interactive_context(transfer_fixture, monkeypatch):
    f = transfer_fixture
    monkeypatch.setattr(get_settings(), "worker_heartbeat_seconds", 0.05)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost"
    ) as client:
        auth = await authorize(client, f)
        accepted = await client.put(
            f"/api/v1/source-transfers/{f['row_id']}/content",
            headers={
                "Authorization": "Bearer " + f["token"],
                "X-Source-Upload-Token": auth.json()["upload_token"],
            },
            content=f["content"],
        )
        assert accepted.status_code == 200, accepted.text
        capability = await client.post(
            f"/api/v1/harness-nodes/{f['node_id']}/capabilities",
            headers={"X-Hypertest-Operator-Key": "test-source-operator"},
            json={
                "project_id": str(f["project_id"]),
                "capability": "harness",
                "constraints": {"interactive_host_adapters": ["fixture-current-agent/v1"]},
            },
        )
        assert capability.status_code == 201, capability.text
        registration = await client.post(
            "/api/v1/interactive/registrations",
            headers={"X-Hypertest-Operator-Key": "test-source-operator"},
            json={
                "actor_ref": "current-agent-" + uuid4().hex,
                "client_instance_id": str(uuid4()),
                "project_id": str(f["project_id"]),
                "scopes": [
                    "task:submit",
                    "run:execute",
                    "run:read",
                    "evidence:read",
                    "report:read",
                ],
            },
        )
        assert registration.status_code == 201, registration.text
        headers = {
            "Authorization": "Bearer " + registration.json()["integration_token"],
            "X-Hypertest-Device-Token": f["token"],
        }
        request = {
            "project_id": str(f["project_id"]),
            "submission_key": "current-" + uuid4().hex,
            "execution_mode": "LOCAL",
            "execution_driver": "INTERACTIVE_MCP",
            "budget": {"max_steps": 32},
            "bootstrap": {
                "repository_url": f["origin"],
                "commit_sha": f["receipt"]["commit_sha"],
                "prd_text": "Executing the application prints pinned followed by one newline.",
                "harness_mode": "LOCAL_CONNECTOR",
                "harness_node_id": str(f["node_id"]),
                "source_bundle_transfer_id": str(f["row_id"]),
            },
        }
        submitted = await client.post(
            "/api/v1/interactive/submissions", headers=headers, json=request
        )
        assert submitted.status_code == 201, submitted.text
        receipt = submitted.json()
        proof = {
            "schema_version": "hypertest.host-attestation/v1alpha1",
            "adapter_id": "fixture-current-agent/v1",
            "provider": "codex",
            "harness": "codex",
            "native_session_id": str(uuid4()),
            "node_id": str(f["node_id"]),
            "workspace_id": uuid7().hex,
            "source_bundle_transfer_id": str(f["row_id"]),
            "attachment_id": "fixture-attachment-" + uuid4().hex,
            "observed_at": datetime.now(UTC).isoformat(),
            "lifecycle": "ACTIVE",
        }
        f.update(
            client=client,
            headers=headers,
            submission_receipt=receipt,
            submission_request=request,
            run_id=UUID(receipt["test_run_id"]),
            job_id=UUID(receipt["initial_job_id"]),
            proof=proof,
            attach_key="attach-" + uuid4().hex,
            tasks=[],
        )
        from hypertest.application.runtime_control import serve_runtime_control

        control_stopping = asyncio.Event()
        control_task = asyncio.create_task(
            serve_runtime_control(AsyncSessionLocal, control_stopping),
            name="interactive-control-fixture",
        )
        f["control_task"] = control_task
        try:
            yield f
        finally:
            control_stopping.set()
            await control_task
            async with AsyncSessionLocal() as db:
                jobs = list(
                    await db.scalars(
                        select(DurableJob).where(
                            DurableJob.project_id == f["project_id"],
                            DurableJob.status.in_(ACTIVE_JOB_STATUSES),
                        )
                    )
                )
                for job in jobs:
                    token = job.lease_token
                    result = await cancel_job(db, job.id)
                    if not f["tasks"] and result.status == JobStatus.CANCEL_REQUESTED:
                        await finish_job(db, job.id, token)
            for task in f["tasks"]:
                try:
                    await asyncio.wait_for(asyncio.shield(task), 5)
                except (TimeoutError, asyncio.CancelledError):
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


async def bind(f, **changes):
    payload = {
        "run_id": str(f["run_id"]),
        "attach_key": f["attach_key"],
        "host_proof": f["proof"],
        **changes,
    }
    return await f["client"].post(
        "/api/v1/interactive/executions/bind", headers=f["headers"], json=payload
    )


async def start(f):
    response = await bind(f)
    assert response.status_code == 201, response.text
    f["execution_id"] = response.json()["id"]
    async with AsyncSessionLocal() as db:
        job = await claim_job(db, "interactive-fixture", lease_seconds=130, run_id=f["run_id"])
        assert job and job.id == f["job_id"]
    task = asyncio.create_task(run_claimed_job(job))
    f["tasks"].append(task)
    for _ in range(100):
        response = await f["client"].get(
            "/api/v1/interactive/executions/by-key",
            headers=f["headers"],
            params={"run_id": str(f["run_id"]), "attach_key": f["attach_key"]},
        )
        if response.json().get("execute_ready"):
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("coordinator never admitted original current-Agent binding")
    proof = {**f["proof"], "observed_at": datetime.now(UTC).isoformat()}
    continuation = await f["client"].post(
        f"/api/v1/interactive/executions/{f['execution_id']}/continue",
        headers=f["headers"],
        json={"continuation_key": "continue-" + uuid4().hex, "host_proof": proof},
    )
    assert continuation.status_code == 200, continuation.text
    f["execution_headers"] = {
        **f["headers"],
        "X-Hypertest-Execution-Token": continuation.json()["execution_token"],
    }
    return continuation


async def tool(f, name, args):
    response = await f["client"].post(
        f"/api/v1/interactive/executions/{f['execution_id']}/tools/{name}",
        headers=f["execution_headers"],
        json={"arguments": args},
    )
    assert response.status_code == 200, response.text
    envelope = response.json()
    for _ in range(200):
        if envelope["status"] not in {"QUEUED", "RUNNING"}:
            break
        await asyncio.sleep(0.05)
        response = await f["client"].get(
            f"/api/v1/interactive/executions/{f['execution_id']}/tools/by-key",
            headers=f["headers"],
            params={"tool_name": name, "idempotency_key": envelope["request_key"]},
        )
        assert response.status_code == 200, response.text
        envelope = response.json()
    assert envelope["status"] == "SUCCEEDED", envelope
    return envelope["result"]


async def test_bind_is_structural_current_native_unique_and_tools_require_live_claim(
    interactive_context,
):
    f = interactive_context
    async with AsyncSessionLocal() as db:
        assert await claim_job(db, "before-bind", run_id=f["run_id"]) is None
    invalid = await bind(f, host_proof={**f["proof"], "adapter_id": "model-provided-fake"})
    assert invalid.status_code == 403
    no_device = await f["client"].post(
        "/api/v1/interactive/executions/bind",
        headers={"Authorization": f["headers"]["Authorization"]},
        json={"run_id": str(f["run_id"]), "attach_key": f["attach_key"], "host_proof": f["proof"]},
    )
    assert no_device.status_code == 403
    bound = await bind(f)
    assert bound.status_code == 201, bound.text
    assert bound.json()["execute_ready"] is False
    repeated = await bind(f)
    assert (
        repeated.status_code == 201 and repeated.json()["binding_id"] == bound.json()["binding_id"]
    )
    changed = await bind(f, host_proof={**f["proof"], "native_session_id": str(uuid4())})
    assert changed.status_code == 409
    another = await f["client"].post(
        "/api/v1/interactive/submissions",
        headers=f["headers"],
        json={**f["submission_request"], "submission_key": "second-" + uuid4().hex},
    )
    assert another.status_code == 201, another.text
    duplicate_native = await bind(
        f, run_id=another.json()["test_run_id"], attach_key="second-attach"
    )
    assert duplicate_native.status_code == 409
    denied = await f["client"].post(
        f"/api/v1/interactive/executions/{bound.json()['id']}/tools/request_mission",
        headers=f["headers"],
        json={"arguments": {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "no-grant"}},
    )
    assert denied.status_code == 403
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AgentSessionRecord)
                .where(AgentSessionRecord.test_run_id == f["run_id"])
            )
            == 1
        )
        binding = await db.get(RunExecutionBinding, UUID(bound.json()["binding_id"]))
        assert binding.status.value == "RESERVED"
        assert (
            await db.get(AgentSessionRecord, binding.primary_agent_session_id)
        ).provider_session_id == f["proof"]["native_session_id"]


async def test_current_agent_mission_submission_waiting_and_same_primary_session(
    interactive_context,
):
    f = interactive_context
    await start(f)
    admitted = await tool(
        f,
        "request_mission",
        {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "requirements"},
    )
    assert admitted["status"] == "ADMITTED"
    proposal = {
        "proposal_type": "REQUIREMENT",
        "operation": "CREATE",
        "idempotency_key": "pinned-output",
        "object_payload": {
            "logical_key": "pinned.output",
            "title": "Print pinned",
            "description": "The application prints pinned and a newline.",
            "requirement_type": "FUNCTIONAL",
            "priority": "P0",
            "source_type": "PRD",
            "source_ref": "PRD#output",
            "confidence": 0.99,
        },
    }
    completed = await tool(
        f, "complete_mission", result_input(admitted, [proposal], "requirements-result")
    )
    assert completed["status"] == "ACCEPTED", completed
    replay = await tool(
        f, "complete_mission", result_input(admitted, [proposal], "requirements-result")
    )
    assert replay == completed
    waiting = await tool(
        f,
        "ask_user",
        {
            "scope": "run",
            "idempotency_key": "question",
            "request": {
                "question_id": "decision",
                "question": "Continue this test Run?",
                "options": ["yes", "no"],
            },
        },
    )
    assert waiting["status"] == "SUSPENDING"
    finished = await asyncio.wait_for(f["tasks"][0], 5)
    assert finished.status == JobStatus.WAITING_INPUT
    async with AsyncSessionLocal() as db:
        binding = await db.scalar(
            select(RunExecutionBinding).where(RunExecutionBinding.test_run_id == f["run_id"])
        )
        assert binding.status.value == "WAITING_INPUT"
        assert (
            await db.get(AgentSessionRecord, binding.primary_agent_session_id)
        ).provider_session_id == f["proof"]["native_session_id"]
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AgentSessionRecord)
                .where(AgentSessionRecord.test_run_id == f["run_id"])
            )
            == 1
        )


async def test_revocation_fences_new_tools_and_explicit_recovery_keeps_native(
    interactive_context, monkeypatch
):
    f = interactive_context
    await start(f)
    # Revoking a short grant is not a business Run cancel; coordinator stops its
    # original claim and preserves the native identity for explicit recovery.
    async with AsyncSessionLocal() as db:
        short = await db.scalar(
            select(InteractiveExecutionGrant).where(
                InteractiveExecutionGrant.interactive_binding_id == UUID(f["execution_id"]),
                InteractiveExecutionGrant.status == "ACTIVE",
            )
        )
        short.status, short.row_version = "REVOKED", short.row_version + 1
        await db.commit()
    refused = await f["client"].post(
        f"/api/v1/interactive/executions/{f['execution_id']}/tools/request_mission",
        headers=f["execution_headers"],
        json={
            "arguments": {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "after-revoke"}
        },
    )
    assert refused.status_code == 403
    stopped = await asyncio.wait_for(f["tasks"][0], 5)
    assert stopped.status == JobStatus.FAILED
    async with AsyncSessionLocal() as db:
        binding = await db.scalar(
            select(RunExecutionBinding).where(RunExecutionBinding.test_run_id == f["run_id"])
        )
        epoch, version = binding.binding_epoch, binding.row_version
    recovery = {
        "expected_epoch": epoch,
        "expected_row_version": version,
        "retry_key": "recover-" + uuid4().hex,
        "host_proof": {**f["proof"], "observed_at": datetime.now(UTC).isoformat()},
    }
    endpoint = f"/api/v1/interactive/executions/{f['execution_id']}/recover"
    assert (
        await f["client"].post(endpoint, headers=f["headers"], json=recovery)
    ).status_code == 401
    headers = {**f["headers"], "X-Hypertest-Operator-Key": "test-source-operator"}
    wrong = await f["client"].post(
        endpoint,
        headers=headers,
        json={
            **recovery,
            "host_proof": {**recovery["host_proof"], "native_session_id": str(uuid4())},
        },
    )
    assert wrong.status_code == 409
    # An API task has no source filesystem privilege. Only the independent
    # runtime-control Worker may touch pinned server workspace bytes.
    from hypertest.application import interactive as interactive_app

    original_verify, verified_tasks = interactive_app.verify_workspace, []

    async def worker_only_verify(*args, **kwargs):
        task = asyncio.current_task()
        assert task is f["control_task"], "API attempted privileged workspace I/O"
        verified_tasks.append(task)
        return await original_verify(*args, **kwargs)

    monkeypatch.setattr(interactive_app, "verify_workspace", worker_only_verify)
    recovered = await f["client"].post(endpoint, headers=headers, json=recovery)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["binding_epoch"] == epoch + 1
    assert verified_tasks == [f["control_task"]]
    repeated = await f["client"].post(
        endpoint,
        headers=headers,
        json={
            **recovery,
            "host_proof": {**recovery["host_proof"], "observed_at": datetime.now(UTC).isoformat()},
        },
    )
    assert repeated.status_code == 200 and repeated.json() == recovered.json()
    query = await f["client"].get(
        endpoint.replace("/recover", "/recoveries/by-key"),
        headers=headers,
        params={"retry_key": recovery["retry_key"]},
    )
    assert query.status_code == 200 and query.json() == recovered.json()
    assert len(verified_tasks) == 1, "recovery retry must query, never rerun Worker recovery"
    stale = await f["client"].post(
        f"/api/v1/interactive/executions/{f['execution_id']}/tools/get_state",
        headers=f["execution_headers"],
        json={"arguments": {}},
    )
    assert stale.status_code == 403
    async with AsyncSessionLocal() as db:
        row = await db.get(InteractiveExecutionBinding, UUID(f["execution_id"]))
        assert row.native_session_id == f["proof"]["native_session_id"] and row.attached_epoch == 1
        new = await db.get(DurableJob, UUID(recovered.json()["new_job_id"]))
        assert new.retry_of_job_id == f["job_id"] and new.status == JobStatus.QUEUED


@pytest.mark.skipif(
    os.environ.get("HYPERTEST_INTERACTIVE_DOCKER_E2E") != "1",
    reason="explicit real Docker acceptance",
)
@pytest.mark.parametrize("revoke_during_runner", [False, True])
async def test_current_agent_real_docker_runner_evidence_gate_report(
    interactive_context, monkeypatch, revoke_during_runner
):
    f = interactive_context
    await start(f)

    async def stage(kind, proposals):
        admitted = await tool(f, "request_mission", {"mission_type": kind, "idempotency_key": kind})
        assert admitted["status"] == "ADMITTED", admitted
        result = await tool(
            f, "complete_mission", result_input(admitted, proposals, kind + "-result")
        )
        assert result["status"] == "ACCEPTED", result
        return result["accepted_keys"]

    requirement = await stage(
        "ANALYZE_REQUIREMENTS",
        [
            {
                "proposal_type": "REQUIREMENT",
                "operation": "CREATE",
                "idempotency_key": "req",
                "object_payload": {
                    "logical_key": "pinned.output",
                    "title": "Print pinned",
                    "description": "The application prints pinned and a newline.",
                    "requirement_type": "FUNCTIONAL",
                    "priority": "P0",
                    "source_type": "PRD",
                    "source_ref": "PRD#output",
                    "confidence": 0.99,
                },
            }
        ],
    )
    risk = await stage(
        "ANALYZE_RISKS",
        [
            {
                "proposal_type": "RISK",
                "operation": "CREATE",
                "idempotency_key": "risk",
                "object_payload": {
                    "requirement_keys": requirement,
                    "category": "FUNCTIONAL",
                    "title": "Incorrect output",
                    "description": "The output may differ from pinned newline.",
                    "severity": "MEDIUM",
                    "probability": "MEDIUM",
                    "rationale": "Output is the public application behavior.",
                    "confidence": 0.95,
                },
            }
        ],
    )
    cases = await stage(
        "DESIGN_TESTS",
        [
            {
                "proposal_type": "TEST_CASE",
                "operation": "CREATE",
                "idempotency_key": "case",
                "object_payload": {
                    "risk_keys": risk,
                    "title": "Print expected output",
                    "description": "Run the fixed app entry point and capture output.",
                    "test_type": "FUNCTIONAL",
                    "priority": "P0",
                    "preconditions": [],
                    "expected_result": "Exactly pinned followed by one newline.",
                    "confidence": 0.99,
                },
            }
        ],
    )
    await stage(
        "IMPLEMENT_TESTS",
        [
            {
                "proposal_type": "TEST_IMPLEMENTATION",
                "operation": "CREATE",
                "idempotency_key": "implementation",
                "object_payload": {
                    "test_case_keys": cases,
                    "repository_url": f["origin"],
                    "commit_sha": f["receipt"]["commit_sha"],
                    "file_path": "tests/test_pinned.py",
                    "symbol": "test_pinned_output",
                    "code": "import runpy\n\ndef test_pinned_output(capsys):\n    runpy.run_path('app.py')\n    assert capsys.readouterr().out == 'pinned\\n'\n",
                },
            }
        ],
    )
    if revoke_during_runner:
        from hypertest.domain.models import Evidence, TestExecution
        from hypertest.runner.backends import DockerRunner

        entered, release = asyncio.Event(), asyncio.Event()
        original_execute = DockerRunner.execute

        async def delayed_execute(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return await original_execute(self, *args, **kwargs)

        monkeypatch.setattr(DockerRunner, "execute", delayed_execute)
        pending = asyncio.create_task(
            f["client"].post(
                f"/api/v1/interactive/executions/{f['execution_id']}/tools/request_execution",
                headers=f["execution_headers"],
                json={"arguments": {"idempotency_key": "official"}},
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        async with AsyncSessionLocal() as db:
            short = await db.scalar(
                select(InteractiveExecutionGrant).where(
                    InteractiveExecutionGrant.interactive_binding_id == UUID(f["execution_id"]),
                    InteractiveExecutionGrant.status == "ACTIVE",
                )
            )
            short.status, short.row_version = "REVOKED", short.row_version + 1
            await db.commit()
        await asyncio.sleep(0.3)
        async with AsyncSessionLocal() as db:
            assert (await db.get(DurableJob, f["job_id"])).status == JobStatus.RUNNING
        release.set()
        outcome = await asyncio.wait_for(pending, 15)
        assert outcome.status_code in {200, 409}, outcome.text
        stopped = await asyncio.wait_for(f["tasks"][0], 5)
        assert stopped.status == JobStatus.FAILED
        async with AsyncSessionLocal() as db:
            executions = list(
                await db.scalars(
                    select(TestExecution).where(TestExecution.test_run_id == f["run_id"])
                )
            )
            assert len(executions) == 1 and executions[0].outcome.value == "PASS"
            assert executions[0].status.value == "COMPLETED"
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Evidence)
                    .where(Evidence.test_run_id == f["run_id"])
                )
                > 0
            )
            binding = await db.scalar(
                select(RunExecutionBinding).where(RunExecutionBinding.test_run_id == f["run_id"])
            )
            recovery = {
                "expected_epoch": binding.binding_epoch,
                "expected_row_version": binding.row_version,
                "retry_key": "drain-recover-" + uuid4().hex,
                "host_proof": {**f["proof"], "observed_at": datetime.now(UTC).isoformat()},
            }
        recovered = await f["client"].post(
            f"/api/v1/interactive/executions/{f['execution_id']}/recover",
            headers={**f["headers"], "X-Hypertest-Operator-Key": "test-source-operator"},
            json=recovery,
        )
        assert recovered.status_code == 200, recovered.text
        async with AsyncSessionLocal() as db:
            resumed = await claim_job(
                db, "interactive-drain-resume", lease_seconds=130, run_id=f["run_id"]
            )
        f["tasks"].append(asyncio.create_task(run_claimed_job(resumed)))
        for _ in range(100):
            current = await f["client"].get(
                "/api/v1/interactive/executions/by-key",
                headers=f["headers"],
                params={"run_id": str(f["run_id"]), "attach_key": f["attach_key"]},
            )
            if current.json().get("execute_ready"):
                break
            await asyncio.sleep(0.02)
        continued = await f["client"].post(
            f"/api/v1/interactive/executions/{f['execution_id']}/continue",
            headers=f["headers"],
            json={
                "continuation_key": "post-drain-" + uuid4().hex,
                "host_proof": recovery["host_proof"],
            },
        )
        assert continued.status_code == 200, continued.text
        f["execution_headers"]["X-Hypertest-Execution-Token"] = continued.json()["execution_token"]
    else:
        execution = await tool(f, "request_execution", {"idempotency_key": "official"})
        assert execution["status"] == "COMPLETED" and execution["outcome"] == "PASS", execution
    state = await tool(f, "get_state", {})
    gate = await tool(f, "evaluate_gate", {"idempotency_key": "gate"})
    assert gate["decision"] == "RELEASE_READY", gate
    async with AsyncSessionLocal() as db:
        run = await db.get(CanonicalRun, f["run_id"])
        source = await db.get(SourceSnapshot, run.source_snapshot_id)
        policy_id = run.policy_snapshot_id
    report = await tool(
        f,
        "submit_report",
        {
            "idempotency_key": "report",
            "schema_version": "hypertest.report/run-summary/v1",
            "test_run_id": str(f["run_id"]),
            "source_snapshot_id": str(source.id),
            "policy_snapshot_id": str(policy_id),
            "commit_sha": source.commit_sha,
            "summary": "Current-Agent real Docker acceptance",
            "markdown": "# Tested\nVerified Runner output.",
            "execution_keys": [e["key"] for e in state["executions"]],
            "evidence_keys": [e["key"] for e in state["evidence"]],
            "finding_keys": [],
            "verdict_key": gate["verdict_key"],
            "unresolved": [],
        },
    )
    assert report["status"] == "ACCEPTED", report
    done = await asyncio.wait_for(f["tasks"][-1], 5)
    assert done.status == JobStatus.SUCCEEDED
    reports = await f["client"].get(
        f"/api/v1/interactive/runs/{f['run_id']}/reports", headers=f["headers"]
    )
    assert reports.status_code == 200 and len(reports.json()["items"]) == 1


async def test_http_wait_cancellation_does_not_cancel_or_replay_worker(
    interactive_context, monkeypatch
):
    from hypertest.application.harness_tools import HarnessTools
    from hypertest.domain.interactive import InteractiveToolRequest

    f = interactive_context
    await start(f)
    entered, release = asyncio.Event(), asyncio.Event()
    original, dispatches = HarnessTools.dispatch, []

    async def blocked(self, name, arguments):
        dispatches.append(asyncio.current_task())
        entered.set()
        await release.wait()
        return await original(self, name, arguments)

    monkeypatch.setattr(HarnessTools, "dispatch", blocked)
    key = "transport-read-" + uuid4().hex
    pending = asyncio.create_task(
        f["client"].post(
            f"/api/v1/interactive/executions/{f['execution_id']}/tools/get_state",
            headers={**f["execution_headers"], "X-Hypertest-Request-Key": key},
            json={"arguments": {}},
        )
    )
    await asyncio.wait_for(entered.wait(), 5)
    assert len(dispatches) == 1 and dispatches[0] is not pending
    assert dispatches[0].get_coro().__qualname__ == "run_claimed_job.<locals>.execute", (
        "API must not execute domain tools"
    )
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    assert not f["tasks"][0].done()
    release.set()
    for _ in range(100):
        result = await f["client"].get(
            f"/api/v1/interactive/executions/{f['execution_id']}/tools/by-key",
            headers=f["headers"],
            params={"tool_name": "get_state", "idempotency_key": key},
        )
        assert result.status_code == 200, result.text
        if result.json()["status"] == "SUCCEEDED":
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError(result.text)
    assert len(dispatches) == 1
    async with AsyncSessionLocal() as db:
        request = await db.scalar(
            select(InteractiveToolRequest).where(InteractiveToolRequest.idempotency_key == key)
        )
        assert request.status == "SUCCEEDED" and request.arguments == {
            "resource": "state",
            "collection": None,
            "path": None,
            "evidence_id": None,
            "entity_id": None,
            "mission_id": None,
            "offset": 0,
            "limit": 30,
        }
        assert "token" not in str(request.arguments)


async def test_device_rotation_revokes_exact_old_execution_capability(interactive_context):
    f = interactive_context
    await start(f)
    rotated = await f["client"].post(
        f"/api/v1/harness-nodes/{f['node_id']}/rotate",
        headers={"X-Hypertest-Operator-Key": "test-source-operator"},
        json={},
    )
    assert rotated.status_code == 200, rotated.text
    denied = await f["client"].post(
        f"/api/v1/interactive/executions/{f['execution_id']}/tools/get_state",
        headers=f["execution_headers"],
        json={"arguments": {}},
    )
    assert denied.status_code == 403, denied.text
    stopped = await asyncio.wait_for(f["tasks"][0], 5)
    assert stopped.status == JobStatus.FAILED


async def test_recovery_worker_rechecks_exact_device_after_source_io(
    interactive_context, monkeypatch
):
    import json

    from hypertest.application import interactive as interactive_app
    from hypertest.domain.harness import RuntimeControlRequest

    f = interactive_context
    await start(f)
    async with AsyncSessionLocal() as db:
        short = await db.scalar(
            select(InteractiveExecutionGrant).where(
                InteractiveExecutionGrant.interactive_binding_id == UUID(f["execution_id"]),
                InteractiveExecutionGrant.status == "ACTIVE",
            )
        )
        short.status, short.row_version = "REVOKED", short.row_version + 1
        await db.commit()
    assert (await asyncio.wait_for(f["tasks"][0], 5)).status == JobStatus.FAILED
    async with AsyncSessionLocal() as db:
        binding = await db.scalar(
            select(RunExecutionBinding).where(RunExecutionBinding.test_run_id == f["run_id"])
        )
        epoch, version = binding.binding_epoch, binding.row_version
    entered, release = asyncio.Event(), asyncio.Event()
    original = interactive_app.verify_workspace

    async def worker_source_check(*args, **kwargs):
        assert asyncio.current_task() is f["control_task"]
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(interactive_app, "verify_workspace", worker_source_check)
    key = "device-race-" + uuid4().hex
    pending = asyncio.create_task(
        f["client"].post(
            f"/api/v1/interactive/executions/{f['execution_id']}/recover",
            headers={**f["headers"], "X-Hypertest-Operator-Key": "test-source-operator"},
            json={
                "expected_epoch": epoch,
                "expected_row_version": version,
                "retry_key": key,
                "host_proof": {**f["proof"], "observed_at": datetime.now(UTC).isoformat()},
            },
        )
    )
    await asyncio.wait_for(entered.wait(), 5)
    try:
        rotated = await f["client"].post(
            f"/api/v1/harness-nodes/{f['node_id']}/rotate",
            headers={"X-Hypertest-Operator-Key": "test-source-operator"},
            json={},
        )
        assert rotated.status_code == 200, rotated.text
    finally:
        release.set()
    result = await asyncio.wait_for(pending, 5)
    assert result.status_code == 409, result.text
    async with AsyncSessionLocal() as db:
        binding = await db.scalar(
            select(RunExecutionBinding).where(RunExecutionBinding.test_run_id == f["run_id"])
        )
        assert binding.binding_epoch == epoch and binding.status.value == "RECOVERY_REQUIRED"
        assert (
            await db.scalar(
                select(func.count())
                .select_from(DurableJob)
                .where(DurableJob.test_run_id == f["run_id"])
            )
            == 1
        )
        command = await db.scalar(
            select(RuntimeControlRequest).where(
                RuntimeControlRequest.payload["payload"]["retry_key"].astext == key
            )
        )
        assert command.status == "FAILED"
        persisted = json.dumps(command.payload)
        for credential in [
            f["headers"]["Authorization"].removeprefix("Bearer "),
            f["headers"]["X-Hypertest-Device-Token"],
            f["execution_headers"]["X-Hypertest-Execution-Token"],
        ]:
            assert credential not in persisted
        assert "server_workspace" not in persisted


async def test_continue_and_integration_revoke_serialize_without_deadlock(
    interactive_context, monkeypatch
):
    """The losing revoker must wait for authority, never deadlock on short rows."""
    import inspect

    from hypertest.application import interactive as interactive_app
    from hypertest.application import interactive_tool_worker

    f = interactive_context
    pause_coordinator, resume_coordinator = asyncio.Event(), asyncio.Event()
    original_consume = interactive_tool_worker.consume_one

    async def paused_consume(*args, **kwargs):
        pause_coordinator.set()
        await resume_coordinator.wait()
        return await original_consume(*args, **kwargs)

    monkeypatch.setattr(interactive_tool_worker, "consume_one", paused_consume)
    await start(f)
    await asyncio.wait_for(pause_coordinator.wait(), 5)
    short_locked, release_continue, revoke_locked = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    original_device, original_now = interactive_app.authenticate_device, interactive_app.now
    continuing = revoking = None

    async def pause_after_short_locks(*args, **kwargs):
        result = await original_device(*args, **kwargs)
        caller = inspect.currentframe().f_back
        if (
            asyncio.current_task() is continuing
            and caller.f_code.co_name == "continue_execution"
            and "latest" in caller.f_locals
        ):
            short_locked.set()
            await release_continue.wait()
        return result

    async def observe_revoke_lock(db):
        if asyncio.current_task() is revoking:
            revoke_locked.set()
        return await original_now(db)

    monkeypatch.setattr(interactive_app, "authenticate_device", pause_after_short_locks)
    monkeypatch.setattr(interactive_app, "now", observe_revoke_lock)
    continuing = asyncio.create_task(
        f["client"].post(
            f"/api/v1/interactive/executions/{f['execution_id']}/continue",
            headers=f["headers"],
            json={
                "continuation_key": "racing-" + uuid4().hex,
                "host_proof": {**f["proof"], "observed_at": datetime.now(UTC).isoformat()},
            },
        )
    )
    try:
        await asyncio.wait_for(short_locked.wait(), 5)
        async with AsyncSessionLocal() as db:
            attachment = await db.get(InteractiveExecutionBinding, UUID(f["execution_id"]))
            grant_id = attachment.grant_id
        revoking = asyncio.create_task(
            f["client"].post(
                f"/api/v1/interactive/grants/{grant_id}/revoke",
                headers={"X-Hypertest-Operator-Key": "test-source-operator"},
            )
        )
        await asyncio.sleep(0.15)
        # With the old reverse order, revoke held integration here and waited
        # for short; continue's INSERT FK then completed the PostgreSQL cycle.
        assert not revoke_locked.is_set(), "continue must already hold shared integration authority"
        release_continue.set()
        continued, revoked = await asyncio.wait_for(asyncio.gather(continuing, revoking), 5)
        assert continued.status_code == revoked.status_code == 200, (continued.text, revoked.text)
        async with AsyncSessionLocal() as db:
            grants = list(
                await db.scalars(
                    select(InteractiveExecutionGrant).where(
                        InteractiveExecutionGrant.interactive_binding_id == UUID(f["execution_id"])
                    )
                )
            )
            assert len(grants) == 2 and all(g.status == "REVOKED" for g in grants)
        denied = await f["client"].post(
            f"/api/v1/interactive/executions/{f['execution_id']}/tools/get_state",
            headers={
                **f["headers"],
                "X-Hypertest-Execution-Token": continued.json()["execution_token"],
            },
            json={"arguments": {}},
        )
        assert denied.status_code == 403
    finally:
        release_continue.set()
        resume_coordinator.set()
        for task in [continuing, revoking]:
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("authority", ["integration", "device"])
async def test_continue_rechecks_authority_after_waiting_for_revoke_or_rotate(
    interactive_context, monkeypatch, authority
):
    from hypertest.api import connector_routes
    from hypertest.application import interactive as interactive_app
    from hypertest.application import interactive_tool_worker

    f = interactive_context
    paused, resume = asyncio.Event(), asyncio.Event()
    consume = interactive_tool_worker.consume_one

    async def paused_consume(*args, **kwargs):
        paused.set()
        await resume.wait()
        return await consume(*args, **kwargs)

    monkeypatch.setattr(interactive_tool_worker, "consume_one", paused_consume)
    await start(f)
    await asyncio.wait_for(paused.wait(), 5)
    authority_locked, release_authority = asyncio.Event(), asyncio.Event()
    mutating = continuing = None
    original_now, original_issue = interactive_app.now, connector_routes.issue_device_grant

    async def revoke_clock(db):
        if asyncio.current_task() is mutating:
            authority_locked.set()
            await release_authority.wait()
        return await original_now(db)

    async def rotate_grant(*args, **kwargs):
        if asyncio.current_task() is mutating:
            authority_locked.set()
            await release_authority.wait()
        return await original_issue(*args, **kwargs)

    if authority == "integration":
        monkeypatch.setattr(interactive_app, "now", revoke_clock)
        async with AsyncSessionLocal() as db:
            attachment = await db.get(InteractiveExecutionBinding, UUID(f["execution_id"]))
            path = f"/api/v1/interactive/grants/{attachment.grant_id}/revoke"
    else:
        monkeypatch.setattr(connector_routes, "issue_device_grant", rotate_grant)
        path = f"/api/v1/harness-nodes/{f['node_id']}/rotate"
    mutating = asyncio.create_task(
        f["client"].post(
            path, headers={"X-Hypertest-Operator-Key": "test-source-operator"}, json={}
        )
    )
    try:
        await asyncio.wait_for(authority_locked.wait(), 5)
        continuing = asyncio.create_task(
            f["client"].post(
                f"/api/v1/interactive/executions/{f['execution_id']}/continue",
                headers=f["headers"],
                json={
                    "continuation_key": "must-not-mint-" + uuid4().hex,
                    "host_proof": {**f["proof"], "observed_at": datetime.now(UTC).isoformat()},
                },
            )
        )
        await asyncio.sleep(0.15)
        assert not continuing.done(), "continue must serialize behind the authority update"
        release_authority.set()
        mutated, rejected = await asyncio.wait_for(asyncio.gather(mutating, continuing), 5)
        assert mutated.status_code == 200, mutated.text
        assert rejected.status_code == 403 and "execution_token" not in rejected.json(), (
            rejected.text
        )
        async with AsyncSessionLocal() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(InteractiveExecutionGrant)
                .where(InteractiveExecutionGrant.interactive_binding_id == UUID(f["execution_id"]))
            )
            assert count == 1, "a stale pre-lock authorization must never mint another short grant"
    finally:
        release_authority.set()
        resume.set()
        for task in [mutating, continuing]:
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
