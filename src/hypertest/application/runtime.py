from __future__ import annotations

import asyncio
import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.agent.base import AgentHarness
from hypertest.agent.codex import CodexCliAdapter
from hypertest.agent.snapshot import SnapshotHarness
from hypertest.application.verifier import VerificationResult, verify_mission_result
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
    TestCaseProposalPayload,
    TestImplementationProposalPayload,
)


class MissionRuntimeError(RuntimeError):
    pass


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
    if mission.mission_type is MissionType.DESIGN_TESTS:
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
    context = dict(contract.get("context", {}))
    context.update(repository_url=snapshot.repository_url, commit_sha=snapshot.commit_sha)
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
    if configuration.exists():
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


async def _fail_attempt(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    agent_session: AgentSessionRecord,
    error_code: str,
    error_message: str,
    provider_metadata: dict[str, Any],
) -> None:
    test_run = await session.get(TestRun, mission.test_run_id)
    if test_run is not None:
        await session.refresh(test_run, with_for_update=True)
    await session.refresh(mission, with_for_update=True)
    cancelled = mission.status is MissionStatus.CANCELLED or (
        test_run is not None and test_run.status is TestRunStatus.CANCELLED
    )
    now = utcnow()
    attempt.status = MissionAttemptStatus.CANCELLED if cancelled else MissionAttemptStatus.FAILED
    attempt.finished_at = now
    attempt.error_code = error_code
    attempt.error_message = error_message
    attempt.provider_metadata = provider_metadata
    if not cancelled:
        mission.status = MissionStatus.RETRYING
        mission.row_version += 1
    agent_session.status = AgentSessionStatus.CLOSED if cancelled else AgentSessionStatus.FAILED
    agent_session.last_active_at = now
    agent_session.closed_at = now
    await session.commit()


def _select_harness(provider: str) -> AgentHarness:
    if provider == "codex":
        return CodexCliAdapter()
    raise MissionRuntimeError(f"unsupported agent provider: {provider}")


async def execute_mission(
    session: AsyncSession,
    mission_id: UUID,
    workspace: str,
    provider: str = "codex",
    harness: AgentHarness | None = None,
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
    if mission.status not in {
        MissionStatus.CREATED,
        MissionStatus.READY,
        MissionStatus.RETRYING,
    }:
        message = f"mission cannot execute from status {mission.status.value}"
        await session.rollback()
        raise MissionRuntimeError(message)
    if test_run.status is TestRunStatus.CANCELLED:
        await session.rollback()
        raise MissionRuntimeError("cancelled test runs cannot execute missions")
    try:
        external_session = await selected_harness.create_session(workspace)
    except Exception as exc:
        await session.rollback()
        raise MissionRuntimeError(f"agent session could not be created: {exc}") from exc
    now = utcnow()
    agent_record = AgentSessionRecord(
        test_run_id=test_run.id,
        provider=external_session.provider,
        harness=type(selected_harness).__name__,
        provider_session_id=external_session.provider_session_id or external_session.id,
        workspace_id=(
            selected_harness.workspace_for(external_session)
            if isinstance(selected_harness, SnapshotHarness)
            else workspace
        ),
        status=AgentSessionStatus.RUNNING,
        last_active_at=now,
    )
    attempt = MissionAttempt(
        mission_id=mission.id,
        attempt_no=mission.current_attempt_no + 1,
        agent_session=agent_record,
        provider=external_session.provider,
        harness=type(selected_harness).__name__,
        status=MissionAttemptStatus.RUNNING,
        started_at=now,
    )
    session.add_all([agent_record, attempt])
    mission.current_attempt_no = attempt.attempt_no
    mission.status = MissionStatus.RUNNING
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
        await session.commit()
    except Exception:
        await session.rollback()
        try:
            await asyncio.wait_for(selected_harness.close(external_session), 5)
        except Exception:
            pass
        raise
    await session.refresh(agent_record)
    await session.refresh(attempt)

    result_payload: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    event_types: list[str] = []

    async def consume_events() -> None:
        nonlocal result_payload, error_payload
        async for event in selected_harness.execute(external_session, contract):
            event_types.append(event.type)
            if event.type == "RESULT_SUBMITTED":
                if result_payload is not None:
                    error_payload = {
                        "error_code": "MULTIPLE_RESULTS",
                        "message": "agent submitted more than one final result",
                    }
                else:
                    result_payload = event.payload
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
    try:
        await asyncio.wait_for(execution_task, timeout=duration)
    except asyncio.CancelledError:
        if not cancellation_observed.is_set():
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
        error_payload = {
            "error_code": "HARNESS_ERROR",
            "message": str(exc),
        }
    finally:
        cancellation_task.cancel()
        await asyncio.gather(cancellation_task, return_exceptions=True)
        try:
            await asyncio.wait_for(selected_harness.close(external_session), 5)
        except Exception:
            event_types.append("HARNESS_CLOSE_ERROR")

    provider_metadata = {"event_types": event_types}
    # Serialize completion with cancellation before processing any result or error.
    await session.refresh(test_run, with_for_update=True)
    await session.refresh(mission, with_for_update=True)
    if mission.status is MissionStatus.CANCELLED or test_run.status is TestRunStatus.CANCELLED:
        attempt.status = MissionAttemptStatus.CANCELLED
        attempt.finished_at = utcnow()
        attempt.provider_metadata = provider_metadata
        agent_record.status = AgentSessionStatus.CLOSED
        agent_record.closed_at = utcnow()
        agent_record.last_active_at = utcnow()
        await session.commit()
        return MissionExecutionResult(mission, attempt, [], [], [], [])
    if harness is None and error_payload is None:
        try:
            await validate_checkout(workspace_path, source.commit_sha, source.repository_url)
        except RuntimeError as exc:
            error_payload = {"error_code": "SOURCE_CHANGED", "message": str(exc)}
    if error_payload is not None:
        error_code = str(error_payload.get("error_code", "AGENT_ERROR"))
        error_message = str(error_payload.get("message") or error_payload)
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
        )
        raise MissionRuntimeError("agent result failed TMP schema validation") from exc

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
