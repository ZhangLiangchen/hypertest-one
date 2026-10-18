"""Real PostgreSQL/Verifier/Gate tool contracts; execution rows are explicit fixtures."""
from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_gate import _official
from test_run_bindings import own_job
from test_snapshot_harness import source_snapshot as _source_snapshot
from test_test_design import case_proposal, requirement_proposal, risk_proposal

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import ProjectCreate
from hypertest.application.bindings import activate_run_binding, create_run_binding
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.harness_tools import (
    TOOL_MODELS,
    WIRE_BUDGET,
    HarnessTools,
    bounded_write_result,
)
from hypertest.application.inputs import cancel_open_inputs
from hypertest.application.jobs import submit_job
from hypertest.application.persistent_workspace import verify_workspace
from hypertest.application.services import ConflictError, canonical_json_sha256, create_project
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    CaseResult,
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    ProposalStatus,
)
from hypertest.domain.harness import RunHarnessState, RunReport, RunToolCall
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob, JobStatus, JobType
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    Mission,
    MissionAttempt,
    MissionProposal,
    Requirement,
    Verdict,
    utcnow,
)
from hypertest.domain.models import TestCase as CanonicalCase
from hypertest.harness_bridge.protocol import PROFILE, canonical
from hypertest.runner.artifacts import _path

source_snapshot = _source_snapshot


@pytest.fixture
async def tool_context(source_snapshot, monkeypatch, request):
    source, commit, repository = source_snapshot
    monkeypatch.setattr(get_settings(), "workspace_root", str(source.parent))
    workspace_id = uuid7().hex
    await verify_workspace(str(source), workspace_id, commit, repository, create=True)
    async with AsyncSessionLocal() as session:
        project = await create_project(session, ProjectCreate(key=public_key("PRJ"),
            name="Persistent tool integration", repository_url=repository))
        options = getattr(request, "param", {})
        run = await bootstrap_run(session, project.id, RunBootstrap(repository_url=repository,
            commit_sha=commit, prd_text=options.get("prd", "The addition function returns the sum of two integers."),
            configuration_text=options.get("configuration", "{}")))
        job = await submit_job(session, run.id, JobType.ADVANCE_RUN, idempotency_key="tools-test",
            payload={"execution_profile": PROFILE, "workspace": str(source), "backend": "docker", "max_steps": 32})
        token = await own_job(session, job)
        binding = await create_run_binding(session, run.id, job_id=job.id, lease_token=token,
            logical_worker_id=uuid7(), harness_host_id=get_settings().bridge_host_id, workspace_id=workspace_id)
        session.add(RunHarnessState(binding_id=binding.id, first_job_id=job.id,
            source_workspace=str(source), max_steps=32, timeout_seconds=300))
        await session.commit()
        await activate_run_binding(session, binding.id, 1, job_id=job.id, lease_token=token,
                                   provider_session_id=str(uuid7()))
        await session.commit()
        context = {"run_id": run.id, "binding_id": binding.id, "job_id": job.id,
                   "token": token, "agent_id": binding.primary_agent_session_id,
                   "source_id": run.source_snapshot_id, "workspace": workspace_id}
    try:
        yield context
    finally:
        async with AsyncSessionLocal() as session:
            job = await session.get(DurableJob, context["job_id"])
            await cancel_open_inputs(session, job)
            if job.status in ACTIVE_JOB_STATUSES:
                job.status, job.finished_at, job.lease_expires_at = JobStatus.FAILED, utcnow(), None
            await session.commit()


def tools(session, context):
    return HarnessTools(session, context["binding_id"], 1, context["job_id"], context["token"])


def result_input(admitted, proposals, key="complete"):
    return {"mission_id": admitted["mission_id"], "attempt_id": admitted["attempt_id"],
        "idempotency_key": key, "result": {"protocol": "hypertest.tmp/v1alpha2",
            "mission_id": admitted["contract"]["mission_id"], "status": "COMPLETED",
            "summary": "Structured test fixture proposal", "proposals": proposals}}


