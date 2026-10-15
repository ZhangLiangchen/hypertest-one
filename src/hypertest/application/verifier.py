from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.coverage import get_test_run_coverage
from hypertest.common.ids import public_key
from hypertest.domain.enums import (
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    ProposalOperation,
    ProposalStatus,
    ProposalType,
    RequirementLifecycle,
    RiskLifecycle,
    TestCaseLifecycle,
)
from hypertest.domain.models import (
    AuditEvent,
    Mission,
    MissionAttempt,
    MissionProposal,
    OutboxEvent,
    Requirement,
    RequirementRisk,
    Risk,
    RiskTestCase,
    TestCase,
    utcnow,
)
from hypertest.protocol import (
    MissionResultSubmission,
    RequirementProposalPayload,
    RiskProposalPayload,
    TestCaseProposalPayload,
)


@dataclass(slots=True)
class VerificationResult:
    accepted: bool
    proposals: list[MissionProposal]
    requirements: list[Requirement]
    risks: list[Risk]
    test_cases: list[TestCase]
    errors: list[dict[str, Any]]


def requirement_source_fingerprint(payload: RequirementProposalPayload) -> str:
    source_ref = (payload.source_ref or "").strip()
    description = " ".join(payload.description.split())
    raw = f"{source_ref}\n{description}".encode()
    return hashlib.sha256(raw).hexdigest()


def risk_fingerprint(payload: RiskProposalPayload) -> str:
    description = " ".join(payload.description.split())
    requirement_keys = "|".join(sorted(payload.requirement_keys))
    raw = f"{payload.category.value}\n{description}\n{requirement_keys}".encode()
    return hashlib.sha256(raw).hexdigest()


