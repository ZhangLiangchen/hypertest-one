"""Operator Gate decisions after a reported Harness cycle; never resume a session."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import ConflictError
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.enums import AgentSessionStatus, TestRunStatus
from hypertest.domain.harness import RunReport
from hypertest.domain.models import AgentSessionRecord, TestRun


async def assert_closed_gate_binding(
    session: AsyncSession, binding: RunExecutionBinding, *, finalize: bool, reason: str | None,
) -> None:
    """Caller holds Run → Binding locks; this grants no Harness execution rights."""
    run = await session.get(TestRun, binding.test_run_id)
    agent = await session.get(AgentSessionRecord, binding.primary_agent_session_id)
    report = await session.scalar(select(RunReport.id).where(
        RunReport.binding_id == binding.id, RunReport.test_run_id == binding.test_run_id,
    ).limit(1))
    if (binding.status is not BindingStatus.CLOSED or agent is None
            or agent.status is not AgentSessionStatus.CLOSED
            or agent.test_run_id != binding.test_run_id or agent.workspace_id != binding.workspace_id
            or run is None or run.status is TestRunStatus.CANCELLED or report is None):
        raise ConflictError("independent Gate reevaluation requires a closed reported Harness cycle")
    if finalize is not True or not reason or not reason.strip():
        raise ConflictError("independent Gate reevaluation requires a final decision and a reason")


async def authorize_gate_job(session: AsyncSession, run_id: UUID, payload: dict) -> None:
    """Bind a Gate-only worker commit to the original CLOSED binding / epoch."""
    from hypertest.application.bindings import get_run_binding

    binding = await get_run_binding(session, run_id, lock=True)
    if binding is None:
        return  # Existing unbound / legacy Gate requests retain their contract.
    await assert_closed_gate_binding(session, binding, finalize=payload.get("finalize", True),
                                     reason=payload.get("reason"))
    session.binding_id, session.binding_epoch = binding.id, binding.binding_epoch
    session.closed_gate_only = True
