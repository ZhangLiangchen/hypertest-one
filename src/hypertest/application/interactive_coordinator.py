"""A durable platform coordinator for the *current* Agent; never spawns a Provider."""

from __future__ import annotations

import asyncio
import math
from datetime import timedelta

from sqlalchemy import select

from hypertest.application.bindings import (
    activate_run_binding,
    assert_binding_claim,
    get_run_binding,
)
from hypertest.application.jobs import JobLeaseLost
from hypertest.application.persistent import consume_answer
from hypertest.application.services import ConflictError
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.enums import ExecutionStatus
from hypertest.domain.harness import RunHarnessState, RunReport
from hypertest.domain.interactive import InteractiveExecutionBinding, InteractiveExecutionGrant
from hypertest.domain.jobs import DurableJob, JobStatus
from hypertest.domain.models import TestExecution


async def advance_interactive_run(db, job: DurableJob) -> dict:
    """Keep exactly this platform claim until report, question, expiry or cancellation.

    The typed transport inbox uses this claim, not a second task queue. The ordinary Worker
    monitor heartbeats it, and trusted Runner I/O can drain after Agent grant loss.
    """
    from hypertest.application.interactive import now

    row = await db.scalar(
        select(InteractiveExecutionBinding).where(
            InteractiveExecutionBinding.test_run_id == job.test_run_id
        )
    )
    if not row:
        raise ConflictError("interactive Run must bind its current Agent before dispatch")
    binding = await db.get(RunExecutionBinding, row.binding_id)
    db.binding_id, db.binding_epoch = binding.id, binding.binding_epoch
    state = await db.get(RunHarnessState, binding.id)
    from hypertest.application.persistent_workspace import verify_workspace, workspace_path
    from hypertest.domain.models import SourceSnapshot, TestRun

    run = await db.get(TestRun, job.test_run_id)
    source = await db.get(SourceSnapshot, run.source_snapshot_id)
    await db.commit()
    target = workspace_path(binding.workspace_id)
    await verify_workspace(
        state.source_workspace,
        binding.workspace_id,
        source.commit_sha,
        source.repository_url,
        create=not target.exists(),
    )
    await assert_binding_claim(
        db,
        binding.id,
        binding.binding_epoch,
        job_id=job.id,
        lease_token=job.lease_token,
        allowed_statuses=(
            BindingStatus.RESERVED,
            BindingStatus.ACTIVE,
            BindingStatus.WAITING_INPUT,
        ),
    )
    if binding.status == BindingStatus.WAITING_INPUT:
        await consume_answer(db, binding, state, job)
    if binding.status == BindingStatus.RESERVED:
        await activate_run_binding(
            db,
            binding.id,
            binding.binding_epoch,
            job_id=job.id,
            lease_token=job.lease_token,
            provider_session_id=row.native_session_id,
        )
    await db.commit()
    binding_id, epoch, job_id, lease_token = (
        binding.id,
        binding.binding_epoch,
        job.id,
        job.lease_token,
    )
    # First continuation has a bounded rendezvous window; no fake Agent heartbeat.
    from hypertest.config import get_settings

    rendezvous_until = await now(db) + timedelta(
        seconds=getattr(get_settings(), "interactive_bind_grace_seconds", 120)
    )
    await db.commit()
    while True:
        # Report/input are authorized completion handoffs, not a new execution.
        # Read them under the current Job fence before ACTIVE-only admission.
        await get_run_binding(db, job.test_run_id, lock=True)
        current_job = await db.get(DurableJob, job_id, with_for_update=True, populate_existing=True)
        clock = await now(db)
        if (
            not current_job
            or current_job.status != JobStatus.RUNNING
            or current_job.lease_token != lease_token
            or not current_job.lease_expires_at
            or current_job.lease_expires_at <= clock
        ):
            raise JobLeaseLost("interactive coordinator lost its original Job claim")
        state = await db.get(RunHarnessState, binding_id, populate_existing=True)
        report = await db.scalar(select(RunReport).where(RunReport.binding_id == binding_id))
        if report:
            return {
                "reason": "REPORT_ACCEPTED",
                "binding_id": str(binding_id),
                "report_id": str(report.id),
                "workspace": state.source_workspace,
            }
        if state.pending_input:
            return {
                "reason": "WAITING_INPUT",
                "binding_id": str(binding_id),
                "_waiting_input": state.pending_input,
                "workspace": state.source_workspace,
            }
        await assert_binding_claim(db, binding_id, epoch, job_id=job_id, lease_token=lease_token)
        clock = await now(db)
        grants = list(
            await db.scalars(
                select(InteractiveExecutionGrant)
                .where(InteractiveExecutionGrant.interactive_binding_id == row.id)
                .order_by(InteractiveExecutionGrant.created_at)
                .execution_options(populate_existing=True)
            )
        )
        current_grants = [grant for grant in grants if grant.job_id == job_id]
        current = current_grants[-1] if current_grants else None
        valid = False
        if current:
            try:
                from hypertest.application.interactive import validate_execution_record

                await validate_execution_record(db, row, current)
                valid = True
            except Exception:
                valid = False
        # Count all epochs/Jobs' authorized intervals, never whole-chat time.
        # A revoked grant without a trusted stop timestamp conservatively keeps
        # its bounded reservation; merging overlapping intervals avoids double
        # charging continuations and never resets consumed time on recovery.
        intervals = sorted((g.not_before, min(g.expires_at, clock)) for g in grants)
        seconds, end = 0.0, None
        for start, finish in intervals:
            start = max(start, end) if end and start < end else start
            if finish > start:
                seconds += (finish - start).total_seconds()
            end = max(end, finish) if end else finish
        exhausted = math.ceil(seconds) >= state.harness_budget_seconds
        if exhausted or (not valid and (current_grants or clock >= rendezvous_until)):
            if current and current.status == "ACTIVE":
                current.status, current.row_version = "REVOKED", current.row_version + 1
            # The original server owner must finish its already accepted Runner.
            active_runner = await db.scalar(
                select(TestExecution.id)
                .where(
                    TestExecution.test_run_id == job.test_run_id,
                    TestExecution.status.in_(
                        [
                            ExecutionStatus.QUEUED,
                            ExecutionStatus.PROVISIONING,
                            ExecutionStatus.RUNNING,
                            ExecutionStatus.COLLECTING,
                        ]
                    ),
                )
                .limit(1)
            )
            await db.commit()
            if active_runner:
                await asyncio.sleep(0.2)
                continue
            raise ConflictError(
                "interactive authorization ended; reconcile original calls and explicitly recover"
            )
        await db.commit()
        if valid:
            from hypertest.application.interactive_tool_worker import consume_one

            if await consume_one(db, row, current_job):
                continue
        await db.commit()
        await asyncio.sleep(0.2)
