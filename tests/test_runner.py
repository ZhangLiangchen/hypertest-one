from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from hypertest.api.schemas import (
    PolicySnapshotCreate,
    ProjectCreate,
    SourceSnapshotCreate,
)
from hypertest.api.schemas import (
    TestRunCreate as RunCreate,
)
from hypertest.application.executions import execute_test_run
from hypertest.application.services import (
    canonical_json_sha256,
    create_policy_snapshot,
    create_project,
    create_source_snapshot,
    create_test_run,
)
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import (
    CaseResult,
    EvidenceStatus,
    EvidenceType,
    ExecutionOutcome,
    ExecutionStatus,
    Priority,
    TrustLevel,
)
from hypertest.domain.enums import (
    TestCaseLifecycle as CaseLifecycle,
)
from hypertest.domain.enums import (
    TestCaseType as CaseType,
)
from hypertest.domain.models import (
    AuditEvent,
    Evidence,
    ExecutionEvidence,
    ExecutionTestCase,
    ImplementationTestCase,
    OutboxEvent,
)
from hypertest.domain.models import (
    TestCase as CanonicalTestCase,
)
from hypertest.domain.models import (
    TestExecution as CanonicalExecution,
)
from hypertest.domain.models import (
    TestImplementation as CanonicalImplementation,
)
from hypertest.runner.artifacts import ArtifactIntegrityError, read_evidence_content, store_content
from hypertest.runner.results import parse_junit
from hypertest.runner.source import SourceValidationError, safe_nodeid


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


async def _setup(session, tmp_path, monkeypatch, code: str, symbol: str = "test_example", generated=False):
    settings = get_settings()
    monkeypatch.setattr(settings, "runner_allow_local", True)
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "README.md").write_text("test source\n")
    if not generated:
        (source / "tests/test_example.py").write_text(code)
    _git(source, "init", "-q")
    _git(source, "remote", "add", "origin", "https://example.invalid/runner.git")
    _git(source, "add", ".")
    _git(source, "-c", "user.name=Runner", "-c", "user.email=runner@example.invalid", "commit", "-qm", "fixture")
    commit = _git(source, "rev-parse", "HEAD")
    project = await create_project(session, ProjectCreate(key=public_key("RUNNER"), name="Runner test"))
    snapshot = await create_source_snapshot(session, project.id, SourceSnapshotCreate(
        repository_url="https://example.invalid/runner.git", commit_sha=commit,
        prd_sha256="a" * 64, configuration_sha256="b" * 64,
    ))
    policy = await create_policy_snapshot(session, PolicySnapshotCreate(
        project_id=project.id, policy_version="runner/v1", content_sha256=canonical_json_sha256({}),
    ))
    run = await create_test_run(session, RunCreate(
        project_id=project.id, source_snapshot_id=snapshot.id, policy_snapshot_id=policy.id,
    ))
    case = CanonicalTestCase(
        key=public_key("TC"), project_id=project.id, source_snapshot_id=snapshot.id,
        case_fingerprint=hashlib.sha256(str(run.id).encode()).hexdigest(),
        title="Execution scenario", description="Run the implementation", test_type=CaseType.FUNCTIONAL,
        priority=Priority.P1, preconditions=[], expected_result="runner produces facts",
        lifecycle_status=CaseLifecycle.ACTIVE, created_by_type="USER",
    )
    implementation = CanonicalImplementation(
        key=public_key("IMP"), project_id=project.id, source_snapshot_id=snapshot.id,
        repository_url=snapshot.repository_url, commit_sha=commit,
        file_path="tests/test_example.py", symbol=symbol, framework="pytest", language="python",
        implementation_fingerprint=hashlib.sha256(f"{run.id}:impl".encode()).hexdigest(),
        created_by_type="USER",
    )
    if generated:
        implementation.source_sha256, implementation.artifact_uri = store_content(code.encode())
    session.add_all([case, implementation])
    await session.flush()
    session.add(ImplementationTestCase(implementation_id=implementation.id, test_case_id=case.id))
    await session.commit()
    return source, run, case, implementation


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "expected_outcome", "case_result"), [
    ("def test_example():\n    assert 1 + 1 == 2\n", ExecutionOutcome.PASS, CaseResult.PASS),
    ("def test_example():\n    assert False, 'actual assertion failure'\n", ExecutionOutcome.FAIL, CaseResult.FAIL),
    ("import pytest\n@pytest.mark.skip(reason='unavailable')\ndef test_example():\n    pass\n", ExecutionOutcome.INCONCLUSIVE, CaseResult.SKIPPED),
])
async def test_real_pytest_facts_idempotency_and_relational_evidence(
    tmp_path, monkeypatch, body, expected_outcome, case_result,
):
    async with AsyncSessionLocal() as session:
        source, run, case, implementation = await _setup(session, tmp_path, monkeypatch, body)
        result = await execute_test_run(session, run.id, str(source), "local", idempotency_key="first")
        assert result.status == ExecutionStatus.COMPLETED
        assert result.outcome == expected_outcome
        fact = await session.get(ExecutionTestCase, (result.id, case.id))
        assert fact.result == case_result
        assert fact.implementation_id == implementation.id
        evidence = list(await session.scalars(select(Evidence).join(
            ExecutionEvidence, ExecutionEvidence.evidence_id == Evidence.id,
        ).where(ExecutionEvidence.execution_id == result.id)))
        assert {item.evidence_type for item in evidence} == {
            EvidenceType.EXECUTION_METADATA, EvidenceType.JUNIT, EvidenceType.STDOUT, EvidenceType.STDERR,
        }
        assert all(item.status == EvidenceStatus.VERIFIED and item.trust_level == TrustLevel.RUNNER for item in evidence)
        metadata = json.loads(read_evidence_content(next(item for item in evidence if item.evidence_type == EvidenceType.EXECUTION_METADATA)))
        assert metadata["outcome"] == expected_outcome.value
        assert metadata["spec"]["implementations"][0]["source_sha256"] == hashlib.sha256(body.encode()).hexdigest()
        repeated = await execute_test_run(session, run.id, "/does-not-exist", "local", idempotency_key="first")
        assert repeated.id == result.id
        assert await session.scalar(select(func.count()).select_from(CanonicalExecution).where(CanonicalExecution.test_run_id == run.id)) == 1
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == result.id)) == 2
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == result.id)) == 2


