"""Loss-tolerant, lease-fenced operational activity without transcript content."""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hypertest.application.services import ConflictError, NotFoundError
from hypertest.common.ids import uuid7
from hypertest.domain.activity import ActivityKind, ActivitySource, MissionActivityEvent
from hypertest.domain.enums import AgentSessionStatus, MissionAttemptStatus, MissionStatus
from hypertest.domain.enums import TestRunStatus as RunStatus
from hypertest.domain.jobs import DurableJob, JobStatus
from hypertest.domain.models import AgentSessionRecord, Mission, MissionAttempt, TestRun

RETENTION = 200
WINDOW_SECONDS = 2
MAX_COUNT = 2_147_483_647
_WRITERS: set[asyncio.Task] = set()
PROVIDER_KINDS = {ActivityKind.SIGNAL_RECEIVED, ActivityKind.TURN_STARTED, ActivityKind.TURN_COMPLETED,
                  ActivityKind.MODEL_ACTIVITY, ActivityKind.TOOL_STARTED, ActivityKind.TOOL_COMPLETED,
                  ActivityKind.FILE_ACTIVITY, ActivityKind.ERROR}
CONTROL_KINDS = {ActivityKind.MISSION_STARTED, ActivityKind.RESUMED, ActivityKind.RESULT_SUBMITTED,
                 ActivityKind.MISSION_FINISHED, ActivityKind.ERROR}


def safe_pair(source: ActivitySource, kind: ActivityKind) -> bool:
    return ((source is ActivitySource.PROVIDER and kind in PROVIDER_KINDS)
            or (source is ActivitySource.CONTROL_PLANE and kind in CONTROL_KINDS))


@dataclass(frozen=True, slots=True)
class ActivityOwner:
    run_id: UUID
    job_id: UUID
    mission_id: UUID
    attempt_id: UUID
    agent_session_id: UUID
    lease_token: UUID


async def persist_activity_batch(
    factory: async_sessionmaker[AsyncSession], owner: ActivityOwner,
    counts: dict[tuple[ActivitySource, ActivityKind], int],
) -> bool:
    """One short transaction, never holding locks across provider I/O.

    Caller bounds time/pool waits. All failures are lossy operational telemetry;
    no canonical entity, heartbeat, lease or lifecycle is changed here.
    """
    if not counts:
        return True
    async with factory() as session:
        await session.execute(text("SET LOCAL statement_timeout = '400ms'"))
        await session.execute(text("SET LOCAL lock_timeout = '50ms'"))
        await session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '800ms'"))
        run = await session.scalar(select(TestRun).where(TestRun.id == owner.run_id)
                                   .with_for_update(nowait=True))
        job = await session.scalar(select(DurableJob).where(DurableJob.id == owner.job_id)
                                   .with_for_update(nowait=True))
        now = await session.scalar(select(func.clock_timestamp()))
        if (run is None or run.status in {RunStatus.CANCELLED, RunStatus.COMPLETED, RunStatus.BLOCKED}
                or job is None or job.test_run_id != owner.run_id
                or job.status is not JobStatus.RUNNING or job.lease_token != owner.lease_token
                or job.lease_expires_at is None or job.lease_expires_at <= now):
            return False
        attempt = await session.scalar(select(MissionAttempt).where(MissionAttempt.id == owner.attempt_id)
                                       .with_for_update(nowait=True))
        mission = await session.get(Mission, owner.mission_id)
        agent = await session.get(AgentSessionRecord, owner.agent_session_id)
        if (attempt is None or mission is None or agent is None
                or attempt.durable_job_id != job.id or attempt.mission_id != mission.id
                or mission.test_run_id != owner.run_id or mission.current_attempt_no != attempt.attempt_no
                or mission.status is not MissionStatus.RUNNING
                or attempt.status is not MissionAttemptStatus.RUNNING
                or attempt.agent_session_id != agent.id or agent.test_run_id != owner.run_id
                or agent.status is not AgentSessionStatus.RUNNING):
            return False
        window = int(now.timestamp()) // WINDOW_SECONDS
        for (source, kind), count in counts.items():
            if (not isinstance(source, ActivitySource) or not isinstance(kind, ActivityKind)
                    or not safe_pair(source, kind) or count <= 0):
                continue
            row = await session.scalar(select(MissionActivityEvent).where(
                MissionActivityEvent.attempt_id == owner.attempt_id,
                MissionActivityEvent.claim_no == job.attempts,
                MissionActivityEvent.window_id == window,
                MissionActivityEvent.source == source.value, MissionActivityEvent.kind == kind.value,
            ))
            if row is None:
                session.add(MissionActivityEvent(
                    id=uuid7(), test_run_id=owner.run_id, durable_job_id=job.id,
                    mission_id=mission.id, attempt_id=attempt.id, agent_session_id=agent.id,
                    claim_no=job.attempts, window_id=window, source=source.value, kind=kind.value,
                    count=min(count, MAX_COUNT), recorded_at=now, last_observed_at=now,
                ))
            else:
                row.count = min(row.count + count, MAX_COUNT)
                row.last_observed_at = now
        await session.flush()
        retained = list(await session.scalars(select(MissionActivityEvent.id).where(
            MissionActivityEvent.attempt_id == owner.attempt_id,
        ).order_by(MissionActivityEvent.recorded_at.desc(), MissionActivityEvent.id.desc()).limit(RETENTION)))
        removed = await session.execute(delete(MissionActivityEvent).where(
            MissionActivityEvent.attempt_id == owner.attempt_id,
            MissionActivityEvent.id.not_in(retained),
        ))
        if removed.rowcount and retained:
            earliest = await session.get(MissionActivityEvent, retained[-1])
            earliest.retention_truncated = True
        await session.flush()
        # Lock ownership does not stop time: repeat the DB-clock expiry check.
        if job.lease_expires_at <= await session.scalar(select(func.clock_timestamp())):
            await session.rollback()
            return False
        await session.commit()
        return True