async def accepted_stage(harness, kind, proposals):
    admitted = await harness.dispatch("request_mission", {"mission_type": kind, "idempotency_key": kind})
    assert admitted["status"] == "ADMITTED", admitted
    result = await harness.dispatch("complete_mission", result_input(admitted, proposals, kind + "-result"))
    assert result["status"] == "ACCEPTED", result
    return result


async def prepare_gate(harness):
    """Accept four typed missions; add explicit official-fact fixtures for Gate tests."""
    requirement = await accepted_stage(harness, "ANALYZE_REQUIREMENTS", [requirement_proposal()])
    proposed_risk = risk_proposal(requirement["accepted_keys"][0])
    proposed_risk["object_payload"]["category"] = "FUNCTIONAL"
    risk = await accepted_stage(harness, "ANALYZE_RISKS", [proposed_risk])
    cases = await accepted_stage(harness, "DESIGN_TESTS", [case_proposal(risk["accepted_keys"][0])])
    _, _, _, _, run, source = await harness.state()
    implementation = {"proposal_type": "TEST_IMPLEMENTATION", "operation": "CREATE",
        "idempotency_key": "arithmetic-implementation", "object_payload": {
            "test_case_keys": cases["accepted_keys"], "repository_url": source.repository_url,
            "commit_sha": source.commit_sha, "file_path": "tests/test_add.py", "symbol": "test_add",
            "code": "from src.arithmetic import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"}}
    await accepted_stage(harness, "IMPLEMENT_TESTS", [implementation])
    case = await harness.db.scalar(select(CanonicalCase).where(CanonicalCase.source_snapshot_id == source.id))
    execution, evidence = await _official(harness.db, run, case, commit=source.commit_sha)
    return run, source, execution, evidence


def report_input(run, source, execution, evidence, verdict_key, key="report"):
    return {"schema_version": "hypertest.report/run-summary/v1", "idempotency_key": key,
        "test_run_id": str(run.id), "source_snapshot_id": str(source.id),
        "policy_snapshot_id": str(run.policy_snapshot_id), "commit_sha": source.commit_sha,
        "summary": "Report contract fixture", "markdown": "# Fixture report\nReferences accepted state only.",
        "execution_keys": [execution.key], "evidence_keys": [e.key for e in evidence],
        "finding_keys": [], "verdict_key": verdict_key, "unresolved": []}


async def test_get_state_exposes_versioned_inputs_and_only_filtered_source(tool_context):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        state = await harness.dispatch("get_state", {})
        assert state["test_run_id"] == str(tool_context["run_id"])
        assert "The addition function" in str(state["context"])
        listing = await harness.dispatch("get_state", {"resource": "source"})
        assert "src/arithmetic.py" in listing["files"] and ".env" not in listing["files"]
        assert not any(path.startswith((".aws/", ".ssh/", ".codex/")) for path in listing["files"])
        content = await harness.dispatch("get_state", {"resource": "source", "path": "src/arithmetic.py"})
        assert "return a + b" in content["content"]
        for path in (".env", "../.env", "/etc/passwd"):
            with pytest.raises(ConflictError, match="credential-filtered"):
                await harness.dispatch("get_state", {"resource": "source", "path": path})
        with pytest.raises(ConflictError, match="does not belong"):
            await harness.dispatch("get_state", {"resource": "evidence", "evidence_id": str(uuid7())})


async def test_typed_mission_contract_real_verifier_and_same_primary_session(tool_context):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        run, _, _, _ = await prepare_gate(harness)
        state = await harness.dispatch("get_state", {})
        assert all(len(state[key]) == 1 for key in ("requirements", "risks", "test_cases", "implementations"))
        attempts = list(await session.scalars(select(MissionAttempt).join(Mission)
            .where(Mission.test_run_id == run.id)))
        assert len(attempts) == 4
        assert all(a.agent_session_id == tool_context["agent_id"] and a.status is MissionAttemptStatus.ACCEPTED for a in attempts)
        missions = list(await session.scalars(select(Mission).where(Mission.test_run_id == run.id)))
        assert all(m.protocol_version == "v1alpha2" for m in missions)
        assert await session.scalar(select(func.count()).select_from(AgentSessionRecord)
            .where(AgentSessionRecord.test_run_id == run.id)) == 1