@pytest.mark.asyncio
async def test_generated_test_overlay_keeps_snapshot_and_checkout_unchanged(tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        source, run, _, _ = await _setup(session, tmp_path, monkeypatch,
            "def test_example():\n    assert True\n", generated=True)
        result = await execute_test_run(session, run.id, str(source), "local", idempotency_key="overlay")
        assert result.outcome == ExecutionOutcome.PASS
        assert not (source / "tests/test_example.py").exists()
        assert _git(source, "status", "--porcelain") == ""


@pytest.mark.asyncio
async def test_timeout_is_not_a_pass_and_retains_metadata(tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        source, run, case, _ = await _setup(session, tmp_path, monkeypatch,
            "import time\ndef test_example():\n    time.sleep(10)\n")
        result = await execute_test_run(session, run.id, str(source), "local", idempotency_key="timeout", timeout_seconds=1)
        assert result.status == ExecutionStatus.TIMED_OUT
        assert result.outcome != ExecutionOutcome.PASS
        assert (await session.get(ExecutionTestCase, (result.id, case.id))).result != CaseResult.PASS
        metadata = await session.scalar(select(Evidence).where(Evidence.execution_id == result.id, Evidence.evidence_type == EvidenceType.EXECUTION_METADATA))
        assert json.loads(read_evidence_content(metadata))["error_code"] == "EXECUTION_TIMEOUT"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["dirty", "wrong_commit", "missing_symbol", "local_disabled"])
async def test_invalid_or_missing_execution_inputs_never_pass(tmp_path, monkeypatch, change):
    async with AsyncSessionLocal() as session:
        source, run, _, implementation = await _setup(session, tmp_path, monkeypatch,
            "def test_example():\n    assert True\n")
        if change == "dirty":
            (source / "README.md").write_text("changed\n")
        elif change == "wrong_commit":
            (source / "README.md").write_text("new commit\n")
            _git(source, "add", ".")
            _git(source, "-c", "user.name=Runner", "-c", "user.email=runner@example.invalid", "commit", "-qm", "changed")
        elif change == "missing_symbol":
            implementation.symbol = "test_absent"
            await session.commit()
        elif change == "local_disabled":
            monkeypatch.setattr(get_settings(), "runner_allow_local", False)
        result = await execute_test_run(session, run.id, str(source), "local", idempotency_key=change)
        assert result.status == ExecutionStatus.ERROR
        assert result.outcome != ExecutionOutcome.PASS


def test_content_address_integrity_and_path_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "artifact_root", str(tmp_path))
    digest, uri = store_content(b"trusted output")
    evidence = SimpleNamespace(sha256=digest, artifact_uri=uri, size_bytes=14)
    assert read_evidence_content(evidence) == b"trusted output"
    path = tmp_path / "sha256" / digest[:2] / digest
    path.chmod(0o644)
    path.write_bytes(b"forged output!")
    with pytest.raises(ArtifactIntegrityError, match="checksum"):
        read_evidence_content(evidence)
    evidence.artifact_uri = "/etc/passwd"
    with pytest.raises(ArtifactIntegrityError, match="URI"):
        read_evidence_content(evidence)
    for unsafe_path, unsafe_symbol in [("../secrets.py", "test_a"), ("tests/a.py", "test_a;rm"), ("tests/a.py", "-k")]:
        with pytest.raises(SourceValidationError):
            safe_nodeid(unsafe_path, unsafe_symbol)


