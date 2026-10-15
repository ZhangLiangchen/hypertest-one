from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.common.ids import public_key
from hypertest.domain.enums import (
    MissionAttemptStatus,
    MissionStatus,
    MissionType,
    ProposalOperation,
    ProposalStatus,
    ProposalType,
    RequirementLifecycle,
)
from hypertest.domain.models import (
    AuditEvent,
    Mission,
    MissionAttempt,
    MissionProposal,
    OutboxEvent,
    Requirement,
    utcnow,
)
from hypertest.protocol import MissionResultSubmission, RequirementProposalPayload


@dataclass(slots=True)
class VerificationResult:
    accepted: bool
    proposals: list[MissionProposal]
    requirements: list[Requirement]
    errors: list[dict[str, Any]]


def requirement_source_fingerprint(payload: RequirementProposalPayload) -> str:
    source_ref = (payload.source_ref or "").strip()
    description = " ".join(payload.description.split())
    raw = f"{source_ref}\n{description}".encode("utf-8")
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
    for index, submission in enumerate(result.proposals):
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
            validation_errors=errors_by_index.get(index) or global_errors,
            reviewed_at=utcnow(),
        )
        session.add(proposal)
        proposals.append(proposal)

    attempt.status = MissionAttemptStatus.REJECTED
    attempt.finished_at = utcnow()
    attempt.result_payload = result.model_dump(mode="json")
    mission.status = MissionStatus.RETRYING
    mission.row_version += 1
    await session.commit()
    for proposal in proposals:
        await session.refresh(proposal)
    return VerificationResult(
        accepted=False,
        proposals=proposals,
        requirements=[],
        errors=[*global_errors, *[error for group in errors_by_index.values() for error in group]],
    )


async def verify_mission_result(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    result: MissionResultSubmission,
) -> VerificationResult:
    """Validate an agent submission and atomically commit accepted canonical state."""

    global_errors: list[dict[str, Any]] = []
    errors_by_index: dict[int, list[dict[str, Any]]] = {}
    validated_payloads: list[RequirementProposalPayload | None] = []

    if mission.mission_type is not MissionType.ANALYZE_REQUIREMENTS:
        global_errors.append(
            _validation_error(
                "UNSUPPORTED_MISSION_TYPE",
                f"canonical verifier does not yet support {mission.mission_type.value}",
            )
        )
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
            _validation_error("NO_PROPOSALS", "ANALYZE_REQUIREMENTS must submit requirements")
        )

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
                    "first canonical loop supports only CREATE",
                    index,
                )
            )
        try:
            payload = RequirementProposalPayload.model_validate(submission.object_payload)
        except ValidationError as exc:
            proposal_errors.append(
                _validation_error("INVALID_REQUIREMENT", str(exc), index)
            )
        if proposal_errors:
            errors_by_index[index] = proposal_errors
        validated_payloads.append(payload)

    existing_keys = {
        value
        for value in await session.scalars(
            select(MissionProposal.idempotency_key).where(MissionProposal.mission_id == mission.id)
        )
    }
    for index, submission in enumerate(result.proposals):
        if submission.idempotency_key in existing_keys:
            errors_by_index.setdefault(index, []).append(
                _validation_error(
                    "PROPOSAL_IDEMPOTENCY_CONFLICT",
                    f"proposal key already exists: {submission.idempotency_key}",
                    index,
                )
            )

    if global_errors or errors_by_index:
        return await _reject_result(
            session,
            mission,
            attempt,
            result,
            errors_by_index,
            global_errors,
        )

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
    return VerificationResult(
        accepted=True,
        proposals=proposals,
        requirements=requirements,
        errors=[],
    )
