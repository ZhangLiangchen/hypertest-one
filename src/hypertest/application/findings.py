"""Evidence-backed finding proposals and controlled canonical lifecycle changes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.lifecycle import record_mission_event
from hypertest.application.services import ConflictError, NotFoundError, canonical_json_sha256
from hypertest.common.ids import public_key
from hypertest.domain.enums import (
    EvidenceStatus,
    FindingClassification,
    FindingEvidenceRelation,
    FindingResolution,
    FindingSeverity,
    FindingStatus,
    MissionAttemptStatus,
    MissionStatus,
    ProposalOperation,
    ProposalStatus,
    ProposalType,
    RequirementLifecycle,
    RiskLifecycle,
    TestCaseLifecycle,
    TrustLevel,
)
from hypertest.domain.models import (
    AuditEvent,
    Evidence,
    Finding,
    FindingEvidence,
    FindingRequirement,
    FindingRisk,
    FindingTestCase,
    Mission,
    MissionAttempt,
    MissionProposal,
    OutboxEvent,
    Requirement,
    Risk,
    SourceSnapshot,
    TestCase,
    TestExecution,
    TestRun,
    utcnow,
)
from hypertest.protocol import MissionResultSubmission
from hypertest.runner.artifacts import ArtifactIntegrityError, read_evidence_content

if TYPE_CHECKING:
    from hypertest.application.verifier import VerificationResult


class FindingProposalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    classification: FindingClassification
    severity: FindingSeverity
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1)
    root_cause: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_keys: list[str] = Field(min_length=1)
    test_case_keys: list[str] = Field(default_factory=list)
    requirement_keys: list[str] = Field(default_factory=list)
    risk_keys: list[str] = Field(default_factory=list)

    @field_validator("evidence_keys", "test_case_keys", "requirement_keys", "risk_keys")
    @classmethod
    def canonical_keys(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("canonical reference keys must not be blank")
        return sorted({value.strip() for value in values})


ACTIVE_FINDING_STATUSES = (
    FindingStatus.NEW,
    FindingStatus.TRIAGED,
    FindingStatus.CONFIRMED,
    FindingStatus.REOPENED,
)
TRUSTED_EVIDENCE_LEVELS = (TrustLevel.RUNNER, TrustLevel.SYSTEM, TrustLevel.EXTERNAL_VERIFIED)


def finding_fingerprint(payload: FindingProposalPayload, test_run: TestRun) -> str:
    # Run-scoped affected component preserves same-run evidence/snapshot boundaries.
    # Cross-run recurrence is a separate future historical comparison policy.
    return canonical_json_sha256(
        {
            "project_id": str(test_run.project_id),
            "classification": payload.classification.value,
            "failure_signature": " ".join(payload.description.split()),
            "affected_component": {
                "test_run_id": str(test_run.id),
                "test_cases": sorted(payload.test_case_keys),
            },
        }
    )


async def verify_findings(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    result: MissionResultSubmission,
) -> VerificationResult:
    # Local import avoids a protocol/runtime/verifier import cycle.
    from hypertest.application.verifier import (
        VerificationResult,
        _prepare_verification,
        _reject_result,
        _validate_proposal_keys,
        _validation_error,
    )

    await _prepare_verification(session, mission, attempt)
    run = mission.test_run
    await session.scalar(select(TestRun).where(TestRun.id == run.id).with_for_update())
    snapshot = await session.get(SourceSnapshot, run.source_snapshot_id)
    assert snapshot is not None
    consistent_execution_ids = set(
        await session.scalars(
            select(TestExecution.id).where(
                TestExecution.test_run_id == run.id,
                TestExecution.source_commit == snapshot.commit_sha,
            )
        )
    )
    evidence_by_key = {
        item.key: item
        for item in await session.scalars(select(Evidence).where(Evidence.test_run_id == run.id))
    }
    cases_by_key = {
        item.key: item
        for item in await session.scalars(
            select(TestCase).where(
                TestCase.project_id == run.project_id,
                TestCase.source_snapshot_id == run.source_snapshot_id,
                TestCase.lifecycle_status == TestCaseLifecycle.ACTIVE,
            )
        )
    }
    requirements_by_key = {
        item.key: item
        for item in await session.scalars(
            select(Requirement).where(
                Requirement.project_id == run.project_id,
                Requirement.source_snapshot_id == run.source_snapshot_id,
                Requirement.lifecycle_status == RequirementLifecycle.ACTIVE,
            )
        )
    }
    risks_by_key = {
        item.key: item
        for item in await session.scalars(
            select(Risk).where(
                Risk.project_id == run.project_id,
                Risk.source_snapshot_id == run.source_snapshot_id,
                Risk.lifecycle_status != RiskLifecycle.OBSOLETE,
            )
        )
    }
    errors_by_index: dict[int, list[dict[str, Any]]] = {}
    payloads: list[FindingProposalPayload | None] = []
    for index, submission in enumerate(result.proposals):
        errors: list[dict[str, Any]] = []
        payload = None
        if submission.proposal_type is not ProposalType.FINDING:
            errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_TYPE", "diagnosis accepts only FINDING proposals", index
                )
            )
        if submission.operation is not ProposalOperation.CREATE:
            errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_OPERATION", "findings support only CREATE proposals", index
                )
            )
        try:
            payload = FindingProposalPayload.model_validate(submission.object_payload)
            for keys, available, code in (
                (payload.evidence_keys, evidence_by_key, "UNKNOWN_EVIDENCE"),
                (payload.test_case_keys, cases_by_key, "UNKNOWN_TEST_CASE"),
                (payload.requirement_keys, requirements_by_key, "UNKNOWN_REQUIREMENT"),
                (payload.risk_keys, risks_by_key, "UNKNOWN_RISK"),
            ):
                missing = [key for key in keys if key not in available]
                if missing:
                    errors.append(
                        _validation_error(
                            code, f"references outside the current run/snapshot: {missing}", index
                        )
                    )
            unverified = [
                key
                for key in payload.evidence_keys
                if key in evidence_by_key
                and evidence_by_key[key].status is not EvidenceStatus.VERIFIED
            ]
            if unverified:
                errors.append(
                    _validation_error(
                        "UNVERIFIED_EVIDENCE",
                        f"finding evidence must be verified: {unverified}",
                        index,
                    )
                )
            inconsistent = [
                key
                for key in payload.evidence_keys
                if key in evidence_by_key
                and evidence_by_key[key].execution_id is not None
                and evidence_by_key[key].execution_id not in consistent_execution_ids
            ]
            if inconsistent:
                errors.append(
                    _validation_error(
                        "EVIDENCE_SNAPSHOT_MISMATCH",
                        f"evidence execution does not match the current source snapshot: {inconsistent}",
                        index,
                    )
                )
        except ValidationError as exc:
            errors.append(_validation_error("INVALID_FINDING", str(exc), index))
        if errors:
            errors_by_index[index] = errors
        payloads.append(payload)
    await _validate_proposal_keys(session, mission, result, errors_by_index)
    if errors_by_index:
        return await _reject_result(session, mission, attempt, result, errors_by_index, [])

    proposals: list[MissionProposal] = []
    findings: list[Finding] = []
    new_by_fingerprint: dict[str, Finding] = {}
    try:
        mission.status = MissionStatus.VERIFYING
        attempt.status = MissionAttemptStatus.SUBMITTED
        attempt.submitted_at = attempt.submitted_at or utcnow()
        attempt.result_payload = result.model_dump(mode="json")
        for submission, payload in zip(result.proposals, payloads, strict=True):
            assert payload is not None
            fingerprint = finding_fingerprint(payload, run)
            finding = new_by_fingerprint.get(fingerprint)
            if finding is None:
                finding = await session.scalar(
                    select(Finding).where(
                        Finding.project_id == run.project_id,
                        Finding.fingerprint == fingerprint,
                        Finding.status.in_(ACTIVE_FINDING_STATUSES),
                    )
                )
            created = finding is None
            if finding is None:
                finding = Finding(
                    key=public_key("FND"),
                    project_id=run.project_id,
                    test_run_id=run.id,
                    fingerprint=fingerprint,
                    classification=payload.classification,
                    severity=payload.severity,
                    title=payload.title,
                    description=payload.description,
                    root_cause=payload.root_cause,
                    confidence=payload.confidence,
                    status=FindingStatus.NEW,
                    reported_by_type="AGENT",
                    reported_by_ref=str(attempt.id),
                )
                session.add(finding)
                await session.flush()
                new_by_fingerprint[fingerprint] = finding
            linked = False
            for keys, available, model, foreign_key in (
                (payload.evidence_keys, evidence_by_key, FindingEvidence, "evidence_id"),
                (payload.test_case_keys, cases_by_key, FindingTestCase, "test_case_id"),
                (
                    payload.requirement_keys,
                    requirements_by_key,
                    FindingRequirement,
                    "requirement_id",
                ),
                (payload.risk_keys, risks_by_key, FindingRisk, "risk_id"),
            ):
                for key in keys:
                    entity_id = available[key].id
                    if await session.get(model, (finding.id, entity_id)) is None:
                        session.add(model(finding_id=finding.id, **{foreign_key: entity_id}))
                        linked = True
            proposal = MissionProposal(
                mission_id=mission.id,
                attempt_id=attempt.id,
                proposal_type=submission.proposal_type,
                operation=submission.operation,
                idempotency_key=submission.idempotency_key,
                object_payload=submission.object_payload,
                rationale=submission.rationale,
                confidence=submission.confidence,
                status=ProposalStatus.ACCEPTED,
                accepted_entity_type="Finding",
                accepted_entity_id=finding.id,
                reviewed_at=utcnow(),
            )
            session.add(proposal)
            proposals.append(proposal)
            findings.append(finding)
            if linked and not created:
                finding.row_version += 1
            if created or linked:
                action = "finding.accepted" if created else "finding.evidence_linked"
                event_payload = {
                    "finding_id": str(finding.id),
                    "finding_key": finding.key,
                    "test_run_id": str(run.id),
                    "mission_id": str(mission.id),
                    "evidence_keys": payload.evidence_keys,
                }
                session.add(
                    AuditEvent(
                        project_id=run.project_id,
                        test_run_id=run.id,
                        actor_type="AGENT",
                        actor_ref=str(attempt.id),
                        action=action,
                        entity_type="Finding",
                        entity_id=finding.id,
                        after_state={
                            "key": finding.key,
                            "status": finding.status.value,
                            "fingerprint": fingerprint,
                        },
                        event_metadata={
                            **event_payload,
                            "proposal_idempotency_key": submission.idempotency_key,
                        },
                    )
                )
                session.add(
                    OutboxEvent(
                        aggregate_type="Finding",
                        aggregate_id=finding.id,
                        event_type=action,
                        payload=event_payload,
                    )
                )
        attempt.status = MissionAttemptStatus.ACCEPTED
        attempt.finished_at = utcnow()
        mission.status = MissionStatus.COMPLETED
        mission.completed_at = utcnow()
        mission.row_version += 1
        await record_mission_event(
            session, mission, "mission.completed", attempt=attempt,
            metadata={"proposal_count": len(proposals),
                      "finding_count": len({item.id for item in findings})},
            before_status=MissionStatus.VERIFYING,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    for item in [*proposals, *findings, attempt, mission]:
        await session.refresh(item)
    return VerificationResult(True, proposals, [], [], [], [], findings=findings)


async def transition_finding(
    session: AsyncSession,
    finding_id: UUID,
    status: FindingStatus,
    resolution: FindingResolution | None = None,
    *,
    reason: str,
    expected_row_version: int | None = None,
) -> Finding:
    if not reason.strip():
        raise ConflictError("a reason is required for finding lifecycle changes")
    status = FindingStatus(status)
    if resolution is not None:
        resolution = FindingResolution(resolution)
    # Serialize with verdict generation, then refresh the locked row for stale sessions.
    original = await session.get(Finding, finding_id)
    if original is None:
        raise NotFoundError("finding not found")
    await session.scalar(
        select(TestRun).where(TestRun.id == original.test_run_id).with_for_update()
    )
    finding = await session.scalar(
        select(Finding)
        .where(Finding.id == finding_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert finding is not None
    if expected_row_version is not None and finding.row_version != expected_row_version:
        raise ConflictError("finding changed; refresh before applying the transition")
    allowed = {
        FindingStatus.NEW: {FindingStatus.TRIAGED},
        FindingStatus.TRIAGED: {FindingStatus.CONFIRMED, FindingStatus.INVALID},
        FindingStatus.CONFIRMED: {FindingStatus.RESOLVED},
        FindingStatus.RESOLVED: {FindingStatus.CLOSED, FindingStatus.REOPENED},
        FindingStatus.CLOSED: {FindingStatus.REOPENED},
        FindingStatus.REOPENED: {FindingStatus.TRIAGED, FindingStatus.CONFIRMED},
        FindingStatus.INVALID: set(),
    }
    if status not in allowed[finding.status]:
        raise ConflictError(f"invalid finding transition: {finding.status.value} -> {status.value}")
    if status is FindingStatus.RESOLVED and resolution is None:
        raise ConflictError("resolving a finding requires a resolution")
    if resolution is not None and status not in {FindingStatus.RESOLVED, FindingStatus.CLOSED}:
        raise ConflictError("resolution is only valid when resolving or closing a finding")
    if status is FindingStatus.REOPENED:
        active = await session.scalar(
            select(Finding.id).where(
                Finding.project_id == finding.project_id,
                Finding.fingerprint == finding.fingerprint,
                Finding.id != finding.id,
                Finding.status.in_(ACTIVE_FINDING_STATUSES),
            )
        )
        if active is not None:
            raise ConflictError("an active finding already tracks this failure fingerprint")
    if status is FindingStatus.CONFIRMED:
        supporting = list(
            await session.scalars(
                select(Evidence)
                .join(
                    FindingEvidence,
                    FindingEvidence.evidence_id == Evidence.id,
                )
                .where(
                    FindingEvidence.finding_id == finding.id,
                    FindingEvidence.relation_type == FindingEvidenceRelation.SUPPORTS,
                    Evidence.test_run_id == finding.test_run_id,
                    Evidence.status == EvidenceStatus.VERIFIED,
                )
            )
        )
        if not supporting:
            raise ConflictError("confirming a finding requires verified supporting evidence")
        if finding.classification is FindingClassification.PRODUCT_DEFECT:
            intact_trusted_evidence = False
            for evidence in supporting:
                if evidence.trust_level not in TRUSTED_EVIDENCE_LEVELS:
                    continue
                try:
                    read_evidence_content(evidence)
                except ArtifactIntegrityError:
                    continue
                intact_trusted_evidence = True
                break
            if not intact_trusted_evidence:
                raise ConflictError(
                    "confirming a product defect requires trusted verified supporting evidence with intact artifacts"
                )
    before = {
        "status": finding.status.value,
        "resolution": finding.resolution.value if finding.resolution else None,
        "row_version": finding.row_version,
    }
    finding.status = status
    finding.row_version += 1
    if status is FindingStatus.CONFIRMED:
        finding.confirmed_by = "USER"
    if status is FindingStatus.RESOLVED:
        finding.resolution = resolution
        finding.resolved_at = utcnow()
    elif status is FindingStatus.REOPENED:
        finding.resolution = None
        finding.resolved_at = None
        finding.confirmed_by = None
    action = f"finding.{status.value.lower()}"
    after = {
        "status": finding.status.value,
        "resolution": finding.resolution.value if finding.resolution else None,
        "row_version": finding.row_version,
    }
    session.add(
        AuditEvent(
            project_id=finding.project_id,
            test_run_id=finding.test_run_id,
            actor_type="USER",
            actor_ref=None,
            action=action,
            entity_type="Finding",
            entity_id=finding.id,
            before_state=before,
            after_state=after,
            event_metadata={"reason": reason.strip()},
        )
    )
    session.add(
        OutboxEvent(
            aggregate_type="Finding",
            aggregate_id=finding.id,
            event_type=action,
            payload={
                "finding_id": str(finding.id),
                "test_run_id": str(finding.test_run_id),
                **after,
                "reason": reason.strip(),
            },
        )
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(finding)
    return finding