def test_empty_or_missing_or_skipped_junit_cannot_report_pass():
    nodeid = "tests/test_example.py::test_example"
    assert parse_junit(b"<testsuites />", [nodeid])[nodeid].result == CaseResult.NOT_RUN
    assert parse_junit(b'<testsuite><testcase classname="tests.test_example" name="test_example"><skipped /></testcase></testsuite>', [nodeid])[nodeid].result == CaseResult.SKIPPED


@pytest.mark.asyncio
async def test_artifact_reuse_and_corruption_rejection_are_atomic(tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        source, run, case, _ = await _setup(session, tmp_path, monkeypatch,
            "def test_example():\n    assert True\n")
        first = await execute_test_run(session, run.id, str(source), "local", idempotency_key="first")
        second = await execute_test_run(session, run.id, str(source), "local", idempotency_key="second")
        assert first.id != second.id
        stderr = await session.scalar(select(Evidence).where(
            Evidence.test_run_id == run.id, Evidence.evidence_type == EvidenceType.STDERR,
        ))
        links = list(await session.scalars(select(ExecutionEvidence.execution_id).where(
            ExecutionEvidence.evidence_id == stderr.id,
        )))
        assert set(links) == {first.id, second.id}
        path = Path(get_settings().artifact_root) / "sha256" / stderr.sha256[:2] / stderr.sha256
        path.chmod(0o644)
        path.write_bytes(b"tampered")
        case_id = case.id
        failed = await execute_test_run(session, run.id, str(source), "local", idempotency_key="third")
        assert failed.status == ExecutionStatus.ERROR
        assert failed.error_code == "EVIDENCE_COLLECTION_ERROR"
        assert (await session.get(ExecutionTestCase, (failed.id, case_id))).result == CaseResult.ERROR
        assert await session.scalar(select(func.count()).select_from(ExecutionEvidence).where(
            ExecutionEvidence.execution_id == failed.id,
        )) == 0
        await session.refresh(stderr)
        assert stderr.status == EvidenceStatus.REJECTED


@pytest.mark.asyncio
async def test_cancellation_records_terminal_state_and_new_retry_keeps_history(tmp_path, monkeypatch):
    async with AsyncSessionLocal() as session:
        source, run, case, _ = await _setup(session, tmp_path, monkeypatch,
            "import time\ndef test_example():\n    time.sleep(10)\n")
        run_id, case_id = run.id, case.id
        task = asyncio.create_task(execute_test_run(
            session, run_id, str(source), "local", idempotency_key="cancel",
        ))
        async with AsyncSessionLocal() as observer:
            for _ in range(100):
                reserved = await observer.scalar(select(CanonicalExecution).where(
                    CanonicalExecution.test_run_id == run_id,
                ))
                if reserved is not None:
                    break
                await asyncio.sleep(0.01)
            assert reserved is not None
            pending = await observer.get(ExecutionTestCase, (reserved.id, case_id))
            assert pending.result == CaseResult.NOT_RUN
        task.cancel()
        cancelled = await task
        assert cancelled.status == ExecutionStatus.CANCELLED
        assert cancelled.outcome != ExecutionOutcome.PASS
        retried = await execute_test_run(session, run_id, str(source), "local",
                                         idempotency_key="retry", timeout_seconds=1)
        assert retried.id != cancelled.id
        assert retried.retry_of_execution_id == cancelled.id
        assert retried.status == ExecutionStatus.TIMED_OUT
