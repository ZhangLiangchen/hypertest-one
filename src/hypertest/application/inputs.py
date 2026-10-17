"""Transactional human questions, worker suspension, and idempotent answers."""
from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.jobs import JobLeaseLost, _event, _lock_job, _now, finish_job
from hypertest.application.lifecycle import record_mission_event
from hypertest.application.services import ConflictError, NotFoundError
from hypertest.common.ids import public_key, uuid7
from hypertest.domain.enums import (
    AgentSessionStatus,
    MissionAttemptStatus,
    MissionStatus,
    TestRunStatus,
)
from hypertest.domain.inputs import InputRequestStatus, MissionInputRequest
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    Mission,
    MissionAttempt,
    OutboxEvent,
    TestRun,
)
from hypertest.protocol import HumanInputRequest


async def _input_event(session: AsyncSession, request: MissionInputRequest, action: str) -> None:
    run = await session.get(TestRun, request.test_run_id)
    payload = {"input_request_id": str(request.id), "mission_id": str(request.mission_id),
               "attempt_id": str(request.attempt_id), "job_id": str(request.durable_job_id),
               "status": request.status.value, "row_version": request.row_version}
    if request.answer is not None:
        payload["answer_sha256"] = hashlib.sha256(request.answer.encode("utf-8")).hexdigest()
    session.add_all([
        AuditEvent(project_id=run.project_id, test_run_id=run.id, actor_type="USER" if action == "input.answered" else "SYSTEM",
                   actor_ref="operator" if action == "input.answered" else "hypertest.worker", action=action,
                   entity_type="MissionInputRequest", entity_id=request.id, after_state=payload),
        OutboxEvent(aggregate_type="MissionInputRequest", aggregate_id=request.id, event_type=action, payload=payload),
    ])


async def get_input_request(session: AsyncSession, request_id: UUID) -> MissionInputRequest:
    request = await session.get(MissionInputRequest, request_id)
    if request is None:
        raise NotFoundError("input request not found")
    return request


async def pause_job_for_input(
    session: AsyncSession, job_id: UUID, lease_token: UUID, *, result: dict[str, Any],
) -> DurableJob:
    """End an owned provider turn atomically, without a FencedSession self-revocation."""
    job = await _lock_job(session, job_id)
    now = await _now(session)
    if (job.lease_token != lease_token or job.status not in {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED}
            or job.lease_expires_at is None or job.lease_expires_at <= now):
        await session.rollback()
        raise JobLeaseLost("cannot suspend work after its lease was lost")
    if job.status is JobStatus.CANCEL_REQUESTED:
        return await finish_job(session, job_id, lease_token)
    if job.job_type not in {JobType.ADVANCE_RUN, JobType.EXECUTE_MISSION}:
        raise ConflictError("this operation cannot request human input")
    owned_expiry = job.lease_expires_at
    marker = result["_waiting_input"]
    question = HumanInputRequest.model_validate(marker["request"])
    mission = await session.scalar(select(Mission).where(Mission.id == UUID(marker["mission_id"])).with_for_update())
    attempt = await session.get(MissionAttempt, UUID(marker["attempt_id"]))
    agent = await session.get(AgentSessionRecord, UUID(marker["agent_session_id"]))
    if (mission is None or attempt is None or agent is None or mission.test_run_id != job.test_run_id
            or attempt.mission_id != mission.id or attempt.durable_job_id != job.id
            or attempt.agent_session_id != agent.id or agent.test_run_id != job.test_run_id
            or mission.status is not MissionStatus.RUNNING or attempt.status is not MissionAttemptStatus.RUNNING
            or (job.job_type is JobType.EXECUTE_MISSION and job.mission_id != mission.id)):
        raise ConflictError("human input does not belong to the current owned attempt")
    reference = marker.get("provider_session_id")
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 512:
        raise ConflictError("provider did not supply a resumable session reference")
    if marker.get("workspace_id") != agent.workspace_id:
        raise ConflictError("waiting workspace identity changed")
    request = MissionInputRequest(
        id=uuid7(), key=public_key("Q"), test_run_id=job.test_run_id, mission_id=mission.id,
        attempt_id=attempt.id, agent_session_id=agent.id, durable_job_id=job.id,
        **question.model_dump(), status=InputRequestStatus.PENDING, created_at=now, row_version=1,
    )
    session.add(request)
    before = mission.status
    mission.status = MissionStatus.WAITING_INPUT
    mission.row_version += 1
    agent.status = AgentSessionStatus.WAITING_INPUT
    agent.provider_session_id = reference
    agent.last_active_at = now
    attempt.provider_metadata = {**(attempt.provider_metadata or {}), **marker.get("provider_metadata", {})}
    job.result = {key: value for key, value in result.items() if key != "_waiting_input"}
    job.result = {**job.result, "reason": "WAITING_INPUT", "mission_id": str(mission.id), "input_request_id": str(request.id)}
    job.status = JobStatus.WAITING_INPUT
    job.lease_token = job.worker_id = job.lease_expires_at = job.heartbeat_at = None
    job.error_code = job.error_message = None
    await session.flush()
    await record_mission_event(session, mission, "mission.waiting_input", attempt=attempt,
                               before_status=before, metadata={"input_request_id": str(request.id),
                               "event_key": f"{request.id}:mission.waiting_input"})
    await _input_event(session, request, "input.requested")
    await _event(session, job, "job.waiting_input")
    await session.flush()
    # Like a fenced canonical commit, suspension cannot publish after its lease
    # expires while validating/writing events. Row locks alone do not stop time.
    if await _now(session) >= owned_expiry:
        await session.rollback()
        raise JobLeaseLost("job lease expired before suspension commit")
    await session.commit()
    return job


