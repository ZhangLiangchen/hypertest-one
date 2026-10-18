from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import ConflictError, get_test_run
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob
from hypertest.domain.models import TestRun


async def guard_manual_mission_mutation(session: AsyncSession, run_id: UUID) -> None:
    """Queued/bound missions change only through their trusted task controller."""
    from hypertest.config import get_settings
    from hypertest.domain.bindings import RunExecutionBinding

    await get_test_run(session, run_id)
    await session.scalar(select(TestRun.id).where(TestRun.id == run_id).with_for_update())
    binding = await session.scalar(select(RunExecutionBinding.id).where(
        RunExecutionBinding.test_run_id == run_id,
    ))
    if binding is not None or get_settings().execution_mode == "queued":
        raise ConflictError("persistent or queued missions are controlled by their background task; use task controls")


async def guard_synchronous_operation(session: AsyncSession, run_id: UUID) -> None:
    """Serialize legacy synchronous requests with durable request admission."""
    from hypertest.config import get_settings
    from hypertest.domain.bindings import RunExecutionBinding

    if get_settings().execution_mode == "queued":
        raise ConflictError("submit a durable task; this API does not execute host operations")
    await get_test_run(session, run_id)
    await session.scalar(select(TestRun.id).where(TestRun.id == run_id).with_for_update())
    if await session.scalar(select(RunExecutionBinding.id).where(RunExecutionBinding.test_run_id == run_id)):
        raise ConflictError("persistent missions are controlled by their background task; use task controls")
    if await session.scalar(select(DurableJob.id).where(
        DurableJob.test_run_id == run_id, DurableJob.status.in_(ACTIVE_JOB_STATUSES),
    ).limit(1)):
        raise ConflictError("test run has active background work; use its task controls")
