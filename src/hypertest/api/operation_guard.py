from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import ConflictError, get_test_run
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob
from hypertest.domain.models import TestRun


async def guard_synchronous_operation(session: AsyncSession, run_id: UUID) -> None:
    """Serialize legacy synchronous requests with durable request admission."""
    await get_test_run(session, run_id)
    await session.scalar(select(TestRun.id).where(TestRun.id == run_id).with_for_update())
    if await session.scalar(select(DurableJob.id).where(
        DurableJob.test_run_id == run_id, DurableJob.status.in_(ACTIVE_JOB_STATUSES),
    ).limit(1)):
        raise ConflictError("test run has active background work; use its task controls")
