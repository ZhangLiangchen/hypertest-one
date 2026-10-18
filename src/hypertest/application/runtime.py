from __future__ import annotations

import asyncio
import hashlib
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hypertest.agent.base import AgentHarness, AgentSession
from hypertest.agent.codex import CodexCliAdapter
from hypertest.agent.snapshot import SnapshotHarness
from hypertest.application.activity import ActivityOwner, ActivityRecorder
from hypertest.application.lifecycle import record_mission_event
from hypertest.application.verifier import VerificationResult, verify_mission_result
from hypertest.common.ids import uuid7
from hypertest.common.repositories import validate_repository_origin
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    AgentSessionStatus,
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    TestRunStatus,
)
from hypertest.domain.models import (
    AgentSessionRecord,
    Finding,
    Mission,
    MissionAttempt,
    MissionProposal,
    Requirement,
    Risk,
    SourceSnapshot,
    TestCase,
    TestImplementation,
    TestRun,
    utcnow,
)
from hypertest.protocol import (
    MissionResultSubmission,
    RequirementProposalPayload,
    RiskProposalPayload,
    TestCaseProposalPayload,
    TestImplementationProposalPayload,
)


def _safe_agent_error(payload: dict[str, Any]) -> tuple[str, str]:
    messages = {
        "PROVIDER_ERROR": "Agent provider process exited unsuccessfully",
        "PROVIDER_RESUME_FAILED": "Agent provider could not resume the recorded session",
        "PROVIDER_SESSION_INVALID": "Agent provider supplied an invalid session reference",
        "PROVIDER_SESSION_CHANGED": "Agent provider changed its recorded session identity",
        "RESULT_MISSING": "Agent did not produce a structured result",
        "RESULT_INVALID": "Agent structured result is invalid",
        "MULTIPLE_RESULTS": "Agent submitted more than one final result",
        "MISSION_TIMEOUT": "mission exceeded its time limit",
        "SOURCE_CHANGED": "Agent workspace changed the immutable source",
        "HARNESS_ERROR": "Agent harness failed before completing a structured result",
    }
    code = payload.get("error_code")
    if not isinstance(code, str) or code not in messages:
        return "AGENT_ERROR", "Agent execution failed before structured verification"
    message = messages[code]
    value = payload.get("return_code")
    if type(value) is int and -32768 <= value <= 32767:
        message += f" (exit code {value})"
    return code, message


class MissionRuntimeError(RuntimeError):
    pass


_APPLICATION_SCOPE_GUIDANCE = {
    MissionType.ANALYZE_REQUIREMENTS.value: (
        "Extract independently verifiable behavior and intrinsic quality constraints of the application. "
        "Do not promote instructions for generating or running its tests into product requirements."
    ),
    MissionType.ANALYZE_RISKS.value: (
        "Identify application failure modes traced to the target requirements. Use testing restrictions "
        "to choose feasible probes, not to invent risks about the orchestration platform's compliance."
    ),
    MissionType.DESIGN_TESTS.value: (
        "Design executable checks of the requested application behavior. Apply test-generation and "
        "execution restrictions as implementation constraints or preconditions, rather than separate "
        "cases that require unrequested HyperTest or Runner internals."
    ),
    MissionType.IMPLEMENT_TESTS.value: (
        "Implement the target application cases while obeying all test-generation restrictions. Do not "
        "invent platform interfaces, dummy passing tests or execution facts. If existing canonical "
        "targets genuinely require an unavailable, out-of-scope component, report that conflict "
        "honestly instead of rewriting targets or claiming completion."
    ),
}


@dataclass(slots=True)
class MissionExecutionResult:
    mission: Mission
    attempt: MissionAttempt
    proposals: list[MissionProposal]
    requirements: list[Requirement]
    risks: list[Risk]
    test_cases: list[TestCase]
    implementations: list[TestImplementation] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    waiting_input: dict[str, Any] | None = None