async def test_admission_rejects_out_of_order_stage_and_invalid_batch_atomically(tool_context):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        rejected = await harness.dispatch("request_mission", {"mission_type": "IMPLEMENT_TESTS", "idempotency_key": "wrong-order"})
        assert rejected["status"] == "REJECTED" and "ANALYZE_REQUIREMENTS" in rejected["reason"]
        admitted = await harness.dispatch("request_mission", {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "requirements"})
        assert admitted["contract"]["protocol"] == "hypertest.tmp/v1alpha2"
        mixed = [requirement_proposal(), risk_proposal("REQ-does-not-exist")]
        result = await harness.dispatch("complete_mission", result_input(admitted, mixed))
        assert result["status"] == "REJECTED"
        assert await session.scalar(select(func.count()).select_from(Requirement)
            .where(Requirement.source_snapshot_id == tool_context["source_id"])) == 0
        proposals = list(await session.scalars(select(MissionProposal).where(MissionProposal.attempt_id == UUID(admitted["attempt_id"]))))
        assert proposals and all(p.status is ProposalStatus.REJECTED for p in proposals)
        assert (await session.get(RunHarnessState, tool_context["binding_id"])).active_attempt_id is None


async def test_gate_and_report_reference_fresh_state_and_platform_decision(tool_context):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        run, source, execution, evidence = await prepare_gate(harness)
        gate = await harness.dispatch("evaluate_gate", {"idempotency_key": "gate"})
        assert gate["status"] == "FINAL" and gate["decision"] == "RELEASE_READY", gate
        args = report_input(run, source, execution, evidence, gate["verdict_key"])
        accepted = await harness.dispatch("submit_report", args)
        assert accepted["status"] == "ACCEPTED", accepted
        report = await session.get(RunReport, UUID(accepted["report_id"]))
        assert report.envelope["verdict_decision"] == "RELEASE_READY"
        assert report.envelope["evidence_keys"] == args["evidence_keys"]
        fresh = tools(session, tool_context)
        assert await fresh.dispatch("submit_report", args) == accepted
        assert fresh.report.id == report.id
        assert await session.scalar(select(func.count()).select_from(RunReport).where(RunReport.binding_id == harness.binding_id)) == 1


@pytest.mark.parametrize("changed", ["canonical", "artifact", "references", "verdict"])
async def test_report_rejects_changed_state_artifacts_or_wrong_references(tool_context, changed):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        run, source, execution, evidence = await prepare_gate(harness)
        gate = await harness.dispatch("evaluate_gate", {"idempotency_key": "gate"})
        args = report_input(run, source, execution, evidence, gate["verdict_key"])
        if changed == "canonical":
            req = await session.scalar(select(Requirement).where(Requirement.source_snapshot_id == source.id))
            req.description += " Updated acceptance condition."
            await session.commit()
        elif changed == "artifact":
            _path(evidence[0].sha256).unlink()
        elif changed == "references":
            args["evidence_keys"] = []
        else:
            args["verdict_key"] = "VERDICT-foreign"
        result = await harness.dispatch("submit_report", args)
        assert result["status"] == "REJECTED", result
        assert not await session.scalar(select(RunReport).where(RunReport.binding_id == harness.binding_id))


async def test_started_operation_without_committed_result_is_unknown_and_not_replayed(tool_context, monkeypatch):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        args = {"idempotency_key": "unresolved-execution"}
        parsed = TOOL_MODELS["request_execution"][0].model_validate(args)
        call = RunToolCall(id=uuid7(), binding_id=harness.binding_id, durable_job_id=harness.job_id,
            binding_epoch=1, tool_name="request_execution", idempotency_key=args["idempotency_key"],
            input_sha256=canonical_json_sha256({"tool": "request_execution", "arguments": parsed.model_dump(mode="json")}), status="STARTED")
        session.add(call)
        await session.commit()

        async def forbidden(*args, **kwargs):
            raise AssertionError("unknown external execution must not replay")

        monkeypatch.setattr(harness, "request_execution", forbidden)
        with pytest.raises(ConflictError, match="OUTCOME_UNKNOWN"):
            await harness.dispatch("request_execution", args)
        await session.refresh(call)
        assert call.status == "UNKNOWN"
        assert (await harness.dispatch("get_state", {}))["unresolved_tool_calls"][0]["id"] == str(call.id)


