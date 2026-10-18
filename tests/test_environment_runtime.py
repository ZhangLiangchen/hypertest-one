"""Binding/Runner integration contracts; doubles are not live-model acceptance."""

from copy import deepcopy

import pytest
from sqlalchemy import func, select
from test_delivery_loop import configure_workspace, prepare_delivery
from test_environment_binding import binding
from test_test_design import ProposalHarness, requirement_proposal

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import ProjectCreate
from hypertest.application import bootstrap, controller
from hypertest.application.executions import execute_test_run, read_evidence_content
from hypertest.application.gate import evaluate_gate
from hypertest.application.jobs import cancel_job, submit_job
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import MissionRuntimeError, execute_mission
from hypertest.application.services import ConflictError, create_project
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    CaseResult,
    EvidenceType,
    ExecutionOutcome,
    ExecutionStatus,
    VerdictDecision,
)
from hypertest.domain.enums import (
    TestRunStatus as RunStatus,
)
from hypertest.domain.environments import EnvironmentRequest
from hypertest.domain.jobs import JobStatus, JobType
from hypertest.domain.models import (
    AgentSessionRecord,
    Evidence,
    ExecutionEvidence,
    ExecutionTestCase,
    MissionAttempt,
)
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.runner import environments
from hypertest.runner.backends import DockerRunner, ProcessResult


async def controlled_run(session, tmp_path, monkeypatch, app="checkout:app"):
    source, commit, origin = configure_workspace(tmp_path, monkeypatch)
    request = EnvironmentRequest(profile_id="python-api-v1", service={"app": app})
    frozen = binding(request)

    async def resolve(_request):
        return deepcopy(frozen)

    monkeypatch.setattr(bootstrap, "resolve_environment", resolve)
    project = await create_project(session, ProjectCreate(key=public_key("ENV_RUNTIME"), name="Environment runtime"))
    run = await bootstrap.bootstrap_run(session, project.id, RunBootstrap(
        repository_url=origin, commit_sha=commit, prd_text="The checkout API must preserve idempotency.",
        environment=request,
    ))
    return source, run, frozen


@pytest.mark.asyncio
async def test_bound_image_preflight_releases_run_lock_and_stops_before_agent(tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        source, run, frozen = await controlled_run(session, tmp_path, monkeypatch)

        async def unavailable(runner):
            assert runner.environment == frozen
            async with AsyncSessionLocal() as competitor:
                assert await competitor.scalar(select(CanonicalRun.id).where(
                    CanonicalRun.id == run.id,
                ).with_for_update(nowait=True)) == run.id
            raise RuntimeError("frozen image absent")

        async def forbidden(*_args, **_kwargs):
            pytest.fail("environment failure must precede Git, Planner and Agent")

        monkeypatch.setattr(DockerRunner, "fingerprint", unavailable)
        for name in ("prepare_managed_workspace", "plan_next_mission", "execute_mission"):
            monkeypatch.setattr(controller, name, forbidden)
        with pytest.raises(ConflictError, match="preflight"):
            await controller.advance_run(session, run.id, workspace=str(source))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["image", "untracked-app"])
async def test_single_mission_validates_bound_environment_before_agent_session(tmp_path, monkeypatch, failure):
    async with AsyncSessionLocal() as session:
        source, run, _ = await controlled_run(session, tmp_path, monkeypatch, app="missing:app")
        plan = await plan_next_mission(session, run.id)

        async def inspect(_binding):
            if failure == "image":
                raise RuntimeError("image unavailable")
            return {}

        monkeypatch.setattr(environments, "validate_environment_binding", inspect)
        with pytest.raises(MissionRuntimeError, match="controlled"):
            await execute_mission(session, plan.mission.id, str(source))
        assert await session.scalar(select(func.count()).select_from(AgentSessionRecord).where(
            AgentSessionRecord.test_run_id == run.id,
        )) == 0
        assert await session.scalar(select(func.count()).select_from(MissionAttempt).where(
            MissionAttempt.mission_id == plan.mission.id,
        )) == 0