def _output_schema_for(mission_type: MissionType) -> str:
    if mission_type is MissionType.ANALYZE_REQUIREMENTS:
        return "hypertest.result/requirement-analysis/v1"
    if mission_type is MissionType.ANALYZE_RISKS:
        return "hypertest.result/risk-analysis/v1"
    if mission_type is MissionType.DESIGN_TESTS:
        return "hypertest.result/test-design/v1"
    if mission_type is MissionType.IMPLEMENT_TESTS:
        return "hypertest.result/test-implementation/v1"
    if mission_type is MissionType.DIAGNOSE_FAILURE:
        return "hypertest.result/failure-diagnosis/v1"
    raise MissionRuntimeError(f"unsupported mission type: {mission_type.value}")


def build_mission_contract(mission: Mission, test_run: TestRun) -> dict[str, Any]:
    contract = dict(mission.spec)
    contract.update(
        {
            "protocol": f"hypertest.tmp/{mission.protocol_version}",
            "mission_id": mission.key,
            "test_run_id": test_run.key,
            "type": mission.mission_type.value,
            "objective": mission.objective,
            "priority": mission.priority.value,
        }
    )
    contract.setdefault(
        "output_contract",
        {
            "schema": _output_schema_for(mission.mission_type),
            "human_summary": True,
        },
    )
    payload_model = None
    proposal_type = None
    if mission.mission_type is MissionType.ANALYZE_REQUIREMENTS:
        payload_model, proposal_type = RequirementProposalPayload, "REQUIREMENT"
    elif mission.mission_type is MissionType.ANALYZE_RISKS:
        payload_model, proposal_type = RiskProposalPayload, "RISK"
    elif mission.mission_type is MissionType.DESIGN_TESTS:
        payload_model, proposal_type = TestCaseProposalPayload, "TEST_CASE"
    elif mission.mission_type is MissionType.IMPLEMENT_TESTS:
        payload_model, proposal_type = TestImplementationProposalPayload, "TEST_IMPLEMENTATION"
    elif mission.mission_type is MissionType.DIAGNOSE_FAILURE:
        from hypertest.application.findings import FindingProposalPayload

        payload_model, proposal_type = FindingProposalPayload, "FINDING"
    if payload_model is not None:
        output_contract = dict(contract["output_contract"])
        output_contract.setdefault("proposal_type", proposal_type)
        output_contract.setdefault("operation", "CREATE")
        output_contract.setdefault("object_payload_schema", payload_model.model_json_schema())
        output_contract.setdefault("result_schema", MissionResultSubmission.model_json_schema())
        contract["output_contract"] = output_contract
    return contract


