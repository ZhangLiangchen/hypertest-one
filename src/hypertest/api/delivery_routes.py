import hashlib
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.delivery_schemas import (
    EvidenceRead,
    ExecutionCaseRead,
    ExecutionCreate,
    ExecutionDetail,
    ExecutionRead,
    FindingRead,
    FindingTransition,
    GateRequest,
    ImplementationRead,
    RunAdvance,
    RunBootstrap,
    VerdictRead,
)
from hypertest.api.operation_guard import guard_synchronous_operation
from hypertest.api.routes import translate_domain_error
from hypertest.api.schemas import (
    MissionAttemptRead,
    MissionProposalRead,
    MissionRead,
    PolicySnapshotRead,
    SourceSnapshotRead,
    TestRunRead,
)
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.controller import advance_run
from hypertest.application.executions import execute_test_run, read_evidence_content
from hypertest.application.findings import transition_finding
from hypertest.application.gate import evaluate_gate
from hypertest.application.jobs import get_worker_status
from hypertest.application.lifecycle import record_mission_event
from hypertest.application.services import ConflictError, get_mission, get_test_run
from hypertest.application.workspaces import prepare_workspace
from hypertest.config import get_settings
from hypertest.db.session import get_db
from hypertest.domain.enums import MissionStatus
from hypertest.domain.models import (
    Evidence,
    ExecutionEvidence,
    ExecutionTestCase,
    Finding,
    FindingEvidence,
    FindingTestCase,
    ImplementationTestCase,
    MissionAttempt,
    MissionProposal,
    PolicySnapshot,
    SourceSnapshot,
    TestCase,
    TestExecution,
    TestImplementation,
    TestRun,
    Verdict,
    VerdictEvidence,
    VerdictFinding,
    utcnow,
)

router = APIRouter()


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return translate_domain_error(exc)


