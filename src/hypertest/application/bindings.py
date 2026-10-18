"""Run ownership and explicit recovery. Callers commit, never hold locks over I/O."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.jobs import JobLeaseLost, _now
from hypertest.application.services import ConflictError, NotFoundError
from hypertest.common.ids import uuid7
from hypertest.domain.bindings import TERMINAL_BINDING_STATUSES, BindingStatus, RunExecutionBinding
from hypertest.domain.enums import AgentSessionStatus, TestRunStatus
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob, JobStatus
from hypertest.domain.models import AgentSessionRecord, AuditEvent, OutboxEvent, TestRun


async def get_run_binding(session: AsyncSession, run_id: UUID, *, lock: bool = False) -> RunExecutionBinding | None:
    if lock:
        await session.scalar(select(TestRun.id).where(TestRun.id == run_id).with_for_update())
    statement = select(RunExecutionBinding).where(RunExecutionBinding.test_run_id == run_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(statement)


async def lock_binding(session: AsyncSession, binding_id: UUID) -> RunExecutionBinding:
    with session.no_autoflush:
        run_id = await session.scalar(select(RunExecutionBinding.test_run_id).where(RunExecutionBinding.id == binding_id))
        if run_id is None:
            raise NotFoundError("run execution binding not found")
        return await get_run_binding(session, run_id, lock=True)


async def record_binding_event(
    session: AsyncSession, binding: RunExecutionBinding, action: str, *,
    previous_epoch: int | None = None, reason: str | None = None,
) -> None:
    run = await session.get(TestRun, binding.test_run_id)
    payload = {"binding_id": str(binding.id), "test_run_id": str(binding.test_run_id),
               "logical_worker_id": str(binding.logical_worker_id),
               "agent_session_id": str(binding.primary_agent_session_id),
               "binding_epoch": binding.binding_epoch, "status": binding.status.value,
               "row_version": binding.row_version}
    if previous_epoch is not None:
        payload["previous_epoch"] = previous_epoch
    if reason is not None:
        payload["reason"] = reason[:256]
    session.add_all([
        AuditEvent(project_id=run.project_id, test_run_id=run.id, actor_type="SYSTEM",
                   actor_ref="hypertest.worker", action=action, entity_type="RunExecutionBinding",
                   entity_id=binding.id, after_state=payload),
        OutboxEvent(aggregate_type="RunExecutionBinding", aggregate_id=binding.id,
                    event_type=action, payload=payload),
    ])


async def assert_binding_claim(
    session: AsyncSession, binding_id: UUID, binding_epoch: int, *, job_id: UUID,
    lease_token: UUID, logical_worker_id: UUID | None = None, harness_host_id: str | None = None,
    allowed_statuses: tuple[BindingStatus, ...] = (BindingStatus.RESERVED, BindingStatus.ACTIVE),
) -> tuple[RunExecutionBinding, AgentSessionRecord, DurableJob]:
    """Run → Binding → Job locks, database clock, fixed owner and primary Session."""
    with session.no_autoflush:
        binding = await lock_binding(session, binding_id)
        job = await session.scalar(select(DurableJob).where(DurableJob.id == job_id)
                                   .with_for_update().execution_options(populate_existing=True))
        agent = await session.get(AgentSessionRecord, binding.primary_agent_session_id)
        run = await session.get(TestRun, binding.test_run_id)
        now = await _now(session)
        if (binding.status not in allowed_statuses or binding.binding_epoch != binding_epoch
                or (logical_worker_id is not None and binding.logical_worker_id != logical_worker_id)
                or (harness_host_id is not None and binding.harness_host_id != harness_host_id)
                or run.status is TestRunStatus.CANCELLED or agent is None
                or agent.test_run_id != binding.test_run_id or agent.workspace_id != binding.workspace_id
                or agent.status in {AgentSessionStatus.CLOSED, AgentSessionStatus.FAILED}
                or job is None or job.test_run_id != binding.test_run_id
                or job.status is not JobStatus.RUNNING or job.lease_token != lease_token
                or job.lease_expires_at is None or job.lease_expires_at <= now):
            raise JobLeaseLost("run binding, epoch, primary session or job claim is no longer valid")
    return binding, agent, job


async def create_run_binding(
    session: AsyncSession, run_id: UUID, *, job_id: UUID, lease_token: UUID,
    logical_worker_id: UUID, harness_host_id: str, workspace_id: str,
    provider: str = "codex", harness: str = "codex", agent_session_id: UUID | None = None,
    binding_id: UUID | None = None,
) -> RunExecutionBinding:
    """Only fresh Runs enter the new profile; legacy sessions are never promoted."""
    if (not harness_host_id.strip() or len(harness_host_id) > 255 or not workspace_id.strip()
            or not provider.strip() or not harness.strip()):
        raise ConflictError("stable host, controlled workspace and provider identities are required")
    run = await session.scalar(select(TestRun).where(TestRun.id == run_id).with_for_update())
    if run is None:
        raise NotFoundError("test run not found")
    existing = await get_run_binding(session, run_id, lock=True)
    if existing is not None:
        await assert_binding_claim(session, existing.id, existing.binding_epoch, job_id=job_id,
                                   lease_token=lease_token, logical_worker_id=logical_worker_id,
                                   harness_host_id=harness_host_id)
        agent = await session.get(AgentSessionRecord, existing.primary_agent_session_id)
        if (existing.workspace_id != workspace_id or agent.provider != provider or agent.harness != harness
                or (agent_session_id is not None and existing.primary_agent_session_id != agent_session_id)
                or (binding_id is not None and existing.id != binding_id)):
            raise ConflictError("run binding identity is immutable")
        return existing
    job = await session.scalar(select(DurableJob).where(DurableJob.id == job_id).with_for_update())
    now = await _now(session)
    if (run.status in {TestRunStatus.CANCELLED, TestRunStatus.COMPLETED}
            or job is None or job.test_run_id != run_id or job.status is not JobStatus.RUNNING
            or job.lease_token != lease_token or job.lease_expires_at is None or job.lease_expires_at <= now):
        raise JobLeaseLost("cannot establish a run binding without a current job claim")
    if await session.scalar(select(AgentSessionRecord.id).where(AgentSessionRecord.test_run_id == run_id).limit(1)):
        raise ConflictError("legacy session history cannot be converted into a persistent run binding")
    agent = AgentSessionRecord(id=agent_session_id or uuid7(), test_run_id=run_id, provider=provider,
                               harness=harness, workspace_id=workspace_id,
                               status=AgentSessionStatus.CREATED, created_at=now, last_active_at=now)
    session.add(agent)
    await session.flush()
    binding = RunExecutionBinding(id=binding_id or uuid7(), test_run_id=run_id,
                                  logical_worker_id=logical_worker_id, primary_agent_session_id=agent.id,
                                  harness_host_id=harness_host_id, workspace_id=workspace_id,
                                  binding_epoch=1, status=BindingStatus.RESERVED,
                                  created_at=now, updated_at=now, row_version=1)
    session.add(binding)
    await session.flush()
    await record_binding_event(session, binding, "binding.reserved")
    return binding


async def transition_binding(
    session: AsyncSession, binding: RunExecutionBinding, status: BindingStatus, *, reason: str,
) -> RunExecutionBinding:
    """Internal transaction helper; admission/claim must be checked by the caller."""
    if binding.status is status:
        return binding
    allowed = {
        BindingStatus.RESERVED: {BindingStatus.ACTIVE, BindingStatus.RECOVERY_REQUIRED, *TERMINAL_BINDING_STATUSES},
        BindingStatus.ACTIVE: {BindingStatus.WAITING_INPUT, BindingStatus.RECOVERY_REQUIRED, *TERMINAL_BINDING_STATUSES},
        BindingStatus.WAITING_INPUT: {BindingStatus.ACTIVE, BindingStatus.RECOVERY_REQUIRED, *TERMINAL_BINDING_STATUSES},
        BindingStatus.RECOVERY_REQUIRED: set(TERMINAL_BINDING_STATUSES),
    }
    if status not in allowed.get(binding.status, set()):
        raise ConflictError("invalid run binding transition; recovery requires explicit verification")
    binding.status, binding.updated_at = status, await _now(session)
    binding.row_version += 1
    await record_binding_event(session, binding, f"binding.{status.value.lower()}", reason=reason)
    return binding


async def activate_run_binding(
    session: AsyncSession, binding_id: UUID, binding_epoch: int, *, job_id: UUID,
    lease_token: UUID, provider_session_id: str,
) -> RunExecutionBinding:
    binding, agent, _ = await assert_binding_claim(session, binding_id, binding_epoch,
                                                  job_id=job_id, lease_token=lease_token)
    if not provider_session_id.strip() or len(provider_session_id) > 512:
        raise ConflictError("a real native provider session reference is required")
    if agent.provider_session_id is not None and agent.provider_session_id != provider_session_id:
        raise ConflictError("persistent native session identity cannot change")
    agent.provider_session_id = provider_session_id
    agent.status, agent.last_active_at = AgentSessionStatus.RUNNING, await _now(session)
    return await transition_binding(session, binding, BindingStatus.ACTIVE, reason="native_session_verified")


async def recover_run_binding(
    session: AsyncSession, binding_id: UUID, *, expected_epoch: int, expected_row_version: int,
    provider_session_id: str, workspace_id: str, harness_host_id: str,
    prior_calls_fenced: bool, workspace_verified: bool,
) -> RunExecutionBinding:
    """Apply trusted verification performed outside this transaction; never replay."""
    binding = await lock_binding(session, binding_id)
    agent = await session.get(AgentSessionRecord, binding.primary_agent_session_id)
    run = await session.get(TestRun, binding.test_run_id)
    if (binding.status is not BindingStatus.RECOVERY_REQUIRED or binding.binding_epoch != expected_epoch
            or binding.row_version != expected_row_version or not prior_calls_fenced or not workspace_verified
            or not provider_session_id or agent.provider_session_id != provider_session_id
            or binding.workspace_id != workspace_id or binding.harness_host_id != harness_host_id
            or agent.status in {AgentSessionStatus.CLOSED, AgentSessionStatus.FAILED}
            or run.status is TestRunStatus.CANCELLED):
        raise ConflictError("recovery requires the original verified session/workspace and fenced old calls")
    if await session.scalar(select(DurableJob.id).where(DurableJob.test_run_id == binding.test_run_id,
                                                       DurableJob.status.in_(ACTIVE_JOB_STATUSES)).limit(1)):
        raise ConflictError("finish the previous job before explicitly recovering its binding")
    now = await _now(session)
    binding.status, binding.binding_epoch = BindingStatus.ACTIVE, expected_epoch + 1
    binding.updated_at = now
    binding.row_version += 1
    agent.status, agent.last_active_at = AgentSessionStatus.RUNNING, binding.updated_at
    await record_binding_event(session, binding, "binding.recovered", previous_epoch=expected_epoch,
                               reason="original_session_verified_old_calls_fenced")
    return binding


async def terminate_run_binding(
    session: AsyncSession, binding_id: UUID, *, status: BindingStatus, reason: str,
) -> RunExecutionBinding:
    if status not in TERMINAL_BINDING_STATUSES:
        raise ValueError("a terminal binding status is required")
    binding = await lock_binding(session, binding_id)
    if binding.status in TERMINAL_BINDING_STATUSES:
        if binding.status is not status:
            raise ConflictError("terminal run binding history is immutable")
        return binding
    await transition_binding(session, binding, status, reason=reason)
    agent = await session.get(AgentSessionRecord, binding.primary_agent_session_id)
    agent.status = AgentSessionStatus.FAILED if status is BindingStatus.FAILED else AgentSessionStatus.CLOSED
    agent.closed_at = agent.last_active_at = await _now(session)
    return binding
