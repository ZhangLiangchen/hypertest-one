"""PostgreSQL guards protect operational history independently of service checks."""
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_run_bindings import bound_run as _bound_run
from test_test_design import create_run

from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import FindingClassification, FindingSeverity, FindingStatus
from hypertest.domain.harness import (
    GitLabIssueOperation,
    RunHarnessState,
    RunReport,
    RuntimeControlRequest,
    RunToolCall,
)
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import Finding, utcnow
from hypertest.domain.models import TestRun as CanonicalRun

bound_run = _bound_run


async def foreign_job(session):
    run = await create_run(session)
    job = DurableJob(id=uuid7(), key=public_key("J"), project_id=run.project_id,
        test_run_id=run.id, job_type=JobType.ADVANCE_RUN, status=JobStatus.FAILED,
        idempotency_key=uuid7().hex, payload={}, finished_at=utcnow())
    session.add(job)
    await session.commit()
    return job.id


async def rejected_sql(statement, params, match):
    async with AsyncSessionLocal() as session:
        with pytest.raises(DBAPIError, match=match):
            await session.execute(text(statement), params)
            await session.commit()
        await session.rollback()


async def test_checkpoint_freezes_budget_and_source_but_retains_pending_input(bound_run):
    bound = bound_run
    async with AsyncSessionLocal() as session:
        state = RunHarnessState(binding_id=bound["binding_id"], first_job_id=bound["job_id"],
            source_workspace="/workspaces/pinned", max_steps=12, timeout_seconds=300)
        session.add(state)
        await session.commit()
        state.pending_input = {"scope": "run", "request": {"question_id": "next", "question": "Continue?"}}
        state.last_call_id, state.last_job_id, state.last_call_epoch = "call-1", bound["job_id"], 1
        await session.commit()
        await session.refresh(state)
        assert state.pending_input["request"]["question"] == "Continue?"
        assert state.harness_budget_seconds == 3600
        other = await foreign_job(session)
    for expression, match in (
        ("max_steps=32", "initial configuration is immutable"),
        ("harness_budget_seconds=7200", "initial configuration is immutable"),
        ("source_workspace='/replacement'", "initial configuration is immutable"),
        ("last_job_id=:other", "call checkpoint ownership mismatch"),
        ("last_call_epoch=2", "call checkpoint ownership mismatch"),
        ("last_call_id=NULL", "call job and epoch together"),
        ("pending_input='[]'::jsonb", "pending input must be a bounded object"),
    ):
        await rejected_sql(f"UPDATE run_harness_states SET {expression} WHERE binding_id=:id",
            {"id": bound["binding_id"], "other": other}, match)
    await rejected_sql("DELETE FROM run_harness_states WHERE binding_id=:id", {"id": bound["binding_id"]}, "cannot be deleted")
    async with AsyncSessionLocal() as session:
        state = await session.get(RunHarnessState, bound["binding_id"])
        assert state.max_steps == 12 and state.last_call_epoch == 1
        state.pending_input = None
        await session.commit()


async def test_checkpoint_rejects_foreign_first_job_and_half_active_stage(bound_run):
    async with AsyncSessionLocal() as session:
        other = await foreign_job(session)
        state = RunHarnessState(binding_id=bound_run["binding_id"], first_job_id=other,
            source_workspace="/workspaces/pinned", max_steps=12, timeout_seconds=300)
        session.add(state)
        with pytest.raises(DBAPIError, match="first job must belong to its run"):
            await session.commit()
        await session.rollback()
        state = RunHarnessState(binding_id=bound_run["binding_id"], first_job_id=bound_run["job_id"],
            source_workspace="/workspaces/pinned", max_steps=12, timeout_seconds=300,
            active_mission_id=uuid7())
        session.add(state)
        with pytest.raises(DBAPIError, match="mission and attempt must be paired"):
            await session.commit()
        await session.rollback()


