from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.api.schemas import (
    MissionCreate,
    PolicySnapshotCreate,
    ProjectCreate,
    SourceSnapshotCreate,
)
from hypertest.api.schemas import TestRunCreate as RunCreate
from hypertest.application.coverage import get_test_run_coverage
from hypertest.application.planner import plan_next_mission
from hypertest.application.runtime import execute_mission
from hypertest.application.services import (
    canonical_json_sha256,
    create_mission,
    create_policy_snapshot,
    create_project,
    create_source_snapshot,
    create_test_run,
)
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    ProposalStatus,
    RiskLifecycle,
)
from hypertest.domain.enums import (
    TestCaseLifecycle as CaseLifecycle,
)
from hypertest.domain.enums import (
    TestCaseType as CaseType,
)
from hypertest.domain.models import (
    AuditEvent,
    MissionProposal,
    OutboxEvent,
    Requirement,
    RequirementRisk,
    Risk,
    RiskTestCase,
)
from hypertest.domain.models import (
    TestCase as CanonicalTestCase,
)
from hypertest.domain.models import (
    TestRun as CanonicalTestRun,
)


class ProposalHarness:
    """A provider-independent agent producing proposals, never canonical writes."""

    def __init__(self, proposals: list[dict[str, Any]]) -> None:
        self.proposals = proposals
        self.contract: dict[str, Any] | None = None

    async def create_session(self, workspace: str) -> AgentSession:
        return AgentSession(id=public_key("AS"), provider="fake")

    async def execute(
        self, session: AgentSession, mission: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        self.contract = mission
        yield AgentEvent(
            type="RESULT_SUBMITTED",
            payload={
                "protocol": "hypertest.tmp/v1alpha1",
                "mission_id": mission["mission_id"],
                "status": "COMPLETED",
                "summary": "Canonical state changes proposed for verification",
                "proposals": self.proposals,
            },
        )

    async def interrupt(self, session: AgentSession) -> None:
        return None

    async def close(self, session: AgentSession) -> None:
        return None


async def create_run(session: AsyncSession, project_id: UUID | None = None) -> CanonicalTestRun:
    suffix = public_key("IT").replace("-", "")[-12:]
    if project_id is None:
        project = await create_project(
            session,
            ProjectCreate(key=f"DESIGN_{suffix}", name="Canonical Test Design Integration"),
        )
        project_id = project.id
    snapshot = await create_source_snapshot(
        session,
        project_id,
        SourceSnapshotCreate(
            repository_url="https://example.invalid/test-design.git",
            commit_sha=suffix,
            prd_sha256="a" * 64,
            configuration_sha256="b" * 64,
        ),
    )
    policy = await create_policy_snapshot(
        session,
        PolicySnapshotCreate(
            project_id=project_id,
            policy_version="test-design-baseline-v1",
            content_sha256=canonical_json_sha256({}),
        ),
    )
    return await create_test_run(
        session,
        RunCreate(
            project_id=project_id,
            source_snapshot_id=snapshot.id,
            policy_snapshot_id=policy.id,
        ),
    )


def requirement_proposal() -> dict[str, Any]:
    return {
        "proposal_type": "REQUIREMENT",
        "operation": "CREATE",
        "idempotency_key": "checkout.submit:v1",
        "object_payload": {
            "logical_key": "checkout.submit",
            "title": "Submit checkout exactly once",
            "description": "A valid checkout request creates exactly one order.",
            "requirement_type": "FUNCTIONAL",
            "priority": "P0",
            "source_type": "PRD",
            "source_ref": "PRD#checkout",
            "confidence": 0.99,
        },
    }


def risk_proposal(requirement_key: str) -> dict[str, Any]:
    return {
        "proposal_type": "RISK",
        "operation": "CREATE",
        "idempotency_key": "checkout.duplicate-order:v1",
        "object_payload": {
            "requirement_keys": [requirement_key],
            "category": "CONCURRENCY",
            "title": "Concurrent checkout creates duplicate orders",
            "description": "Concurrent requests can race past the checkout idempotency check.",
            "severity": "HIGH",
            "probability": "MEDIUM",
            "rationale": "Order creation has an externally visible side effect.",
            "confidence": 0.95,
        },
    }


def case_proposal(
    risk_key: str,
    *,
    proposal_key: str = "checkout.functional:v1",
    test_type: str = "FUNCTIONAL",
) -> dict[str, Any]:
    return {
        "proposal_type": "TEST_CASE",
        "operation": "CREATE",
        "idempotency_key": proposal_key,
        "object_payload": {
            "risk_keys": [risk_key],
            "title": f"Verify {test_type.lower()} checkout idempotency",
            "description": "Submit the same valid checkout twice and inspect persisted orders.",
            "test_type": test_type,
            "priority": "P0",
            "preconditions": ["A customer has a nonempty basket."],
            "expected_result": "Exactly one order exists for the checkout idempotency key.",
            "confidence": 0.96,
        },
    }


async def identify_risk(session: AsyncSession, test_run: CanonicalTestRun) -> Risk:
    requirements_plan = await plan_next_mission(session, test_run.id)
    assert requirements_plan.mission is not None
    requirements = await execute_mission(
        session,
        requirements_plan.mission.id,
        workspace=".",
        harness=ProposalHarness([requirement_proposal()]),
    )
    risks_plan = await plan_next_mission(session, test_run.id)
    assert risks_plan.mission is not None
    risks = await execute_mission(
        session,
        risks_plan.mission.id,
        workspace=".",
        harness=ProposalHarness([risk_proposal(requirements.requirements[0].key)]),
    )
    return risks.risks[0]


async def case_count(session: AsyncSession, test_run: CanonicalTestRun) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(CanonicalTestCase)
        .where(CanonicalTestCase.source_snapshot_id == test_run.source_snapshot_id)
    )


