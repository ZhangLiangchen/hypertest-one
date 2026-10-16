"""Verify implementation proposals without treating agent assertions as execution facts."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.lifecycle import record_mission_event
from hypertest.application.services import canonical_json_sha256
from hypertest.common.ids import public_key
from hypertest.domain.enums import (
    ImplementationValidationStatus,
    MissionAttemptStatus,
    MissionStatus,
    ProposalOperation,
    ProposalStatus,
    ProposalType,
    TestCaseLifecycle,
)
from hypertest.domain.models import (
    AuditEvent,
    ImplementationTestCase,
    Mission,
    MissionAttempt,
    MissionProposal,
    OutboxEvent,
    SourceSnapshot,
    TestCase,
    TestImplementation,
    utcnow,
)
from hypertest.protocol import MissionResultSubmission, TestImplementationProposalPayload

if TYPE_CHECKING:
    from hypertest.application.verifier import VerificationResult


def implementation_fingerprint(payload: TestImplementationProposalPayload) -> str:
    identity = {
        "repository_url": payload.repository_url.strip().rstrip("/"),
        "commit_sha": payload.commit_sha.lower(),
        "file_path": payload.file_path,
        "symbol": payload.symbol,
    }
    if payload.code is not None:
        identity["source_sha256"] = hashlib.sha256(payload.code.encode()).hexdigest()
    return canonical_json_sha256(identity)


async def verify_test_implementations(
    session: AsyncSession,
    mission: Mission,
    attempt: MissionAttempt,
    result: MissionResultSubmission,
) -> VerificationResult:
    from hypertest.application.verifier import (
        VerificationResult,
        _prepare_verification,
        _reject_result,
        _validate_proposal_keys,
        _validation_error,
    )

    await _prepare_verification(session, mission, attempt)
    test_run = mission.test_run
    snapshot = await session.get(SourceSnapshot, test_run.source_snapshot_id)
    assert snapshot is not None
    cases = list(
        await session.scalars(
            select(TestCase).where(
                TestCase.project_id == test_run.project_id,
                TestCase.source_snapshot_id == test_run.source_snapshot_id,
                TestCase.lifecycle_status == TestCaseLifecycle.ACTIVE,
            )
        )
    )
    cases_by_key = {case.key: case for case in cases}
    validated: list[TestImplementationProposalPayload | None] = []
    errors_by_index: dict[int, list[dict]] = {}
    existing_by_fingerprint: dict[str, TestImplementation] = {}
    for index, submission in enumerate(result.proposals):
        errors: list[dict] = []
        payload = None
        if submission.proposal_type is not ProposalType.TEST_IMPLEMENTATION:
            errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_TYPE",
                    "IMPLEMENT_TESTS accepts only TEST_IMPLEMENTATION",
                    index,
                )
            )
        if submission.operation is not ProposalOperation.CREATE:
            errors.append(
                _validation_error(
                    "INVALID_PROPOSAL_OPERATION",
                    "implementation proposals support only CREATE",
                    index,
                )
            )
        try:
            payload = TestImplementationProposalPayload.model_validate(submission.object_payload)
            if payload.code is not None and not payload.file_path.startswith("tests/"):
                errors.append(
                    _validation_error(
                        "INVALID_TEST_IMPLEMENTATION",
                        "generated test assets must use paths under tests/",
                        index,
                    )
                )
            unknown = [key for key in payload.test_case_keys if key not in cases_by_key]
            if unknown:
                errors.append(
                    _validation_error(
                        "UNKNOWN_TEST_CASE",
                        f"cases must be active in the current snapshot: {unknown}",
                        index,
                    )
                )
            if (
                payload.repository_url != snapshot.repository_url.strip().rstrip("/")
                or payload.commit_sha != snapshot.commit_sha.lower()
            ):
                errors.append(
                    _validation_error(
                        "IMPLEMENTATION_SOURCE_MISMATCH",
                        "implementation repository and commit must match the immutable source snapshot",
                        index,
                    )
                )
            fingerprint = implementation_fingerprint(payload)
            existing = await session.scalar(
                select(TestImplementation).where(
                    TestImplementation.source_snapshot_id == snapshot.id,
                    TestImplementation.implementation_fingerprint == fingerprint,
                )
            )
            if existing is not None:
                existing_by_fingerprint[fingerprint] = existing
                if existing.validation_status not in {
                    ImplementationValidationStatus.PENDING,
                    ImplementationValidationStatus.VALIDATED,
                }:
                    errors.append(
                        _validation_error(
                            "IMPLEMENTATION_NOT_USABLE",
                            "a rejected or stale implementation cannot be revived by a CREATE proposal",
                            index,
                        )
                    )
        except ValidationError as exc:
            errors.append(_validation_error("INVALID_TEST_IMPLEMENTATION", str(exc), index))
        validated.append(payload)
        if errors:
            errors_by_index[index] = errors
    await _validate_proposal_keys(session, mission, result, errors_by_index)
    # One execution overlays each path once. Distinct symbols may share a module,
    # but the complete immutable module bytes must agree across all usable assets.
    existing_assets = list(
        await session.scalars(
            select(TestImplementation).where(
                TestImplementation.project_id == test_run.project_id,
                TestImplementation.source_snapshot_id == snapshot.id,
                TestImplementation.validation_status.in_(
                    [
                        ImplementationValidationStatus.PENDING,
                        ImplementationValidationStatus.VALIDATED,
                    ]
                ),
            )
        )
    )
    signatures_by_path: dict[str, set[str]] = {}
    for item in existing_assets:
        signature = (item.source_sha256 or "INVALID_ARTIFACT") if item.artifact_uri else "TRACKED"
        signatures_by_path.setdefault(item.file_path, set()).add(signature)
    indexes_by_path: dict[str, list[int]] = {}
    for index, payload in enumerate(validated):
        if payload is None:
            continue
        signature = hashlib.sha256(payload.code.encode()).hexdigest() if payload.code else "TRACKED"
        signatures_by_path.setdefault(payload.file_path, set()).add(signature)
        indexes_by_path.setdefault(payload.file_path, []).append(index)
    for path, indexes in indexes_by_path.items():
        if len(signatures_by_path[path]) > 1:
            for index in indexes:
                errors_by_index.setdefault(index, []).append(
                    _validation_error(
                        "CONFLICTING_IMPLEMENTATION_SOURCE",
                        f"shared file {path} must use identical full-module source; choose a unique path for different generated source",
                        index,
                    )
                )
    if errors_by_index:
        return await _reject_result(session, mission, attempt, result, errors_by_index, [])

    if mission.spec.get("acceptance_criteria", {}).get("implementation_progress_required"):
        covered = set(
            await session.scalars(
                select(ImplementationTestCase.test_case_id)
                .join(
                    TestImplementation,
                    TestImplementation.id == ImplementationTestCase.implementation_id,
                )
                .where(
                    TestImplementation.project_id == test_run.project_id,
                    TestImplementation.source_snapshot_id == snapshot.id,
                    TestImplementation.validation_status.in_(
                        [
                            ImplementationValidationStatus.PENDING,
                            ImplementationValidationStatus.VALIDATED,
                        ]
                    ),
                )
            )
        )
        targets = set(mission.spec.get("targets", {}).get("test_cases", []))
        missing = {case.key for case in cases if case.id not in covered} & targets
        if not any(
            payload is not None and set(payload.test_case_keys) & missing for payload in validated
        ):
            return await _reject_result(
                session,
                mission,
                attempt,
                result,
                {},
                [
                    _validation_error(
                        "NO_IMPLEMENTATION_PROGRESS",
                        "proposals must implement a currently missing target test case",
                    ),
                ],
            )

    proposals: list[MissionProposal] = []
    implementations: list[TestImplementation] = []
    links_by_implementation: dict[UUID, set[UUID]] = {}
    try:
        mission.status = MissionStatus.VERIFYING
        attempt.status = MissionAttemptStatus.SUBMITTED
        attempt.submitted_at = attempt.submitted_at or utcnow()
        attempt.result_payload = result.model_dump(mode="json")
        for submission, payload in zip(result.proposals, validated, strict=True):
            assert payload is not None
            fingerprint = implementation_fingerprint(payload)
            implementation = existing_by_fingerprint.get(fingerprint)
            created = implementation is None
            if implementation is None:
                source_sha256 = None
                artifact_uri = None
                if payload.code is not None:
                    from hypertest.runner.artifacts import store_content

                    source_sha256, artifact_uri = store_content(payload.code.encode())
                implementation = TestImplementation(
                    key=public_key("IMPL"),
                    project_id=test_run.project_id,
                    source_snapshot_id=snapshot.id,
                    repository_url=payload.repository_url,
                    commit_sha=payload.commit_sha,
                    file_path=payload.file_path,
                    symbol=payload.symbol,
                    framework=payload.framework,
                    language=payload.language,
                    implementation_fingerprint=fingerprint,
                    source_sha256=source_sha256,
                    artifact_uri=artifact_uri,
                    validation_status=ImplementationValidationStatus.PENDING,
                    created_by_type="AGENT",
                    created_by_ref=str(attempt.id),
                )
                session.add(implementation)
                await session.flush()
                existing_by_fingerprint[fingerprint] = implementation
            if implementation.id not in links_by_implementation:
                links_by_implementation[implementation.id] = set(
                    await session.scalars(
                        select(ImplementationTestCase.test_case_id).where(
                            ImplementationTestCase.implementation_id == implementation.id,
                        )
                    )
                )
            linked = links_by_implementation[implementation.id]
            new_keys = [key for key in payload.test_case_keys if cases_by_key[key].id not in linked]
            for key in new_keys:
                case_id = cases_by_key[key].id
                session.add(
                    ImplementationTestCase(
                        implementation_id=implementation.id,
                        test_case_id=case_id,
                    )
                )
                linked.add(case_id)
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
                accepted_entity_type="TestImplementation",
                accepted_entity_id=implementation.id,
                reviewed_at=utcnow(),
            )
            session.add(proposal)
            proposals.append(proposal)
            implementations.append(implementation)
            if created or new_keys:
                action = "implementation.accepted" if created else "implementation.linked"
                state = {
                    "key": implementation.key,
                    "implementation_fingerprint": fingerprint,
                    "validation_status": implementation.validation_status.value,
                    "test_case_keys": new_keys,
                }
                session.add(
                    AuditEvent(
                        project_id=test_run.project_id,
                        test_run_id=test_run.id,
                        actor_type="AGENT",
                        actor_ref=str(attempt.id),
                        action=action,
                        entity_type="TestImplementation",
                        entity_id=implementation.id,
                        after_state=state,
                        event_metadata={
                            "mission_id": str(mission.id),
                            "proposal_idempotency_key": submission.idempotency_key,
                        },
                    )
                )
                session.add(
                    OutboxEvent(
                        aggregate_type="TestImplementation",
                        aggregate_id=implementation.id,
                        event_type=action,
                        payload={
                            **state,
                            "implementation_id": str(implementation.id),
                            "test_run_id": str(test_run.id),
                            "mission_id": str(mission.id),
                        },
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
                      "implementation_count": len({item.id for item in implementations})},
            before_status=MissionStatus.VERIFYING,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    for row in [*proposals, *implementations, attempt, mission]:
        await session.refresh(row)
    return VerificationResult(
        True,
        proposals,
        [],
        [],
        [],
        [],
        implementations=implementations,
    )
