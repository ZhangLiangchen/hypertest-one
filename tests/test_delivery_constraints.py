"""Real PostgreSQL checks for durable canonical delivery invariants."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.common.ids import public_key
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionPurpose,
    ExecutionStatus,
    FindingClassification,
    FindingSeverity,
    FindingStatus,
    TrustLevel,
    VerdictDecision,
    VerdictStatus,
)
from hypertest.domain.models import (
    Evidence,
    Finding,
    PolicySnapshot,
    Project,
    SourceSnapshot,
    Verdict,
)
from hypertest.domain.models import TestExecution as CanonicalExecution
from hypertest.domain.models import TestRun as CanonicalRun


async def delivery_run(session: AsyncSession) -> tuple[CanonicalRun, PolicySnapshot]:
    project = Project(key=public_key("CONSTRAINT"), name="Canonical delivery constraints")
    session.add(project)
    await session.flush()
    snapshot = SourceSnapshot(
        project_id=project.id,
        repository_url="https://example.invalid/constraints",
        commit_sha="a" * 40,
        prd_sha256="b" * 64,
        configuration_sha256="c" * 64,
        source_fingerprint="d" * 64,
    )
    policy = PolicySnapshot(
        project_id=project.id,
        policy_name="constraints",
        policy_version="1",
        content_sha256="e" * 64,
    )
    session.add_all([snapshot, policy])
    await session.flush()
    run = CanonicalRun(
        key=public_key("TR"),
        project_id=project.id,
        source_snapshot_id=snapshot.id,
        policy_snapshot_id=policy.id,
        trigger_type="MANUAL",
        created_by="constraint-test",
    )
    session.add(run)
    await session.commit()
    return run, policy


async def execution_for(session: AsyncSession, run: CanonicalRun) -> CanonicalExecution:
    execution = CanonicalExecution(
        key=public_key("EX"),
        test_run_id=run.id,
        idempotency_key="constraint-execution",
        purpose=ExecutionPurpose.OFFICIAL,
        runner_backend="constraint-test",
        environment_id="postgres-integration",
        environment_fingerprint="f" * 64,
        source_commit="a" * 40,
        execution_spec_sha256="1" * 64,
        spec={"targets": ["tests/test_example.py"]},
    )
    session.add(execution)
    await session.commit()
    return execution


async def rejects_sql(
    session: AsyncSession, statement: str, parameters: dict[str, Any], message: str
) -> None:
    # A savepoint isolates the deliberately rejected SQL without erasing test history.
    with pytest.raises(DBAPIError, match=message):
        async with session.begin_nested():
            await session.execute(text(statement), parameters)


async def test_execution_input_identity_is_immutable_through_terminal_state() -> None:
    async with AsyncSessionLocal() as session:
        run, _ = await delivery_run(session)
        execution = await execution_for(session, run)
        await rejects_sql(
            session,
            "UPDATE test_executions SET source_commit=:value WHERE id=:id",
            {"value": "z" * 40, "id": execution.id},
            "execution input is immutable",
        )
        await rejects_sql(
            session,
            "UPDATE test_executions SET spec=CAST(:value AS json) WHERE id=:id",
            {"value": '{"targets":["tests/replaced.py"]}', "id": execution.id},
            "execution input is immutable",
        )
        execution.status = ExecutionStatus.RUNNING
        execution.started_at = datetime.now(UTC)
        await session.flush()
        execution.status = ExecutionStatus.COMPLETED
        execution.outcome = ExecutionOutcome.PASS
        execution.finished_at = datetime.now(UTC)
        execution.exit_code = 0
        await session.commit()
        await rejects_sql(
            session,
            "UPDATE test_executions SET idempotency_key=:value WHERE id=:id",
            {"value": "rewritten", "id": execution.id},
            "execution input is immutable",
        )
        await session.refresh(execution)
        assert execution.spec == {"targets": ["tests/test_example.py"]}
        assert execution.outcome is ExecutionOutcome.PASS


async def test_evidence_content_cannot_change_during_verification() -> None:
    async with AsyncSessionLocal() as session:
        run, _ = await delivery_run(session)
        execution = await execution_for(session, run)
        evidence = Evidence(
            key=public_key("EV"),
            test_run_id=run.id,
            execution_id=execution.id,
            evidence_type=EvidenceType.STDOUT,
            trust_level=TrustLevel.RUNNER,
            sha256="2" * 64,
            collector="constraint-test",
            source="runner",
            inline_summary="Original runner output",
        )
        session.add(evidence)
        await session.commit()
        for column, value in (
            ("sha256", "3" * 64),
            ("inline_summary", "Agent replacement output"),
            ("trust_level", "AGENT_REPORTED"),
        ):
            await rejects_sql(
                session,
                f"UPDATE evidence SET {column}=:value WHERE id=:id",
                {"value": value, "id": evidence.id},
                "evidence content is immutable",
            )
        evidence.status = EvidenceStatus.VERIFIED
        evidence.verified_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(evidence)
        assert evidence.status is EvidenceStatus.VERIFIED
        assert evidence.sha256 == "2" * 64
        assert evidence.inline_summary == "Original runner output"


async def test_final_verdict_preserves_decision_history_and_only_allows_revocation() -> None:
    async with AsyncSessionLocal() as session:
        run, policy = await delivery_run(session)
        verdict = Verdict(
            key=public_key("VER"),
            test_run_id=run.id,
            sequence_no=1,
            decision=VerdictDecision.BLOCKED,
            status=VerdictStatus.FINAL,
            reason="Execution evidence is incomplete",
            policy_snapshot_id=policy.id,
            state_snapshot_hash="4" * 64,
            evidence_manifest_sha256="5" * 64,
            issued_by_type="SYSTEM",
            finalized_at=datetime.now(UTC),
        )
        session.add(verdict)
        await session.commit()
        for column, value in (("reason", "Rewritten rationale"), ("decision", "PASS")):
            await rejects_sql(
                session,
                f"UPDATE verdicts SET {column}=:value WHERE id=:id",
                {"value": value, "id": verdict.id},
                "final verdict is append-only",
            )
        await rejects_sql(
            session,
            "DELETE FROM verdicts WHERE id=:id",
            {"id": verdict.id},
            "final verdict is append-only",
        )
        verdict.status = VerdictStatus.REVOKED
        verdict.revoked_at = datetime.now(UTC)
        await session.commit()
        await rejects_sql(
            session,
            "UPDATE verdicts SET reason=:value WHERE id=:id",
            {"value": "Rewritten after revocation", "id": verdict.id},
            "final verdict is append-only",
        )
        await session.refresh(verdict)
        assert verdict.status is VerdictStatus.REVOKED
        assert verdict.decision is VerdictDecision.BLOCKED
        assert verdict.reason == "Execution evidence is incomplete"
        assert verdict.revoked_at is not None


async def test_active_finding_fingerprint_deduplicates_without_erasing_resolved_history() -> None:
    async with AsyncSessionLocal() as session:
        run, _ = await delivery_run(session)
        fields = {
            "project_id": run.project_id,
            "test_run_id": run.id,
            "fingerprint": "6" * 64,
            "classification": FindingClassification.UNKNOWN,
            "severity": FindingSeverity.MINOR,
            "title": "Failure signature",
            "description": "Canonical finding deduplication",
            "reported_by_type": "SYSTEM",
        }
        original = Finding(key=public_key("FIND"), **fields)
        session.add(original)
        await session.commit()
        with pytest.raises(IntegrityError, match="uq_finding_active_fingerprint"):
            async with session.begin_nested():
                session.add(Finding(key=public_key("FIND"), **fields))
                await session.flush()
        original.status = FindingStatus.RESOLVED
        original.resolved_at = datetime.now(UTC)
        await session.flush()
        recurrence = Finding(key=public_key("FIND"), **fields)
        session.add(recurrence)
        await session.commit()
        history = list(
            await session.scalars(
                select(Finding).where(
                    Finding.project_id == run.project_id,
                    Finding.fingerprint == "6" * 64,
                )
            )
        )
        assert len(history) == 2
        assert {item.status for item in history} == {FindingStatus.NEW, FindingStatus.RESOLVED}
        assert original.id != recurrence.id