@pytest.mark.asyncio
async def test_continuous_planner_loop_commits_relational_test_design() -> None:
    """Exercise the full loop against PostgreSQL, including partial dimension progress."""
    async with AsyncSessionLocal() as session:
        assert session.bind is not None and session.bind.dialect.name == "postgresql"
        test_run = await create_run(session)
        first_plan = await plan_next_mission(session, test_run.id)
        assert first_plan.reason == "REQUIREMENTS_MISSING"
        assert first_plan.mission is not None
        assert first_plan.mission.mission_type is MissionType.ANALYZE_REQUIREMENTS
        repeated_plan = await plan_next_mission(session, test_run.id)
        assert repeated_plan.mission is not None
        assert repeated_plan.mission.id == first_plan.mission.id

        requirements = await execute_mission(
            session,
            first_plan.mission.id,
            workspace=".",
            harness=ProposalHarness([requirement_proposal()]),
        )
        assert len(requirements.requirements) == 1
        requirement = requirements.requirements[0]
        risk_plan = await plan_next_mission(session, test_run.id)
        assert risk_plan.reason == "RISK_COVERAGE_GAP"
        assert risk_plan.mission is not None
        assert risk_plan.mission.mission_type is MissionType.ANALYZE_RISKS
        risks = await execute_mission(
            session,
            risk_plan.mission.id,
            workspace=".",
            harness=ProposalHarness([risk_proposal(requirement.key)]),
        )
        assert len(risks.risks) == 1
        risk = risks.risks[0]
        assert await session.get(RequirementRisk, (requirement.id, risk.id)) is not None

        design_plan = await plan_next_mission(session, test_run.id)
        assert design_plan.reason == "TEST_DESIGN_COVERAGE_GAP"
        assert design_plan.mission is not None
        assert design_plan.mission.mission_type is MissionType.DESIGN_TESTS
        assert design_plan.mission.status is MissionStatus.READY
        context_risk = design_plan.mission.spec["context"]["risks"][0]
        assert context_risk["key"] == risk.key
        assert context_risk["description"] == risk.description
        assert context_risk["category"] == "CONCURRENCY"
        repeated_design = await plan_next_mission(session, test_run.id)
        assert repeated_design.mission is not None
        assert repeated_design.mission.id == design_plan.mission.id

        functional = case_proposal(risk.key)
        duplicate = deepcopy(functional)
        duplicate["idempotency_key"] = "checkout.functional:duplicate"
        duplicate["object_payload"]["description"] = (
            " Submit  the same valid checkout twice\n and inspect persisted orders. "
        )
        duplicate["object_payload"]["risk_keys"] = [risk.key, risk.key]
        harness = ProposalHarness([functional, duplicate])
        execution = await execute_mission(
            session, design_plan.mission.id, workspace=".", harness=harness
        )
        assert execution.mission.status is MissionStatus.COMPLETED
        assert execution.attempt.status is MissionAttemptStatus.ACCEPTED
        assert len(execution.proposals) == 2
        assert {proposal.status for proposal in execution.proposals} == {ProposalStatus.ACCEPTED}
        assert len({case.id for case in execution.test_cases}) == 1
        functional_case = execution.test_cases[0]
        assert functional_case.source_snapshot_id == test_run.source_snapshot_id
        assert functional_case.project_id == test_run.project_id
        assert functional_case.test_type is CaseType.FUNCTIONAL
        assert functional_case.lifecycle_status is CaseLifecycle.ACTIVE
        assert functional_case.preconditions == functional["object_payload"]["preconditions"]
        assert functional_case.expected_result == functional["object_payload"]["expected_result"]
        assert len(functional_case.case_fingerprint) == 64
        assert functional_case.created_at is not None
        assert functional_case.updated_at is not None
        assert {p.accepted_entity_id for p in execution.proposals} == {functional_case.id}
        assert harness.contract is not None
        assert harness.contract["context"]["risks"][0]["key"] == risk.key
        assert await session.get(RiskTestCase, (risk.id, functional_case.id)) is not None
        assert await case_count(session, test_run) == 1

        partial_plan = await plan_next_mission(session, test_run.id)
        assert partial_plan.reason == "TEST_DESIGN_COVERAGE_GAP"
        assert partial_plan.mission is not None
        assert partial_plan.mission.id != design_plan.mission.id
        assert partial_plan.mission.mission_type is MissionType.DESIGN_TESTS
        repeated_partial_plan = await plan_next_mission(session, test_run.id)
        assert repeated_partial_plan.mission is not None
        assert repeated_partial_plan.mission.id == partial_plan.mission.id

        concurrency = await execute_mission(
            session,
            partial_plan.mission.id,
            workspace=".",
            harness=ProposalHarness(
                [
                    case_proposal(
                        risk.key, proposal_key="checkout.concurrent:v1", test_type="CONCURRENCY"
                    )
                ]
            ),
        )
        assert concurrency.attempt.status is MissionAttemptStatus.ACCEPTED
        assert len(concurrency.test_cases) == 1
        concurrency_case = concurrency.test_cases[0]
        assert concurrency_case.test_type is CaseType.CONCURRENCY
        assert concurrency_case.id != functional_case.id
        assert await case_count(session, test_run) == 2

        complete = await plan_next_mission(session, test_run.id)
        assert complete.reason == "IMPLEMENTATION_COVERAGE_GAP"
        assert complete.mission is not None
        assert complete.mission.mission_type is MissionType.IMPLEMENT_TESTS
        coverage = await get_test_run_coverage(session, test_run.id)
        assert coverage.requirement_count == 1
        assert coverage.risk_count == 1
        assert coverage.test_case_count == 2
        assert coverage.risk_identification_coverage == 1.0
        assert coverage.risk_test_coverage == 1.0
        assert coverage.risks[0].complete
        assert coverage.risks[0].missing_dimensions == []

        recheck_payload = MissionCreate(
            mission_type=MissionType.DESIGN_TESTS,
            objective="Confirm canonical test cases are deduplicated across missions",
            spec={"context": {"risks": [{"key": risk.key}]}},
            idempotency_key=f"{test_run.key}:DESIGN_TESTS:RECHECK",
        )
        recheck = await create_mission(session, test_run.id, recheck_payload)
        same_recheck = await create_mission(session, test_run.id, recheck_payload)
        assert same_recheck.id == recheck.id
        duplicate["idempotency_key"] = "checkout.functional:recheck"
        duplicate["object_payload"]["title"] = "Another title for the same test intent"
        duplicate["object_payload"]["priority"] = "P1"
        deduplicated = await execute_mission(
            session, recheck.id, workspace=".", harness=ProposalHarness([duplicate])
        )
        assert deduplicated.test_cases[0].id == functional_case.id
        assert await case_count(session, test_run) == 2

        for case in (functional_case, concurrency_case):
            link = await session.get(RiskTestCase, (risk.id, case.id))
            assert link is not None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.entity_id == case.id, AuditEvent.action == "test_case.accepted"
                    )
                )
                == 1
            )

            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(
                        OutboxEvent.aggregate_id == case.id,
                        OutboxEvent.event_type == "test_case.accepted",
                    )
                )
                == 1
            )

        # Historical designs remain canonical but do not satisfy current coverage.
        concurrency_case.lifecycle_status = CaseLifecycle.DEPRECATED
        await session.commit()
        coverage = await get_test_run_coverage(session, test_run.id)
        assert coverage.test_case_count == 1
        assert coverage.risk_test_coverage == 0.0
        assert coverage.risks[0].missing_dimensions == [CaseType.CONCURRENCY]
        reopened_gap = await plan_next_mission(session, test_run.id)
        assert reopened_gap.reason == "TEST_DESIGN_COVERAGE_GAP"
        assert reopened_gap.mission is not None
        assert reopened_gap.mission.status is MissionStatus.READY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_reference", ["missing", "other_snapshot", "other_project", "obsolete"]
)
async def test_invalid_risk_reference_rejects_entire_test_design_result(
    invalid_reference: str,
) -> None:
    async with AsyncSessionLocal() as session:
        test_run = await create_run(session)
        risk = await identify_risk(session, test_run)
        if invalid_reference == "missing":
            invalid_risk_key = public_key("RISK")
        elif invalid_reference == "obsolete":
            risk.lifecycle_status = RiskLifecycle.OBSOLETE
            await session.commit()
            invalid_risk_key = risk.key
        else:
            other_run = await create_run(
                session,
                project_id=test_run.project_id if invalid_reference == "other_snapshot" else None,
            )
            other_risk = await identify_risk(session, other_run)
            invalid_risk_key = other_risk.key

        mission = await create_mission(
            session,
            test_run.id,
            MissionCreate(
                mission_type=MissionType.DESIGN_TESTS,
                objective="Reject references outside active canonical snapshot state",
                spec={"context": {"source_snapshot": str(test_run.source_snapshot_id)}},
                idempotency_key=f"{test_run.key}:INVALID_REFERENCE",
            ),
        )
        result = await execute_mission(
            session,
            mission.id,
            workspace=".",
            harness=ProposalHarness(
                [
                    case_proposal(risk.key, proposal_key="first-valid"),
                    case_proposal(invalid_risk_key, proposal_key="second-invalid"),
                ]
            ),
        )
        assert result.attempt.status is MissionAttemptStatus.REJECTED
        assert result.mission.status is MissionStatus.RETRYING
        assert result.test_cases == []
        assert await case_count(session, test_run) == 0
        assert {proposal.status for proposal in result.proposals} == {ProposalStatus.REJECTED}
        assert any(
            error["code"] == "UNKNOWN_RISK"
            for proposal in result.proposals
            for error in proposal.validation_errors or []
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.test_run_id == test_run.id, AuditEvent.action == "test_case.accepted"
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RiskTestCase)
                .where(RiskTestCase.risk_id == risk.id)
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("test_type", "UNRECOGNIZED_CATEGORY"),
        ("risk_keys", []),
        ("expected_result", ""),
        ("preconditions", "an unstructured precondition"),
        ("confidence", 1.01),
    ],
)
async def test_invalid_test_case_schema_is_rejected_without_canonical_writes(
    field: str, value: Any
) -> None:
    async with AsyncSessionLocal() as session:
        test_run = await create_run(session)
        risk = await identify_risk(session, test_run)
        plan = await plan_next_mission(session, test_run.id)
        assert plan.mission is not None
        invalid = case_proposal(risk.key, proposal_key="invalid-schema")
        invalid["object_payload"][field] = value
        result = await execute_mission(
            session,
            plan.mission.id,
            workspace=".",
            harness=ProposalHarness([case_proposal(risk.key), invalid]),
        )
        assert result.attempt.status is MissionAttemptStatus.REJECTED
        assert result.test_cases == []
        assert await case_count(session, test_run) == 0
        assert any(
            error["code"] == "INVALID_TEST_CASE"
            for proposal in result.proposals
            for error in proposal.validation_errors or []
        )