async def _hydrate_source_context(
    session: AsyncSession,
    test_run: TestRun,
    contract: dict[str, Any],
) -> None:
    snapshot = await session.get(SourceSnapshot, test_run.source_snapshot_id)
    if snapshot is None:
        raise MissionRuntimeError("source snapshot not found")
    try:
        validate_repository_origin(snapshot.repository_url)
    except ValueError as exc:
        raise MissionRuntimeError(str(exc)) from None
    context = dict(contract.get("context", {}))
    context.update(repository_url=snapshot.repository_url, commit_sha=snapshot.commit_sha)
    scope_guidance = _APPLICATION_SCOPE_GUIDANCE.get(contract["type"])
    if scope_guidance is not None:
        context["testing_scope"] = {
            "repository_url": snapshot.repository_url,
            "commit_sha": snapshot.commit_sha,
            "subject_boundary": (
                "The system under test is the pinned repository application, limited to the product "
                "features explicitly requested in the original PRD. HyperTest, the Agent harness and "
                "the trusted Runner are testing infrastructure, not additional test subjects merely "
                "because their operation is mentioned."
            ),
            "constraint_handling": (
                "Distinguish the application's expected behavior and own quality constraints from "
                "directions about test dependencies, loading, file placement, source immutability "
                "or official execution. Those directions remain mandatory test implementation or "
                "execution constraints; do not turn them into extra application Requirements, Risks "
                "or TestCases. If the pinned application itself implements a testing or Runner "
                "feature and that feature is explicitly requested, it remains a valid test subject."
            ),
            "stage_guidance": scope_guidance,
        }
    root = Path(get_settings().artifact_root).resolve()
    if snapshot.prd_artifact_uri:
        artifact = Path(snapshot.prd_artifact_uri).resolve()
        expected = (root / "inputs" / f"{snapshot.prd_sha256}.txt").resolve()
        if not artifact.is_relative_to(root) or artifact != expected:
            raise MissionRuntimeError("PRD artifact is outside the configured input artifact store")
        try:
            content = artifact.read_bytes()
            if hashlib.sha256(content).hexdigest() != snapshot.prd_sha256:
                raise MissionRuntimeError(
                    "PRD artifact checksum does not match the source snapshot"
                )
            context["prd_text"] = content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise MissionRuntimeError("PRD artifact cannot be read as UTF-8 text") from exc
    configuration = root / "inputs" / f"{snapshot.configuration_sha256}.txt"
    # A PRD artifact URI identifies materialized inputs (including Web bootstrap,
    # which saves both artifacts). Missing configuration must not silently change
    # that fixed input. Legacy direct snapshots can contain only hashes and no
    # materialized PRD/configuration; their existing optional context is retained.
    if snapshot.prd_artifact_uri or configuration.exists():
        if not configuration.resolve().is_relative_to(root):
            raise MissionRuntimeError(
                "configuration artifact is outside the configured input store"
            )
        try:
            content = configuration.read_bytes()
            if hashlib.sha256(content).hexdigest() != snapshot.configuration_sha256:
                raise MissionRuntimeError(
                    "configuration artifact checksum does not match the snapshot"
                )
            context["configuration_text"] = content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise MissionRuntimeError(
                "configuration artifact cannot be read as UTF-8 text"
            ) from exc
    contract["context"] = context


async def _hydrate_answer_context(
    session: AsyncSession, test_run: TestRun, contract: dict[str, Any],
) -> None:
    from hypertest.domain.inputs import InputRequestStatus, MissionInputRequest

    answered = list(await session.scalars(select(MissionInputRequest).where(
        MissionInputRequest.test_run_id == test_run.id,
        MissionInputRequest.status.in_([InputRequestStatus.ANSWERED, InputRequestStatus.CONSUMED]),
    ).order_by(MissionInputRequest.created_at, MissionInputRequest.id)))
    context = dict(contract.get("context", {}))
    # Always replace this runtime projection; frozen input cannot inject an
    # invented operator answer or overwrite PRD/configuration/source identity.
    context["human_inputs"] = [
        {"request_id": str(item.id), "question_id": item.question_id,
         "question": item.question, "answer": item.answer}
        for item in answered
    ]
    contract["context"] = context


