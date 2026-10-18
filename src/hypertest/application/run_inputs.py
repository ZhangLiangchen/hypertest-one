"""Persistent questions at Run boundaries, without reopening completed stages."""
from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.bindings import assert_binding_claim, lock_binding, transition_binding
from hypertest.application.jobs import JobLeaseLost, _event, _now
from hypertest.application.services import ConflictError, NotFoundError
from hypertest.common.ids import public_key, uuid7
from hypertest.domain.bindings import BindingStatus
from hypertest.domain.enums import (
    AgentSessionStatus,
    MissionAttemptStatus,
    MissionStatus,
    TestRunStatus,
)
from hypertest.domain.inputs import InputRequestStatus, MissionInputRequest
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import (
    AuditEvent,
    Mission,
    MissionAttempt,
    OutboxEvent,
    TestRun,
)
from hypertest.domain.run_inputs import RunInputRequest
from hypertest.protocol import HumanInputRequest


async def assert_no_open_run_input(session: AsyncSession, run_id: UUID) -> None:
    # Caller holds the Run lock. A common DB trigger separately protects raw SQL.
    for model in (MissionInputRequest, RunInputRequest):
        if await session.scalar(select(model.id).where(model.test_run_id == run_id,
                model.status.in_([InputRequestStatus.PENDING, InputRequestStatus.ANSWERED])).limit(1)):
            raise ConflictError("test run already has an open human input request")


async def _run_input_event(session: AsyncSession, request: RunInputRequest, action: str) -> None:
    run = await session.get(TestRun, request.test_run_id)
    payload = {"input_request_id": str(request.id), "scope": "run", "binding_id": str(request.binding_id),
               "agent_session_id": str(request.agent_session_id), "job_id": str(request.durable_job_id),
               "status": request.status.value, "row_version": request.row_version}
    if request.answer is not None:
        payload["answer_sha256"] = hashlib.sha256(request.answer.encode("utf-8")).hexdigest()
    is_answer = action == "input.answered"
    session.add_all([
        AuditEvent(project_id=run.project_id, test_run_id=run.id, actor_type="USER" if is_answer else "SYSTEM",
                   actor_ref="operator" if is_answer else "hypertest.worker", action=action,
                   entity_type="RunInputRequest", entity_id=request.id, after_state=payload),
        OutboxEvent(aggregate_type="RunInputRequest", aggregate_id=request.id, event_type=action, payload=payload),
    ])


async def pause_run_for_input(
    session: AsyncSession, binding_id: UUID, binding_epoch: int, *, job_id: UUID, lease_token: UUID,
    input_request: HumanInputRequest | dict[str, Any], checkpoint: dict[str, Any],
    context_mission_id: UUID | None = None, context_attempt_id: UUID | None = None,
) -> DurableJob:
    """Use an ordinary Session: suspension revokes its own active claim atomically."""
    question = HumanInputRequest.model_validate(input_request)
    binding = await lock_binding(session, binding_id)
    existing = await session.scalar(select(RunInputRequest).where(
        RunInputRequest.binding_id == binding_id, RunInputRequest.question_id == question.question_id))
    if existing is not None:
        if (existing.question, existing.options, existing.durable_job_id, existing.context_mission_id,
            existing.context_attempt_id, existing.agent_session_id, existing.test_run_id) != (
                question.question, question.options, job_id, context_mission_id, context_attempt_id,
                binding.primary_agent_session_id, binding.test_run_id):
            raise ConflictError("question identity is already bound to different input")
        # Replaying an acknowledged create is a read of its immutable identity,
        # including after the original claim was released or the answer consumed.
        # It must never suspend the Job again or overwrite its later checkpoint.
        job = await session.get(DurableJob, existing.durable_job_id)
        await session.commit()
        return job
    binding, agent, job = await assert_binding_claim(session, binding_id, binding_epoch,
        job_id=job_id, lease_token=lease_token, allowed_statuses=(BindingStatus.ACTIVE,))
    if job.job_type is not JobType.ADVANCE_RUN:
        raise ConflictError("run-level questions require a full test-cycle job")
    if not agent.provider_session_id:
        raise ConflictError("provider did not supply a resumable session reference")
    owned_expiry = job.lease_expires_at
    await assert_no_open_run_input(session, binding.test_run_id)
    if await session.scalar(select(MissionAttempt.id).join(Mission).where(
        Mission.test_run_id == binding.test_run_id,
        MissionAttempt.status.in_([MissionAttemptStatus.CREATED, MissionAttemptStatus.RUNNING, MissionAttemptStatus.SUBMITTED]),
    ).limit(1)):
        raise ConflictError("use a mission-scoped question for the active attempt")
    context_mission = None
    if context_mission_id is not None:
        context_mission = await session.get(Mission, context_mission_id)
        if (context_mission is None or context_mission.test_run_id != binding.test_run_id
                or context_mission.status is not MissionStatus.COMPLETED):
            raise ConflictError("run question context must be a completed stage in this run")
    if context_attempt_id is not None:
        attempt = await session.get(MissionAttempt, context_attempt_id)
        if attempt is None or attempt.status is not MissionAttemptStatus.ACCEPTED:
            raise ConflictError("run question context must be an accepted attempt")
        attempt_mission = await session.get(Mission, attempt.mission_id)
        if (attempt_mission.test_run_id != binding.test_run_id or attempt_mission.status is not MissionStatus.COMPLETED
                or (context_mission_id is not None and attempt.mission_id != context_mission_id)):
            raise ConflictError("run question context belongs to another stage or run")
    now = await _now(session)
    request = RunInputRequest(id=uuid7(), key=public_key("Q"), test_run_id=binding.test_run_id,
        binding_id=binding.id, agent_session_id=agent.id, durable_job_id=job.id,
        context_mission_id=context_mission_id, context_attempt_id=context_attempt_id,
        **question.model_dump(), status=InputRequestStatus.PENDING, created_at=now, row_version=1)
    session.add(request)
    await transition_binding(session, binding, BindingStatus.WAITING_INPUT, reason="run_input_requested")
    agent.status, agent.last_active_at = AgentSessionStatus.WAITING_INPUT, now
    job.result = {**checkpoint, "reason": "WAITING_INPUT", "input_scope": "run", "input_request_id": str(request.id)}
    job.status = JobStatus.WAITING_INPUT
    job.lease_token = job.worker_id = job.lease_expires_at = job.heartbeat_at = None
    job.error_code = job.error_message = None
    await session.flush()
    await _run_input_event(session, request, "input.requested")
    await _event(session, job, "job.waiting_input")
    await session.flush()
    if await _now(session) >= owned_expiry:
        await session.rollback()
        raise JobLeaseLost("job lease expired before run suspension commit")
    await session.commit()
    return job


