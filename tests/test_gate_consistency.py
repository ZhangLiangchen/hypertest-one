"""A verdict's coverage decision and state hash must describe one canonical state."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from test_gate import _official, _seed
from test_test_design import risk_proposal

from hypertest.api.schemas import MissionCreate
from hypertest.api.schemas import TestRunCreate as RunCreate
from hypertest.application import gate
from hypertest.application.coverage import get_test_run_coverage
from hypertest.application.services import create_mission, create_test_run
from hypertest.application.verifier import verify_mission_result
from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionAttemptStatus, MissionStatus, MissionType, VerdictDecision
from hypertest.domain.models import Mission, MissionAttempt
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.protocol import MissionResultSubmission


@pytest.mark.asyncio
async def test_gate_serializes_cross_run_canonical_commits_for_shared_source_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Risk proposal in another run must not land between coverage and hashing."""
    async with AsyncSessionLocal() as setup:
        assert setup.bind is not None and setup.bind.dialect.name == "postgresql"
        run, requirement, _, case = await _seed(setup)
        await _official(setup, run, case)
        other_run = await create_test_run(setup, RunCreate(
            project_id=run.project_id, source_snapshot_id=run.source_snapshot_id,
            policy_snapshot_id=run.policy_snapshot_id,
        ))
        mission = await create_mission(setup, other_run.id, MissionCreate(
            mission_type=MissionType.ANALYZE_RISKS, objective="Analyze one additional risk.",
            spec={}, idempotency_key=public_key("GATE_CONSISTENCY"),
        ))
        mission.status = MissionStatus.RUNNING
        mission.current_attempt_no = 1
        attempt = MissionAttempt(
            mission_id=mission.id, attempt_no=1, status=MissionAttemptStatus.RUNNING,
        )
        setup.add(attempt)
        await setup.commit()
        run_id, other_run_id, mission_id, attempt_id = run.id, other_run.id, mission.id, attempt.id
        submission = MissionResultSubmission.model_validate({
            "protocol": "hypertest.tmp/v1alpha1", "mission_id": mission.key,
            "status": "COMPLETED", "summary": "An additional risk needs canonical coverage.",
            "proposals": [risk_proposal(requirement.key)],
        })

    coverage_read = asyncio.Event()
    allow_gate_snapshot = asyncio.Event()
    writer_started = asyncio.Event()
    pids: dict[str, int] = {}
    real_coverage = gate.get_test_run_coverage

    async def pause_after_coverage(session, test_run_id, *args, **kwargs):
        coverage = await real_coverage(session, test_run_id, *args, **kwargs)
        assert coverage.risk_test_coverage == 1
        coverage_read.set()
        await allow_gate_snapshot.wait()
        return coverage

    monkeypatch.setattr(gate, "get_test_run_coverage", pause_after_coverage)

    async def evaluate():
        async with AsyncSessionLocal() as session:
            pids["gate"] = await session.scalar(select(func.pg_backend_pid()))
            return await gate.evaluate_gate(session, run_id)

    async def propose_risk():
        async with AsyncSessionLocal() as session:
            pids["writer"] = await session.scalar(select(func.pg_backend_pid()))
            pending = await session.get(Mission, mission_id)
            current_attempt = await session.get(MissionAttempt, attempt_id)
            assert pending is not None and current_attempt is not None
            pending.test_run = await session.get(CanonicalRun, other_run_id)
            writer_started.set()
            return await verify_mission_result(session, pending, current_attempt, submission)

    gate_task = asyncio.create_task(evaluate())
    writer_task = None
    try:
        async with asyncio.timeout(10):
            await coverage_read.wait()
            writer_task = asyncio.create_task(propose_risk())
            await writer_started.wait()
            # Inspect actual PostgreSQL lock ownership instead of relying on sleeps
            # or mocking either canonical state or the proposal transaction.
            async with AsyncSessionLocal() as monitor:
                while True:
                    blockers = await monitor.scalar(select(func.pg_blocking_pids(pids["writer"])))
                    if pids["gate"] in blockers:
                        break
                    assert not writer_task.done(), "canonical commit bypassed the snapshot lock"
                    await asyncio.sleep(0.01)
            assert not writer_task.done()
            allow_gate_snapshot.set()
            first = await gate_task
            accepted = await writer_task
    finally:
        allow_gate_snapshot.set()
        for task in (gate_task, writer_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (gate_task, writer_task) if task is not None),
            return_exceptions=True,
        )

    assert first.decision is VerdictDecision.RELEASE_READY
    assert accepted.accepted and len(accepted.risks) == 1
    monkeypatch.setattr(gate, "get_test_run_coverage", real_coverage)
    async with AsyncSessionLocal() as session:
        coverage = await get_test_run_coverage(session, run_id)
        assert coverage.risk_count == 2
        assert coverage.risk_test_coverage == 0.5
        second = await gate.evaluate_gate(session, run_id)
        assert second.decision is VerdictDecision.BLOCKED
        assert second.id != first.id
        assert second.sequence_no == first.sequence_no + 1
        assert second.state_snapshot_hash != first.state_snapshot_hash
        assert "required test design dimensions are incomplete" in second.reason
        assert (await gate.evaluate_gate(session, run_id)).id == second.id