@pytest.mark.asyncio
async def test_service_failure_cannot_become_pass_even_with_complete_passing_junit(tmp_path, monkeypatch):
    import test_delivery_loop

    source, commit, origin = configure_workspace(tmp_path, monkeypatch)
    request = EnvironmentRequest(profile_id="python-api-v1", service={"app": "checkout:app"})
    frozen = binding(request)
    original_bootstrap = bootstrap.bootstrap_run

    async def resolve(_request):
        return deepcopy(frozen)

    async def bound_bootstrap(session, project_id, payload):
        return await original_bootstrap(session, project_id, payload.model_copy(update={"environment": request}))

    async def inspect(_binding):
        return {}

    async def fingerprint(_runner):
        return {"backend": "docker", "image_id": frozen["image_id"], "environment_definition": frozen}

    async def failed_service(_runner, staged, output, nodeids, timeout, identity):
        # This is a collector contract double, deliberately contradictory.
        (output / "junit.xml").write_text(
            '<testsuites><testsuite tests="1"><testcase classname="tests.test_checkout_generated" '
            'name="test_checkout_idempotency" time="0.1" /></testsuite></testsuites>'
        )
        return ProcessResult(b"pytest exit0", b"", 0, service_metadata={"service_early_exit": True},
                             service_log=b"service unexpectedly exited", error_code="SERVICE_EARLY_EXIT")

    monkeypatch.setattr(bootstrap, "resolve_environment", resolve)
    monkeypatch.setattr(test_delivery_loop, "bootstrap_run", bound_bootstrap)
    monkeypatch.setattr(environments, "validate_environment_binding", inspect)
    monkeypatch.setattr(DockerRunner, "fingerprint", fingerprint)
    monkeypatch.setattr(DockerRunner, "execute", failed_service)
    async with AsyncSessionLocal() as session:
        state = await prepare_delivery(session, source, commit, origin)
        result = await execute_test_run(session, state.run.id, str(source), idempotency_key="service-error")
        assert result.status is ExecutionStatus.ERROR
        assert result.outcome is ExecutionOutcome.INCONCLUSIVE
        assert result.error_code == "SERVICE_EARLY_EXIT"
        facts = list(await session.scalars(select(ExecutionTestCase).where(ExecutionTestCase.execution_id == result.id)))
        assert facts and all(item.result is not CaseResult.PASS for item in facts)
        evidence = list(await session.scalars(select(Evidence).join(ExecutionEvidence).where(
            ExecutionEvidence.execution_id == result.id,
        )))
        logs = [item for item in evidence if item.evidence_type is EvidenceType.LOG]
        assert len(logs) == 1 and read_evidence_content(logs[0]) == b"service unexpectedly exited"
        verdict = await evaluate_gate(session, state.run.id)
        assert verdict.decision is VerdictDecision.BLOCKED


@pytest.mark.asyncio
async def test_hydrated_environment_is_authoritative_and_docker_required(tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        source, run, frozen = await controlled_run(session, tmp_path, monkeypatch)
        with pytest.raises(ConflictError, match="Docker"):
            await controller.advance_run(session, run.id, workspace=str(source), backend="local")

        async def inspect(_binding):
            return {}

        monkeypatch.setattr(environments, "validate_environment_binding", inspect)
        plan = await plan_next_mission(session, run.id)
        harness = ProposalHarness([requirement_proposal()])
        await execute_mission(session, plan.mission.id, str(source), harness=harness)
        context = harness.contract["context"]["execution_environment"]
        assert context["request"] == frozen["request"]
        assert context["image_id"] == frozen["image_id"]
        assert context["base_url_environment_variable"] == "HYPERTEST_BASE_URL"
        assert context["service_base_url"] == "http://127.0.0.1:8765"
        assert "TestClient" in context["service_testing_instructions"]


@pytest.mark.asyncio
async def test_direct_mission_cannot_bypass_job_queued_during_image_inspection(tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        source, run, _ = await controlled_run(session, tmp_path, monkeypatch)
        plan = await plan_next_mission(session, run.id)
        queued_id = None

        async def inspect(_binding):
            nonlocal queued_id
            async with AsyncSessionLocal() as competitor:
                job = await submit_job(competitor, run.id, JobType.ADVANCE_RUN,
                                       payload={"workspace": str(source)}, idempotency_key="racing-queue")
                assert job.status is JobStatus.QUEUED
                queued_id = job.id
            return {}

        monkeypatch.setattr(environments, "validate_environment_binding", inspect)
        harness = ProposalHarness([requirement_proposal()])
        try:
            with pytest.raises(MissionRuntimeError, match="active background work"):
                await execute_mission(session, plan.mission.id, str(source), harness=harness)
            assert harness.contract is None
            assert await session.scalar(select(func.count()).select_from(MissionAttempt).where(
                MissionAttempt.mission_id == plan.mission.id,
            )) == 0
        finally:
            await session.rollback()
            if queued_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cancel_job(cleanup, queued_id)


@pytest.mark.asyncio
async def test_execution_observes_cancellation_committed_during_image_inspection(tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        source, run, frozen = await controlled_run(session, tmp_path, monkeypatch)

        async def inspect(_runner):
            async with AsyncSessionLocal() as competitor:
                changed = await competitor.get(CanonicalRun, run.id, with_for_update=True)
                changed.status = RunStatus.CANCELLED
                await competitor.commit()
            return {"image_id": frozen["image_id"], "environment_definition": frozen}

        async def forbidden(*_args, **_kwargs):
            pytest.fail("cancelled run must not start a Runner")

        monkeypatch.setattr(DockerRunner, "fingerprint", inspect)
        monkeypatch.setattr(DockerRunner, "execute", forbidden)
        with pytest.raises(ConflictError, match="cancelled"):
            await execute_test_run(session, run.id, str(source), idempotency_key="cancel-window")
        assert await session.scalar(select(func.count()).select_from(CanonicalExecution).where(
            CanonicalExecution.test_run_id == run.id,
        )) == 0
        await session.refresh(run)
        assert run.status is RunStatus.CANCELLED