def case_fingerprint(
    payload: TestCaseProposalPayload,
    source_snapshot_id: UUID,
    risks: list[Risk],
) -> str:
    """Normalize test intent and canonical risk identities, never vendor session state."""

    normalized = {
        "source_snapshot_id": str(source_snapshot_id),
        "description": " ".join(payload.description.split()),
        "test_type": payload.test_type.value,
        "preconditions": [" ".join(value.split()) for value in payload.preconditions],
        "expected_result": " ".join(payload.expected_result.split()),
        "risk_fingerprints": sorted({risk.risk_fingerprint for risk in risks}),
    }
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _validation_error(code: str, message: str, proposal_index: int | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if proposal_index is not None:
        error["proposal_index"] = proposal_index
    return error


async def _reject_result(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    result: MissionResultSubmission,
    errors_by_index: dict[int, list[dict[str, Any]]],
    global_errors: list[dict[str, Any]],
) -> VerificationResult:
    proposals: list[MissionProposal] = []
    # The proposal key is mission-scoped, including rejected attempts. Preserve the
    # original row on replay; the new attempt's result_payload records the rejection.
    proposals_by_key = {
        proposal.idempotency_key: proposal
        for proposal in await session.scalars(
            select(MissionProposal).where(MissionProposal.mission_id == mission.id)
        )
    }
    for index, submission in enumerate(result.proposals):
        existing_proposal = proposals_by_key.get(submission.idempotency_key)
        if existing_proposal is not None:
            proposals.append(existing_proposal)
            continue
        proposal = MissionProposal(
            mission_id=mission.id,
            attempt_id=attempt.id,
            proposal_type=submission.proposal_type,
            operation=submission.operation,
            idempotency_key=submission.idempotency_key,
            object_payload=submission.object_payload,
            rationale=submission.rationale,
            confidence=submission.confidence,
            status=ProposalStatus.REJECTED,
            validation_errors=errors_by_index.get(index)
            or global_errors
            or [_validation_error("BATCH_REJECTED", "another proposal in this batch is invalid")],
            reviewed_at=utcnow(),
        )
        session.add(proposal)
        proposals.append(proposal)
        proposals_by_key[submission.idempotency_key] = proposal

    attempt.status = MissionAttemptStatus.REJECTED
    attempt.finished_at = utcnow()
    attempt.result_payload = result.model_dump(mode="json")
    errors = [*global_errors, *[error for group in errors_by_index.values() for error in group]]
    if errors:
        # Replayed keys preserve their original proposal rows, so the current
        # attempt must retain its own rejection reason for operators and retries.
        attempt.error_code = errors[0]["code"]
        attempt.error_message = "; ".join(dict.fromkeys(error["message"] for error in errors))
    mission.status = MissionStatus.RETRYING
    mission.row_version += 1
    await session.commit()
    for proposal in proposals:
        await session.refresh(proposal)
    return VerificationResult(
        accepted=False,
        proposals=proposals,
        requirements=[],
        risks=[],
        test_cases=[],
        errors=errors,
    )


async def _existing_proposal_keys(session: AsyncSession, mission: Mission) -> set[str]:
    return {
        value
        for value in await session.scalars(
            select(MissionProposal.idempotency_key).where(MissionProposal.mission_id == mission.id)
        )
    }


async def _validate_proposal_keys(
    session: AsyncSession,
    mission: Mission,
    result: MissionResultSubmission,
    errors_by_index: dict[int, list[dict[str, Any]]],
) -> None:
    existing_keys = await _existing_proposal_keys(session, mission)
    indexes_by_key: dict[str, list[int]] = {}
    for index, submission in enumerate(result.proposals):
        indexes_by_key.setdefault(submission.idempotency_key, []).append(index)
    for key, indexes in indexes_by_key.items():
        if key not in existing_keys and len(indexes) == 1:
            continue
        for index in indexes:
            errors_by_index.setdefault(index, []).append(
                _validation_error(
                    "PROPOSAL_IDEMPOTENCY_CONFLICT",
                    f"proposal key already exists or is repeated in the batch: {key}",
                    index,
                )
            )


async def _verify_requirements(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    result: MissionResultSubmission,
) -> VerificationResult:
    errors_by_index: dict[int, list[dict[str, Any]]] = {}
    validated_payloads: list[RequirementProposalPayload | None] = []

    for index, submission in enumerate(result.proposals):
        proposal_errors: list[dict[str, Any]] = []
        payload: RequirementProposalPayload | None = None
        if submission.proposal_type is not ProposalType.REQUIREMENT:
            proposal_errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_TYPE",
                    "ANALYZE_REQUIREMENTS accepts only REQUIREMENT proposals",
                    index,
                )
            )
        if submission.operation is not ProposalOperation.CREATE:
            proposal_errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_OPERATION",
                    "canonical requirement loop supports only CREATE",
                    index,
                )
            )
        try:
            payload = RequirementProposalPayload.model_validate(submission.object_payload)
        except ValidationError as exc:
            proposal_errors.append(_validation_error("INVALID_REQUIREMENT", str(exc), index))
        if proposal_errors:
            errors_by_index[index] = proposal_errors
        validated_payloads.append(payload)

    await _validate_proposal_keys(session, mission, result, errors_by_index)

    if errors_by_index:
        return await _reject_result(session, mission, attempt, result, errors_by_index, [])

    test_run = mission.test_run
    proposals: list[MissionProposal] = []
    requirements: list[Requirement] = []
    new_by_fingerprint: dict[str, Requirement] = {}

    try:
        mission.status = MissionStatus.VERIFYING
        attempt.status = MissionAttemptStatus.SUBMITTED
        attempt.submitted_at = attempt.submitted_at or utcnow()
        attempt.result_payload = result.model_dump(mode="json")

        for submission, payload in zip(result.proposals, validated_payloads, strict=True):
            assert payload is not None
            proposal = MissionProposal(
                mission_id=mission.id,
                attempt_id=attempt.id,
                proposal_type=submission.proposal_type,
                operation=submission.operation,
                idempotency_key=submission.idempotency_key,
                object_payload=submission.object_payload,
                rationale=submission.rationale,
                confidence=submission.confidence,
                status=ProposalStatus.VALIDATING,
            )
            session.add(proposal)
            proposals.append(proposal)

            fingerprint = requirement_source_fingerprint(payload)
            requirement = new_by_fingerprint.get(fingerprint)
            if requirement is None:
                requirement = await session.scalar(
                    select(Requirement).where(
                        Requirement.source_snapshot_id == test_run.source_snapshot_id,
                        Requirement.source_fingerprint == fingerprint,
                    )
                )
            if requirement is None:
                requirement = Requirement(
                    key=public_key("REQ"),
                    project_id=test_run.project_id,
                    source_snapshot_id=test_run.source_snapshot_id,
                    logical_key=payload.logical_key,
                    title=payload.title,
                    description=payload.description,
                    requirement_type=payload.requirement_type,
                    priority=payload.priority,
                    source_type=payload.source_type,
                    source_ref=payload.source_ref,
                    source_fingerprint=fingerprint,
                    confidence=payload.confidence,
                    lifecycle_status=RequirementLifecycle.ACTIVE,
                    created_by_type="AGENT",
                    created_by_ref=str(attempt.id),
                )
                session.add(requirement)
                await session.flush()
                new_by_fingerprint[fingerprint] = requirement
                session.add(
                    AuditEvent(
                        project_id=test_run.project_id,
                        test_run_id=test_run.id,
                        actor_type="AGENT",
                        actor_ref=str(attempt.id),
                        action="requirement.accepted",
                        entity_type="Requirement",
                        entity_id=requirement.id,
                        after_state={
                            "key": requirement.key,
                            "title": requirement.title,
                            "source_fingerprint": requirement.source_fingerprint,
                        },
                        event_metadata={
                            "mission_id": str(mission.id),
                            "proposal_idempotency_key": submission.idempotency_key,
                        },
                    )
                )
                session.add(
                    OutboxEvent(
                        aggregate_type="Requirement",
                        aggregate_id=requirement.id,
                        event_type="requirement.accepted",
                        payload={
                            "requirement_id": str(requirement.id),
                            "requirement_key": requirement.key,
                            "test_run_id": str(test_run.id),
                            "mission_id": str(mission.id),
                        },
                    )
                )

            proposal.status = ProposalStatus.ACCEPTED
            proposal.accepted_entity_type = "Requirement"
            proposal.accepted_entity_id = requirement.id
            proposal.reviewed_at = utcnow()
            requirements.append(requirement)

        attempt.status = MissionAttemptStatus.ACCEPTED
        attempt.finished_at = utcnow()
        mission.status = MissionStatus.COMPLETED
        mission.completed_at = utcnow()
        mission.row_version += 1
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    for proposal in proposals:
        await session.refresh(proposal)
    for requirement in requirements:
        await session.refresh(requirement)
    await session.refresh(attempt)
    await session.refresh(mission)
    return VerificationResult(True, proposals, requirements, [], [], [])