class ActivityRecorder:
    """One bounded coalescer/task per owned provider turn; stdout never awaits DB."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], owner: ActivityOwner) -> None:
        self.factory, self.owner = factory, owner
        # The key space is fixed by the enums, independent of provider content.
        self.pending: Counter[tuple[ActivitySource, ActivityKind]] = Counter()
        self.stopping = asyncio.Event()
        self.task: asyncio.Task | None = None

    def start(self, *, resumed: bool = False) -> None:
        if len(_WRITERS) >= 4:
            # Even a cancellation-resistant driver must not create an unbounded
            # number of leftover telemetry tasks across successive turns.
            self.stopping.set()
            return
        self.record(ActivitySource.CONTROL_PLANE, ActivityKind.RESUMED if resumed else ActivityKind.MISSION_STARTED)
        self.task = asyncio.create_task(self._run())
        _WRITERS.add(self.task)
        def retired(task: asyncio.Task) -> None:
            _WRITERS.discard(task)
            if not task.cancelled():
                task.exception()
        self.task.add_done_callback(retired)

    def record(self, source: ActivitySource, kind: ActivityKind) -> None:
        if (not self.stopping.is_set() and isinstance(source, ActivitySource)
                and isinstance(kind, ActivityKind) and safe_pair(source, kind)):
            key = (source, kind)
            self.pending[key] = min(self.pending[key] + 1, MAX_COUNT)

    def observe(self, event_type: str, payload: dict) -> None:
        if not isinstance(event_type, str):
            return
        if event_type == "ACTIVITY":
            try:
                kind = ActivityKind(payload.get("activity_kind", "SIGNAL_RECEIVED"))
            except (TypeError, ValueError):
                kind = ActivityKind.SIGNAL_RECEIVED
            # Provider payloads cannot masquerade as a control-plane milestone.
            if kind in {ActivityKind.MISSION_STARTED, ActivityKind.RESUMED,
                        ActivityKind.RESULT_SUBMITTED, ActivityKind.MISSION_FINISHED}:
                kind = ActivityKind.SIGNAL_RECEIVED
            self.record(ActivitySource.PROVIDER, kind)
        elif event_type in {"RESULT_SUBMITTED", "ERROR"}:
            self.record(ActivitySource.CONTROL_PLANE, ActivityKind(event_type))
        elif event_type in {"TOOL_STARTED", "TOOL_COMPLETED", "TURN_STARTED", "TURN_COMPLETED"}:
            self.record(ActivitySource.PROVIDER, ActivityKind(event_type))
        elif event_type in {"FILE_CHANGED", "PROGRESS", "WARNING"}:
            self.record(ActivitySource.PROVIDER, ActivityKind.FILE_ACTIVITY if event_type == "FILE_CHANGED"
                        else ActivityKind.SIGNAL_RECEIVED)

    async def _flush(self) -> None:
        batch = dict(self.pending)
        self.pending.clear()
        if not batch:
            return
        try:
            await asyncio.wait_for(persist_activity_batch(self.factory, self.owner, batch), timeout=0.75)
        except Exception:
            # Drop this batch rather than replaying old signals with a fresh DB
            # timestamp or leaking database/provider errors into product logs.
            pass

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=WINDOW_SECONDS)
            except TimeoutError:
                pass
            await self._flush()
            if self.stopping.is_set() and not self.pending:
                return

    async def close(self) -> None:
        self.stopping.set()
        if self.task is None:
            return
        try:
            done, _ = await asyncio.wait({self.task}, timeout=1.25)
        except asyncio.CancelledError:
            self.task.cancel()
            # Preserve caller cancellation (Worker shutdown/cancel). Telemetry
            # cleanup may not convert it into successful canonical acceptance.
            await asyncio.wait({self.task}, timeout=0.1)
            raise
        if not done:
            self.task.cancel()
            await asyncio.wait({self.task}, timeout=0.1)
        if self.task.done() and not self.task.cancelled():
            self.task.exception()  # retrieve optional writer failures, never expose them


async def read_job_activity(session: AsyncSession, job_id: UUID, *, limit: int = 30, before: UUID | None = None) -> dict:
    job = await session.get(DurableJob, job_id)
    if job is None:
        raise NotFoundError("job not found")
    now = await session.scalar(select(func.clock_timestamp()))
    query = select(MissionActivityEvent).where(MissionActivityEvent.durable_job_id == job_id)
    if before is not None:
        cursor = await session.scalar(select(MissionActivityEvent).where(
            MissionActivityEvent.id == before, MissionActivityEvent.durable_job_id == job_id,
        ))
        if cursor is None:
            raise ConflictError("Activity cursor expired")
        query = query.where(tuple_(MissionActivityEvent.recorded_at, MissionActivityEvent.id)
                            < tuple_(cursor.recorded_at, cursor.id))
    events = list(await session.scalars(query.order_by(
        MissionActivityEvent.recorded_at.desc(), MissionActivityEvent.id.desc(),
    ).limit(limit + 1)))
    next_cursor = str(events[limit - 1].id) if len(events) > limit else None
    events = events[:limit]
    active = (await session.execute(select(MissionAttempt, Mission).join(Mission).where(
        MissionAttempt.durable_job_id == job.id, Mission.test_run_id == job.test_run_id,
        MissionAttempt.status == MissionAttemptStatus.RUNNING,
        Mission.status == MissionStatus.RUNNING,
    ).order_by(MissionAttempt.started_at.desc(), MissionAttempt.id.desc()).limit(1))).first()
    phase = {JobStatus.QUEUED: "QUEUED", JobStatus.WAITING_INPUT: "WAITING_INPUT",
             JobStatus.CANCEL_REQUESTED: "CANCEL_REQUESTED"}.get(job.status, "PLATFORM_WORK")
    if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED}:
        phase = "TERMINAL"
    current = None
    turn_started = last_signal = None
    run_status = await session.scalar(select(TestRun.status).where(TestRun.id == job.test_run_id))
    if run_status is RunStatus.CANCELLED and job.status is JobStatus.RUNNING:
        phase = "CANCEL_REQUESTED"
    if (active and job.status is JobStatus.RUNNING
            and run_status not in {RunStatus.CANCELLED, RunStatus.COMPLETED, RunStatus.BLOCKED}):
        attempt, mission = active
        current = {"mission_id": mission.id, "mission_key": mission.key, "mission_type": mission.mission_type.value,
                   "attempt_id": attempt.id, "attempt_no": attempt.attempt_no, "agent_session_id": attempt.agent_session_id}
        scope = (MissionActivityEvent.attempt_id == attempt.id, MissionActivityEvent.claim_no == job.attempts)
        last_signal = await session.scalar(select(func.max(MissionActivityEvent.last_observed_at)).where(
            *scope, MissionActivityEvent.source == ActivitySource.PROVIDER.value,
        ))
        turn_started = await session.scalar(select(func.min(MissionActivityEvent.recorded_at)).where(
            *scope, MissionActivityEvent.source == ActivitySource.CONTROL_PLANE.value,
            MissionActivityEvent.kind.in_([ActivityKind.MISSION_STARTED.value, ActivityKind.RESUMED.value]),
        ))
        submitted = await session.scalar(select(MissionActivityEvent.id).where(
            *scope, MissionActivityEvent.source == ActivitySource.CONTROL_PLANE.value,
            MissionActivityEvent.kind == ActivityKind.RESULT_SUBMITTED.value,
        ).limit(1))
        phase = "RESULT_VALIDATION" if submitted else "AGENT_RUNNING"
    return {
        "job_id": job.id, "server_time": now,
        "summary": {"phase": phase, "current_attempt": current, "turn_started_at": turn_started,
                    "last_provider_signal_at": last_signal,
                    "provider_signal_age_seconds": max(0, (now - last_signal).total_seconds()) if last_signal else None,
                    "worker_heartbeat_at": job.heartbeat_at,
                    "worker_heartbeat_age_seconds": max(0, (now - job.heartbeat_at).total_seconds()) if job.heartbeat_at else None},
        "items": [{"id": e.id, "kind": e.kind, "source": e.source, "recorded_at": e.recorded_at,
                   "last_observed_at": e.last_observed_at, "count": e.count, "mission_id": e.mission_id,
                   "attempt_id": e.attempt_id, "agent_session_id": e.agent_session_id} for e in events],
        "next_cursor": next_cursor, "retention_per_attempt": RETENTION, "window_seconds": WINDOW_SECONDS,
        "truncated": bool(await session.scalar(select(MissionActivityEvent.id).where(
            MissionActivityEvent.durable_job_id == job.id, MissionActivityEvent.retention_truncated.is_(True),
        ).limit(1))),
    }
