"""Real PostgreSQL/Worker contracts with a fake host transport, not model acceptance."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import select
from test_run_bindings import own_job
from test_snapshot_harness import source_snapshot as _source_snapshot

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import ProjectCreate
from hypertest.application import persistent
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.harness_tools import HarnessTools
from hypertest.application.inputs import answer_input_request, cancel_open_inputs
from hypertest.application.jobs import cancel_job, submit_job
from hypertest.application.persistent_workspace import workspace_path
from hypertest.application.services import create_project
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.enums import AgentSessionStatus, MissionAttemptStatus
from hypertest.domain.harness import RunHarnessState, RunReport, RunToolCall
from hypertest.domain.inputs import InputRequestStatus, MissionInputRequest
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob, JobStatus, JobType
from hypertest.domain.models import AgentSessionRecord, MissionAttempt, utcnow
from hypertest.domain.run_inputs import RunInputRequest
from hypertest.harness_bridge.protocol import PROFILE, BridgeError
from hypertest.runner.artifacts import store_content
from hypertest.worker import run_claimed_job

source_snapshot = _source_snapshot


def question(scope="run", key="question-one"):
    return ("ask_user", {"scope": scope, "idempotency_key": key,
        "request": {"question_id": key, "question": "Should testing continue?", "options": ["Continue", "Stop"]}})


class FakeBridge:
    """Use the actual Worker and domain dispatch, injecting only host transport."""
    def __init__(self):
        self.native = str(uuid7())
        self.program = [question()]
        self.created, self.started, self.restored = [], [], []
        self.interrupted, self.closed, self.renewed, self.recovered = [], [], [], []
        self.results = []
        self.calls = {}
        self.epoch = 1
        self.start_ack_lost = False
        self.restore_error = None
        self.elapsed_seconds = 0.1

    async def capabilities(self):
        return {"profile": PROFILE, "host_id": get_settings().bridge_host_id}

    async def create_session(self, context):
        self.created.append(context)
        return {"session_id": context.session_id}

    async def start_call(self, context, contract, *, call_id, resume=False):
        self.started.append((context, contract, call_id, resume))
        self.calls[call_id] = {"context": context, "pending": list(self.program), "stopped": False,
                              "elapsed_seconds": self.elapsed_seconds}
        if self.start_ack_lost:
            raise BridgeError("OUTCOME_UNKNOWN", "simulated lost ACK")
        return {"call_id": call_id, "status": "RUNNING"}

    async def get_call(self, context, call_id, cursor=0, management=False):
        call = self.calls[call_id]
        pending = call["pending"]
        return {"call_id": call_id, "cursor": cursor + 1, "provider_session_id": self.native,
            "status": "RUNNING" if pending else "COMPLETED", "stopped": call["stopped"],
            "elapsed_seconds": call["elapsed_seconds"],
            "pending_tools": ([{"tool_call_id": "tool-" + str(len(self.results)),
                "name": pending[0][0], "arguments": pending[0][1]}] if pending else [])}

    async def respond_tool(self, context, call_id, tool_call_id, result):
        call = self.calls[call_id]
        name, _ = call["pending"].pop(0)
        self.results.append((name, result))
        return {"accepted": True}

    async def renew(self, context, call_id):
        assert context.expires_at > 0 and context.binding_epoch == self.epoch
        self.renewed.append((context, call_id))
        return {"expires_at": context.expires_at}

    async def interrupt(self, context, call_id):
        self.interrupted.append((context, call_id))
        self.calls[call_id]["stopped"] = True
        return {"stopped": True}

    async def restore_session(self, context):
        self.restored.append(context)
        if self.restore_error:
            raise BridgeError(self.restore_error)
        return {"provider_session_id": self.native, "workspace_id": context.workspace_id,
                "binding_epoch": self.epoch, "recovery_required": False}

    async def recover(self, context, call_id, *, new_epoch):
        self.recovered.append((context, call_id, new_epoch))
        self.epoch = new_epoch
        return {"binding_epoch": new_epoch, "provider_session_id": self.native}

    async def close(self, context, call_id, terminal=True):
        self.closed.append((context, call_id))
        return {"closed": True, "stopped": True}


@pytest.fixture
async def runtime_context(source_snapshot, monkeypatch):
    source, commit, repository = source_snapshot
    settings = get_settings()
    monkeypatch.setattr(settings, "workspace_root", str(source.parent))
    monkeypatch.setattr(settings, "worker_heartbeat_seconds", 0.1)
    monkeypatch.setattr(settings, "worker_lease_seconds", 30)
    monkeypatch.setattr(settings, "harness_mode", "bridge")
    bridge = FakeBridge()
    monkeypatch.setattr(persistent, "bridge_client", lambda: bridge)

    async def fingerprint(_):
        return "fake-runner-fingerprint-for-runtime-only"

    async def cleanup(*args, **kwargs):
        return {}

    monkeypatch.setattr(persistent.DockerRunner, "fingerprint", fingerprint)
    monkeypatch.setattr("hypertest.worker.cleanup_job_resources", cleanup)
    async with AsyncSessionLocal() as session:
        project = await create_project(session, ProjectCreate(key=public_key("PRJ"),
            name="Persistent runtime integration", repository_url=repository))
        run = await bootstrap_run(session, project.id, RunBootstrap(repository_url=repository,
            commit_sha=commit, prd_text="The addition function returns the sum of two integers."))
        job = await submit_job(session, run.id, JobType.ADVANCE_RUN, idempotency_key="persistent-test",
            payload={"execution_profile": PROFILE, "workspace": str(source), "backend": "docker"})
        await own_job(session, job)
        value = {"run_id": run.id, "job": job, "bridge": bridge, "source": source}
    try:
        yield value
    finally:
        async with AsyncSessionLocal() as session:
            jobs = list(await session.scalars(select(DurableJob).where(DurableJob.test_run_id == value["run_id"])))
            for job in jobs:
                await cancel_open_inputs(session, job)
                if job.status in ACTIVE_JOB_STATUSES:
                    job.status, job.finished_at, job.lease_expires_at = JobStatus.FAILED, utcnow(), None
            await session.commit()


async def binding_rows(session, context):
    binding = await session.scalar(select(RunExecutionBinding).where(RunExecutionBinding.test_run_id == context["run_id"]))
    agent = await session.get(AgentSessionRecord, binding.primary_agent_session_id)
    state = await session.get(RunHarnessState, binding.id)
    return binding, agent, state


@pytest.mark.parametrize("scope", ["run", "mission"])
async def test_question_answer_resumes_same_binding_native_workspace_and_attempt(runtime_context, scope):
    context, bridge = runtime_context, runtime_context["bridge"]
    bridge.program = [("get_state", {})]
    if scope == "mission":
        bridge.program.append(("request_mission", {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "analysis"}))
    bridge.program.append(question(scope))
    paused = await run_claimed_job(context["job"])
    assert paused.status is JobStatus.WAITING_INPUT, (paused.error_code, paused.error_message, bridge.results)
    async with AsyncSessionLocal() as session:
        binding, agent, state = await binding_rows(session, context)
        identity = (binding.id, binding.logical_worker_id, agent.id, agent.provider_session_id, binding.workspace_id)
        original_attempt = state.active_attempt_id
        assert binding.status is BindingStatus.WAITING_INPUT and binding.binding_epoch == 1
        assert agent.status is AgentSessionStatus.WAITING_INPUT and agent.provider_session_id == bridge.native
        assert workspace_path(binding.workspace_id).joinpath("src/arithmetic.py").is_file()
        assert not workspace_path(binding.workspace_id).joinpath(".env").exists()
        question_id = UUID(paused.result["input_request_id"])
        model = RunInputRequest if scope == "run" else MissionInputRequest
        stored = await session.get(model, question_id)
        assert stored.status is InputRequestStatus.PENDING
        await answer_input_request(session, stored.id, answer="Continue with the original expectations.",
                                   expected_row_version=stored.row_version, idempotency_key="answer-first")
        resumed = await session.get(DurableJob, paused.id)
        old_token = context["job"].lease_token
        await own_job(session, resumed)
        assert resumed.lease_token != old_token
    bridge.program = [("get_state", {}), question(scope, "question-two")]
    paused_again = await run_claimed_job(resumed)
    assert paused_again.status is JobStatus.WAITING_INPUT, (paused_again.error_code, paused_again.error_message)
    async with AsyncSessionLocal() as session:
        binding, agent, state = await binding_rows(session, context)
        assert identity == (binding.id, binding.logical_worker_id, agent.id, agent.provider_session_id, binding.workspace_id)
        assert binding.binding_epoch == 1 and state.active_attempt_id == original_attempt
        assert (await session.get(model, question_id)).status is InputRequestStatus.CONSUMED
        if scope == "mission":
            assert (await session.get(MissionAttempt, original_attempt)).status is MissionAttemptStatus.RUNNING
    assert len(bridge.created) == 1 and len(bridge.started) == 2
    assert [item[3] for item in bridge.started] == [False, True]
    assert bridge.started[0][0].session_id == bridge.started[1][0].session_id
    assert "Continue with the original expectations." in str(bridge.results)
    assert not bridge.closed


async def test_ambiguous_start_ack_reconciles_original_call_without_replay(runtime_context):
    bridge = runtime_context["bridge"]
    bridge.start_ack_lost = True
    paused = await run_claimed_job(runtime_context["job"])
    assert paused.status is JobStatus.WAITING_INPUT, paused.error_message
    assert len(bridge.started) == 1 and len(bridge.created) == 1


@pytest.mark.parametrize("rejected_tool", [
    ("get_state", {"resource": "evidence"}),
    ("get_state", {"resource": "entity", "collection": "requirements", "entity_id": str(uuid7())}),
    ("request_execution", {"idempotency_key": "premature-execution"}),
])
@pytest.mark.parametrize("active_mission", [False, True])
async def test_rejected_tool_continues_same_native_call_after_database_rollback(
    runtime_context, rejected_tool, active_mission,
):
    bridge = runtime_context["bridge"]
    prefix = [("request_mission", {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "analysis"})] if active_mission else []
    bridge.program = [*prefix, rejected_tool, ("get_state", {}), question("mission" if active_mission else "run")]
    paused = await run_claimed_job(runtime_context["job"])
    assert paused.status is JobStatus.WAITING_INPUT, (paused.error_code, paused.error_message, bridge.results)
    assert bridge.results[len(prefix)][1]["status"] == "REJECTED"
    assert [name for name, _ in bridge.results] == [*(name for name, _ in prefix), rejected_tool[0], "get_state", "ask_user"]
    assert len(bridge.created) == len(bridge.started) == 1
    async with AsyncSessionLocal() as session:
        binding, agent, state = await binding_rows(session, runtime_context)
        assert binding.status is BindingStatus.WAITING_INPUT and binding.binding_epoch == 1
        assert agent.provider_session_id == bridge.native
        assert state.pending_input["request"]["question_id"] == "question-one"
        if rejected_tool[0] == "request_execution":
            call = await session.scalar(select(RunToolCall).where(
                RunToolCall.binding_id == binding.id,
                RunToolCall.idempotency_key == "premature-execution"))
            assert call.status == "FAILED" and call.result["status"] == "REJECTED"


async def test_native_turn_without_question_or_accepted_report_is_failure(runtime_context):
    bridge = runtime_context["bridge"]
    bridge.program = [("get_state", {})]
    finished = await run_claimed_job(runtime_context["job"])
    assert finished.status is JobStatus.FAILED
    assert "without an accepted report or question" in finished.error_message
    async with AsyncSessionLocal() as session:
        binding, agent, state = await binding_rows(session, runtime_context)
        assert binding.status is BindingStatus.RECOVERY_REQUIRED
        assert agent.provider_session_id == bridge.native and state.last_call_id == bridge.started[0][2]
    assert bridge.interrupted and not bridge.closed


async def test_grant_renews_during_slow_domain_tool(runtime_context, monkeypatch):
    bridge = runtime_context["bridge"]
    bridge.program = [("get_state", {}), question()]
    dispatch = HarnessTools.dispatch

    async def slow_dispatch(self, name, arguments):
        if name == "get_state":
            await asyncio.sleep(0.35)
        return await dispatch(self, name, arguments)

    monkeypatch.setattr(HarnessTools, "dispatch", slow_dispatch)
    paused = await run_claimed_job(runtime_context["job"])
    assert paused.status is JobStatus.WAITING_INPUT, paused.error_message
    assert bridge.renewed
    first = bridge.started[0][0]
    assert all(replace(ctx, expires_at=first.expires_at) == first for ctx, _ in bridge.renewed)
    assert all(call_id == bridge.started[0][2] for _, call_id in bridge.renewed)


async def test_missing_native_session_after_answer_never_creates_replacement(runtime_context):
    context, bridge = runtime_context, runtime_context["bridge"]
    paused = await run_claimed_job(context["job"])
    assert paused.status is JobStatus.WAITING_INPUT
    async with AsyncSessionLocal() as session:
        request = await session.get(RunInputRequest, UUID(paused.result["input_request_id"]))
        await answer_input_request(session, request.id, answer="Continue", expected_row_version=request.row_version,
                                   idempotency_key="restore-answer")
        job = await session.get(DurableJob, paused.id)
        await own_job(session, job)
    bridge.restore_error = "NATIVE_SESSION_LOST"
    finished = await run_claimed_job(job)
    assert finished.status is JobStatus.FAILED and finished.error_code == "BRIDGEERROR"
    assert len(bridge.created) == len(bridge.started) == 1
    async with AsyncSessionLocal() as session:
        binding, agent, _ = await binding_rows(session, context)
        assert binding.status is BindingStatus.RECOVERY_REQUIRED
        assert agent.provider_session_id == bridge.native


async def test_explicit_recovery_increments_epoch_without_replacing_original_session(runtime_context):
    context, bridge = runtime_context, runtime_context["bridge"]
    bridge.program = [("get_state", {})]
    failed = await run_claimed_job(context["job"])
    assert failed.status is JobStatus.FAILED
    async with AsyncSessionLocal() as session:
        binding, agent, _ = await binding_rows(session, context)
        original = (binding.id, agent.id, binding.workspace_id, agent.provider_session_id)
        result = await persistent.recover_binding(session, binding.id,
            expected_epoch=binding.binding_epoch, expected_row_version=binding.row_version)
        assert result["binding_epoch"] == 2 and result["status"] == "ACTIVE"
        job = await submit_job(session, context["run_id"], JobType.ADVANCE_RUN,
            payload=failed.payload, idempotency_key="explicit-recovery")
        await own_job(session, job)
    bridge.program = [question()]
    paused = await run_claimed_job(job)
    assert paused.status is JobStatus.WAITING_INPUT, paused.error_message
    async with AsyncSessionLocal() as session:
        binding, agent, _ = await binding_rows(session, context)
        assert (binding.id, agent.id, binding.workspace_id, agent.provider_session_id) == original
        assert binding.binding_epoch == 2
    assert len(bridge.created) == 1
    assert bridge.started[-1][0].binding_epoch == 2 and bridge.started[-1][3] is True
    assert bridge.recovered[0][0].claim_token == "management"


async def test_source_tamper_after_answer_stops_before_native_resume(runtime_context):
    context, bridge = runtime_context, runtime_context["bridge"]
    paused = await run_claimed_job(context["job"])
    assert paused.status is JobStatus.WAITING_INPUT
    async with AsyncSessionLocal() as session:
        request = await session.get(RunInputRequest, UUID(paused.result["input_request_id"]))
        await answer_input_request(session, request.id, answer="Continue", expected_row_version=request.row_version,
                                   idempotency_key="tamper-answer")
        job = await session.get(DurableJob, paused.id)
        await own_job(session, job)
        binding, _, _ = await binding_rows(session, context)
        workspace_path(binding.workspace_id).joinpath("src/arithmetic.py").write_text("tampered")
    stopped = await run_claimed_job(job)
    assert stopped.status is JobStatus.FAILED and "pinned source" in stopped.error_message
    assert len(bridge.started) == 1


async def test_runtime_closes_only_after_accepted_report_record(runtime_context, monkeypatch):
    """Isolate runtime completion with an injected report, not fabricated test facts."""
    bridge = runtime_context["bridge"]
    bridge.program = [("submit_report", {})]

    async def accept_test_report(self, name, arguments):
        assert name == "submit_report"
        binding, _, job, _, run, _ = await self.state()
        digest, uri = store_content(b"Runtime contract fixture only; not model acceptance.")
        self.report = RunReport(id=uuid7(), test_run_id=run.id, binding_id=binding.id,
            durable_job_id=job.id, idempotency_key="runtime-fixture-report",
            envelope={"fixture": "runtime-completion-only"}, artifact_uri=uri, content_sha256=digest)
        self.db.add(self.report)
        await self.db.commit()
        return {"status": "ACCEPTED", "report_id": str(self.report.id)}

    monkeypatch.setattr(HarnessTools, "dispatch", accept_test_report)
    finished = await run_claimed_job(runtime_context["job"])
    assert finished.status is JobStatus.SUCCEEDED, finished.error_message
    assert finished.result["reason"] == "REPORT_ACCEPTED"
    async with AsyncSessionLocal() as session:
        binding, agent, _ = await binding_rows(session, runtime_context)
        report = await session.get(RunReport, UUID(finished.result["report_id"]))
        assert report.durable_job_id == finished.id and report.binding_id == binding.id
        assert binding.status is BindingStatus.CLOSED and agent.status is AgentSessionStatus.CLOSED
    assert len(bridge.closed) == 1 and bridge.interrupted


async def test_cancel_while_tool_waits_does_not_deliver_late_result(runtime_context, monkeypatch):
    context, bridge = runtime_context, runtime_context["bridge"]
    bridge.program = [("get_state", {})]
    entered, release = asyncio.Event(), asyncio.Event()
    dispatch = HarnessTools.dispatch

    async def waiting_dispatch(self, name, arguments):
        entered.set()
        await release.wait()
        return await dispatch(self, name, arguments)

    monkeypatch.setattr(HarnessTools, "dispatch", waiting_dispatch)
    running = asyncio.create_task(run_claimed_job(context["job"]))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        async with AsyncSessionLocal() as session:
            await cancel_job(session, context["job"].id)
        release.set()
        finished = await asyncio.wait_for(running, timeout=5)
        assert finished.status is JobStatus.CANCELLED
        assert bridge.interrupted and not bridge.results and not bridge.closed
        async with AsyncSessionLocal() as session:
            binding, _, _ = await binding_rows(session, context)
            # Cancelling this Job fences its call; ending the entire Run is a
            # different operator action. This Run requires explicit recovery.
            assert binding.status is BindingStatus.RECOVERY_REQUIRED
    finally:
        release.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)


async def test_question_checkpoint_crash_recovers_as_run_input_without_reopening_failed_attempt(runtime_context, monkeypatch):
    context, bridge = runtime_context, runtime_context["bridge"]
    bridge.program = [
        ("request_mission", {"mission_type": "ANALYZE_REQUIREMENTS", "idempotency_key": "crash-analysis"}),
        question("mission", "question-before-crash"),
    ]
    respond = bridge.respond_tool

    async def lost_question_response(ctx, call_id, tool_call_id, result):
        await respond(ctx, call_id, tool_call_id, result)
        if result.get("status") == "SUSPENDING":
            raise RuntimeError("crash after durable question intent before pause transaction")

    monkeypatch.setattr(bridge, "respond_tool", lost_question_response)
    failed = await run_claimed_job(context["job"])
    assert failed.status is JobStatus.FAILED
    async with AsyncSessionLocal() as session:
        binding, agent, state = await binding_rows(session, context)
        original_identity = (binding.id, agent.id, agent.provider_session_id, binding.workspace_id)
        original_attempt = state.active_attempt_id
        assert state.pending_input["scope"] == "mission"
        assert (await session.get(MissionAttempt, original_attempt)).status is MissionAttemptStatus.FAILED
        await persistent.recover_binding(session, binding.id, expected_epoch=binding.binding_epoch,
                                         expected_row_version=binding.row_version)
        await session.refresh(state)
        assert state.active_attempt_id is state.active_mission_id is None
        assert state.pending_input["scope"] == "run" and state.pending_input["binding_epoch"] == 2
        assert "attempt_id" not in state.pending_input and "mission_id" not in state.pending_input
        recovered = await submit_job(session, context["run_id"], JobType.ADVANCE_RUN,
            payload=failed.payload, idempotency_key="resume-question-checkpoint")
        await own_job(session, recovered)
    monkeypatch.setattr(bridge, "respond_tool", respond)
    paused = await run_claimed_job(recovered)
    assert paused.status is JobStatus.WAITING_INPUT, paused.error_message
    assert len(bridge.started) == 1, "presenting saved question must not issue another native turn"
    async with AsyncSessionLocal() as session:
        binding, agent, state = await binding_rows(session, context)
        assert original_identity == (binding.id, agent.id, agent.provider_session_id, binding.workspace_id)
        request = await session.get(RunInputRequest, UUID(paused.result["input_request_id"]))
        assert request.question_id == "question-before-crash" and request.durable_job_id == recovered.id
        assert (await session.get(MissionAttempt, original_attempt)).status is MissionAttemptStatus.FAILED
        await answer_input_request(session, request.id, answer="Continue from the saved decision.",
            expected_row_version=request.row_version, idempotency_key="answer-recovered-question")
        resumed = await session.get(DurableJob, recovered.id)
        await own_job(session, resumed)
    bridge.program = [("get_state", {}), question("run", "question-after-recovery")]
    second_pause = await run_claimed_job(resumed)
    assert second_pause.status is JobStatus.WAITING_INPUT, second_pause.error_message
    assert len(bridge.created) == 1 and len(bridge.started) == 2
    assert bridge.started[-1][0].binding_epoch == 2 and bridge.started[-1][3] is True
    assert "Continue from the saved decision." in str(bridge.results)


async def test_waiting_answer_uses_remaining_frozen_harness_budget(runtime_context, monkeypatch):
    context, bridge = runtime_context, runtime_context["bridge"]
    monkeypatch.setattr(get_settings(), "harness_max_seconds", 10)
    bridge.elapsed_seconds = 2.2
    paused = await run_claimed_job(context["job"])
    assert paused.status is JobStatus.WAITING_INPUT
    assert bridge.started[0][1]["timeout_seconds"] == 10
    async with AsyncSessionLocal() as session:
        _, _, state = await binding_rows(session, context)
        assert state.harness_budget_seconds == 10
        assert await persistent.remaining_harness_budget(session, state) == 7
        ledger = await session.scalar(select(RunToolCall).where(RunToolCall.binding_id == state.binding_id,
            RunToolCall.tool_name == "__bridge_call__"))
        assert ledger.status == "SUCCEEDED" and ledger.result["elapsed_seconds"] == 3
        question_id = UUID(paused.result["input_request_id"])
        request = await session.get(RunInputRequest, question_id)
        await answer_input_request(session, request.id, answer="Continue", expected_row_version=request.row_version,
                                   idempotency_key="budget-answer")
        resumed = await session.get(DurableJob, paused.id)
        await own_job(session, resumed)
    monkeypatch.setattr(get_settings(), "harness_max_seconds", 7200)
    bridge.elapsed_seconds = 1.1
    bridge.program = [question("run", "budget-question-two")]
    again = await run_claimed_job(resumed)
    assert again.status is JobStatus.WAITING_INPUT, again.error_message
    assert bridge.started[-1][1]["timeout_seconds"] == 7
    async with AsyncSessionLocal() as session:
        _, _, state = await binding_rows(session, context)
        assert state.harness_budget_seconds == 10
        assert await persistent.remaining_harness_budget(session, state) == 5


async def test_unknown_call_reserves_budget_until_confirmed_explicit_recovery(runtime_context, monkeypatch):
    context, bridge = runtime_context, runtime_context["bridge"]
    monkeypatch.setattr(get_settings(), "harness_max_seconds", 10)
    bridge.elapsed_seconds = 3.4
    bridge.program = [("get_state", {})]
    interrupt = bridge.interrupt

    async def unknown_stop(ctx, call_id):
        return {"stopped": False}

    monkeypatch.setattr(bridge, "interrupt", unknown_stop)
    failed = await run_claimed_job(context["job"])
    assert failed.status is JobStatus.FAILED
    async with AsyncSessionLocal() as session:
        binding, _, state = await binding_rows(session, context)
        assert await persistent.remaining_harness_budget(session, state) == 0
        ledger = await session.scalar(select(RunToolCall).where(RunToolCall.binding_id == binding.id,
            RunToolCall.tool_name == "__bridge_call__"))
        assert ledger.status == "STARTED" and ledger.result["reserved_seconds"] == 10
        with pytest.raises(persistent.ConflictError, match="cannot be confirmed stopped"):
            await persistent.recover_binding(session, binding.id, expected_epoch=binding.binding_epoch,
                                             expected_row_version=binding.row_version)
        assert await persistent.remaining_harness_budget(session, state) == 0
        await session.rollback()
    monkeypatch.setattr(bridge, "interrupt", interrupt)
    monkeypatch.setattr(get_settings(), "harness_max_seconds", 7200)
    async with AsyncSessionLocal() as session:
        binding, _, state = await binding_rows(session, context)
        await persistent.recover_binding(session, binding.id, expected_epoch=binding.binding_epoch,
                                         expected_row_version=binding.row_version)
        assert await persistent.remaining_harness_budget(session, state) == 6
        # A new Job is permitted to ask for a different budget, but this binding's
        # immutable first configuration continues to govern it.
        changed_payload = {**failed.payload, "max_steps": 32, "timeout_seconds": 3600}
        resumed = await submit_job(session, context["run_id"], JobType.ADVANCE_RUN,
            payload=changed_payload, idempotency_key="new-budget-does-not-reset-binding")
        await own_job(session, resumed)
    bridge.program = [question("run", "recovery-budget-question")]
    bridge.elapsed_seconds = 0.1
    paused = await run_claimed_job(resumed)
    assert paused.status is JobStatus.WAITING_INPUT, paused.error_message
    assert bridge.started[-1][1]["timeout_seconds"] == 6
    async with AsyncSessionLocal() as session:
        _, _, state = await binding_rows(session, context)
        assert (state.harness_budget_seconds, state.max_steps, state.timeout_seconds) == (10, 12, 300)
        assert await persistent.remaining_harness_budget(session, state) == 5


async def test_exhausted_harness_budget_prevents_new_native_call_after_answer(runtime_context, monkeypatch):
    context, bridge = runtime_context, runtime_context["bridge"]
    monkeypatch.setattr(get_settings(), "harness_max_seconds", 3)
    bridge.elapsed_seconds = 3.2
    paused = await run_claimed_job(context["job"])
    assert paused.status is JobStatus.WAITING_INPUT
    async with AsyncSessionLocal() as session:
        _, _, state = await binding_rows(session, context)
        assert await persistent.remaining_harness_budget(session, state) == 0
        request = await session.get(RunInputRequest, UUID(paused.result["input_request_id"]))
        await answer_input_request(session, request.id, answer="Continue", expected_row_version=request.row_version,
                                   idempotency_key="exhausted-answer")
        resumed = await session.get(DurableJob, paused.id)
        await own_job(session, resumed)
    monkeypatch.setattr(get_settings(), "harness_max_seconds", 7200)
    failed = await run_claimed_job(resumed)
    assert failed.status is JobStatus.FAILED and "active-time budget is exhausted" in failed.error_message
    assert len(bridge.started) == 1 and len(bridge.created) == 1