@pytest.mark.parametrize("operation", ["request_mission", "complete_mission", "ask_user", "evaluate_gate", "submit_report"])
async def test_started_operations_reconcile_exact_committed_result_without_repeating_handler(tool_context, monkeypatch, operation):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        if operation in {"evaluate_gate", "submit_report"}:
            run, source, execution, evidence = await prepare_gate(harness)
            if operation == "submit_report":
                gate = await harness.dispatch("evaluate_gate", {"idempotency_key": "prepare-gate"})
                args = report_input(run, source, execution, evidence, gate["verdict_key"], key="crash-report")
            else:
                args = {"idempotency_key": "crash-gate"}
        elif operation == "complete_mission":
            admitted = await harness.dispatch("request_mission", {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "prepare-stage"})
            args = result_input(admitted, [requirement_proposal()], key="crash-complete")
        elif operation == "ask_user":
            args = {"scope": "run", "idempotency_key": "crash-question",
                "request": {"question_id": "question", "question": "Continue?", "options": []}}
        else:
            args = {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "crash-admission"}
        original_audit = harness.audit

        async def fail_at_completion(action, entity_id, payload):
            if action == "harness.tool_completed":
                # ask_user writes atomically with completion; persist the intent
                # first to model a crash after its own durable checkpoint.
                if operation == "ask_user":
                    await session.flush()
                    state = await session.get(RunHarnessState, harness.binding_id)
                    pending = dict(state.pending_input)
                    await session.rollback()
                    state = await session.get(RunHarnessState, harness.binding_id)
                    state.pending_input = pending
                    await session.commit()
                raise RuntimeError("crash after domain commit before tool completion")
            await original_audit(action, entity_id, payload)

        monkeypatch.setattr(harness, "audit", fail_at_completion)
        with pytest.raises(RuntimeError, match="crash after"):
            await harness.dispatch(operation, args)
        await session.rollback()
        fresh = tools(session, tool_context)

        async def forbidden(*args, **kwargs):
            raise AssertionError("committed operation must reconcile, not execute again")

        monkeypatch.setattr(fresh, operation, forbidden)
        result = await fresh.dispatch(operation, args)
        assert result["status"] in {"ADMITTED", "ACCEPTED", "SUSPENDING", "FINAL"}, result
        call = await session.scalar(select(RunToolCall).where(RunToolCall.binding_id == fresh.binding_id,
            RunToolCall.idempotency_key == args["idempotency_key"]))
        assert call.status == "SUCCEEDED"
        assert await session.scalar(select(AuditEvent).where(AuditEvent.action == "harness.tool_reconciled", AuditEvent.entity_id == call.id))
        if operation == "evaluate_gate":
            assert await session.scalar(select(func.count()).select_from(Verdict).where(Verdict.test_run_id == tool_context["run_id"])) == 1
        if operation == "submit_report":
            assert fresh.report and fresh.report.id == UUID(result["report_id"])