async def test_tool_call_unknown_is_reconciled_once_and_result_history_cannot_be_rewritten(bound_run):
    async with AsyncSessionLocal() as session:
        call = RunToolCall(id=uuid7(), binding_id=bound_run["binding_id"], durable_job_id=bound_run["job_id"],
            binding_epoch=1, tool_name="request_execution", idempotency_key="execution", input_sha256="a"*64)
        session.add(call)
        await session.commit()
        call_id = call.id
        call.status = "UNKNOWN"
        await session.commit()
        call.status, call.result, call.finished_at = "SUCCEEDED", {"execution_id": str(uuid7())}, utcnow()
        await session.commit()
        original = dict(call.result)
    for expression, match in (("result='{}'::jsonb", "terminal tool call history"),
        ("status='STARTED'", "terminal tool call history"),
        ("input_sha256=repeat('b',64)", "identity and input are immutable")):
        await rejected_sql(f"UPDATE run_tool_calls SET {expression} WHERE id=:id", {"id": call_id}, match)
    await rejected_sql("DELETE FROM run_tool_calls WHERE id=:id", {"id": call_id}, "cannot be deleted")
    async with AsyncSessionLocal() as session:
        assert (await session.get(RunToolCall, call_id)).result == original


@pytest.mark.parametrize("budget", [0, 7201])
async def test_checkpoint_rejects_out_of_bounds_active_time_budget(bound_run, budget):
    async with AsyncSessionLocal() as session:
        state = RunHarnessState(binding_id=bound_run["binding_id"], first_job_id=bound_run["job_id"],
            source_workspace="/workspaces/pinned", max_steps=12, timeout_seconds=300,
            harness_budget_seconds=budget)
        session.add(state)
        with pytest.raises(DBAPIError, match="ck_harness_budgets"):
            await session.commit()
        await session.rollback()


async def test_bridge_call_reservation_is_preserved_until_verified_terminal_time(bound_run):
    async with AsyncSessionLocal() as session:
        call = RunToolCall(id=uuid7(), binding_id=bound_run["binding_id"], durable_job_id=bound_run["job_id"],
            binding_epoch=1, tool_name="__bridge_call__", idempotency_key="bridge:call-budget", input_sha256="a"*64,
            result={"reserved_seconds": 60, "call_id": "call-budget"})
        session.add(call)
        await session.commit()
        call_id = call.id
        call.status = "UNKNOWN"
        await session.commit()
    for expression, match in (
        ("result=jsonb_set(result,'{reserved_seconds}','30')", "reservation and identity are immutable"),
        ("result=jsonb_set(result,'{call_id}','\"replacement\"')", "reservation and identity are immutable"),
        ("result=result||jsonb_build_object('elapsed_seconds',0)", "cannot release reserved time"),
        ("status='SUCCEEDED',finished_at=now(),result=result||jsonb_build_object('elapsed_seconds',61,'native_status','COMPLETED')", "requires verified elapsed time"),
        ("status='FAILED',finished_at=now(),result=result||jsonb_build_object('elapsed_seconds',-1,'native_status','FAILED')", "requires verified elapsed time"),
    ):
        await rejected_sql(f"UPDATE run_tool_calls SET {expression} WHERE id=:id", {"id": call_id}, match)
    async with AsyncSessionLocal() as session:
        call = await session.get(RunToolCall, call_id)
        call.status, call.finished_at = "SUCCEEDED", utcnow()
        call.result = {**call.result, "elapsed_seconds": 12, "native_status": "COMPLETED"}
        await session.commit()
        assert call.result["reserved_seconds"] == 60 and call.result["elapsed_seconds"] == 12


@pytest.mark.parametrize("invalid", ["job", "epoch", "initial_result", "digest"])
async def test_tool_call_insert_rejects_foreign_or_fabricated_identity(bound_run, invalid):
    async with AsyncSessionLocal() as session:
        other = await foreign_job(session) if invalid == "job" else bound_run["job_id"]
        call = RunToolCall(binding_id=bound_run["binding_id"], durable_job_id=other,
            binding_epoch=2 if invalid == "epoch" else 1, tool_name="evaluate_gate", idempotency_key="gate",
            input_sha256="not-a-hash" if invalid == "digest" else "a"*64,
            result={"status":"SUCCEEDED"} if invalid == "initial_result" else None)
        session.add(call)
        with pytest.raises(DBAPIError, match="ownership mismatch|epoch is not current|outcome does not match|input digest"):
            await session.commit()
        await session.rollback()


