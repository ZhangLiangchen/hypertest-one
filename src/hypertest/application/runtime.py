from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.agent.base import AgentHarness
from hypertest.agent.codex import CodexCliAdapter
from hypertest.application.verifier import VerificationResult, verify_mission_result
from hypertest.domain.enums import (
    AgentSessionStatus,
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    TestRunStatus,
)
from hypertest.domain.models import (
    AgentSessionRecord,
    Mission,
    MissionAttempt,
    MissionProposal,
    Requirement,
    Risk,
    TestRun,
    utcnow,
)
from hypertest.protocol import MissionResultSubmission


class MissionRuntimeError(RuntimeError):
    pass


@dataclass(slots=True)
class MissionExecutionResult:
    mission: Mission
    attempt: MissionAttempt
    proposals: list[MissionProposal]
    requirements: list[Requirement]
    risks: list[Risk]


def _output_schema_for(mission_type: MissionType) -> str:
    if mission_type is MissionType.ANALYZE_REQUIREMENTS:
        return "hypertest.result/requirement-analysis/v1"
    if mission_type is MissionType.ANALYZE_RISKS:
        return "hypertest.result/risk-analysis/v1"
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
    return contract


async def _fail_attempt(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    agent_session: AgentSessionRecord,
    error_code: str,
    error_message: str,
    provider_metadata: dict[str, Any],
) -> None:
    now = utcnow()
    attempt.status = MissionAttemptStatus.FAILED
    attempt.finished_at = now
    attempt.error_code = error_code
    attempt.error_message = error_message
    attempt.provider_metadata = provider_metadata
    mission.status = MissionStatus.RETRYING
    mission.row_version += 1
    agent_session.status = AgentSessionStatus.FAILED
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
    }:
        raise MissionRuntimeError(
            "runtime currently supports ANALYZE_REQUIREMENTS and ANALYZE_RISKS only"
        )
    if mission.status not in {
        MissionStatus.CREATED,
        MissionStatus.READY,
        MissionStatus.RETRYING,
    }:
        raise MissionRuntimeError(f"mission cannot execute from status {mission.status.value}")

    selected_harness = harness or _select_harness(provider)
    external_session = await selected_harness.create_session(workspace)
    now = utcnow()
    agent_record = AgentSessionRecord(
        test_run_id=test_run.id,
        provider=external_session.provider,
        harness=type(selected_harness).__name__,
        provider_session_id=external_session.provider_session_id or external_session.id,
        workspace_id=workspace,
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
    if test_run.status is TestRunStatus.CREATED:
        test_run.status = TestRunStatus.ANALYZING
        test_run.started_at = test_run.started_at or now
        test_run.row_version += 1
    await session.commit()
    await session.refresh(agent_record)
    await session.refresh(attempt)

    result_payload: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    event_types: list[str] = []
    contract = build_mission_contract(mission, test_run)

    try:
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
    except Exception as exc:
        error_payload = {
            "error_code": "HARNESS_ERROR",
            "message": str(exc),
        }
    finally:
        try:
            await selected_harness.close(external_session)
        except Exception:
            event_types.append("HARNESS_CLOSE_ERROR")

    provider_metadata = {"event_types": event_types}
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
    )