@router.get("/capabilities")
async def read_capabilities(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    return {
        "agent_providers": ["codex"] if shutil.which(settings.codex_binary) else [],
        "runner_backends": (["docker"] if shutil.which("docker") else [])
        + (["local"] if settings.runner_allow_local else []),
        "workspace_root": settings.workspace_root,
        "runner_image": settings.runner_image,
        "mode": "single_operator",
        "worker": await get_worker_status(db),
    }


@router.get("/source-snapshots/{snapshot_id}", response_model=SourceSnapshotRead)
async def read_source_snapshot(snapshot_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await db.get(SourceSnapshot, snapshot_id)
    if item is None:
        raise HTTPException(status_code=404, detail="source snapshot not found")
    return item


@router.get("/policy-snapshots/{snapshot_id}", response_model=PolicySnapshotRead)
async def read_policy_snapshot(snapshot_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await db.get(PolicySnapshot, snapshot_id)
    if item is None:
        raise HTTPException(status_code=404, detail="policy snapshot not found")
    return item


@router.get("/source-snapshots/{snapshot_id}/prd")
async def read_prd(snapshot_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await db.get(SourceSnapshot, snapshot_id)
    if item is None:
        raise HTTPException(status_code=404, detail="source snapshot not found")
    root = Path(get_settings().artifact_root).resolve()
    path = Path(item.prd_artifact_uri or "")
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root / "inputs"):
            raise ValueError("unsupported input artifact")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item.prd_sha256:
            raise ValueError("PRD checksum mismatch")
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=409, detail="PRD artifact unavailable or checksum mismatch"
        ) from exc
    return Response(content, media_type="text/plain", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/source-snapshots/{snapshot_id}/configuration")
async def read_configuration(snapshot_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await db.get(SourceSnapshot, snapshot_id)
    if item is None:
        raise HTTPException(status_code=404, detail="source snapshot not found")
    root = Path(get_settings().artifact_root).resolve()
    path = root / "inputs" / f"{item.configuration_sha256}.txt"
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("unsupported configuration artifact")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item.configuration_sha256:
            raise ValueError("configuration checksum mismatch")
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=409, detail="configuration artifact unavailable or checksum mismatch"
        ) from exc
    return Response(content, media_type="text/plain", headers={"X-Content-Type-Options": "nosniff"})


@router.post("/projects/{project_id}/runs/bootstrap", response_model=TestRunRead, status_code=201)
async def post_bootstrap(
    project_id: UUID, payload: RunBootstrap, db: AsyncSession = Depends(get_db)
):
    try:
        return await bootstrap_run(db, project_id, payload)
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/test-runs/{run_id}/advance")
async def post_advance(run_id: UUID, payload: RunAdvance, db: AsyncSession = Depends(get_db)):
    try:
        await guard_synchronous_operation(db, run_id)
        return await advance_run(db, run_id, **payload.model_dump())
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/test-runs/{run_id}/prepare-workspace")
async def post_prepare_workspace(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await guard_synchronous_operation(db, run_id)
        return await prepare_workspace(db, run_id)
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/test-runs/{run_id}/implementations", response_model=list[ImplementationRead])
async def read_implementations(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        run = await get_test_run(db, run_id)
        items = list(
            await db.scalars(
                select(TestImplementation)
                .where(
                    TestImplementation.source_snapshot_id == run.source_snapshot_id,
                    TestImplementation.project_id == run.project_id,
                )
                .order_by(TestImplementation.created_at)
            )
        )
        keys: dict[UUID, list[str]] = {item.id: [] for item in items}
        if items:
            links = await db.execute(
                select(ImplementationTestCase.implementation_id, TestCase.key)
                .join(TestCase, TestCase.id == ImplementationTestCase.test_case_id)
                .where(ImplementationTestCase.implementation_id.in_(keys))
                .order_by(TestCase.key)
            )
            for item_id, key in links:
                keys[item_id].append(key)
        return [
            ImplementationRead.model_validate(item).model_copy(
                update={"test_case_keys": keys[item.id]}
            )
            for item in items
        ]
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.get("/test-runs/{run_id}/executions", response_model=list[ExecutionRead])
async def read_executions(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_test_run(db, run_id)
        return list(
            await db.scalars(
                select(TestExecution)
                .where(TestExecution.test_run_id == run_id)
                .order_by(TestExecution.created_at.desc())
            )
        )
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.post("/test-runs/{run_id}/executions", response_model=ExecutionRead, status_code=201)
async def post_execution(
    run_id: UUID, payload: ExecutionCreate, db: AsyncSession = Depends(get_db)
):
    try:
        await guard_synchronous_operation(db, run_id)
        return await execute_test_run(db, run_id, **payload.model_dump())
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/executions/{execution_id}", response_model=ExecutionDetail)
async def read_execution(execution_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await db.get(TestExecution, execution_id)
    if item is None:
        raise HTTPException(status_code=404, detail="execution not found")
    rows = await db.execute(
        select(ExecutionTestCase, TestCase.key)
        .join(TestCase, TestCase.id == ExecutionTestCase.test_case_id)
        .where(ExecutionTestCase.execution_id == execution_id)
        .order_by(TestCase.key)
    )
    evidence_keys = list(
        await db.scalars(
            select(Evidence.key)
            .join(ExecutionEvidence, ExecutionEvidence.evidence_id == Evidence.id)
            .where(ExecutionEvidence.execution_id == execution_id)
            .order_by(Evidence.key)
        )
    )
    return ExecutionDetail(
        execution=item,
        evidence_keys=evidence_keys,
        test_cases=[
            ExecutionCaseRead.model_validate(row).model_copy(update={"test_case_key": key})
            for row, key in rows
        ],
    )


@router.get("/test-runs/{run_id}/evidence", response_model=list[EvidenceRead])
async def read_evidence(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_test_run(db, run_id)
        return list(
            await db.scalars(
                select(Evidence)
                .where(Evidence.test_run_id == run_id)
                .order_by(Evidence.created_at.desc())
            )
        )
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.get("/evidence/{evidence_id}/content")
async def read_evidence_artifact(evidence_id: UUID, db: AsyncSession = Depends(get_db)):
    item = await db.get(Evidence, evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    try:
        content = read_evidence_content(item)
        return Response(
            content, media_type="text/plain", headers={"X-Content-Type-Options": "nosniff"}
        )
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=409, detail="artifact missing or integrity verification failed"
        ) from exc


async def _finding_read(db: AsyncSession, item: Finding) -> FindingRead:
    evidence_keys = list(
        await db.scalars(
            select(Evidence.key)
            .join(FindingEvidence, FindingEvidence.evidence_id == Evidence.id)
            .where(FindingEvidence.finding_id == item.id)
            .order_by(Evidence.key)
        )
    )
    case_keys = list(
        await db.scalars(
            select(TestCase.key)
            .join(FindingTestCase, FindingTestCase.test_case_id == TestCase.id)
            .where(FindingTestCase.finding_id == item.id)
            .order_by(TestCase.key)
        )
    )
    return FindingRead.model_validate(item).model_copy(
        update={
            "evidence_keys": evidence_keys,
            "test_case_keys": case_keys,
        }
    )


@router.get("/test-runs/{run_id}/findings", response_model=list[FindingRead])
async def read_findings(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_test_run(db, run_id)
        items = await db.scalars(
            select(Finding).where(Finding.test_run_id == run_id).order_by(Finding.created_at.desc())
        )
        return [await _finding_read(db, item) for item in items]
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.post("/findings/{finding_id}/transition", response_model=FindingRead)
async def post_finding_transition(
    finding_id: UUID, payload: FindingTransition, db: AsyncSession = Depends(get_db)
):
    try:
        item = await transition_finding(db, finding_id, **payload.model_dump())
        return await _finding_read(db, item)
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc


async def _verdict_read(db: AsyncSession, item: Verdict) -> VerdictRead:
    evidence_keys = list(
        await db.scalars(
            select(Evidence.key)
            .join(VerdictEvidence, VerdictEvidence.evidence_id == Evidence.id)
            .where(VerdictEvidence.verdict_id == item.id)
            .order_by(Evidence.key)
        )
    )
    finding_keys = list(
        await db.scalars(
            select(Finding.key)
            .join(VerdictFinding, VerdictFinding.finding_id == Finding.id)
            .where(VerdictFinding.verdict_id == item.id)
            .order_by(Finding.key)
        )
    )
    return VerdictRead.model_validate(item).model_copy(
        update={
            "evidence_keys": evidence_keys,
            "finding_keys": finding_keys,
        }
    )


@router.get("/test-runs/{run_id}/verdicts", response_model=list[VerdictRead])
async def read_verdicts(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_test_run(db, run_id)
        items = await db.scalars(
            select(Verdict)
            .where(Verdict.test_run_id == run_id)
            .order_by(Verdict.sequence_no.desc())
        )
        return [await _verdict_read(db, item) for item in items]
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.post("/test-runs/{run_id}/evaluate", response_model=VerdictRead)
async def post_gate(run_id: UUID, payload: GateRequest, db: AsyncSession = Depends(get_db)):
    try:
        await guard_synchronous_operation(db, run_id)
        item = await evaluate_gate(db, run_id, finalize=payload.finalize)
        return await _verdict_read(db, item)
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/missions/{mission_id}/attempts", response_model=list[MissionAttemptRead])
async def read_attempts(mission_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_mission(db, mission_id)
        return list(
            await db.scalars(
                select(MissionAttempt)
                .where(MissionAttempt.mission_id == mission_id)
                .order_by(MissionAttempt.attempt_no.desc())
            )
        )
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.get("/missions/{mission_id}/proposals", response_model=list[MissionProposalRead])
async def read_proposals(mission_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_mission(db, mission_id)
        return list(
            await db.scalars(
                select(MissionProposal)
                .where(MissionProposal.mission_id == mission_id)
                .order_by(MissionProposal.created_at)
            )
        )
    except RuntimeError as exc:
        raise _http_error(exc) from exc


async def _mission_action(db: AsyncSession, mission_id: UUID, retry: bool):
    mission = await get_mission(db, mission_id)
    await db.scalar(
        select(TestRun)
        .where(TestRun.id == mission.test_run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    mission = await db.scalar(
        select(type(mission))
        .where(type(mission).id == mission_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    before_status = mission.status
    if retry:
        if mission.status == MissionStatus.RETRYING:
            return mission
        if mission.status != MissionStatus.FAILED:
            raise ConflictError("only FAILED missions can be reopened for retry")
        mission.status = MissionStatus.RETRYING
    else:
        if mission.status == MissionStatus.CANCELLED:
            return mission
        if mission.status in {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.EXPIRED}:
            raise ConflictError("terminal missions cannot be cancelled")
        mission.status = MissionStatus.CANCELLED
        mission.cancelled_at = utcnow()
    mission.row_version += 1
    action = "mission.retry_requested" if retry else "mission.cancelled"
    await record_mission_event(
        db, mission, action, before_status=before_status,
        actor_type="USER", actor_ref="web",
        metadata={"reason": "operator requested retry" if retry else "operator cancelled mission"},
    )
    await db.commit()
    await db.refresh(mission)
    return mission


@router.post("/missions/{mission_id}/retry", response_model=MissionRead)
async def retry_mission(mission_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await _mission_action(db, mission_id, True)
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.post("/missions/{mission_id}/cancel", response_model=MissionRead)
async def cancel_mission(mission_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await _mission_action(db, mission_id, False)
    except RuntimeError as exc:
        raise _http_error(exc) from exc
