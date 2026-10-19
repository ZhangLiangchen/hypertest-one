"""PostgreSQL queue, explicit recovery, and lease-fenced canonical commits.

A lease prevents stale workers from committing facts. It does not promise exactly
once external execution: expired work is interrupted and requires operator retry.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import ConflictError, NotFoundError
from hypertest.common.ids import public_key, uuid7
from hypertest.domain.enums import (
    AgentSessionStatus,
    CaseResult,
    ExecutionOutcome,
    ExecutionStatus,
    MissionAttemptStatus,
    MissionStatus,
    TestRunStatus,
    VerdictDecision,
)
from hypertest.domain.jobs import (
    ACTIVE_JOB_STATUSES,
    DurableJob,
    JobStatus,
    JobType,
    WorkerHeartbeat,
)
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    ExecutionTestCase,
    Mission,
    MissionAttempt,
    OutboxEvent,
    TestExecution,
    TestRun,
)


class JobLeaseLost(RuntimeError):
    """This worker no longer owns permission to commit canonical state."""


class FencedAsyncSession(AsyncSession):
    def __init__(self, *args, job_id: UUID, lease_token: UUID, test_run_id: UUID, **kwargs):
        super().__init__(*args, **kwargs)
        self.job_id, self.lease_token, self.test_run_id = job_id, lease_token, test_run_id

    async def _check_lease(self) -> None:
        with self.no_autoflush:
            # Canonical services use this aggregate lock too. Always acquire it
            # before the job lock so cancellation/recovery cannot deadlock them.
            await self.scalar(select(TestRun.id).where(TestRun.id == self.test_run_id).with_for_update())
            from hypertest.domain.bindings import BindingStatus, RunExecutionBinding

            binding = (await self.execute(select(
                RunExecutionBinding.id, RunExecutionBinding.binding_epoch, RunExecutionBinding.status,
            ).where(RunExecutionBinding.test_run_id == self.test_run_id).with_for_update())).one_or_none()
            expected_id = getattr(self, "binding_id", None)
            closed_gate_only = getattr(self, "closed_gate_only", False)
            allowed_binding_statuses = ({BindingStatus.CLOSED} if closed_gate_only else {
                BindingStatus.RESERVED, BindingStatus.ACTIVE, BindingStatus.WAITING_INPUT})
            if expected_id is not None and (binding is None or binding[0] != expected_id
                    or binding[1] != self.binding_epoch or binding[2] not in allowed_binding_statuses):
                await self.rollback()
                raise JobLeaseLost("persistent run binding was revoked or recovered by another owner")
            row = (await self.execute(select(
                DurableJob.status, DurableJob.lease_token, DurableJob.lease_expires_at,
                DurableJob.job_type, DurableJob.payload, DurableJob.test_run_id,
            ).where(DurableJob.id == self.job_id).with_for_update())).one_or_none()
            now = await self.scalar(select(func.clock_timestamp()))
        if (row is None or row[0] is not JobStatus.RUNNING or row[1] != self.lease_token
                or row[2] is None or row[2] <= now or row[5] != self.test_run_id):
            await self.rollback()
            raise JobLeaseLost("job lease expired, was cancelled, or belongs to another worker")
        if closed_gate_only:
            from hypertest.application.gate_governance import assert_closed_gate_binding

            if row[3] is not JobType.EVALUATE_GATE or binding is None or expected_id is None:
                await self.rollback()
                raise JobLeaseLost("closed binding authorization is limited to Gate-only work")
            await assert_closed_gate_binding(self, await self.get(RunExecutionBinding, binding[0]),
                finalize=row[4].get("finalize", True), reason=row[4].get("reason"))

    async def commit(self) -> None:
        await self._check_lease()
        await self.flush()
        await self._check_lease()
        await super().commit()


async def _now(session: AsyncSession):
    return await session.scalar(select(func.clock_timestamp()))


async def _event(session: AsyncSession, job: DurableJob, action: str) -> None:
    payload = {"job_id": str(job.id), "job_type": job.job_type.value,
               "status": job.status.value, "test_run_id": str(job.test_run_id),
               "error_code": job.error_code}
    if job.job_type is JobType.EVALUATE_GATE and job.payload.get("reason"):
        # Operator intent is audit metadata, never a Gate fact or decision input.
        payload["request_reason"] = job.payload["reason"]
    if job.job_type is JobType.EVALUATE_GATE and job.status is JobStatus.SUCCEEDED:
        result = job.result or {}
        try:
            verdict_id = str(UUID(result["verdict_id"]))
            key, sequence = result["verdict_key"], result["sequence_no"]
            decision = VerdictDecision(result["decision"]).value
            if not isinstance(key, str) or not 1 <= len(key) <= 64 or type(sequence) is not int or sequence < 1:
                raise ValueError("unsupported Gate result reference")
        except (KeyError, ValueError, TypeError):
            pass
        else:
            payload.update(verdict_id=verdict_id, verdict_key=key, decision=decision, sequence_no=sequence)
    session.add_all([
        AuditEvent(project_id=job.project_id, test_run_id=job.test_run_id,
                   actor_type="SYSTEM", actor_ref=job.worker_id, action=action,
                   entity_type="DurableJob", entity_id=job.id, after_state=payload),
        OutboxEvent(aggregate_type="DurableJob", aggregate_id=job.id,
                    event_type=action, payload=payload),
    ])


async def get_job(session: AsyncSession, job_id: UUID) -> DurableJob:
    job = await session.get(DurableJob, job_id)
    if job is None:
        raise NotFoundError("job not found")
    return job


def _validate_payload(job_type: JobType, payload: dict[str, Any]) -> dict[str, Any]:
    # Input snapshots are operational options only. Canonical run/mission refs
    # live in FK columns, never in opaque payloads.
    from hypertest.api.delivery_schemas import ExecutionCreate, GateRequest, RunAdvance
    from hypertest.api.schemas import MissionExecuteRequest

    models = {JobType.ADVANCE_RUN: RunAdvance, JobType.EXECUTE_TESTS: ExecutionCreate,
              JobType.EVALUATE_GATE: GateRequest, JobType.EXECUTE_MISSION: MissionExecuteRequest}
    if job_type is JobType.PREPARE_WORKSPACE:
        if payload:
            raise ConflictError("workspace preparation accepts no payload options")
        return {}
    model = models[job_type]
    extras = set(payload) - set(model.model_fields)
    if extras:
        raise ConflictError("unsupported job payload fields: " + ", ".join(sorted(extras)))
    result = model.model_validate(payload).model_dump(mode="json")
    if result.get("execution_profile") is None:
        result.pop("execution_profile", None)
    return result


async def submit_job(
    session: AsyncSession, run_id: UUID, job_type: JobType, *, payload: dict[str, Any],
    idempotency_key: str, mission_id: UUID | None = None, retry_of_job_id: UUID | None = None,
) -> DurableJob:
    if not idempotency_key.strip() or len(idempotency_key) > 512:
        raise ConflictError("job requires an idempotency key of 1–512 characters")
    job_type = JobType(job_type)
    payload = _validate_payload(job_type, payload)
    # Defensively freeze caller-owned dictionaries (and reject non-JSON values).
    payload = json.loads(json.dumps(payload, allow_nan=False))
    run = await session.scalar(select(TestRun).where(TestRun.id == run_id).with_for_update())
    if run is None:
        raise NotFoundError("test run not found")
    existing = await session.scalar(select(DurableJob).where(
        DurableJob.test_run_id == run_id, DurableJob.idempotency_key == idempotency_key))
    if existing is not None:
        # Compare schema defaults in memory. Existing immutable history predates
        # additive options such as prepare_workspace=False and must not be rewritten.
        existing_payload = _validate_payload(existing.job_type, existing.payload)
        if (existing.job_type, existing_payload, existing.mission_id, existing.retry_of_job_id) != (
            job_type, payload, mission_id, retry_of_job_id,
        ):
            raise ConflictError("idempotency key is already bound to a different job request")
        await session.commit()
        return existing
    if run.status is TestRunStatus.CANCELLED:
        raise ConflictError("cancelled test runs cannot accept work")
    from hypertest.application.bindings import get_run_binding
    from hypertest.domain.bindings import BindingStatus

    binding = await get_run_binding(session, run_id, lock=True)
    from hypertest.domain.harness_selection import RunHarnessSelection
    selection = await session.get(RunHarnessSelection, run_id)
    if selection is not None and job_type is JobType.EVALUATE_GATE and binding is None:
        raise ConflictError("local Harness governance requires a closed reported binding")
    if selection is not None and (job_type is not JobType.EVALUATE_GATE):
        if job_type is not JobType.ADVANCE_RUN or payload.get("execution_profile") != "run-persistent-harness/v1":
            raise ConflictError("local Harness runs require their original persistent profile")
    if binding is not None:
        if job_type is JobType.EVALUATE_GATE:
            from hypertest.application.gate_governance import assert_closed_gate_binding

            await assert_closed_gate_binding(session, binding, finalize=payload["finalize"], reason=payload["reason"])
        elif job_type is not JobType.ADVANCE_RUN or payload.get("execution_profile") != "run-persistent-harness/v1":
            raise ConflictError("persistent runs must continue through their original Harness profile")
        elif binding.status is not BindingStatus.ACTIVE:
            raise ConflictError("run binding requires explicit recovery or a new testing round")
    if (job_type is JobType.EXECUTE_MISSION) != (mission_id is not None):
        raise ConflictError("EXECUTE_MISSION requires exactly one mission reference")
    if mission_id is not None:
        mission = await session.get(Mission, mission_id)
        if mission is None or mission.test_run_id != run_id:
            raise ConflictError("mission does not belong to this test run")
        if mission.status not in {MissionStatus.CREATED, MissionStatus.READY, MissionStatus.RETRYING}:
            raise ConflictError("mission is not executable")
    active = await session.scalar(select(DurableJob.id).where(
        DurableJob.test_run_id == run_id, DurableJob.status.in_(ACTIVE_JOB_STATUSES)))
    if active is not None:
        raise ConflictError("test run already has active work; wait or cancel the active job")
    active_mission = await session.scalar(select(Mission.id).where(
        Mission.test_run_id == run_id,
        Mission.status.in_([MissionStatus.RUNNING, MissionStatus.DISPATCHED, MissionStatus.SUBMITTED, MissionStatus.VERIFYING, MissionStatus.WAITING_INPUT]),
    ).limit(1))
    active_execution = await session.scalar(select(TestExecution.id).where(
        TestExecution.test_run_id == run_id,
        TestExecution.status.in_([ExecutionStatus.QUEUED, ExecutionStatus.PROVISIONING, ExecutionStatus.RUNNING, ExecutionStatus.COLLECTING]),
    ).limit(1))
    if active_mission is not None or active_execution is not None:
        raise ConflictError("test run already has active synchronous work; cancel or finish it before queueing")
    if retry_of_job_id is not None:
        previous = await session.get(DurableJob, retry_of_job_id)
        if (previous is None or previous.test_run_id != run_id
            or previous.status not in {JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.CANCELLED}):
            raise ConflictError("only terminal unsuccessful jobs in this run can be retried")
        previous_payload = _validate_payload(previous.job_type, previous.payload)
        if (previous.job_type, previous_payload, previous.mission_id) != (job_type, payload, mission_id):
            raise ConflictError("retry must preserve the original job input")
    job = DurableJob(id=uuid7(), key=public_key("JOB"), project_id=run.project_id,
                     test_run_id=run_id, mission_id=mission_id, retry_of_job_id=retry_of_job_id,
                     job_type=job_type, status=JobStatus.QUEUED, payload=payload,
                     idempotency_key=idempotency_key)
    session.add(job)
    await _event(session, job, "job.queued")
    await session.commit()
    return job


async def retry_job(session: AsyncSession, job_id: UUID, *, idempotency_key: str) -> DurableJob:
    previous = await get_job(session, job_id)
    return await submit_job(session, previous.test_run_id, previous.job_type,
                            payload=previous.payload, idempotency_key=idempotency_key,
                            mission_id=previous.mission_id, retry_of_job_id=previous.id)


async def claim_job(session: AsyncSession, worker_id: str, *, lease_seconds: float = 30) -> DurableJob | None:
    if not worker_id or len(worker_id) > 255 or lease_seconds <= 0:
        raise ValueError("worker identity and positive lease duration required")
    # Lock the aggregate before the queue row. Audit inserts reference TestRun,
    # so a Job-first claim can deadlock with Run-first cancellation via FK locks.
    from sqlalchemy import and_, exists, or_

    from hypertest.config import get_settings
    from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
    from hypertest.domain.connector import HarnessNode, RunHarnessPlacement
    from hypertest.domain.harness import RunReport
    from hypertest.domain.harness_selection import RunHarnessSelection

    # Platform Workers may resume a fixed local Connector placement. Host
    # affinity still fences server bindings to their configured UDS host.
    local_placement = exists(select(RunHarnessPlacement.id).join(
        HarnessNode, HarnessNode.id == RunHarnessPlacement.node_id,
    ).join(RunHarnessSelection,
        RunHarnessSelection.test_run_id == RunHarnessPlacement.test_run_id,
    ).where(
        RunHarnessPlacement.binding_id == RunExecutionBinding.id,
        RunHarnessPlacement.test_run_id == TestRun.id,
        RunHarnessPlacement.mode == "LOCAL_CONNECTOR",
        RunHarnessSelection.mode == "LOCAL_CONNECTOR",
        RunHarnessPlacement.node_id == RunHarnessSelection.node_id,
        RunHarnessPlacement.source_bundle_transfer_id == RunHarnessSelection.source_bundle_transfer_id,
        HarnessNode.node_kind == "LOCAL_CONNECTOR",
        HarnessNode.node_key == RunExecutionBinding.harness_host_id,
    ))
    run = await session.scalar(select(TestRun).join(
        DurableJob, DurableJob.test_run_id == TestRun.id,
    ).outerjoin(RunExecutionBinding, RunExecutionBinding.test_run_id == TestRun.id)
        .where(DurableJob.status == JobStatus.QUEUED,
               or_(RunExecutionBinding.id.is_(None),
                   and_(RunExecutionBinding.status.in_([BindingStatus.RESERVED, BindingStatus.ACTIVE, BindingStatus.WAITING_INPUT]),
                        or_(RunExecutionBinding.harness_host_id == get_settings().bridge_host_id, local_placement)),
                   and_(DurableJob.job_type == JobType.EVALUATE_GATE,
                        RunExecutionBinding.status == BindingStatus.CLOSED,
                        exists(select(RunReport.id).where(RunReport.binding_id == RunExecutionBinding.id,
                            RunReport.test_run_id == TestRun.id)),
                        exists(select(AgentSessionRecord.id).where(
                            AgentSessionRecord.id == RunExecutionBinding.primary_agent_session_id,
                            AgentSessionRecord.test_run_id == TestRun.id,
                            AgentSessionRecord.status == AgentSessionStatus.CLOSED)))))
        .order_by(DurableJob.created_at, DurableJob.id)
        .with_for_update(of=TestRun, skip_locked=True).limit(1))
    if run is None:
        await session.rollback()
        return None
    from hypertest.application.bindings import get_run_binding

    await get_run_binding(session, run.id, lock=True)
    job = await session.scalar(select(DurableJob).where(
        DurableJob.test_run_id == run.id, DurableJob.status == JobStatus.QUEUED,
    ).with_for_update(skip_locked=True).limit(1))
    if job is None:
        await session.rollback()
        return None
    now = await _now(session)
    if run.status is TestRunStatus.CANCELLED:
        job.status, job.finished_at, job.cancel_requested_at = JobStatus.CANCELLED, now, now
        job.error_code, job.error_message = "RUN_CANCELLED", "Test run was cancelled before dispatch"
        await _event(session, job, "job.cancelled")
        await session.commit()
        return None
    job.status, job.worker_id, job.lease_token = JobStatus.RUNNING, worker_id, uuid7()
    job.attempts += 1
    job.started_at = job.started_at or now
    job.heartbeat_at, job.lease_expires_at = now, now + timedelta(seconds=lease_seconds)
    await _event(session, job, "job.started")
    await session.commit()
    return job


async def heartbeat_job(session: AsyncSession, job_id: UUID, lease_token: UUID, *, lease_seconds: float = 30) -> JobStatus:
    job = await session.scalar(select(DurableJob).where(DurableJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    now = await _now(session)
    if job is None or job.lease_token != lease_token or job.status not in {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED} or job.lease_expires_at is None or job.lease_expires_at <= now:
        await session.rollback()
        raise JobLeaseLost("job lease is no longer owned")
    if job.status is JobStatus.RUNNING:
        job.heartbeat_at, job.lease_expires_at = now, now + timedelta(seconds=lease_seconds)
    status = job.status
    await session.commit()
    return status


async def _lock_job(session: AsyncSession, job_id: UUID) -> DurableJob:
    run_id = await session.scalar(select(DurableJob.test_run_id).where(DurableJob.id == job_id))
    if run_id is None:
        raise NotFoundError("job not found")
    await session.scalar(select(TestRun).where(TestRun.id == run_id).with_for_update().execution_options(populate_existing=True))
    from hypertest.application.bindings import get_run_binding

    await get_run_binding(session, run_id, lock=True)
    return await session.scalar(select(DurableJob).where(DurableJob.id == job_id)
                                .with_for_update().execution_options(populate_existing=True))


async def _recover_work(session: AsyncSession, job: DurableJob, *, cancelled: bool, error_code: str, message: str) -> None:
    if job.job_type is JobType.EVALUATE_GATE:
        # Gate governance owns no executable work. Its failure must not alter the
        # reported cycle's Run lifecycle, Session, questions or formal facts.
        return
    now = await _now(session)
    from hypertest.application.bindings import (
        get_run_binding,
        terminate_run_binding,
        transition_binding,
    )
    from hypertest.application.lifecycle import record_mission_event
    from hypertest.domain.bindings import TERMINAL_BINDING_STATUSES, BindingStatus

    binding = await get_run_binding(session, job.test_run_id, lock=True)
    if binding is not None and binding.status not in TERMINAL_BINDING_STATUSES:
        bound_run = await session.get(TestRun, job.test_run_id)
        if bound_run.status is TestRunStatus.CANCELLED:
            await terminate_run_binding(session, binding.id, status=BindingStatus.CANCELLED,
                                        reason="run_cancelled")
        else:
            await transition_binding(session, binding, BindingStatus.RECOVERY_REQUIRED,
                                     reason=error_code)

    # Explicit ownership survives process/DB clock skew and never guesses which
    # legacy synchronous operation happened to overlap this job.
    active_attempts = select(MissionAttempt.mission_id).where(
        MissionAttempt.durable_job_id == job.id,
        MissionAttempt.status.in_([MissionAttemptStatus.CREATED, MissionAttemptStatus.RUNNING, MissionAttemptStatus.SUBMITTED]),
    )
    mission_query = select(Mission).where(
        Mission.test_run_id == job.test_run_id,
        Mission.id.in_(active_attempts),
        Mission.status.in_([MissionStatus.RUNNING, MissionStatus.DISPATCHED, MissionStatus.SUBMITTED, MissionStatus.VERIFYING, MissionStatus.WAITING_INPUT]),
    )
    if job.job_type is JobType.EXECUTE_MISSION:
        mission_query = mission_query.where(Mission.id == job.mission_id)
    elif job.job_type is not JobType.ADVANCE_RUN:
        mission_query = mission_query.where(False)
    missions = list(await session.scalars(mission_query.order_by(Mission.id).with_for_update()))
    for mission in missions:
        before_status = mission.status
        mission.status = MissionStatus.CANCELLED if cancelled else MissionStatus.RETRYING
        if cancelled:
            mission.cancelled_at = now
        mission.row_version += 1
        attempts = list(await session.scalars(select(MissionAttempt).where(
            MissionAttempt.mission_id == mission.id,
            MissionAttempt.durable_job_id == job.id,
            MissionAttempt.status.in_([MissionAttemptStatus.CREATED, MissionAttemptStatus.RUNNING, MissionAttemptStatus.SUBMITTED]),
        ).with_for_update()))
        for attempt in attempts:
            attempt.status = MissionAttemptStatus.CANCELLED if cancelled else MissionAttemptStatus.FAILED
            attempt.error_code, attempt.error_message, attempt.finished_at = error_code, message, now
            if attempt.agent_session_id:
                agent = await session.get(AgentSessionRecord, attempt.agent_session_id)
                if agent is not None and (binding is None or agent.id != binding.primary_agent_session_id):
                    agent.status = AgentSessionStatus.CLOSED if cancelled else AgentSessionStatus.FAILED
                    agent.closed_at = agent.last_active_at = now
            await record_mission_event(
                session, mission, "mission.cancelled" if cancelled else "mission.interrupted",
                attempt=attempt, before_status=before_status,
                metadata={"error_code": error_code, "reason": "durable_job_recovery", "job_id": str(job.id)},
            )
    from hypertest.application.inputs import cancel_open_inputs

    await cancel_open_inputs(session, job)
    executions = list(await session.scalars(select(TestExecution).where(
        TestExecution.test_run_id == job.test_run_id,
        TestExecution.durable_job_id == job.id,
        TestExecution.status.in_([ExecutionStatus.QUEUED, ExecutionStatus.PROVISIONING, ExecutionStatus.RUNNING, ExecutionStatus.COLLECTING]),
    ).with_for_update()))
    if job.job_type not in {JobType.ADVANCE_RUN, JobType.EXECUTE_TESTS}:
        executions = []
    for execution in executions:
        execution.status = ExecutionStatus.CANCELLED if cancelled else ExecutionStatus.ERROR
        execution.outcome, execution.finished_at = ExecutionOutcome.INCONCLUSIVE, now
        execution.error_code, execution.error_message = error_code, message
        facts = list(await session.scalars(select(ExecutionTestCase).where(ExecutionTestCase.execution_id == execution.id)))
        for fact in facts:
            fact.result, fact.failure_summary = CaseResult.ERROR, message
        action = "execution.cancelled" if cancelled else "execution.interrupted"
        payload = {"execution_id": str(execution.id), "job_id": str(job.id),
                   "status": execution.status.value, "outcome": execution.outcome.value,
                   "error_code": error_code, "case_count": len(facts)}
        session.add_all([
            AuditEvent(project_id=job.project_id, test_run_id=job.test_run_id,
                       actor_type="SYSTEM", actor_ref="hypertest.worker", action=action,
                       entity_type="TestExecution", entity_id=execution.id, after_state=payload),
            OutboxEvent(aggregate_type="TestExecution", aggregate_id=execution.id,
                        event_type=action, payload=payload),
        ])
    run = await session.get(TestRun, job.test_run_id)
    if run.status not in {TestRunStatus.CANCELLED, TestRunStatus.COMPLETED}:
        run.status = TestRunStatus.BLOCKED
        run.row_version += 1


async def cancel_job(session: AsyncSession, job_id: UUID) -> DurableJob:
    job = await _lock_job(session, job_id)
    if job.status not in ACTIVE_JOB_STATUSES:
        await session.commit()
        return job
    now = await _now(session)
    job.cancel_requested_at = job.cancel_requested_at or now
    paused = job.status is JobStatus.WAITING_INPUT or (
        job.status is JobStatus.QUEUED and bool((job.result or {}).get("input_request_id"))
    )
    if job.status in {JobStatus.QUEUED, JobStatus.WAITING_INPUT}:
        if paused:
            await _recover_work(session, job, cancelled=True, error_code="JOB_CANCELLED",
                                message="Operator cancelled durable work")
        job.status, job.finished_at, job.lease_expires_at = JobStatus.CANCELLED, now, None
        await _event(session, job, "job.cancelled")
    else:
        job.status = JobStatus.CANCEL_REQUESTED
        # Propagate durable cancellation immediately; the live worker separately
        # interrupts provider/runner resources and finalizes its task.
        await _recover_work(session, job, cancelled=True, error_code="JOB_CANCELLED", message="Operator cancelled durable work")
        await _event(session, job, "job.cancel_requested")
    await session.commit()
    if paused:
        await cleanup_job_resources(session, job)
    return job


async def finish_job(session: AsyncSession, job_id: UUID, lease_token: UUID, *, result: dict | None = None,
                     error_code: str | None = None, error_message: str | None = None, interrupted: bool = False) -> DurableJob:
    job = await _lock_job(session, job_id)
    now = await _now(session)
    if job.lease_token != lease_token or job.status not in {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED} or job.lease_expires_at is None or job.lease_expires_at <= now:
        await session.rollback()
        raise JobLeaseLost("cannot finish a job after its lease was lost")
    if job.status is JobStatus.CANCEL_REQUESTED:
        target = JobStatus.CANCELLED
        error_code, error_message = "JOB_CANCELLED", "Operator cancelled durable work"
        await _recover_work(session, job, cancelled=True, error_code=error_code, message=error_message)
    elif error_code:
        target = JobStatus.INTERRUPTED if interrupted else JobStatus.FAILED
        error_message = (error_message or "Worker failed")[:2048]
        await _recover_work(session, job, cancelled=False, error_code=error_code, message=error_message)
    else:
        target = JobStatus.SUCCEEDED
        from hypertest.application.bindings import get_run_binding, terminate_run_binding
        from hypertest.domain.bindings import BindingStatus
        from hypertest.domain.harness import RunReport

        binding = await get_run_binding(session, job.test_run_id, lock=True)
        if binding is not None and job.job_type is JobType.ADVANCE_RUN:
            report = await session.get(RunReport, UUID((result or {}).get("report_id", "")))
            if report is None or report.binding_id != binding.id or report.durable_job_id != job.id:
                raise ConflictError("persistent job completion requires its accepted report")
            await terminate_run_binding(session, binding.id, status=BindingStatus.CLOSED,
                                        reason="report_accepted_native_call_closed")
    # Set the complete terminal record together after any recovery queries;
    # the DB intentionally refuses a second update of terminal history.
    # Controlled dispatcher failures may carry committed steps/identities so the
    # operator can inspect and recover. Cancellation/interruption still discard
    # any speculative handler result; all terminal history remains immutable.
    checkpoint = job.result if (job.result or {}).get("input_request_id") else None
    terminal_result = result if target in {JobStatus.SUCCEEDED, JobStatus.FAILED} else None
    if terminal_result is None and checkpoint is not None:
        # This checkpoint was committed before the resumed handler began. Keep
        # accepted progress even when restoration/preflight fails or is cancelled.
        terminal_result = {**checkpoint, "reason": target.value, "resume_stopped": True}
    job.status, job.result = target, terminal_result
    job.error_code, job.error_message = error_code, error_message
    job.finished_at, job.lease_expires_at = now, None
    await _event(session, job, f"job.{job.status.value.lower()}")
    await session.commit()
    return job


async def recover_expired_jobs(session: AsyncSession) -> list[DurableJob]:
    # Do not claim/replay expired work. External side effects may have occurred.
    candidates = list(await session.scalars(select(DurableJob.id).where(
        DurableJob.status.in_([JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED]),
        DurableJob.lease_expires_at <= func.clock_timestamp(),
    ).order_by(DurableJob.id)))
    recovered = []
    for job_id in candidates:
        job = await _lock_job(session, job_id)
        now = await _now(session)
        if job.status not in {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED} or job.lease_expires_at > now:
            # Release the read locks without expiring recovered ORM records from
            # earlier iterations; they are used for post-commit resource cleanup.
            await session.commit()
            continue
        cancelled = job.status is JobStatus.CANCEL_REQUESTED
        code = "JOB_CANCELLED" if cancelled else "WORKER_LEASE_EXPIRED"
        message = "Work was interrupted; inspect external resources before explicit retry"
        await _recover_work(session, job, cancelled=cancelled, error_code=code, message=message)
        job.status = JobStatus.CANCELLED if cancelled else JobStatus.INTERRUPTED
        job.error_code, job.error_message = code, message
        job.finished_at, job.lease_expires_at = now, None
        await _event(session, job, f"job.{job.status.value.lower()}")
        await session.commit()
        recovered.append(job)
    # No aggregate/job row locks are held while calling the Docker API.
    for job in recovered:
        await cleanup_job_resources(session, job, on_worker=True)
    return recovered


async def cleanup_job_resources(session: AsyncSession, job: DurableJob, *, on_worker: bool = False) -> dict[str, Any]:
    if job.job_type is JobType.EVALUATE_GATE:
        # A Gate-only operation owns no Provider, Runner or workspace resources.
        return {"external_resources": "not_applicable"}
    from hypertest.config import get_settings

    if get_settings().execution_mode == "queued" and not on_worker:
        from hypertest.application.runtime_control import request_control

        return await request_control(session, "CLEANUP_JOB", {"job_id": str(job.id)}, wait=False)
    from hypertest.agent.snapshot import cleanup_managed_agent_workspace
    from hypertest.runner.backends import cleanup_docker_job_resources

    workspaces = list(await session.scalars(select(AgentSessionRecord.workspace_id).join(
        MissionAttempt, MissionAttempt.agent_session_id == AgentSessionRecord.id,
    ).where(MissionAttempt.durable_job_id == job.id,
            AgentSessionRecord.status.in_([AgentSessionStatus.CLOSED, AgentSessionStatus.FAILED]))))
    # Release all read/FK locks before filesystem or Docker I/O.
    await session.commit()
    cleanup = await cleanup_docker_job_resources(job.id)
    from hypertest.application.persistent import cleanup_bound_call

    cleanup.update(await cleanup_bound_call(session, job))
    removed, failures = 0, 0
    for workspace in set(workspaces):
        try:
            removed += bool(await asyncio.to_thread(cleanup_managed_agent_workspace, workspace))
        except OSError:
            failures += 1
    cleanup = {**cleanup, "agent_workspaces_removed": removed, "agent_workspace_cleanup_failures": failures}
    payload = {"job_id": str(job.id), "test_run_id": str(job.test_run_id), **cleanup}
    session.add_all([
        AuditEvent(project_id=job.project_id, test_run_id=job.test_run_id,
                   actor_type="SYSTEM", actor_ref="hypertest.worker", action="job.resources_cleanup",
                   entity_type="DurableJob", entity_id=job.id, event_metadata=payload),
        OutboxEvent(aggregate_type="DurableJob", aggregate_id=job.id,
                    event_type="job.resources_cleanup", payload=payload),
    ])
    await session.commit()
    return cleanup


async def record_worker_heartbeat(session: AsyncSession, worker_id: str, active_job_id: UUID | None = None) -> None:
    from sqlalchemy.dialects.postgresql import insert

    now = await _now(session)
    await session.execute(insert(WorkerHeartbeat).values(
        worker_id=worker_id, started_at=now, last_seen_at=now, active_job_id=active_job_id,
    ).on_conflict_do_update(index_elements=[WorkerHeartbeat.worker_id], set_={
        "last_seen_at": now, "active_job_id": active_job_id,
    }))
    await session.commit()


async def get_worker_status(session: AsyncSession) -> dict[str, Any]:
    from hypertest.config import get_settings

    cutoff = await _now(session) - timedelta(seconds=get_settings().worker_lease_seconds * 2)
    count = await session.scalar(select(func.count()).select_from(WorkerHeartbeat).where(
        WorkerHeartbeat.last_seen_at >= cutoff))
    last_seen = await session.scalar(select(func.max(WorkerHeartbeat.last_seen_at)))
    return {"available": bool(count), "last_seen_at": last_seen, "active_workers": count}