async def _verify_risks(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    result: MissionResultSubmission,
) -> VerificationResult:
    errors_by_index: dict[int, list[dict[str, Any]]] = {}
    validated_payloads: list[RiskProposalPayload | None] = []
    test_run = mission.test_run

    requirements = list(
        await session.scalars(
            select(Requirement).where(
                Requirement.source_snapshot_id == test_run.source_snapshot_id,
                Requirement.lifecycle_status == RequirementLifecycle.ACTIVE,
            )
        )
    )
    requirements_by_key = {requirement.key: requirement for requirement in requirements}

    for index, submission in enumerate(result.proposals):
        proposal_errors: list[dict[str, Any]] = []
        payload: RiskProposalPayload | None = None
        if submission.proposal_type is not ProposalType.RISK:
            proposal_errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_TYPE",
                    "ANALYZE_RISKS accepts only RISK proposals",
                    index,
                )
            )
        if submission.operation is not ProposalOperation.CREATE:
            proposal_errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_OPERATION",
                    "canonical risk loop supports only CREATE",
                    index,
                )
            )
        try:
            payload = RiskProposalPayload.model_validate(submission.object_payload)
            missing = [key for key in payload.requirement_keys if key not in requirements_by_key]
            if missing:
                proposal_errors.append(
                    _validation_error(
                        "UNKNOWN_REQUIREMENT",
                        f"risk references requirements outside current snapshot: {missing}",
                        index,
                    )
                )
        except ValidationError as exc:
            proposal_errors.append(_validation_error("INVALID_RISK", str(exc), index))
        if proposal_errors:
            errors_by_index[index] = proposal_errors
        validated_payloads.append(payload)

    await _validate_proposal_keys(session, mission, result, errors_by_index)

    if errors_by_index:
        return await _reject_result(session, mission, attempt, result, errors_by_index, [])

    proposals: list[MissionProposal] = []
    risks: list[Risk] = []
    new_by_fingerprint: dict[str, Risk] = {}

    try:
        mission.status = MissionStatus.VERIFYING
        attempt.status = MissionAttemptStatus.SUBMITTED
        attempt.submitted_at = attempt.submitted_at or utcnow()
        attempt.result_payload = result.model_dump(mode="json")

        for submission, payload in zip(result.proposals, validated_payloads, strict=True):
            assert payload is not None
            proposal = MissionProposal(
                mission_id=mission.id,
                attempt_id=attempt.id,
                proposal_type=submission.proposal_type,
                operation=submission.operation,
                idempotency_key=submission.idempotency_key,
                object_payload=submission.object_payload,
                rationale=submission.rationale,
                confidence=submission.confidence,
                status=ProposalStatus.VALIDATING,
            )
            session.add(proposal)
            proposals.append(proposal)

            fingerprint = risk_fingerprint(payload)
            risk = new_by_fingerprint.get(fingerprint)
            if risk is None:
                risk = await session.scalar(
                    select(Risk).where(
                        Risk.source_snapshot_id == test_run.source_snapshot_id,
                        Risk.risk_fingerprint == fingerprint,
                    )
                )
            if risk is None:
                risk = Risk(
                    key=public_key("RISK"),
                    project_id=test_run.project_id,
                    source_snapshot_id=test_run.source_snapshot_id,
                    risk_fingerprint=fingerprint,
                    category=payload.category,
                    title=payload.title,
                    description=payload.description,
                    severity=payload.severity,
                    probability=payload.probability,
                    rationale=payload.rationale,
                    confidence=payload.confidence,
                    lifecycle_status=RiskLifecycle.OPEN,
                    created_by_type="AGENT",
                    created_by_ref=str(attempt.id),
                )
                session.add(risk)
                await session.flush()
                new_by_fingerprint[fingerprint] = risk
                for requirement_key in payload.requirement_keys:
                    session.add(
                        RequirementRisk(
                            requirement_id=requirements_by_key[requirement_key].id,
                            risk_id=risk.id,
                        )
                    )
                session.add(
                    AuditEvent(
                        project_id=test_run.project_id,
                        test_run_id=test_run.id,
                        actor_type="AGENT",
                        actor_ref=str(attempt.id),
                        action="risk.accepted",
                        entity_type="Risk",
                        entity_id=risk.id,
                        after_state={
                            "key": risk.key,
                            "title": risk.title,
                            "category": risk.category.value,
                            "risk_fingerprint": risk.risk_fingerprint,
                        },
                        event_metadata={
                            "mission_id": str(mission.id),
                            "requirement_keys": payload.requirement_keys,
                            "proposal_idempotency_key": submission.idempotency_key,
                        },
                    )
                )
                session.add(
                    OutboxEvent(
                        aggregate_type="Risk",
                        aggregate_id=risk.id,
                        event_type="risk.accepted",
                        payload={
                            "risk_id": str(risk.id),
                            "risk_key": risk.key,
                            "test_run_id": str(test_run.id),
                            "mission_id": str(mission.id),
                            "requirement_keys": payload.requirement_keys,
                        },
                    )
                )

            proposal.status = ProposalStatus.ACCEPTED
            proposal.accepted_entity_type = "Risk"
            proposal.accepted_entity_id = risk.id
            proposal.reviewed_at = utcnow()
            risks.append(risk)

        attempt.status = MissionAttemptStatus.ACCEPTED
        attempt.finished_at = utcnow()
        mission.status = MissionStatus.COMPLETED
        mission.completed_at = utcnow()
        mission.row_version += 1
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    for proposal in proposals:
        await session.refresh(proposal)
    for risk in risks:
        await session.refresh(risk)
    await session.refresh(attempt)
    await session.refresh(mission)
    return VerificationResult(True, proposals, [], risks, [], [])


