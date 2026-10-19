"""PostgreSQL/API/Worker governance contracts; Runner/model facts are explicit fixtures.

These regressions do not substitute for the separately recorded real Web E2E.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_gate import _official, _seed
from test_run_bindings import own_job

from hypertest.application.bindings import (
    activate_run_binding,
    create_run_binding,
    terminate_run_binding,
    transition_binding,
)
from hypertest.application.findings import transition_finding
from hypertest.application.gate import evaluate_gate
from hypertest.application.gate_governance import authorize_gate_job
from hypertest.application.jobs import (
    FencedAsyncSession,
    JobLeaseLost,
    cancel_job,
    claim_job,
    cleanup_job_resources,
    finish_job,
    recover_expired_jobs,
    retry_job,
    submit_job,
)
from hypertest.application.services import ConflictError
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal, engine
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.enums import (
    AgentSessionStatus,
    CaseResult,
    FindingResolution,
    FindingStatus,
    VerdictDecision,
)
from hypertest.domain.harness import RunHarnessState, RunReport
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob, JobStatus, JobType
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    Evidence,
    Finding,
    FindingEvidence,
    FindingTestCase,
    OutboxEvent,
    Verdict,
)
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.harness_bridge.protocol import PROFILE
from hypertest.main import app
from hypertest.runner.artifacts import read_evidence_content, store_content
from hypertest.worker import dispatch_job, run_claimed_job

REASON = "Review the recorded Finding disposition against the frozen policy."


async def seed_cycle(*, result=CaseResult.FAIL, status=BindingStatus.CLOSED, report=True):
    async with AsyncSessionLocal() as session:
        run, _, _, case = await _seed(session)
        original = await submit_job(session, run.id, JobType.ADVANCE_RUN,
            payload={"execution_profile": PROFILE, "workspace": "."}, idempotency_key="initial-cycle")
        token = await own_job(session, original)
        binding = await create_run_binding(session, run.id, job_id=original.id, lease_token=token,
            logical_worker_id=uuid7(), harness_host_id="original-harness-unavailable-for-gate",
            workspace_id=str(uuid7()))
        session.add(RunHarnessState(binding_id=binding.id, first_job_id=original.id,
            source_workspace="/fixture/no-filesystem-required-by-gate", max_steps=12, timeout_seconds=300))
        await session.commit()
        if status is not BindingStatus.RESERVED:
            await activate_run_binding(session, binding.id, 1, job_id=original.id, lease_token=token,
                                       provider_session_id=str(uuid7()))
            await session.commit()
        execution, evidence = await _official(session, run, case, result=result)
        finding = Finding(key=public_key("FIND"), project_id=run.project_id, test_run_id=run.id,
            fingerprint=uuid7().hex * 2, classification="PRODUCT_DEFECT", severity="CRITICAL",
            title="Recorded discrepancy", description="The official assertion requires operator review.",
            status=FindingStatus.NEW, reported_by_type="USER")
        session.add(finding)
        await session.flush()
        session.add_all([FindingEvidence(finding_id=finding.id, evidence_id=evidence[0].id, relation_type="SUPPORTS"),
                         FindingTestCase(finding_id=finding.id, test_case_id=case.id)])
        await session.commit()
        first = await evaluate_gate(session, run.id)
        saved_report = None
        if report:
            digest, uri = store_content(b"# Original accepted report fixture\n")
            saved_report = RunReport(test_run_id=run.id, binding_id=binding.id, durable_job_id=original.id,
                idempotency_key="original-report", content_sha256=digest, artifact_uri=uri,
                envelope={"verdict_key": first.key, "verdict_decision": first.decision.value,
                          "private_fixture": "must-not-be-projected"})
            session.add(saved_report)
            await session.commit()
        if status is BindingStatus.CLOSED and report:
            await finish_job(session, original.id, token, result={"report_id": str(saved_report.id)})
        else:
            if status in {BindingStatus.CLOSED, BindingStatus.FAILED, BindingStatus.CANCELLED}:
                await terminate_run_binding(session, binding.id, status=status, reason="explicit fixture terminal state")
            elif status in {BindingStatus.RECOVERY_REQUIRED, BindingStatus.WAITING_INPUT}:
                await transition_binding(session, binding, status, reason="explicit fixture state")
            original.status, original.finished_at, original.lease_expires_at = JobStatus.FAILED, await session.scalar(select(func.clock_timestamp())), None
            await session.commit()
        return {"run": run.id, "binding": binding.id, "agent": binding.primary_agent_session_id,
                "finding": finding.id, "first_verdict": first.id, "execution": execution.id,
                "evidence": [item.id for item in evidence], "report": saved_report.id if saved_report else None}


@pytest.fixture
async def closed_cycle():
    context = await seed_cycle()
    try:
        yield context
    finally:
        async with AsyncSessionLocal() as session:
            jobs = list(await session.scalars(select(DurableJob).where(
                DurableJob.test_run_id == context["run"], DurableJob.status.in_(ACTIVE_JOB_STATUSES))))
            for job in jobs:
                job.status, job.finished_at, job.lease_expires_at = JobStatus.FAILED, await session.scalar(select(func.clock_timestamp())), None
            await session.commit()


async def queue_and_run(context, *, key=None, reason=REASON):
    async with AsyncSessionLocal() as session:
        job = await submit_job(session, context["run"], JobType.EVALUATE_GATE,
            payload={"finalize": True, "reason": reason}, idempotency_key=key or public_key("GATE"))
        claimed = await claim_job(session, "gate-only-worker")
        assert claimed is not None and claimed.id == job.id
    finished = await run_claimed_job(claimed)
    assert finished is not None and finished.status is JobStatus.SUCCEEDED, finished.error_message if finished else None
    return finished


async def snapshot_history(context):
    async with AsyncSessionLocal() as session:
        values = {}
        for name, model, identity in (
            ("binding", RunExecutionBinding, context["binding"]),
            ("agent", AgentSessionRecord, context["agent"]),
            ("checkpoint", RunHarnessState, context["binding"]),
            ("report", RunReport, context["report"]),
            ("execution", CanonicalExecution, context["execution"]),
            ("first_verdict", Verdict, context["first_verdict"]),
        ):
            row = await session.get(model, identity)
            values[name] = {column.key: getattr(row, column.key) for column in row.__mapper__.columns}
        values["evidence"] = {str(identity): read_evidence_content(await session.get(Evidence, identity))
                              for identity in context["evidence"]}
        return values


async def test_closed_finding_disposition_and_gate_preserve_failure_and_history(closed_cycle, monkeypatch):
    context = closed_cycle
    monkeypatch.setattr(get_settings(), "execution_mode", "queued")
    async def forbidden(*args, **kwargs):
        raise AssertionError("Gate-only governance must not invoke host integrations")
    monkeypatch.setattr("hypertest.application.persistent.advance_persistent_run", forbidden)
    monkeypatch.setattr("hypertest.application.persistent.cleanup_bound_call", forbidden)
    monkeypatch.setattr("hypertest.runner.backends.cleanup_docker_job_resources", forbidden)
    before = await snapshot_history(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        endpoint = f"/api/v1/findings/{context['finding']}/transition"
        for version, status in ((1, "TRIAGED"), (2, "CONFIRMED")):
            response = await client.post(endpoint, json={"status": status, "reason": "Review trusted evidence.",
                                                        "expected_row_version": version})
            assert response.status_code == 200, response.text
        stale = await client.post(endpoint, json={"status": "RESOLVED", "resolution": "RISK_ACCEPTED",
                                                "reason": "Stale operator view.", "expected_row_version": 2})
        assert stale.status_code == 409
        request = {"operation": "EVALUATE_GATE", "payload": {"finalize": True, "reason": REASON},
                   "idempotency_key": "confirmed-review"}
        queued = await client.post(f"/api/v1/test-runs/{context['run']}/jobs", json=request)
        assert queued.status_code == 202, queued.text
        async with AsyncSessionLocal() as session:
            claimed = await claim_job(session, "independent-gate-worker")
        assert claimed is not None and str(claimed.id) == queued.json()["id"]
        reviewed = await run_claimed_job(claimed)
        assert reviewed.status is JobStatus.SUCCEEDED
        assert reviewed.result["decision"] == "RELEASE_BLOCKED"
        for version, status in ((3, "RESOLVED"), (4, "CLOSED")):
            response = await client.post(endpoint, json={"status": status, "resolution": "RISK_ACCEPTED",
                "reason": "Accepted for tracking; official failures remain facts.", "expected_row_version": version})
            assert response.status_code == 200, response.text
        resolved = await queue_and_run(context, key="closed-review")
        repeat = await queue_and_run(context, key="unchanged-review", reason="A second operator requests the same facts.")
        assert repeat.result["verdict_id"] == resolved.result["verdict_id"]
        assert resolved.result["decision"] == "RELEASE_BLOCKED"
        reports = (await client.get(f"/api/v1/test-runs/{context['run']}/reports")).json()
        harness = (await client.get(f"/api/v1/test-runs/{context['run']}/harness")).json()
        assert harness["reports"] == reports
        assert reports[0]["verdict_key"] != resolved.result["verdict_key"]
        assert reports[0]["verdict_decision"] == "RELEASE_BLOCKED"
        assert "envelope" not in reports[0] and "private_fixture" not in str(reports)
        assert (await client.get(f"/api/v1/reports/{context['report']}/content")).content == b"# Original accepted report fixture\n"
    assert await snapshot_history(context) == before
    async with AsyncSessionLocal() as session:
        verdicts = list(await session.scalars(select(Verdict).where(Verdict.test_run_id == context["run"]).order_by(Verdict.sequence_no)))
        assert [item.sequence_no for item in verdicts] == [1, 2, 3]
        assert "latest official execution failed" in verdicts[-1].reason
        assert "Confirmed product defects" not in verdicts[-1].reason
        assert (await session.get(CanonicalRun, context["run"])).current_verdict_id == verdicts[-1].id
        assert await session.scalar(select(func.count()).select_from(AgentSessionRecord).where(AgentSessionRecord.test_run_id == context["run"])) == 1
        for model, field in ((AuditEvent, AuditEvent.entity_id), (OutboxEvent, OutboxEvent.aggregate_id)):
            records = list(await session.scalars(select(model).where(field == claimed.id)))
            assert len(records) == 3
            assert all((row.after_state if model is AuditEvent else row.payload)["request_reason"] == REASON for row in records)
            succeeded = next(row for row in records if (row.action if model is AuditEvent else row.event_type) == "job.succeeded")
            result = succeeded.after_state if model is AuditEvent else succeeded.payload
            assert {key: result[key] for key in ("verdict_id", "verdict_key", "decision", "sequence_no")} == {
                key: reviewed.result[key] for key in ("verdict_id", "verdict_key", "decision", "sequence_no")}
        for job in (resolved, repeat):
            audit = await session.scalar(select(AuditEvent).where(AuditEvent.entity_id == job.id,
                                                                 AuditEvent.action == "job.succeeded"))
            assert audit.after_state["verdict_id"] == resolved.result["verdict_id"]


@pytest.mark.parametrize("status", [BindingStatus.RESERVED, BindingStatus.ACTIVE, BindingStatus.WAITING_INPUT,
    BindingStatus.RECOVERY_REQUIRED, BindingStatus.FAILED, BindingStatus.CANCELLED])
async def test_independent_gate_does_not_bypass_any_nonclosed_binding(status):
    context = await seed_cycle(status=status)
    async with AsyncSessionLocal() as session:
        with pytest.raises(ConflictError, match="closed reported"):
            await submit_job(session, context["run"], JobType.EVALUATE_GATE,
                payload={"reason": REASON}, idempotency_key="must-not-bypass")
        await session.rollback()
        with pytest.raises(ConflictError, match="closed reported"):
            await authorize_gate_job(session, context["run"], {"finalize": True, "reason": REASON})


async def test_unreported_closed_binding_cannot_accept_gate():
    context = await seed_cycle(report=False)
    async with AsyncSessionLocal() as session:
        with pytest.raises(ConflictError, match="closed reported"):
            await submit_job(session, context["run"], JobType.EVALUATE_GATE,
                payload={"reason": REASON}, idempotency_key="no-report")


async def test_closed_gate_tracks_confirmed_and_resolved_findings_on_passing_facts():
    context = await seed_cycle(result=CaseResult.PASS)
    original = await snapshot_history(context)
    async with AsyncSessionLocal() as session:
        await transition_finding(session, context["finding"], FindingStatus.TRIAGED, reason="Reviewed discrepancy.")
        await transition_finding(session, context["finding"], FindingStatus.CONFIRMED,
                                 reason="Trusted evidence supports this independently reported defect.")
    blocked = await queue_and_run(context)
    assert blocked.result["decision"] == "RELEASE_BLOCKED"
    async with AsyncSessionLocal() as session:
        await transition_finding(session, context["finding"], FindingStatus.RESOLVED,
                                 FindingResolution.NOT_REPRODUCIBLE, reason="Review removed this tracked blocker.")
    ready = await queue_and_run(context)
    assert ready.result["decision"] == "RELEASE_READY"
    assert await snapshot_history(context) == original
    async with AsyncSessionLocal() as session:
        verdicts = list(await session.scalars(select(Verdict).where(Verdict.test_run_id == context["run"]).order_by(Verdict.sequence_no)))
        assert [row.decision for row in verdicts] == [VerdictDecision.RELEASE_READY,
            VerdictDecision.RELEASE_BLOCKED, VerdictDecision.RELEASE_READY]
        assert [row.sequence_no for row in verdicts] == [1, 2, 3]


async def test_closed_binding_with_nonclosed_primary_session_is_rejected(closed_cycle):
    context = closed_cycle
    async with AsyncSessionLocal() as session:
        agent = await session.get(AgentSessionRecord, context["agent"])
        agent.status = AgentSessionStatus.RUNNING
        await session.commit()
        with pytest.raises(ConflictError, match="closed reported"):
            await submit_job(session, context["run"], JobType.EVALUATE_GATE,
                payload={"reason": REASON}, idempotency_key="inconsistent-session")


@pytest.mark.parametrize("operation,payload", [
    (JobType.ADVANCE_RUN, {"execution_profile": PROFILE, "workspace": "."}),
    (JobType.PREPARE_WORKSPACE, {}),
    (JobType.EXECUTE_TESTS, {"workspace": ".", "idempotency_key": "execution-bypass"}),
])
async def test_closed_gate_exception_does_not_reopen_execution_controls(closed_cycle, operation, payload):
    async with AsyncSessionLocal() as session:
        with pytest.raises(ConflictError, match="recovery|original Harness"):
            await submit_job(session, closed_cycle["run"], operation,
                payload=payload, idempotency_key="not-gate")


@pytest.mark.parametrize("payload,status", [({}, 409), ({"reason": "ok", "finalize": False}, 409),
    ({"reason": "   "}, 422), ({"reason": "x\x00y"}, 422), ({"reason": "x" * 2001}, 422)])
async def test_closed_gate_requires_bounded_reason_and_final_decision(closed_cycle, payload, status):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/test-runs/{closed_cycle['run']}/jobs", json={
            "operation": "EVALUATE_GATE", "idempotency_key": "invalid-input", "payload": payload})
        assert response.status_code == status, response.text
        if status == 422:
            assert isinstance(response.json()["detail"], list)
            assert all(set(item) <= {"type", "loc", "msg"} for item in response.json()["detail"])
            assert "x\\u0000y" not in response.text


async def test_closed_gate_concurrent_idempotency_exclusion_and_explicit_retry(closed_cycle):
    context = closed_cycle
    async def submit(key, reason=REASON):
        async with AsyncSessionLocal() as session:
            return await submit_job(session, context["run"], JobType.EVALUATE_GATE,
                payload={"reason": reason}, idempotency_key=key)
    first, repeated = await asyncio.gather(submit("same-request"), submit("same-request", f"  {REASON}  "))
    assert first.id == repeated.id and first.payload["reason"] == REASON
    with pytest.raises(ConflictError, match="different job request"):
        await submit("same-request", "different reason")
    with pytest.raises(ConflictError, match="active work"):
        await submit("competing-request")
    async with AsyncSessionLocal() as session:
        await cancel_job(session, first.id)
        retry = await retry_job(session, first.id, idempotency_key="explicit-retry")
        assert retry.retry_of_job_id == first.id and retry.payload == first.payload
        claimed = await claim_job(session, "new-gate-worker")
    finished = await run_claimed_job(claimed)
    assert finished.status is JobStatus.SUCCEEDED


@pytest.mark.parametrize("revocation", ["expired", "cancelled", "epoch"])
async def test_closed_gate_commit_is_fenced_after_revocation(closed_cycle, revocation):
    context = closed_cycle
    async with AsyncSessionLocal() as session:
        await transition_finding(session, context["finding"], FindingStatus.TRIAGED,
                                 reason="A changed state must roll back its new Verdict if ownership is lost.")
        await submit_job(session, context["run"], JobType.EVALUATE_GATE,
            payload={"reason": REASON}, idempotency_key="stale-worker")
        claimed = await claim_job(session, "stale-gate-worker")
        run = await session.get(CanonicalRun, context["run"])
        original_run = {column.key: getattr(run, column.key) for column in run.__mapper__.columns}
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=claimed.id,
            lease_token=claimed.lease_token, test_run_id=context["run"]) as stale:
        await authorize_gate_job(stale, context["run"], claimed.payload)
        if revocation == "epoch":
            stale.binding_epoch += 1  # An incorrectly correlated worker cannot use the closed privilege.
            await stale.rollback()
        else:
            await stale.rollback()  # Release admission locks before the independent cancellation transaction.
            async with AsyncSessionLocal() as session:
                if revocation == "cancelled":
                    await cancel_job(session, claimed.id)
                else:
                    job = await session.get(DurableJob, claimed.id)
                    job.lease_expires_at = await session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
                    await session.commit()
        with pytest.raises(JobLeaseLost):
            await dispatch_job(stale, claimed) if revocation != "epoch" else await evaluate_gate(stale, context["run"])
    async with AsyncSessionLocal() as session:
        if revocation == "expired":
            assert len(await recover_expired_jobs(session)) == 1
        else:
            job = await session.get(DurableJob, claimed.id)
            if job.status in ACTIVE_JOB_STATUSES:
                await finish_job(session, claimed.id, claimed.lease_token, error_code="TEST_INTERRUPTED")
        assert await session.scalar(select(func.count()).select_from(Verdict).where(Verdict.test_run_id == context["run"])) == 1
        assert (await session.get(RunExecutionBinding, context["binding"])).status is BindingStatus.CLOSED
        assert (await session.get(AgentSessionRecord, context["agent"])).status is AgentSessionStatus.CLOSED
        run = await session.get(CanonicalRun, context["run"])
        assert {column.key: getattr(run, column.key) for column in run.__mapper__.columns} == original_run
        assert await cleanup_job_resources(session, claimed) == {"external_resources": "not_applicable"}


async def test_closed_gate_cannot_commit_using_another_runs_job(closed_cycle):
    context = closed_cycle
    other = await seed_cycle()
    async with AsyncSessionLocal() as session:
        await submit_job(session, context["run"], JobType.EVALUATE_GATE,
            payload={"reason": REASON}, idempotency_key="wrong-run-owner")
        claimed = await claim_job(session, "foreign-job-worker")
    async with FencedAsyncSession(bind=engine, expire_on_commit=False, job_id=claimed.id,
            lease_token=claimed.lease_token, test_run_id=other["run"]) as wrong:
        await authorize_gate_job(wrong, other["run"], claimed.payload)
        with pytest.raises(JobLeaseLost):
            await evaluate_gate(wrong, other["run"])
    async with AsyncSessionLocal() as session:
        await finish_job(session, claimed.id, claimed.lease_token, error_code="WRONG_RUN_TEST")
        assert await session.scalar(select(func.count()).select_from(Verdict).where(Verdict.test_run_id == other["run"])) == 1


async def test_gate_return_to_prior_semantics_appends_instead_of_rewinding():
    async with AsyncSessionLocal() as session:
        run, requirement, _, case = await _seed(session)
        await _official(session, run, case)
        first = await evaluate_gate(session, run.id)
        original = requirement.description
        requirement.description = "A changed acceptance requirement."
        await session.commit()
        second = await evaluate_gate(session, run.id)
        requirement.description = original
        await session.commit()
        third = await evaluate_gate(session, run.id)
        assert third.id != first.id and third.state_snapshot_hash == first.state_snapshot_hash
        assert third.sequence_no == second.sequence_no + 1
        assert (await session.get(CanonicalRun, run.id)).current_verdict_id == third.id
        assert third.decision is VerdictDecision.RELEASE_READY
        assert (await evaluate_gate(session, run.id)).id == third.id


async def test_finding_history_is_bounded_scoped_and_projects_only_governance_fields(closed_cycle):
    context = closed_cycle
    async with AsyncSessionLocal() as session:
        finding = await transition_finding(session, context["finding"], FindingStatus.TRIAGED,
                                           reason="Operator reviewed the original Runner evidence.")
        await transition_finding(session, finding.id, FindingStatus.CONFIRMED,
                                 reason="Evidence confirms the product defect.")
        run = await session.get(CanonicalRun, context["run"])
        foreign_run, _, _, _ = await _seed(session)
        for entity_type, entity_id, run_id, action in (
            ("Mission", finding.id, run.id, "finding.confirmed"),
            ("Finding", uuid7(), run.id, "finding.confirmed"),
            ("Finding", finding.id, foreign_run.id, "finding.confirmed"),
            ("Finding", finding.id, run.id, "finding.evidence_linked"),
        ):
            session.add(AuditEvent(project_id=run.project_id, test_run_id=run_id,
                actor_type="USER", action=action, entity_type=entity_type, entity_id=entity_id,
                event_metadata={"reason": "PRIVATE_UNRELATED_RECORD"}))
        session.add(AuditEvent(project_id=run.project_id, test_run_id=run.id, actor_type="USER",
            actor_ref="PRIVATE_ACTOR_REF", action="finding.accepted", entity_type="Finding", entity_id=finding.id,
            before_state={"status": "PROVIDER_TEXT", "resolution": ["malformed"], "row_version": "3", "raw": "PRIVATE_STATE"},
            after_state={"status": "NEW", "resolution": None, "row_version": 1, "raw": "PRIVATE_STATE"},
            event_metadata={"reason": "r" * 2100, "provider_metadata": "PRIVATE_PROVIDER_BODY"}))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        endpoint = f"/api/v1/findings/{context['finding']}/history"
        latest = await client.get(endpoint, params={"limit": 1})
        assert latest.status_code == 200
        assert latest.json()["truncated"] is True and len(latest.json()["events"]) == 1
        event = latest.json()["events"][0]
        assert event["reason"] == "r" * 2000 and event["reason_truncated"] is True
        assert event["before"] == {"status": None, "resolution": None, "row_version": None}
        assert event["after"] == {"status": "NEW", "resolution": None, "row_version": 1}
        full = await client.get(endpoint)
        assert full.status_code == 200
        assert full.json()["truncated"] is False and len(full.json()["events"]) == 3
        assert [row["action"] for row in full.json()["events"]] == ["finding.accepted", "finding.confirmed", "finding.triaged"]
        assert full.json()["events"][1]["before"]["status"] == "TRIAGED"
        assert full.json()["events"][1]["after"]["status"] == "CONFIRMED"
        assert full.json()["events"][1]["actor_type"] == "USER"
        assert "PRIVATE_" not in full.text
        assert all("actor_ref" not in row and "event_metadata" not in row for row in full.json()["events"])
        for limit in (0, 101):
            assert (await client.get(endpoint, params={"limit": limit})).status_code == 422
        assert (await client.get(f"/api/v1/findings/{uuid7()}/history")).status_code == 404
