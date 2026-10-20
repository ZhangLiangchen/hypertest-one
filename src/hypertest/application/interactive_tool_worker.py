"""Consume typed transport requests inside the original task Worker, never the API."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.application import interactive as app
from hypertest.application.harness_tools import HarnessTools
from hypertest.application.jobs import FencedAsyncSession, JobLeaseLost
from hypertest.application.services import ConflictError
from hypertest.db.session import AsyncSessionLocal, engine
from hypertest.domain.harness import RunToolCall
from hypertest.domain.interactive import (
    InteractiveExecutionBinding,
    InteractiveExecutionGrant,
    InteractiveToolRequest,
)
from hypertest.domain.jobs import DurableJob, JobStatus


class InteractiveFencedSession(FencedAsyncSession):
    """Recheck registered capability references at every domain commit."""

    async def _check_lease(self):
        await super()._check_lease()
        if not getattr(self, "drain_accepted_external", False):
            row = await self.get(
                InteractiveExecutionBinding, self.interactive_execution_id, populate_existing=True
            )
            short = await self.get(
                InteractiveExecutionGrant, self.execution_grant_id, populate_existing=True
            )
            await app.validate_execution_record(self, row, short)

    async def commit(self):
        # Only an exact immutable Runner reservation accepted under valid grant
        # may drain. Source checks or merely entering request_execution cannot.
        accepted_runner = False
        if getattr(self, "domain_tool_name", None) == "request_execution":
            from hypertest.domain.models import TestExecution

            with self.no_autoflush:
                call = await self.scalar(
                    select(RunToolCall).where(
                        RunToolCall.binding_id == self.binding_id,
                        RunToolCall.idempotency_key == self.domain_tool_key,
                    )
                )
                if call:
                    accepted_runner = (
                        await self.scalar(
                            select(TestExecution.id).where(
                                TestExecution.test_run_id == self.test_run_id,
                                TestExecution.idempotency_key == f"harness:{call.id}",
                            )
                        )
                        is not None
                    )
        await super().commit()
        if accepted_runner:
            self.drain_accepted_external = True


async def consume_one(db, row, job) -> bool:
    """One delivery, with no resumption/replay of a RUNNING or UNKNOWN request."""
    request = await db.scalar(
        select(InteractiveToolRequest)
        .where(
            InteractiveToolRequest.interactive_binding_id == row.id,
            InteractiveToolRequest.job_id == job.id,
            InteractiveToolRequest.status == "QUEUED",
        )
        .order_by(InteractiveToolRequest.created_at)
        .limit(1)
    )
    if not request:
        return False
    request_id, job_id, lease_token = request.id, job.id, job.lease_token
    short = await db.get(
        InteractiveExecutionGrant, request.execution_grant_id, populate_existing=True
    )
    try:
        await app.validate_execution_record(db, row, short)
        if (
            short.binding_epoch != request.binding_epoch
            or short.claim_identity != request.claim_identity
        ):
            raise JobLeaseLost("queued request belongs to a stale owner")
    except (HTTPException, JobLeaseLost, ConflictError):
        request = await db.get(
            InteractiveToolRequest, request_id, with_for_update=True, populate_existing=True
        )
        if request.status != "QUEUED":
            return False
        finished = await app.now(db)
        request.status, request.error_code = "REJECTED", "EXECUTION_AUTHORIZATION_ENDED"
        request.finished_at = finished
        await db.commit()
        return True
    claimed = await app.now(db)
    request = await db.get(
        InteractiveToolRequest, request_id, with_for_update=True, populate_existing=True
    )
    if request.status != "QUEUED":
        return False
    request.status, request.claimed_at = "RUNNING", claimed
    name, arguments, epoch, grant_id = (
        request.tool_name,
        request.arguments,
        request.binding_epoch,
        short.id,
    )
    await db.commit()
    result, error = None, None
    try:
        async with InteractiveFencedSession(
            bind=engine,
            expire_on_commit=False,
            job_id=job_id,
            lease_token=lease_token,
            test_run_id=row.test_run_id,
        ) as runtime:
            runtime.interactive_execution_id, runtime.execution_grant_id = row.id, grant_id
            runtime.domain_tool_name = name
            runtime.domain_tool_key = arguments.get("idempotency_key")
            tools = HarnessTools(runtime, row.binding_id, epoch, job_id, lease_token)
            result = await tools.dispatch(name, arguments)
    except (HTTPException, JobLeaseLost, ConflictError, ValueError, RuntimeError) as exc:
        # An interrupted call is queried/reconciled by exact durable identity;
        # never dispatch it again to learn whether a side effect happened.
        error = (
            "EXECUTION_AUTHORIZATION_ENDED"
            if isinstance(exc, (HTTPException, JobLeaseLost))
            else "TOOL_OUTCOME_UNKNOWN"
        )
    except BaseException:
        # Worker cancellation/crash must leave an explicit uncertain delivery.
        await record_result(request_id, job_id, lease_token, None, "WORKER_INTERRUPTED")
        raise
    await record_result(request_id, job_id, lease_token, result, error)
    return True


async def record_result(request_id, job_id, lease_token, result, error):
    async with AsyncSessionLocal() as ledger:
        request = await ledger.get(InteractiveToolRequest, request_id)
        if request is None:
            return
        row = await ledger.get(InteractiveExecutionBinding, request.interactive_binding_id)
        from hypertest.application.bindings import get_run_binding

        await get_run_binding(ledger, row.test_run_id, lock=True)
        job = await ledger.get(DurableJob, job_id, with_for_update=True, populate_existing=True)
        request = await ledger.get(
            InteractiveToolRequest, request_id, with_for_update=True, populate_existing=True
        )
        clock = await app.now(ledger)
        # Stale owner cannot publish a transport result after lease replacement.
        # The exact canonical RunToolCall remains queryable by the new owner.
        if (
            not request
            or request.status != "RUNNING"
            or not job
            or job.status != JobStatus.RUNNING
            or job.lease_token != lease_token
            or not job.lease_expires_at
            or job.lease_expires_at <= clock
        ):
            return
        if result is not None:
            request.status, request.result = "SUCCEEDED", result
        else:
            call = await ledger.scalar(
                select(RunToolCall).where(
                    RunToolCall.binding_id
                    == (
                        await ledger.get(
                            InteractiveExecutionBinding, request.interactive_binding_id
                        )
                    ).binding_id,
                    RunToolCall.idempotency_key == request.idempotency_key,
                    RunToolCall.tool_name == request.tool_name,
                    RunToolCall.input_sha256 == request.input_digest,
                )
            )
            if call and call.status in {"SUCCEEDED", "FAILED"} and call.result is not None:
                request.status, request.result = (
                    ("SUCCEEDED" if call.status == "SUCCEEDED" else "REJECTED"),
                    call.result,
                )
            else:
                request.status = "UNKNOWN" if call or request.claimed_at else "REJECTED"
            request.error_code = None if request.status == "SUCCEEDED" else error
        request.finished_at = clock
        await ledger.commit()