@pytest.mark.asyncio
async def test_duplicate_proposal_keys_reject_safely_and_retry_with_new_keys() -> None:
    async with AsyncSessionLocal() as session:
        test_run = await create_run(session)
        risk = await identify_risk(session, test_run)
        plan = await plan_next_mission(session, test_run.id)
        assert plan.mission is not None
        valid = case_proposal(risk.key, proposal_key="valid-rejected-batch")
        invalid = case_proposal(public_key("RISK"), proposal_key="invalid-rejected-batch")
        rejected = await execute_mission(
            session,
            plan.mission.id,
            workspace=".",
            harness=ProposalHarness([valid, invalid]),
        )
        assert rejected.attempt.status is MissionAttemptStatus.REJECTED
        original_proposal_ids = {proposal.id for proposal in rejected.proposals}
        duplicate_retry = await execute_mission(
            session, plan.mission.id, workspace=".", harness=ProposalHarness([valid])
        )
        assert duplicate_retry.attempt.status is MissionAttemptStatus.REJECTED
        assert duplicate_retry.attempt.attempt_no == 2
        assert (
            duplicate_retry.attempt.result_payload["proposals"][0]["idempotency_key"]
            == valid["idempotency_key"]
        )
        assert await case_count(session, test_run) == 0
        persisted = list(
            await session.scalars(
                select(MissionProposal).where(MissionProposal.mission_id == plan.mission.id)
            )
        )
        assert {proposal.id for proposal in persisted} == original_proposal_ids
        assert all(proposal.status is ProposalStatus.REJECTED for proposal in persisted)

        repeated_in_batch = case_proposal(risk.key, proposal_key="same-batch-key")
        rejected_batch = await execute_mission(
            session,
            plan.mission.id,
            workspace=".",
            harness=ProposalHarness([repeated_in_batch, deepcopy(repeated_in_batch)]),
        )
        assert rejected_batch.attempt.status is MissionAttemptStatus.REJECTED
        assert await case_count(session, test_run) == 0
        assert any(
            error["code"] == "PROPOSAL_IDEMPOTENCY_CONFLICT"
            for proposal in rejected_batch.proposals
            for error in proposal.validation_errors or []
        )

        valid["idempotency_key"] = "corrected-retry-key"
        accepted = await execute_mission(
            session, plan.mission.id, workspace=".", harness=ProposalHarness([valid])
        )
        assert accepted.attempt.status is MissionAttemptStatus.ACCEPTED
        assert accepted.attempt.attempt_no == 4
        assert accepted.mission.status is MissionStatus.COMPLETED
        assert await case_count(session, test_run) == 1


