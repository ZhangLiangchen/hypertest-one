"""Runner-controlled facts, collected artifacts, and atomic canonical execution commits."""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import ConflictError, NotFoundError, canonical_json_sha256
from hypertest.common.ids import public_key
from hypertest.domain.enums import (
    CaseResult,
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionPurpose,
    ExecutionStatus,
    ImplementationValidationStatus,
    TestCaseLifecycle,
    TestRunStatus,
    TrustLevel,
)
from hypertest.domain.models import (
    AuditEvent,
    Evidence,
    ExecutionEvidence,
    ExecutionTestCase,
    ImplementationTestCase,
    OutboxEvent,
    SourceSnapshot,
    TestCase,
    TestExecution,
    TestImplementation,
    TestRun,
    utcnow,
)
from hypertest.runner.artifacts import read_evidence_content, store_content
from hypertest.runner.backends import DockerRunner, LocalRunner, ProcessResult
from hypertest.runner.results import NodeResult, parse_junit
from hypertest.runner.source import (
    SourceValidationError,
    copy_tracked_source,
    implementation_content,
    safe_nodeid,
    validate_checkout,
)

__all__ = ["execute_test_run", "read_evidence_content"]


async def _audit(
    session: AsyncSession, run: TestRun, entity_type: str, entity_id: UUID,
    action: str, state: dict,
) -> None:
    session.add(AuditEvent(
        project_id=run.project_id, test_run_id=run.id,
        actor_type="RUNNER", actor_ref="hypertest.runner/v1", action=action,
        entity_type=entity_type, entity_id=entity_id, after_state=state,
    ))
    session.add(OutboxEvent(
        aggregate_type=entity_type, aggregate_id=entity_id,
        event_type=action.lower(), payload=state,
    ))


async def _evidence(
    session: AsyncSession, run: TestRun, execution: TestExecution,
    evidence_type: EvidenceType, content: bytes, content_type: str,
) -> Evidence:
    digest, uri = store_content(content)
    existing = await session.scalar(select(Evidence).where(
        Evidence.test_run_id == run.id, Evidence.sha256 == digest,
        Evidence.evidence_type == evidence_type,
    ))
    if existing is None:
        existing = Evidence(
            key=public_key("EV"), test_run_id=run.id, execution_id=execution.id,
            evidence_type=evidence_type, trust_level=TrustLevel.RUNNER,
            artifact_uri=uri, content_type=content_type, sha256=digest,
            size_bytes=len(content), collector="hypertest.runner/v1", source="RUNNER",
            status=EvidenceStatus.VERIFIED, verified_at=utcnow(),
            inline_summary=f"{evidence_type.value}: {len(content)} bytes",
        )
        session.add(existing)
        await session.flush()
        read_evidence_content(existing)
        await _audit(session, run, "Evidence", existing.id, "evidence.verified", {
            "evidence_id": str(existing.id), "execution_id": str(execution.id),
            "sha256": digest, "evidence_type": evidence_type.value,
        })
    else:
        read_evidence_content(existing)
        if existing.trust_level != TrustLevel.RUNNER or existing.status != EvidenceStatus.VERIFIED:
            raise ConflictError("existing content is not verified Runner evidence")
    session.add(ExecutionEvidence(execution_id=execution.id, evidence_id=existing.id))
    return existing