async def _verify_test_cases(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    result: MissionResultSubmission,
) -> VerificationResult:
    errors_by_index: dict[int, list[dict[str, Any]]] = {}
    validated_payloads: list[TestCaseProposalPayload | None] = []
    test_run = mission.test_run
    risks = list(
        await session.scalars(
            select(Risk).where(
                Risk.project_id == test_run.project_id,
                Risk.source_snapshot_id == test_run.source_snapshot_id,
                Risk.lifecycle_status != RiskLifecycle.OBSOLETE,
            )
        )
    )
    risks_by_key = {risk.key: risk for risk in risks}

    # Validate the complete batch before touching canonical rows or relationship
    # tables. A single bad reference rejects the whole result atomically.
    for index, submission in enumerate(result.proposals):
        proposal_errors: list[dict[str, Any]] = []
        payload: TestCaseProposalPayload | None = None
        if submission.proposal_type is not ProposalType.TEST_CASE:
            proposal_errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_TYPE",
                    "DESIGN_TESTS accepts only TEST_CASE proposals",
                    index,
                )
            )
        if submission.operation is not ProposalOperation.CREATE:
            proposal_errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_OPERATION",
                    "canonical test design loop supports only CREATE",
                    index,
                )
            )
        try:
            payload = TestCaseProposalPayload.model_validate(submission.object_payload)
            missing = [key for key in payload.risk_keys if key not in risks_by_key]
            if missing:
                proposal_errors.append(
                    _validation_error(
                        "UNKNOWN_RISK",
                        "test case references risks outside the current project/source snapshot "
                        f"or with OBSOLETE lifecycle: {missing}",
                        index,
                    )
                )
        except ValidationError as exc:
            proposal_errors.append(_validation_error("INVALID_TEST_CASE", str(exc), index))
        if proposal_errors:
            errors_by_index[index] = proposal_errors
        validated_payloads.append(payload)

    await _validate_proposal_keys(session, mission, result, errors_by_index)
    if errors_by_index:
        return await _reject_result(session, mission, attempt, result, errors_by_index, [])

    requested_gaps = mission.spec.get("acceptance_criteria", {}).get("risk_coverage_gaps")
    if requested_gaps is not None:
        # Mission scope remains immutable while coverage may advance concurrently.
        # Accept partial progress, but never complete a mission that cannot reduce
        # any of its still-open requested dimensions.
        requested = {
            (gap["risk_key"], dimension)
            for gap in requested_gaps
            for dimension in gap["missing_dimensions"]
        }
        coverage = await get_test_run_coverage(session, test_run.id)
        current = {
            (risk.risk_key, dimension.value)
            for risk in coverage.risks
            for dimension in risk.missing_dimensions
        }
        contributes = False
        for payload in validated_payloads:
            assert payload is not None
            pairs = {(key, payload.test_type.value) for key in payload.risk_keys}
            if not pairs & requested & current:
                continue
            fingerprint = case_fingerprint(
                payload,
                test_run.source_snapshot_id,
                [risks_by_key[key] for key in payload.risk_keys],
            )
            existing = await session.scalar(
                select(TestCase).where(
                    TestCase.project_id == test_run.project_id,
                    TestCase.source_snapshot_id == test_run.source_snapshot_id,
                    TestCase.case_fingerprint == fingerprint,
                )
            )
            if existing is None or existing.lifecycle_status is TestCaseLifecycle.ACTIVE:
                contributes = True
                break
        if not contributes:
            return await _reject_result(
                session,
                mission,
                attempt,
                result,
                {},
                [_validation_error(
                    "NO_COVERAGE_PROGRESS",
                    "test proposals must cover a currently missing target risk dimension",
                )],
            )

    proposals: list[MissionProposal] = []
    test_cases: list[TestCase] = []
    new_by_fingerprint: dict[str, TestCase] = {}
    try:
        mission.status = MissionStatus.VERIFYING
        attempt.status = MissionAttemptStatus.SUBMITTED
        attempt.submitted_at = attempt.submitted_at or utcnow()
        attempt.result_payload = result.model_dump(mode="json")

        for submission, payload in zip(result.proposals, validated_payloads, strict=True):
            assert payload is not None
            proposal = MissionProposal(
                mission_id=mission.id,
                attempt_id=attempt.id,
                proposal_type=submission.proposal_type,
                operation=submission.operation,
                idempotency_key=submission.idempotency_key,
                object_payload=submission.object_payload,
                rationale=submission.rationale,
                confidence=submission.confidence,
                status=ProposalStatus.VALIDATING,
            )
            session.add(proposal)
            proposals.append(proposal)

            linked_risks = [risks_by_key[key] for key in payload.risk_keys]
            fingerprint = case_fingerprint(payload, test_run.source_snapshot_id, linked_risks)
            test_case = new_by_fingerprint.get(fingerprint)
            if test_case is None:
                test_case = await session.scalar(
                    select(TestCase).where(
                        TestCase.project_id == test_run.project_id,
                        TestCase.source_snapshot_id == test_run.source_snapshot_id,
                        TestCase.case_fingerprint == fingerprint,
                    )
                )
            if test_case is None:
                test_case = TestCase(
                    key=public_key("TC"),
                    project_id=test_run.project_id,
                    source_snapshot_id=test_run.source_snapshot_id,
                    case_fingerprint=fingerprint,
                    title=payload.title,
                    description=payload.description,
                    test_type=payload.test_type,
                    priority=payload.priority,
                    preconditions=payload.preconditions,
                    expected_result=payload.expected_result,
                    confidence=payload.confidence,
                    lifecycle_status=TestCaseLifecycle.ACTIVE,
                    created_by_type="AGENT",
                    created_by_ref=str(attempt.id),
                )
                session.add(test_case)
                await session.flush()
                new_by_fingerprint[fingerprint] = test_case
                session.add_all(
                    RiskTestCase(risk_id=risk.id, test_case_id=test_case.id)
                    for risk in linked_risks
                )
                session.add(
                    AuditEvent(
                        project_id=test_run.project_id,
                        test_run_id=test_run.id,
                        actor_type="AGENT",
                        actor_ref=str(attempt.id),
                        action="test_case.accepted",
                        entity_type="TestCase",
                        entity_id=test_case.id,
                        after_state={
                            "key": test_case.key,
                            "title": test_case.title,
                            "test_type": test_case.test_type.value,
                            "case_fingerprint": test_case.case_fingerprint,
                        },
                        event_metadata={
                            "mission_id": str(mission.id),
                            "risk_keys": payload.risk_keys,
                            "proposal_idempotency_key": submission.idempotency_key,
                        },
                    )
                )
                session.add(
                    OutboxEvent(
                        aggregate_type="TestCase",
                        aggregate_id=test_case.id,
                        event_type="test_case.accepted",
                        payload={
                            "test_case_id": str(test_case.id),
                            "test_case_key": test_case.key,
                            "test_run_id": str(test_run.id),
                            "mission_id": str(mission.id),
                            "risk_keys": payload.risk_keys,
                        },
                    )
                )

            proposal.status = ProposalStatus.ACCEPTED
            proposal.accepted_entity_type = "TestCase"
            proposal.accepted_entity_id = test_case.id
            proposal.reviewed_at = utcnow()
            test_cases.append(test_case)

        attempt.status = MissionAttemptStatus.ACCEPTED
        attempt.finished_at = utcnow()
        mission.status = MissionStatus.COMPLETED
        mission.completed_at = utcnow()
        mission.row_version += 1
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    for proposal in proposals:
        await session.refresh(proposal)
    for test_case in test_cases:
        await session.refresh(test_case)
    await session.refresh(attempt)
    await session.refresh(mission)
    return VerificationResult(True, proposals, [], [], test_cases, [])