async def answer_input_request(
    session: AsyncSession, request_id: UUID, *, answer: str, expected_row_version: int, idempotency_key: str,
) -> tuple[MissionInputRequest, DurableJob]:
    if not answer.strip() or len(answer) > 12000 or "\x00" in answer:
        raise ConflictError("answer must contain 1–12000 characters and no NUL")
    if not idempotency_key.strip() or len(idempotency_key) > 512:
        raise ConflictError("answer requires an idempotency key of 1–512 characters")
    request = await get_input_request(session, request_id)
    job = await _lock_job(session, request.durable_job_id)
    mission = await session.scalar(select(Mission).where(Mission.id == request.mission_id).with_for_update())
    await session.refresh(request, with_for_update=True)
    # An ambiguous HTTP retry is safe even after consumption or task completion.
    if request.answer is not None:
        if request.answer_idempotency_key == idempotency_key and request.answer == answer:
            await session.commit()
            return request, job
        raise ConflictError("this question already has an immutable answer")
    run = await session.get(TestRun, request.test_run_id)
    if (request.status is not InputRequestStatus.PENDING or request.row_version != expected_row_version
            or run.status is TestRunStatus.CANCELLED or job.status is not JobStatus.WAITING_INPUT
            or mission.status is not MissionStatus.WAITING_INPUT):
        raise ConflictError("question is no longer awaiting this answer; refresh its current state")
    now = await _now(session)
    request.answer, request.answer_idempotency_key = answer, idempotency_key
    request.answered_at = now
    request.status = InputRequestStatus.ANSWERED
    request.row_version += 1
    job.status = JobStatus.QUEUED
    job.result = {**(job.result or {}), "reason": "RESUME_QUEUED"}
    await _input_event(session, request, "input.answered")
    await _event(session, job, "job.queued")
    await session.commit()
    return request, job


async def cancel_open_inputs(session: AsyncSession, job: DurableJob) -> None:
    requests = list(await session.scalars(select(MissionInputRequest).where(
        MissionInputRequest.durable_job_id == job.id,
        MissionInputRequest.status.in_([InputRequestStatus.PENDING, InputRequestStatus.ANSWERED]),
    ).with_for_update()))
    now = await _now(session)
    for request in requests:
        request.status = InputRequestStatus.CANCELLED
        request.cancelled_at = now
        request.row_version += 1
        await _input_event(session, request, "input.cancelled")