async def test_report_is_append_only_and_cross_run_or_different_content_address_is_rejected(bound_run):
    async with AsyncSessionLocal() as session:
        other = await foreign_job(session)
        report = RunReport(id=uuid7(), binding_id=bound_run["binding_id"], test_run_id=bound_run["run_id"],
            durable_job_id=bound_run["job_id"], idempotency_key="report", envelope={"verdict_key":"V-fixture"},
            artifact_uri="sha256:"+"a"*64, content_sha256="a"*64)
        session.add(report)
        await session.commit()
        report_id = report.id
    for expression in ("envelope='{}'::jsonb", "content_sha256=repeat('b',64)", "durable_job_id=:other"):
        await rejected_sql(f"UPDATE run_reports SET {expression} WHERE id=:id", {"id":report_id,"other":other}, "append-only")
    await rejected_sql("DELETE FROM run_reports WHERE id=:id", {"id":report_id}, "append-only")
    for job_id, uri in ((other,"sha256:"+"a"*64), (bound_run["job_id"],"sha256:"+"b"*64)):
        async with AsyncSessionLocal() as session:
            session.add(RunReport(binding_id=bound_run["binding_id"], test_run_id=bound_run["run_id"],
                durable_job_id=job_id, idempotency_key=uuid7().hex, envelope={}, artifact_uri=uri,content_sha256="a"*64))
            with pytest.raises(DBAPIError, match="ownership mismatch|immutable content address"):
                await session.commit()
            await session.rollback()


async def test_control_unknown_is_terminal_and_payload_cannot_change_after_queueing():
    async with AsyncSessionLocal() as session:
        now=utcnow()
        control=RuntimeControlRequest(id=uuid7(),operation="CAPABILITIES",payload={},created_at=now,expires_at=now+timedelta(seconds=30))
        session.add(control)
        await session.commit()
        control_id=control.id
        control.status,control.error_code,control.finished_at="UNKNOWN","CONTROL_DEADLINE_EXPIRED",utcnow()
        await session.commit()
    for expression,match in (("status='QUEUED',finished_at=NULL", "terminal runtime control"),
        ("payload='{\"binding_id\":\"forged\"}'::jsonb", "identity is immutable")):
        await rejected_sql(f"UPDATE runtime_control_requests SET {expression} WHERE id=:id", {"id":control_id},match)
    await rejected_sql("DELETE FROM runtime_control_requests WHERE id=:id", {"id":control_id}, "cannot be deleted")


async def test_issue_authorization_and_actual_reference_are_irreversible_history(bound_run):
    async with AsyncSessionLocal() as session:
        run=await session.get(CanonicalRun,bound_run["run_id"])
        finding=Finding(id=uuid7(),key=public_key("F"),project_id=run.project_id,test_run_id=run.id,
            fingerprint=uuid7().hex*2,classification=FindingClassification.PRODUCT_DEFECT,
            severity=FindingSeverity.MAJOR,title="Fixture defect",description="Test constraint",status=FindingStatus.NEW,reported_by_type="AGENT")
        session.add(finding)
        await session.flush()
        op=GitLabIssueOperation(id=uuid7(),binding_id=bound_run["binding_id"],test_run_id=run.id,
            finding_id=finding.id,durable_job_id=bound_run["job_id"],input_sha256="a"*64,
            draft={"title":"Frozen"},authorization={"project_id":42,"assignee_id":7})
        session.add(op)
        await session.commit()
        op_id=op.id
        op.status="UNKNOWN"
        await session.commit()
        op.status,op.issue_iid,op.issue_url="SUCCEEDED",42,"https://gitlab.example.test/team/project/-/issues/42"
        await session.commit()
    for expression,match in (("\"authorization\"='{}'::jsonb","authorization and ownership are immutable"),
        ("draft='{}'::jsonb","authorization and ownership are immutable"),
        ("issue_iid=43", "terminal GitLab operation history")):
        await rejected_sql(f"UPDATE gitlab_issue_operations SET {expression} WHERE id=:id",{"id":op_id},match)
    await rejected_sql("DELETE FROM gitlab_issue_operations WHERE id=:id",{"id":op_id},"cannot be deleted")
    async with AsyncSessionLocal() as session:
        assert (await session.scalar(select(GitLabIssueOperation).where(GitLabIssueOperation.id==op_id))).issue_iid==42