async def verify_mission_result(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    result: MissionResultSubmission,
) -> VerificationResult:
    """Validate an agent submission and atomically commit accepted canonical state."""

    global_errors: list[dict[str, Any]] = []
    if result.mission_id != mission.key:
        global_errors.append(
            _validation_error(
                "MISSION_ID_MISMATCH",
                f"expected {mission.key}, got {result.mission_id}",
            )
        )
    if result.status != "COMPLETED":
        global_errors.append(
            _validation_error("RESULT_NOT_COMPLETED", f"agent result status is {result.status}")
        )
    if not result.proposals:
        global_errors.append(
            _validation_error("NO_PROPOSALS", f"{mission.mission_type.value} must submit proposals")
        )
    if mission.mission_type not in {
        MissionType.ANALYZE_REQUIREMENTS,
        MissionType.ANALYZE_RISKS,
        MissionType.DESIGN_TESTS,
    }:
        global_errors.append(
            _validation_error(
                "UNSUPPORTED_MISSION_TYPE",
                f"canonical verifier does not yet support {mission.mission_type.value}",
            )
        )
    if global_errors:
        return await _reject_result(session, mission, attempt, result, {}, global_errors)

    if mission.mission_type is MissionType.ANALYZE_REQUIREMENTS:
        return await _verify_requirements(session, mission, attempt, result)
    if mission.mission_type is MissionType.ANALYZE_RISKS:
        return await _verify_risks(session, mission, attempt, result)
    return await _verify_test_cases(session, mission, attempt, result)