async def get_run_input_request(session: AsyncSession, request_id: UUID) -> RunInputRequest:
    request = await session.get(RunInputRequest, request_id)
    if request is None:
        raise NotFoundError("input request not found")
    return request


async def answer_run_input_request(
    session: AsyncSession, request_id: UUID, *, answer: str, expected_row_version: int, idempotency_key: str,
) -> tuple[RunInputRequest, DurableJob]:
    if not answer.strip() or len(answer) > 12000 or "\x00" in answer:
        raise ConflictError("answer must contain 1–12000 characters and no NUL")
    if not idempotency_key.strip() or len(idempotency_key) > 512 or "\x00" in idempotency_key:
        raise ConflictError("answer requires an idempotency key of 1–512 characters")
    request = await get_run_input_request(session, request_id)
    binding = await lock_binding(session, request.binding_id)
    job = await session.scalar(select(DurableJob).where(DurableJob.id == request.durable_job_id)
                               .with_for_update().execution_options(populate_existing=True))
    await session.refresh(request, with_for_update=True)
    if request.answer is not None:
        if (request.answer, request.answer_idempotency_key) == (answer, idempotency_key):
            await session.commit()
            return request, job
        raise ConflictError("this question already has an immutable answer")
    run = await session.get(TestRun, request.test_run_id)
    if (request.status is not InputRequestStatus.PENDING or request.row_version != expected_row_version
            or binding.status is not BindingStatus.WAITING_INPUT or run.status is TestRunStatus.CANCELLED
            or job.status is not JobStatus.WAITING_INPUT):
        raise ConflictError("question is no longer awaiting this answer; refresh its current state")
    now = await _now(session)
    request.answer, request.answer_idempotency_key = answer, idempotency_key
    request.status, request.answered_at = InputRequestStatus.ANSWERED, now
    request.row_version += 1
    job.status = JobStatus.QUEUED
    job.result = {**(job.result or {}), "reason": "RESUME_QUEUED"}
    await _run_input_event(session, request, "input.answered")
    await _event(session, job, "job.queued")
    await session.commit()
    return request, job


async def consume_run_input_request(
    session: AsyncSession, request_id: UUID, *, binding_id: UUID, binding_epoch: int,
    job_id: UUID, lease_token: UUID, provider_session_id: str, workspace_id: str,
) -> RunInputRequest:
    """Caller verifies the actual host session/workspace before this short transaction."""
    binding, agent, job = await assert_binding_claim(session, binding_id, binding_epoch,
        job_id=job_id, lease_token=lease_token, allowed_statuses=(BindingStatus.WAITING_INPUT,))
    request = await session.scalar(select(RunInputRequest).where(RunInputRequest.id == request_id).with_for_update())
    if (request is None or request.status is not InputRequestStatus.ANSWERED
            or request.binding_id != binding.id or request.agent_session_id != agent.id
            or request.durable_job_id != job.id or not provider_session_id
            or agent.provider_session_id != provider_session_id or binding.workspace_id != workspace_id):
        raise ConflictError("answer cannot resume a different binding, job, session or workspace")
    now = await _now(session)
    request.status, request.consumed_at = InputRequestStatus.CONSUMED, now
    request.row_version += 1
    agent.status, agent.last_active_at = AgentSessionStatus.RUNNING, now
    await transition_binding(session, binding, BindingStatus.ACTIVE, reason="run_input_consumed")
    await _run_input_event(session, request, "input.consumed")
    await session.flush()
    await assert_binding_claim(session, binding_id, binding_epoch, job_id=job_id, lease_token=lease_token)
    await session.commit()
    return request


async def cancel_run_input_requests(session: AsyncSession, job: DurableJob) -> None:
    """Called under Run → Binding → Job locks by cancellation/recovery."""
    requests = list(await session.scalars(select(RunInputRequest).where(
        RunInputRequest.durable_job_id == job.id,
        RunInputRequest.status.in_([InputRequestStatus.PENDING, InputRequestStatus.ANSWERED]),
    ).with_for_update()))
    now = await _now(session)
    for request in requests:
        request.status, request.cancelled_at = InputRequestStatus.CANCELLED, now
        request.row_version += 1
        await _run_input_event(session, request, "input.cancelled")