@pytest.mark.asyncio
async def test_planner_rejects_designs_that_do_not_close_any_requested_dimension() -> None:
    async with AsyncSessionLocal() as session:
        test_run = await create_run(session)
        risk = await identify_risk(session, test_run)
        initial = await plan_next_mission(session, test_run.id)
        assert initial.mission is not None
        await execute_mission(
            session,
            initial.mission.id,
            workspace=".",
            harness=ProposalHarness([case_proposal(risk.key)]),
        )
        partial = await plan_next_mission(session, test_run.id)
        assert partial.mission is not None
        repeated_intent = case_proposal(risk.key, proposal_key="functional-again")
        no_progress = await execute_mission(
            session,
            partial.mission.id,
            workspace=".",
            harness=ProposalHarness([repeated_intent]),
        )
        assert no_progress.attempt.status is MissionAttemptStatus.REJECTED
        assert await case_count(session, test_run) == 1
        assert any(
            error["code"] == "NO_COVERAGE_PROGRESS"
            for proposal in no_progress.proposals
            for error in proposal.validation_errors or []
        )
        pending = await plan_next_mission(session, test_run.id)
        assert pending.mission is not None
        assert pending.mission.id == partial.mission.id
        accepted = await execute_mission(
            session,
            partial.mission.id,
            workspace=".",
            harness=ProposalHarness(
                [
                    case_proposal(
                        risk.key, proposal_key="concurrency-after-retry", test_type="CONCURRENCY"
                    )
                ]
            ),
        )
        assert accepted.attempt.status is MissionAttemptStatus.ACCEPTED
        assert await case_count(session, test_run) == 2
        final = await plan_next_mission(session, test_run.id)
        assert final.reason == "IMPLEMENTATION_COVERAGE_GAP"
        assert final.mission is not None
        assert final.mission.mission_type is MissionType.IMPLEMENT_TESTS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pending_status", [MissionStatus.CREATED, MissionStatus.READY, MissionStatus.RETRYING]
)
async def test_planner_replaces_stale_pending_design_after_external_coverage_progress(
    pending_status: MissionStatus, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AsyncSessionLocal() as session:
        test_run = await create_run(session)
        risk_a = await identify_risk(session, test_run)
        # Simulate a plan still being assembled without thawing a READY contract.
        with monkeypatch.context() as patch:
            if pending_status is MissionStatus.CREATED:
                async def remain_created(session, mission):
                    return mission
                patch.setattr("hypertest.application.planner._mark_ready", remain_created)
            initial = await plan_next_mission(session, test_run.id)
        assert initial.mission is not None
        stale_mission = initial.mission
        assert stale_mission.spec["targets"]["risks"] == [risk_a.key]
        stale_mission.status = pending_status
        await session.commit()

        external_design = await create_mission(
            session,
            test_run.id,
            MissionCreate(
                mission_type=MissionType.DESIGN_TESTS,
                objective="Independent design work covers the original risk",
                spec={"context": {"risks": [{"key": risk_a.key}]}},
                idempotency_key=f"{test_run.key}:EXTERNAL_DESIGN_A",
                created_by="user",
            ),
        )
        completed_a = await execute_mission(
            session,
            external_design.id,
            workspace=".",
            harness=ProposalHarness(
                [
                    case_proposal(risk_a.key),
                    case_proposal(
                        risk_a.key, proposal_key="external-concurrency", test_type="CONCURRENCY"
                    ),
                ]
            ),
        )
        assert completed_a.attempt.status is MissionAttemptStatus.ACCEPTED
        coverage = await get_test_run_coverage(session, test_run.id)
        assert coverage.risks[0].complete

        requirement_key = await session.scalar(
            select(Requirement.key)
            .join(RequirementRisk, RequirementRisk.requirement_id == Requirement.id)
            .where(RequirementRisk.risk_id == risk_a.id)
        )
        assert requirement_key is not None
        external_analysis = await create_mission(
            session,
            test_run.id,
            MissionCreate(
                mission_type=MissionType.ANALYZE_RISKS,
                objective="Independent analysis identifies an additional security risk",
                spec={"context": {"requirements": [{"key": requirement_key}]}},
                idempotency_key=f"{test_run.key}:EXTERNAL_RISK_B",
                created_by="user",
            ),
        )
        proposal_b = risk_proposal(requirement_key)
        proposal_b["idempotency_key"] = "checkout.unauthorized-order:v1"
        proposal_b["object_payload"].update(
            category="SECURITY",
            title="Unauthorized checkout creates an order",
            description="An unauthenticated caller may submit another customer's checkout.",
        )
        identified_b = await execute_mission(
            session,
            external_analysis.id,
            workspace=".",
            harness=ProposalHarness([proposal_b]),
        )
        risk_b = identified_b.risks[0]
        replacement = await plan_next_mission(session, test_run.id)
        assert replacement.reason == "TEST_DESIGN_COVERAGE_GAP"
        assert replacement.mission is not None
        assert replacement.mission.id != stale_mission.id
        assert replacement.mission.spec["targets"]["risks"] == [risk_b.key]
        assert replacement.mission.status is MissionStatus.READY
        await session.refresh(stale_mission)
        assert stale_mission.status is MissionStatus.CANCELLED
        assert stale_mission.cancelled_at is not None
        repeated = await plan_next_mission(session, test_run.id)
        assert repeated.mission is not None
        assert repeated.mission.id == replacement.mission.id


@pytest.mark.asyncio
async def test_risk_test_case_association_has_real_postgresql_foreign_keys() -> None:
    async with AsyncSessionLocal() as session:
        test_run = await create_run(session)
        risk = await identify_risk(session, test_run)
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(RiskTestCase(risk_id=risk.id, test_case_id=uuid7()))
                await session.flush()
