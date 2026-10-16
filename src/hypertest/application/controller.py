"""Bounded user-triggered control-plane cycle; the Planner owns stage decisions."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.agent.base import AgentHarness
from hypertest.application.executions import execute_test_run
from hypertest.application.gate import evaluate_gate
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import execute_mission
from hypertest.application.services import ConflictError, canonical_json_sha256, get_test_run
from hypertest.domain.enums import ExecutionPurpose, MissionAttemptStatus, MissionStatus
from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob
from hypertest.domain.models import TestExecution, TestImplementation, TestRun


async def _guard_operation_owner(session: AsyncSession, run_id: UUID) -> None:
    # The compatibility HTTP controller can span several owning-service commits.
    # Recheck admission after planning, under the same aggregate lock used by
    # the next reservation, so it cannot launch work belonging to a queued job.
    await session.scalar(select(TestRun.id).where(TestRun.id == run_id).with_for_update())
    active = await session.scalar(select(DurableJob.id).where(
        DurableJob.test_run_id == run_id, DurableJob.status.in_(ACTIVE_JOB_STATUSES),
    ))
    if active is not None and active != getattr(session, "job_id", None):
        raise ConflictError("test run has active background work; use its task controls")


async def advance_run(
    session: AsyncSession,
    run_id: UUID,
    *,
    workspace: str,
    backend: str = "docker",
    timeout_seconds: int = 300,
    max_steps: int = 12,
    harness: AgentHarness | None = None,
) -> dict:
    """Run concrete missions/executions until a verdict, interruption, or step limit.

    Every completed step is already persisted by its owning service. Failures are
    visible through Attempts/Executions; no synthetic agent output is supplied.
    Harness injection exists only for integration tests, never in the HTTP schema.
    """
    run = await get_test_run(session, run_id)
    steps: list[dict[str, str]] = []
    for _ in range(max_steps):
        await _guard_operation_owner(session, run_id)
        planned = await plan_next_mission(session, run_id)
        await _guard_operation_owner(session, run_id)
        if planned.mission is not None:
            mission = planned.mission
            if mission.status not in {
                MissionStatus.CREATED,
                MissionStatus.READY,
                MissionStatus.RETRYING,
            }:
                return {
                    "reason": "MISSION_IN_PROGRESS",
                    "steps": steps,
                    "mission_id": str(mission.id),
                }
            result = await execute_mission(
                session, mission.id, workspace=workspace, harness=harness
            )
            steps.append(
                {
                    "action": "mission",
                    "id": str(result.mission.id),
                    "key": result.mission.key,
                    "status": result.mission.status.value,
                }
            )
            if result.attempt.status is not MissionAttemptStatus.ACCEPTED:
                return {"reason": "MISSION_REJECTED", "steps": steps, "mission_id": str(mission.id)}
            continue
        if planned.reason == "EXECUTION_REQUIRED":
            assets = list(
                await session.scalars(
                    select(TestImplementation)
                    .where(
                        TestImplementation.source_snapshot_id == run.source_snapshot_id,
                        TestImplementation.project_id == run.project_id,
                    )
                    .order_by(TestImplementation.id)
                )
            )
            signature = canonical_json_sha256(
                {"assets": [[str(item.id), item.implementation_fingerprint] for item in assets]}
            )
            generation = await session.scalar(
                select(func.count())
                .select_from(TestExecution)
                .where(TestExecution.test_run_id == run_id)
            )
            execution = await execute_test_run(
                session,
                run_id,
                workspace=workspace,
                backend=backend,
                purpose=ExecutionPurpose.OFFICIAL,
                idempotency_key=f"cycle:{signature}:{generation}",
                timeout_seconds=timeout_seconds,
            )
            steps.append(
                {
                    "action": "execution",
                    "id": str(execution.id),
                    "key": execution.key,
                    "status": execution.status.value,
                }
            )
            continue
        if planned.reason == "VERDICT_REQUIRED":
            verdict = await evaluate_gate(session, run_id, finalize=True)
            steps.append(
                {
                    "action": "verdict",
                    "id": str(verdict.id),
                    "key": verdict.key,
                    "status": verdict.status.value,
                }
            )
            return {"reason": "VERDICT_FINALIZED", "steps": steps, "verdict_id": str(verdict.id)}
        return {"reason": planned.reason, "steps": steps}
    return {"reason": "STEP_LIMIT_REACHED", "steps": steps}