@pytest.mark.parametrize("tool_context", [{
    "prd": ("中文需求。" * 400_000)[:2_000_000],
    "configuration": "configuration=" + "x" * 99_980,
}], indirect=True)
async def test_large_frozen_inputs_are_chunked_without_changing_their_content(tool_context):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        overview = await harness.dispatch("get_state", {})
        assert len(canonical(overview)) < 2_000_000
        for resource, field, total in (("prd", "prd_text", 2_000_000),
                                       ("configuration", "configuration_text", 99_994)):
            initial = overview["context"][field]
            assert len(initial) == 24000
            continuation = overview["context"][field + "_continuation"]
            assert continuation["resource"] == resource and continuation["offset"] == 24000
            first = await harness.dispatch("get_state", {"resource": resource})
            second = await harness.dispatch("get_state", {"resource": resource, "offset": first["next_offset"]})
            last = await harness.dispatch("get_state", {"resource": resource, "offset": total - 17})
            assert first["content"] == initial and len(second["content"]) == 24000
            assert len(last["content"]) == 17 and last["next_offset"] is None
            assert len(canonical(first)) < 150_000
        admitted = await harness.dispatch("request_mission", {
            "mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "large-prd-admission"})
        assert admitted["status"] == "ADMITTED" and len(canonical(admitted)) < 2_000_000
        assert len(admitted["contract"]["context"]["prd_text"]) == 24000
        assert admitted["contract"]["context"]["prd_text_continuation"]["resource"] == "prd"


async def test_state_collection_pagination_is_explicit_stable_and_complete(tool_context):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        proposals = []
        for number in range(36):
            proposal = requirement_proposal()
            proposal["idempotency_key"] = f"page-requirement-{number}"
            proposal["object_payload"].update(logical_key=f"requirement.{number}",
                title=f"Requirement {number}", description=f"Distinct expected behavior {number}.",
                source_ref=f"PRD#{number}")
            proposals.append(proposal)
        await accepted_stage(harness, "ANALYZE_REQUIREMENTS", proposals)
        first = await harness.dispatch("get_state", {"collection": "requirements"})
        page = first["collections"]["requirements"]
        assert page == {"total": 36, "next_offset": 30}
        assert len(first["requirements"]) == 30 and "risks" not in first
        second = await harness.dispatch("get_state", {"collection": "requirements", "offset": page["next_offset"]})
        assert len(second["requirements"]) == 6
        assert second["collections"]["requirements"]["next_offset"] is None
        ids = [row["id"] for row in first["requirements"] + second["requirements"]]
        assert len(set(ids)) == 36 and ids == sorted(ids)
        repeated = await harness.dispatch("get_state", {"collection": "requirements", "offset": 30})
        assert repeated["requirements"] == second["requirements"]
        empty = await harness.dispatch("get_state", {"collection": "requirements", "offset": 36})
        assert empty["requirements"] == [] and empty["collections"]["requirements"]["total"] == 36


async def read_json_resource(harness, request):
    parts = []
    offset = 0
    while True:
        page = await harness.dispatch("get_state", {**request, "offset": offset})
        assert page["encoding"] == "json" and len(canonical(page)) <= WIRE_BUDGET
        parts.append(page["content"])
        if page["next_offset"] is None:
            return json.loads("".join(parts))
        assert page["next_offset"] > offset
        offset = page["next_offset"]


async def test_large_canonical_rows_and_mission_targets_remain_fully_readable_below_wire_budget(tool_context):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        proposals = []
        for number in range(6):
            proposed = requirement_proposal()
            proposed["idempotency_key"] = f"large-{number}"
            proposed["object_payload"].update(logical_key=f"large.{number}", title=f"Large requirement {number}",
                description=("中文验收条件。" * 22_000) + str(number), source_ref=f"PRD#{number}")
            proposals.append(proposed)
        accepted = await accepted_stage(harness, "ANALYZE_REQUIREMENTS", proposals)
        assert len(accepted["accepted_keys"]) == 6
        overview = await harness.dispatch("get_state", {})
        assert len(canonical(overview)) <= WIRE_BUDGET
        row = overview["requirements"][0]
        assert row["_truncated"] and row["_detail"]["resource"] == "entity"
        detail = await read_json_resource(harness, {key: value for key, value in row["_detail"].items() if key != "offset"})
        original = await session.get(Requirement, UUID(row["id"]))
        assert detail["description"] == original.description
        admitted = await harness.dispatch("request_mission", {
            "mission_type": "ANALYZE_RISKS", "idempotency_key": "large-context-admission"})
        assert admitted["status"] == "ADMITTED" and len(canonical(admitted)) <= WIRE_BUDGET
        contract = admitted["contract"]
        assert contract["_truncated"] and contract["_detail"]["resource"] == "contract"
        full_contract = await read_json_resource(harness, {
            "resource": "contract", "mission_id": admitted["mission_id"]})
        assert len(full_contract["targets"]["requirements"]) == 6
        descriptions = [item["description"] for item in full_contract["context"]["requirements"]]
        assert descriptions == [item["object_payload"]["description"] for item in proposals]
        assert len(canonical(await harness.dispatch("get_state", {}))) <= WIRE_BUDGET
        with pytest.raises(ConflictError, match="does not belong"):
            await harness.dispatch("get_state", {"resource": "entity", "collection": "requirements", "entity_id": str(uuid7())})
        with pytest.raises(ConflictError, match="does not belong"):
            await harness.dispatch("get_state", {"resource": "contract", "mission_id": str(uuid7())})


def test_large_accepted_outcome_is_summarized_without_becoming_transport_failure():
    result = bounded_write_result({"status": "ACCEPTED", "mission_id": str(uuid7()),
        "attempt_id": str(uuid7()), "accepted_keys": ["x" * 5000] * 1000})
    assert result["status"] == "ACCEPTED" and result["response_truncated"]
    assert result["contract_resource"]["resource"] == "contract"
    assert len(canonical(result)) <= WIRE_BUDGET


async def test_completed_failure_diagnosis_allows_negative_gate_and_report_without_reopening_stage(tool_context):
    async with AsyncSessionLocal() as session:
        harness = tools(session, tool_context)
        run, source, _, _ = await prepare_gate(harness)
        case = await session.scalar(select(CanonicalCase).where(CanonicalCase.source_snapshot_id == source.id))
        failed_execution, failed_evidence = await _official(session, run, case,
            commit=source.commit_sha, result=CaseResult.FAIL)
        # A premature Gate request may inspect admission, but cannot authorize
        # creation of a different typed stage as a side effect.
        rejected = await harness.dispatch("evaluate_gate", {"idempotency_key": "premature-failure-gate"})
        assert rejected["status"] == "REJECTED" and "DIAGNOSE_FAILURE" in rejected["reason"]
        assert await session.scalar(select(func.count()).select_from(Mission).where(
            Mission.test_run_id == run.id, Mission.mission_type == MissionType.DIAGNOSE_FAILURE)) == 0
        admitted = await harness.dispatch("request_mission", {
            "mission_type": "DIAGNOSE_FAILURE", "idempotency_key": "diagnose-official-failure"})
        assert admitted["status"] == "ADMITTED", admitted
        state = await harness.dispatch("get_state", {})
        finding = {"proposal_type": "FINDING", "operation": "CREATE", "idempotency_key": "official-defect",
            "object_payload": {"classification": "PRODUCT_DEFECT", "severity": "BLOCKER",
                "title": "Official execution observed incorrect behavior", "description": "The official case failed its expected result.",
                "confidence": 0.95, "evidence_keys": [item.key for item in failed_evidence],
                "test_case_keys": [case.key], "requirement_keys": [item["key"] for item in state["requirements"]],
                "risk_keys": [item["key"] for item in state["risks"]]}}
        accepted = await harness.dispatch("complete_mission", result_input(admitted, [finding], "diagnosis-result"))
        assert accepted["status"] == "ACCEPTED", accepted
        gate = await harness.dispatch("evaluate_gate", {"idempotency_key": "post-diagnosis-gate"})
        assert gate["status"] == "FINAL" and gate["decision"] == "RELEASE_BLOCKED", gate
        state = await harness.dispatch("get_state", {})
        report = report_input(run, source, failed_execution, failed_evidence, gate["verdict_key"], "negative-report")
        report.update(execution_keys=[item["key"] for item in state["executions"]],
            evidence_keys=[item["key"] for item in state["evidence"]],
            finding_keys=[item["key"] for item in state["findings"]])
        saved = await harness.dispatch("submit_report", report)
        assert saved["status"] == "ACCEPTED", saved
        diagnostics = list(await session.scalars(select(Mission).where(
            Mission.test_run_id == run.id, Mission.mission_type == MissionType.DIAGNOSE_FAILURE)))
        assert len(diagnostics) == 1 and diagnostics[0].status is MissionStatus.COMPLETED
        attempts = list(await session.scalars(select(MissionAttempt).where(MissionAttempt.mission_id == diagnostics[0].id)))
        assert len(attempts) == 1 and attempts[0].status is MissionAttemptStatus.ACCEPTED
        stored_report = await session.get(RunReport, UUID(saved["report_id"]))
        assert stored_report.envelope["verdict_decision"] == "RELEASE_BLOCKED"