async def execute_test_run(
    session: AsyncSession, run_id: UUID, workspace: str, backend: str = "docker",
    purpose: ExecutionPurpose = ExecutionPurpose.OFFICIAL, *,
    idempotency_key: str, timeout_seconds: int = 300,
) -> TestExecution:
    """Execute canonical implementations; clients supply neither commands nor result facts."""
    from hypertest.application.jobs import JobLeaseLost
    from hypertest.runner.backends import runner_job_id

    if not idempotency_key.strip() or len(idempotency_key) > 512:
        raise ConflictError("execution requires an idempotency key of 1–512 characters")
    if backend not in {"docker", "local"} or not 1 <= timeout_seconds <= 3600:
        raise ConflictError("unsupported runner backend or timeout outside 1–3600 seconds")
    run = await session.scalar(select(TestRun).where(TestRun.id == run_id).with_for_update()
                               .execution_options(populate_existing=True))
    if run is None:
        raise NotFoundError("test run not found")
    existing = await session.scalar(select(TestExecution).where(
        TestExecution.test_run_id == run_id, TestExecution.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        await session.commit()
        return existing
    if run.status == TestRunStatus.CANCELLED:
        raise ConflictError("cancelled test runs cannot execute")
    snapshot = await session.get(SourceSnapshot, run.source_snapshot_id)
    assert snapshot is not None
    binding = snapshot.environment_definition
    if binding is not None and backend != "docker":
        raise ConflictError("controlled environments require the Docker runner")
    runner = (DockerRunner(environment=binding) if binding is not None else
              DockerRunner() if backend == "docker" else LocalRunner())
    identity = {"backend": backend, "available": False}
    setup_error: Exception | None = None
    # Fingerprinting can contact Docker. Release aggregate/lease locks and then
    # recheck admission before reserving formal execution facts.
    await session.commit()
    try:
        identity = await runner.fingerprint()
    except JobLeaseLost:
        raise
    except Exception as exc:
        setup_error = exc
    await session.commit()
    run = await session.scalar(select(TestRun).where(TestRun.id == run_id).with_for_update()
                               .execution_options(populate_existing=True))
    assert run is not None
    existing = await session.scalar(select(TestExecution).where(
        TestExecution.test_run_id == run_id, TestExecution.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        await session.commit()
        return existing
    if run.status == TestRunStatus.CANCELLED:
        raise ConflictError("cancelled test runs cannot execute")
    from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob

    active_owner = await session.scalar(select(DurableJob.id).where(
        DurableJob.test_run_id == run_id, DurableJob.status.in_(ACTIVE_JOB_STATUSES),
    ))
    owning_job = getattr(session, "job_id", None) or runner_job_id.get()
    if active_owner is not None and active_owner != (UUID(str(owning_job)) if owning_job else None):
        raise ConflictError("test run has active background work; use its task controls")
    # Implementations belong to the shared source snapshot. Gate and Verifier
    # take the same lock after TestRun so cross-run reads see one coherent state.
    snapshot = await session.scalar(select(SourceSnapshot).where(
        SourceSnapshot.id == run.source_snapshot_id,
    ).with_for_update())
    assert snapshot is not None
    cases = list(await session.scalars(select(TestCase).where(
        TestCase.project_id == run.project_id,
        TestCase.source_snapshot_id == snapshot.id,
        TestCase.lifecycle_status == TestCaseLifecycle.ACTIVE,
    ).order_by(TestCase.key)))
    links = list((await session.execute(
        select(TestImplementation, ImplementationTestCase.test_case_id)
        .join(ImplementationTestCase, ImplementationTestCase.implementation_id == TestImplementation.id)
        .where(
            ImplementationTestCase.test_case_id.in_([case.id for case in cases]),
            TestImplementation.project_id == run.project_id,
            TestImplementation.source_snapshot_id == snapshot.id,
            TestImplementation.validation_status.in_([
                ImplementationValidationStatus.PENDING, ImplementationValidationStatus.VALIDATED,
            ]),
        ).order_by(TestImplementation.key)
    )).all())
    implementations = {item.id: item for item, _ in links}
    source = Path(workspace).expanduser().resolve()
    observed_hashes: dict[UUID, str] = {}
    nodeids: dict[UUID, str] = {}
    invalid_implementations: set[UUID] = set()
    try:
        for implementation in implementations.values():
            nodeids[implementation.id] = safe_nodeid(implementation.file_path, implementation.symbol)
            if implementation.commit_sha != snapshot.commit_sha or implementation.repository_url != snapshot.repository_url:
                raise SourceValidationError("implementation source does not match the run snapshot")
            if implementation.framework.lower() != "pytest" or implementation.language.lower() != "python":
                raise SourceValidationError("the MVP trusted runner supports Python pytest implementations")
            if implementation.artifact_uri:
                content = implementation_content(implementation)
            else:
                path = source / implementation.file_path
                if path.is_symlink() or not path.resolve().is_relative_to(source):
                    raise SourceValidationError("implementation source escapes workspace")
                content = path.read_bytes()
            observed_hashes[implementation.id] = hashlib.sha256(content).hexdigest()
            if implementation.source_sha256 and implementation.source_sha256 != observed_hashes[implementation.id]:
                raise SourceValidationError("implementation source checksum changed")
    except JobLeaseLost:
        raise
    except Exception as exc:
        setup_error = exc
    spec = {
        "schema": "hypertest.execution/v1", "source_snapshot_id": str(snapshot.id),
        "source_commit": snapshot.commit_sha, "repository_url": snapshot.repository_url,
        "backend": backend, "environment": identity, "purpose": purpose.value,
        "timeout_seconds": timeout_seconds,
        "test_cases": [str(case.id) for case in cases],
        "implementations": [{"id": str(item.id), "file_path": item.file_path,
                             "symbol": item.symbol, "source_sha256": observed_hashes.get(item.id),
                             "artifact_uri": item.artifact_uri}
                            for item in implementations.values()],
        "case_links": [{"implementation_id": str(item.id), "test_case_id": str(case_id)}
                       for item, case_id in links],
    }
    if binding is not None:
        spec["environment_definition"] = binding
    previous = await session.scalar(select(TestExecution).where(
        TestExecution.test_run_id == run.id, TestExecution.purpose == purpose,
        TestExecution.source_commit == snapshot.commit_sha,
    ).order_by(TestExecution.created_at.desc(), TestExecution.id.desc()).limit(1))
    owner = getattr(session, "job_id", None) or runner_job_id.get()
    execution = TestExecution(
        durable_job_id=UUID(str(owner)) if owner is not None else None,
        key=public_key("EX"), test_run_id=run.id, idempotency_key=idempotency_key,
        retry_of_execution_id=(previous.id if previous is not None and previous.status in {
            ExecutionStatus.ERROR, ExecutionStatus.TIMED_OUT, ExecutionStatus.CANCELLED,
        } else None),
        purpose=purpose, runner_backend=backend,
        environment_id=(f"docker:{binding['request']['profile_id']}" if binding is not None else f"{backend}:pytest"),
        environment_fingerprint=canonical_json_sha256(identity),
        source_commit=snapshot.commit_sha, execution_spec_sha256=canonical_json_sha256(spec),
        spec=spec, status=ExecutionStatus.RUNNING, started_at=utcnow(),
        runner_instance=socket.gethostname(),
    )
    session.add(execution)
    run.status = TestRunStatus.EXECUTING
    await session.flush()
    for case in cases:
        linked = next((item for item, case_id in links if case_id == case.id), None)
        session.add(ExecutionTestCase(
            execution_id=execution.id, test_case_id=case.id,
            implementation_id=linked.id if linked else None, result=CaseResult.NOT_RUN,
        ))
    await _audit(session, run, "TestExecution", execution.id, "execution.started", {
        "execution_id": str(execution.id), "spec_sha256": execution.execution_spec_sha256,
    })
    # Reserve the immutable request before external work. Same-key calls never execute again.
    await session.commit()
    process = ProcessResult(b"", b"", None)
    junit: bytes | None = None
    results: dict[str, NodeResult] = {}
    validated: set[UUID] = set()
    try:
        if setup_error:
            raise setup_error
        if not cases or not implementations:
            raise SourceValidationError("there are no active implemented test cases to execute")
        covered_cases = {case_id for _, case_id in links}
        if covered_cases != {case.id for case in cases}:
            raise SourceValidationError("every active test case requires an implementation")
        files = await validate_checkout(source, snapshot.commit_sha, snapshot.repository_url)
        with tempfile.TemporaryDirectory(prefix="hypertest-runner-") as temporary:
            scratch = Path(temporary)
            staged, output = scratch / "repo", scratch / "results"
            copy_tracked_source(source, staged, files)
            output.mkdir()
            overlays: dict[str, str] = {}
            for implementation in implementations.values():
                if implementation.artifact_uri:
                    if implementation.file_path in files:
                        raise SourceValidationError("generated tests cannot overwrite tracked source files")
                    content = implementation_content(implementation)
                    digest = hashlib.sha256(content).hexdigest()
                    if implementation.file_path in overlays and overlays[implementation.file_path] != digest:
                        raise SourceValidationError("implementations have conflicting source overlays")
                    overlays[implementation.file_path] = digest
                    destination = staged / implementation.file_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                else:
                    if implementation.file_path not in files:
                        raise SourceValidationError("existing implementations must be tracked in the source commit")
                    digest = hashlib.sha256((staged / implementation.file_path).read_bytes()).hexdigest()
                if digest != observed_hashes[implementation.id]:
                    raise SourceValidationError("implementation source changed before execution")
                validated.add(implementation.id)
            await validate_checkout(source, snapshot.commit_sha, snapshot.repository_url)
            process = await runner.execute(staged, output, sorted(set(nodeids.values())), timeout_seconds, identity)
            for implementation in implementations.values():
                digest = hashlib.sha256((staged / implementation.file_path).read_bytes()).hexdigest()
                if digest != observed_hashes[implementation.id]:
                    raise SourceValidationError("implementation source changed during execution")
                if implementation.artifact_uri:
                    implementation_content(implementation)
            await validate_checkout(source, snapshot.commit_sha, snapshot.repository_url)
            if (output / "junit.xml").exists():
                report = output / "junit.xml"
                if report.is_symlink() or report.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("JUnit artifact is unsafe or exceeds collection limit")
                junit = report.read_bytes()
                results = parse_junit(junit, sorted(set(nodeids.values())))
            if process.timed_out:
                execution.status, execution.outcome = ExecutionStatus.TIMED_OUT, ExecutionOutcome.INCONCLUSIVE
                execution.error_code = "EXECUTION_TIMEOUT"
                execution.error_message = "Runner exceeded the execution timeout"
            elif process.error_code:
                execution.status, execution.outcome = ExecutionStatus.ERROR, ExecutionOutcome.INCONCLUSIVE
                execution.error_code = process.error_code
                execution.error_message = "The controlled service environment did not complete reliably"
            elif process.exit_code not in {0, 1} or not results:
                execution.status, execution.outcome = ExecutionStatus.ERROR, ExecutionOutcome.INCONCLUSIVE
                execution.error_code = "COLLECTION_ERROR"
                execution.error_message = "pytest did not produce complete trusted execution results"
            else:
                execution.status = ExecutionStatus.COMPLETED
                states = {result.result for result in results.values()}
                if CaseResult.NOT_RUN in states or CaseResult.ERROR in states:
                    execution.status, execution.outcome = ExecutionStatus.ERROR, ExecutionOutcome.INCONCLUSIVE
                    execution.error_code = "INCOMPLETE_RESULTS"
                elif CaseResult.FAIL in states:
                    execution.outcome = ExecutionOutcome.FAIL
                elif states == {CaseResult.PASS} and process.exit_code == 0:
                    execution.outcome = ExecutionOutcome.PASS
                else:
                    execution.outcome = ExecutionOutcome.INCONCLUSIVE
    except asyncio.CancelledError:
        execution.status, execution.outcome = ExecutionStatus.CANCELLED, ExecutionOutcome.INCONCLUSIVE
        execution.error_code, execution.error_message = "EXECUTION_CANCELLED", "Execution was cancelled"
    except JobLeaseLost:
        raise
    except Exception as exc:
        execution.status, execution.outcome = ExecutionStatus.ERROR, ExecutionOutcome.INCONCLUSIVE
        execution.error_code = ("SOURCE_VALIDATION_ERROR" if isinstance(exc, SourceValidationError) else
                                "ENVIRONMENT_UNAVAILABLE" if binding is not None and setup_error is not None else "RUNNER_ERROR")
        execution.error_message = str(exc)[:2048]
    # Serialize fact completion with gate evaluation on the aggregate root.
    with session.no_autoflush:
        await session.scalar(select(TestRun).where(TestRun.id == run_id).with_for_update())
        await session.scalar(select(SourceSnapshot.id).where(
            SourceSnapshot.id == snapshot.id,
        ).with_for_update())
    execution.exit_code, execution.finished_at = process.exit_code, utcnow()
    for implementation in implementations.values():
        node_result = results.get(nodeids.get(implementation.id, ""))
        if node_result is not None and node_result.result == CaseResult.NOT_RUN:
            invalid_implementations.add(implementation.id)
        if implementation.id in invalid_implementations:
            implementation.validation_status = (
                ImplementationValidationStatus.STALE
                if implementation.validation_status == ImplementationValidationStatus.VALIDATED
                else ImplementationValidationStatus.REJECTED
            )
            await _audit(session, run, "TestImplementation", implementation.id, "implementation.rejected", {
                "implementation_id": str(implementation.id), "reason": "Expected test was not collected",
                "validation_status": implementation.validation_status.value,
            })
        elif (implementation.id in validated and node_result is not None
              and execution.error_code != "SOURCE_VALIDATION_ERROR"):
            if implementation.validation_status != ImplementationValidationStatus.VALIDATED:
                implementation.validation_status = ImplementationValidationStatus.VALIDATED
                implementation.source_sha256 = observed_hashes[implementation.id]
                await _audit(session, run, "TestImplementation", implementation.id, "implementation.validated", {
                    "implementation_id": str(implementation.id), "source_sha256": implementation.source_sha256,
                })
    priority = {CaseResult.PASS: 0, CaseResult.SKIPPED: 1, CaseResult.FAIL: 2,
                CaseResult.ERROR: 3, CaseResult.NOT_RUN: 4, CaseResult.BLOCKED: 5}
    for case in cases:
        related = [(item, results.get(nodeids.get(item.id, ""), NodeResult(CaseResult.NOT_RUN)))
                   for item, case_id in links if case_id == case.id]
        if related:
            implementation, result = max(related, key=lambda pair: priority[pair[1].result])
        else:
            implementation, result = None, NodeResult(CaseResult.NOT_RUN)
        if execution.status in {ExecutionStatus.ERROR, ExecutionStatus.TIMED_OUT, ExecutionStatus.CANCELLED} and result.result == CaseResult.PASS:
            result = NodeResult(CaseResult.ERROR, result.duration_ms, execution.error_message)
        fact = await session.get(ExecutionTestCase, (execution.id, case.id))
        assert fact is not None
        fact.implementation_id = implementation.id if implementation else None
        fact.result, fact.duration_ms = result.result, result.duration_ms
        fact.failure_summary = result.summary or execution.error_message
    try:
        evidence = []
        for kind, content, content_type in [
            (EvidenceType.STDOUT, process.stdout, "text/plain"),
            (EvidenceType.STDERR, process.stderr, "text/plain"),
            *([(EvidenceType.JUNIT, junit, "application/xml")] if junit is not None else []),
            *([(EvidenceType.LOG, process.service_log, "text/plain")] if process.service_log is not None else []),
        ]:
            evidence.append(await _evidence(session, run, execution, kind, content, content_type))
        metadata = {
            "execution_id": str(execution.id), "spec": spec,
            "execution_spec_sha256": execution.execution_spec_sha256,
            "status": execution.status.value, "outcome": execution.outcome.value,
            "exit_code": execution.exit_code, "error_code": execution.error_code,
            "error_message": execution.error_message,
            "started_at": execution.started_at.isoformat(), "finished_at": execution.finished_at.isoformat(),
            "artifacts": [{"evidence_id": str(item.id), "type": item.evidence_type.value,
                           "sha256": item.sha256} for item in evidence],
            "test_results": {nodeid: {"result": result.result.value, "duration_ms": result.duration_ms,
                                      "summary": result.summary} for nodeid, result in results.items()},
        }
        if process.service_metadata is not None:
            metadata["service"] = process.service_metadata
        await _evidence(session, run, execution, EvidenceType.EXECUTION_METADATA,
                        json.dumps(metadata, sort_keys=True).encode(), "application/json")
        run.status = TestRunStatus.VERIFYING
        await _audit(session, run, "TestExecution", execution.id, "execution.completed", {
            "execution_id": str(execution.id), "status": execution.status.value,
            "outcome": execution.outcome.value, "exit_code": execution.exit_code,
        })
        await session.commit()
    except JobLeaseLost:
        # The fence already rolled back pending facts. Canonical recovery belongs
        # to the new owner; never bypass it or read expired ORM attributes here.
        raise
    except Exception as exc:
        # A collector failure must never leave a successful/partially committed fact chain.
        execution_id, project_run_id = execution.id, run.id
        await session.rollback()
        run = await session.scalar(select(TestRun).where(TestRun.id == project_run_id).with_for_update())
        execution = await session.get(TestExecution, execution_id)
        assert run is not None and execution is not None
        execution.status, execution.outcome = ExecutionStatus.ERROR, ExecutionOutcome.INCONCLUSIVE
        execution.error_code, execution.error_message = "EVIDENCE_COLLECTION_ERROR", str(exc)[:2048]
        execution.exit_code, execution.finished_at = process.exit_code, utcnow()
        # Preserve the historical artifact row while rejecting content that no longer verifies.
        prior_evidence = list(await session.scalars(select(Evidence).where(Evidence.test_run_id == run.id)))
        for item in prior_evidence:
            try:
                read_evidence_content(item)
            except Exception:
                if item.status != EvidenceStatus.REJECTED:
                    item.status, item.rejection_reason = EvidenceStatus.REJECTED, "Artifact integrity verification failed"
                    await _audit(session, run, "Evidence", item.id, "evidence.rejected", {"evidence_id": str(item.id)})
        case_ids = [UUID(value) for value in spec["test_cases"]]
        for case_id in case_ids:
            fact = await session.get(ExecutionTestCase, (execution.id, case_id))
            assert fact is not None
            fact.result, fact.failure_summary = CaseResult.ERROR, execution.error_message
        run.status = TestRunStatus.VERIFYING
        await _audit(session, run, "TestExecution", execution.id, "execution.completed", {
            "execution_id": str(execution.id), "status": execution.status.value,
            "outcome": execution.outcome.value, "error_code": execution.error_code,
        })
        await session.commit()
    return execution