async def _fail_attempt(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    agent_session: AgentSessionRecord,
    error_code: str,
    error_message: str,
    provider_metadata: dict[str, Any],
    *,
    result_payload: dict[str, Any] | None = None,
) -> None:
    test_run = await session.get(TestRun, mission.test_run_id)
    if test_run is not None:
        await session.refresh(test_run, with_for_update=True)
    await session.refresh(mission, with_for_update=True)
    before_status = mission.status
    cancelled = mission.status is MissionStatus.CANCELLED or (
        test_run is not None and test_run.status is TestRunStatus.CANCELLED
    )
    now = utcnow()
    rejected = error_code == "RESULT_SCHEMA_ERROR"
    attempt.status = (
        MissionAttemptStatus.CANCELLED if cancelled else
        MissionAttemptStatus.REJECTED if rejected else MissionAttemptStatus.FAILED
    )
    attempt.finished_at = now
    attempt.error_code = error_code
    attempt.error_message = error_message
    attempt.provider_metadata = {**(attempt.provider_metadata or {}), **provider_metadata}
    if result_payload is not None:
        attempt.result_payload = result_payload
    if rejected:
        attempt.submitted_at = attempt.submitted_at or now
    if not cancelled:
        mission.status = MissionStatus.RETRYING
        mission.row_version += 1
    elif mission.status is not MissionStatus.CANCELLED:
        mission.status = MissionStatus.CANCELLED
        mission.cancelled_at = now
        mission.row_version += 1
    agent_session.status = (
        AgentSessionStatus.CLOSED if cancelled or rejected else AgentSessionStatus.FAILED
    )
    agent_session.last_active_at = now
    agent_session.closed_at = now
    if cancelled:
        action, reason = "mission.cancelled", "mission execution cancelled by the control plane"
    elif rejected:
        action, reason = "mission.result_rejected", "agent result envelope failed schema validation"
    elif error_code == "MISSION_TIMEOUT":
        action, reason = "mission.timed_out", "mission exceeded its execution time limit"
    elif error_code == "EXECUTION_INTERRUPTED":
        action, reason = "mission.interrupted", "request or worker task interrupted before acceptance"
    else:
        action, reason = "mission.attempt_failed", "agent attempt failed before canonical acceptance"
    try:
        await record_mission_event(
            session, mission, action, attempt=attempt,
            metadata={"reason": reason, "error_code": error_code}, before_status=before_status,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def _select_harness(provider: str) -> AgentHarness:
    if provider == "codex":
        settings = get_settings()
        extra_args = ("--ignore-user-config",) if settings.codex_ignore_user_config else ()
        if settings.codex_model:
            extra_args += ("--model", settings.codex_model)
        return CodexCliAdapter(binary=settings.codex_binary, extra_args=extra_args)
    raise MissionRuntimeError(f"unsupported agent provider: {provider}")


async def _execute_mission(
    session: AsyncSession,
    mission_id: UUID,
    workspace: str,
    provider: str = "codex",
    harness: AgentHarness | None = None,
    *,
    attempt_context: dict[str, UUID],
) -> MissionExecutionResult:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise MissionRuntimeError("mission not found")
    test_run = await session.get(TestRun, mission.test_run_id)
    if test_run is None:
        raise MissionRuntimeError("test run not found")
    if mission.mission_type not in {
        MissionType.ANALYZE_REQUIREMENTS,
        MissionType.ANALYZE_RISKS,
        MissionType.DESIGN_TESTS,
        MissionType.IMPLEMENT_TESTS,
        MissionType.DIAGNOSE_FAILURE,
    }:
        raise MissionRuntimeError(f"runtime does not support {mission.mission_type.value}")
    allowed_root = Path(get_settings().workspace_root).resolve()
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_relative_to(allowed_root) or not workspace_path.is_dir():
        raise MissionRuntimeError(
            "mission workspace must be a directory under the configured workspace root"
        )
    workspace = str(workspace_path)
    contract = build_mission_contract(mission, test_run)
    await _hydrate_source_context(session, test_run, contract)
    await _hydrate_answer_context(session, test_run, contract)
    if harness is None:
        from hypertest.runner.source import validate_checkout

        source = await session.get(SourceSnapshot, test_run.source_snapshot_id)
        assert source is not None
        tracked_files = await validate_checkout(
            workspace_path, source.commit_sha, source.repository_url
        )
    try:
        duration = float(mission.spec.get("constraints", {}).get("max_duration_seconds", 1800))
    except (TypeError, ValueError) as exc:
        raise MissionRuntimeError("max_duration_seconds must be a positive duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise MissionRuntimeError("max_duration_seconds must be a positive duration")
    duration = min(duration, 3600)

    selected_harness = harness or _select_harness(provider)
    if harness is None:
        selected_harness = SnapshotHarness(selected_harness, workspace_path, tracked_files)
    # Reserve one attempt under the same lock order as cancellation. A competing
    # request observes RUNNING before it can create another external agent session.
    await session.refresh(test_run, with_for_update=True)
    await session.refresh(mission, with_for_update=True)
    is_resume = mission.status is MissionStatus.WAITING_INPUT
    if mission.status not in {
        MissionStatus.CREATED, MissionStatus.READY, MissionStatus.RETRYING, MissionStatus.WAITING_INPUT,
    }:
        message = f"mission cannot execute from status {mission.status.value}"
        await session.rollback()
        raise MissionRuntimeError(message)
    if test_run.status is TestRunStatus.CANCELLED:
        await session.rollback()
        raise MissionRuntimeError("cancelled test runs cannot execute missions")
    from hypertest.runner.backends import runner_job_id

    job_reference = getattr(session, "job_id", None) or runner_job_id.get()
    durable_job_id = UUID(str(job_reference)) if job_reference is not None else None
    now = utcnow()
    if is_resume:
        from hypertest.domain.inputs import InputRequestStatus, MissionInputRequest

        if durable_job_id is None:
            raise MissionRuntimeError("human input resume requires its original durable job")
        question = await session.scalar(select(MissionInputRequest).where(
            MissionInputRequest.test_run_id == test_run.id,
            MissionInputRequest.mission_id == mission.id,
            MissionInputRequest.durable_job_id == durable_job_id,
            MissionInputRequest.status == InputRequestStatus.ANSWERED,
        ).order_by(MissionInputRequest.created_at.desc(), MissionInputRequest.id.desc())
            .with_for_update().limit(1))
        if question is None:
            raise MissionRuntimeError("waiting mission has no answered input for this durable job")
        attempt = await session.get(MissionAttempt, question.attempt_id)
        agent_record = await session.get(AgentSessionRecord, question.agent_session_id)
        if (attempt is None or agent_record is None or attempt.mission_id != mission.id
                or attempt.attempt_no != mission.current_attempt_no
                or attempt.durable_job_id != durable_job_id
                or attempt.agent_session_id != agent_record.id
                or agent_record.test_run_id != test_run.id
                or agent_record.status is not AgentSessionStatus.WAITING_INPUT
                or attempt.status is not MissionAttemptStatus.RUNNING):
            raise MissionRuntimeError("answered input does not own the current waiting attempt/session")
        gateway_id = (attempt.provider_metadata or {}).get("gateway_session_id")
        if not isinstance(gateway_id, str) or not gateway_id or not agent_record.provider_session_id:
            raise MissionRuntimeError("persisted provider session identity is unavailable for resume")
        if agent_record.provider != provider:
            raise MissionRuntimeError("resume must use the original agent provider")
        external_session = AgentSession(
            id=gateway_id, provider=agent_record.provider,
            provider_session_id=agent_record.provider_session_id,
        )
        attempt_context.update(attempt_id=attempt.id, agent_session_id=agent_record.id)
        try:
            await selected_harness.restore_session(external_session, agent_record.workspace_id)
        except Exception as exc:
            raise MissionRuntimeError("agent session could not be restored") from exc
        question.status = InputRequestStatus.CONSUMED
        question.consumed_at = now
        question.row_version += 1
        mission.status = MissionStatus.RUNNING
        mission.row_version += 1
        agent_record.status = AgentSessionStatus.RUNNING
        agent_record.last_active_at = now
        await record_mission_event(
            session, mission, "mission.resumed", attempt=attempt,
            before_status=MissionStatus.WAITING_INPUT,
            metadata={"request_id": str(question.id), "reason": "operator answer consumed",
                      "event_key": f"{mission.id}:mission.resumed:{question.id}"},
        )
        from hypertest.application.inputs import _input_event

        await _input_event(session, question, "input.consumed")
        try:
            await session.commit()
        except BaseException:
            await session.rollback()
            await selected_harness.close(external_session)
            raise
    else:
        try:
            external_session = await selected_harness.create_session(workspace)
        except Exception as exc:
            await session.rollback()
            from hypertest.application.jobs import JobLeaseLost

            if isinstance(exc, JobLeaseLost):
                raise
            raise MissionRuntimeError("agent session could not be created") from exc
        agent_record = AgentSessionRecord(
            id=uuid7(), test_run_id=test_run.id, provider=external_session.provider,
            harness=type(selected_harness).__name__,
            provider_session_id=external_session.provider_session_id,
            workspace_id=(selected_harness.workspace_for(external_session)
                          if isinstance(selected_harness, SnapshotHarness) else workspace),
            status=AgentSessionStatus.RUNNING, last_active_at=now,
        )
        attempt = MissionAttempt(
            id=uuid7(), mission_id=mission.id, durable_job_id=durable_job_id,
            attempt_no=mission.current_attempt_no + 1, agent_session=agent_record,
            provider=external_session.provider, harness=type(selected_harness).__name__,
            status=MissionAttemptStatus.CREATED,
            provider_metadata={"gateway_session_id": external_session.id},
        )
        session.add_all([agent_record, attempt])
        attempt_context.update(attempt_id=attempt.id, agent_session_id=agent_record.id)
        before_status = mission.status
        mission.current_attempt_no = attempt.attempt_no
        mission.status = MissionStatus.DISPATCHED
        mission.dispatched_at = mission.dispatched_at or now
        mission.row_version += 1
        next_run_status = {
            MissionType.DESIGN_TESTS: TestRunStatus.DESIGNING,
            MissionType.IMPLEMENT_TESTS: TestRunStatus.IMPLEMENTING,
            MissionType.DIAGNOSE_FAILURE: TestRunStatus.DIAGNOSING,
        }.get(mission.mission_type, TestRunStatus.ANALYZING)
        if test_run.status not in {TestRunStatus.COMPLETED, TestRunStatus.CANCELLED}:
            test_run.status = next_run_status
            test_run.started_at = test_run.started_at or now
            test_run.row_version += 1
        try:
            await record_mission_event(
                session, mission, "mission.dispatched", attempt=attempt,
                metadata={"reason": "mission dispatched to a replaceable agent worker"},
                before_status=before_status,
            )
            mission.status = MissionStatus.RUNNING
            mission.row_version += 1
            attempt.status = MissionAttemptStatus.RUNNING
            attempt.started_at = now
            await record_mission_event(
                session, mission, "mission.started", attempt=attempt,
                metadata={"reason": "agent attempt started"}, before_status=MissionStatus.DISPATCHED,
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            try:
                await asyncio.wait_for(selected_harness.close(external_session), 5)
            except Exception:
                pass
            raise

    result_payload: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    event_types = deque((attempt.provider_metadata or {}).get("event_types", [])[-256:], maxlen=256)
    known_events = {"SESSION_STARTED", "MISSION_STARTED", "ACTIVITY", "TOOL_STARTED", "TOOL_COMPLETED",
                    "FILE_CHANGED", "EXECUTION_REQUESTED", "WAITING_INPUT", "PROGRESS", "WARNING",
                    "ERROR", "RESULT_SUBMITTED", "MISSION_FINISHED"}
    activity = None
    owned_token = getattr(session, "lease_token", None)
    if durable_job_id is not None and isinstance(owned_token, UUID):
        activity = ActivityRecorder(async_sessionmaker(session.bind, expire_on_commit=False), ActivityOwner(
            test_run.id, durable_job_id, mission.id, attempt.id, agent_record.id, owned_token,
        ))
        activity.start(resumed=is_resume)

    async def consume_events() -> None:
        nonlocal result_payload, error_payload
        stream = (selected_harness.resume(external_session, contract) if is_resume
                  else selected_harness.execute(external_session, contract))
        async for event in stream:
            event_types.append(event.type if isinstance(event.type, str) and event.type in known_events else "UNKNOWN_EVENT")
            if activity is not None:
                activity.observe(event.type, event.payload if isinstance(event.payload, dict) else {})
            if event.type == "RESULT_SUBMITTED":
                if result_payload is not None:
                    error_payload = {
                        "error_code": "MULTIPLE_RESULTS",
                        "message": "agent submitted more than one final result",
                    }
                else:
                    result_payload = event.payload
            elif event.type == "SESSION_STARTED":
                reference = event.payload.get("provider_session_id")
                if isinstance(reference, str) and reference:
                    if (external_session.provider_session_id
                            and external_session.provider_session_id != reference):
                        error_payload = {"error_code": "PROVIDER_SESSION_CHANGED",
                                         "message": "provider changed the persisted session identity"}
                    else:
                        external_session.provider_session_id = reference
            elif event.type == "ERROR":
                error_payload = event.payload

    execution_task = asyncio.create_task(consume_events())
    cancellation_observed = asyncio.Event()

    async def watch_cancellation() -> None:
        while True:
            await asyncio.sleep(0.5)
            try:
                async with AsyncSessionLocal() as observer:
                    statuses = (
                        await observer.execute(
                            select(Mission.status, TestRun.status)
                            .join(TestRun, TestRun.id == Mission.test_run_id)
                            .where(Mission.id == mission_id)
                        )
                    ).one_or_none()
            except Exception:
                event_types.append("CANCELLATION_POLL_ERROR")
                return
            if statuses and (
                statuses[0] is MissionStatus.CANCELLED or statuses[1] is TestRunStatus.CANCELLED
            ):
                cancellation_observed.set()
                try:
                    await asyncio.wait_for(selected_harness.interrupt(external_session), 5)
                except Exception:
                    event_types.append("HARNESS_INTERRUPT_ERROR")
                finally:
                    execution_task.cancel()
                return

    cancellation_task = asyncio.create_task(watch_cancellation())
    retain_workspace = False
    try:
        try:
            await asyncio.wait_for(execution_task, timeout=duration)
        except asyncio.CancelledError:
            if not cancellation_observed.is_set():
                try:
                    await asyncio.wait_for(selected_harness.interrupt(external_session), 5)
                except Exception:
                    event_types.append("HARNESS_INTERRUPT_ERROR")
                raise
        except TimeoutError:
            try:
                await asyncio.wait_for(selected_harness.interrupt(external_session), 5)
            except Exception:
                event_types.append("HARNESS_INTERRUPT_ERROR")
            error_payload = {
                "error_code": "MISSION_TIMEOUT",
                "message": "mission exceeded its time limit",
            }
        except Exception as exc:
            from hypertest.application.jobs import JobLeaseLost

            if isinstance(exc, JobLeaseLost):
                raise
            error_payload = {
                "error_code": "HARNESS_ERROR",
                "message": str(exc),
            }
        finally:
            cancellation_task.cancel()
            await asyncio.gather(cancellation_task, return_exceptions=True)

        # No completion/verification row lock is held while a separate writer
        # drains. Its NOWAIT/time bounds also make collisions lossy, not blocking.
        if activity is not None:
            await activity.close()

        provider_metadata = {**(attempt.provider_metadata or {}), "event_types": list(event_types)}
        # Serialize completion with cancellation before processing any result or error.
        await session.refresh(test_run, with_for_update=True)
        await session.refresh(mission, with_for_update=True)
        if external_session.provider_session_id:
            agent_record.provider_session_id = external_session.provider_session_id
        if mission.status is MissionStatus.CANCELLED or test_run.status is TestRunStatus.CANCELLED:
            before_status = mission.status
            if mission.status is not MissionStatus.CANCELLED:
                mission.status = MissionStatus.CANCELLED
                mission.cancelled_at = utcnow()
                mission.row_version += 1
            attempt.status = MissionAttemptStatus.CANCELLED
            attempt.finished_at = utcnow()
            attempt.provider_metadata = provider_metadata
            agent_record.status = AgentSessionStatus.CLOSED
            agent_record.closed_at = utcnow()
            agent_record.last_active_at = utcnow()
            await record_mission_event(
                session, mission, "mission.cancelled", attempt=attempt,
                metadata={"reason": "mission execution cancelled by the control plane"},
                before_status=before_status,
            )
            await session.commit()
            return MissionExecutionResult(mission, attempt, [], [], [], [])
        if harness is None and error_payload is None:
            try:
                await validate_checkout(workspace_path, source.commit_sha, source.repository_url)
            except RuntimeError as exc:
                error_payload = {"error_code": "SOURCE_CHANGED", "message": str(exc)}
        if error_payload is not None:
            error_code, error_message = _safe_agent_error(error_payload)
            await _fail_attempt(
                session,
                mission,
                attempt,
                agent_record,
                error_code,
                error_message,
                provider_metadata,
            )
            raise MissionRuntimeError(error_message)
        if result_payload is None:
            message = "agent finished without RESULT_SUBMITTED"
            await _fail_attempt(
                session,
                mission,
                attempt,
                agent_record,
                "RESULT_MISSING",
                message,
                provider_metadata,
            )
            raise MissionRuntimeError(message)

        try:
            result = MissionResultSubmission.model_validate(result_payload)
        except ValidationError as exc:
            await _fail_attempt(
                session,
                mission,
                attempt,
                agent_record,
                "RESULT_SCHEMA_ERROR",
                str(exc),
                provider_metadata,
                result_payload=result_payload,
            )
            raise MissionRuntimeError("agent result failed TMP schema validation") from exc

        if result.status == "WAITING_INPUT":
            invalid_identity = (
                result.mission_id != mission.key
                or result.protocol != f"hypertest.tmp/{mission.protocol_version}"
            )
            if invalid_identity or durable_job_id is None or not external_session.provider_session_id:
                message = ("input request does not match the immutable mission" if invalid_identity else
                           "human input requires a durable job and a persisted native provider session")
                await _fail_attempt(
                    session, mission, attempt, agent_record, "INPUT_REQUEST_UNSUPPORTED",
                    message, provider_metadata, result_payload=result_payload,
                )
                raise MissionRuntimeError(message)
            assert result.input_request is not None
            # Persist observed native identity while the original lease still owns
            # RUNNING. Waiting states and the question are committed atomically by
            # the Worker's separate pause transaction, never through this fence.
            await session.commit()
            marker = {
                "mission_id": str(mission.id), "attempt_id": str(attempt.id),
                "agent_session_id": str(agent_record.id),
                "provider_session_id": external_session.provider_session_id,
                "workspace_id": agent_record.workspace_id,
                "request": result.input_request.model_dump(mode="json"),
                "provider_metadata": provider_metadata,
            }
            retain_workspace = True
            return MissionExecutionResult(
                mission, attempt, [], [], [], [], waiting_input=marker,
            )

        agent_record.status = AgentSessionStatus.CLOSED
        agent_record.last_active_at = utcnow()
        agent_record.closed_at = utcnow()
        attempt.provider_metadata = provider_metadata
        verification: VerificationResult = await verify_mission_result(
            session,
            mission,
            attempt,
            result,
        )
        await session.refresh(mission)
        await session.refresh(attempt)
        return MissionExecutionResult(
            mission=mission,
            attempt=attempt,
            proposals=verification.proposals,
            requirements=verification.requirements,
            risks=verification.risks,
            test_cases=verification.test_cases,
            implementations=verification.implementations,
            findings=verification.findings,
        )

    finally:
        if activity is not None:
            await activity.close()
        if not retain_workspace:
            try:
                await asyncio.wait_for(selected_harness.close(external_session), 5)
            except Exception:
                event_types.append("HARNESS_CLOSE_ERROR")


async def execute_mission(
    session: AsyncSession,
    mission_id: UUID,
    workspace: str,
    provider: str = "codex",
    harness: AgentHarness | None = None,
) -> MissionExecutionResult:
    """Run one owned attempt, preserving interruption history before re-raising.

    Interrupted database work is rolled back before retiring this attempt. The
    supplied session remains authoritative, including durable-worker lease fencing.
    """

    ownership: dict[str, UUID] = {}
    try:
        return await _execute_mission(
            session, mission_id, workspace, provider, harness, attempt_context=ownership,
        )
    except asyncio.CancelledError:
        await session.rollback()
        attempt_id = ownership.get("attempt_id")
        if attempt_id is not None:
            attempt = await session.get(MissionAttempt, attempt_id)
            if attempt is not None and attempt.status in {
                MissionAttemptStatus.CREATED, MissionAttemptStatus.RUNNING,
                MissionAttemptStatus.SUBMITTED,
            }:
                mission = await session.get(Mission, mission_id)
                agent_record = await session.get(AgentSessionRecord, ownership["agent_session_id"])
                if mission is not None and agent_record is not None:
                    await _fail_attempt(
                        session, mission, attempt, agent_record, "EXECUTION_INTERRUPTED",
                        "request or worker task interrupted before canonical acceptance",
                        {"event_types": ["EXECUTION_INTERRUPTED"]},
                    )
        raise
