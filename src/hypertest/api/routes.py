from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import (
    MissionCreate,
    MissionExecuteRequest,
    MissionExecutionRead,
    MissionRead,
    PolicySnapshotCreate,
    PolicySnapshotRead,
    ProjectCreate,
    ProjectRead,
    RequirementRead,
    SourceSnapshotCreate,
    SourceSnapshotRead,
    TestRunCreate,
    TestRunRead,
)
from hypertest.application.runtime import MissionRuntimeError, execute_mission
from hypertest.application.services import (
    ConflictError,
    NotFoundError,
    create_mission,
    create_policy_snapshot,
    create_project,
    create_source_snapshot,
    create_test_run,
    get_mission,
    get_project,
    get_test_run,
    list_requirements_for_test_run,
)
from hypertest.db.session import get_db

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hypertest-one"}


def translate_domain_error(exc: RuntimeError) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, MissionRuntimeError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def post_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_project(db, payload)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def read_project(project_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await get_project(db, project_id)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.post(
    "/projects/{project_id}/source-snapshots",
    response_model=SourceSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_source_snapshot(
    project_id: UUID,
    payload: SourceSnapshotCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await create_source_snapshot(db, project_id, payload)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.post(
    "/policy-snapshots",
    response_model=PolicySnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_policy_snapshot(
    payload: PolicySnapshotCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await create_policy_snapshot(db, payload)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.post("/test-runs", response_model=TestRunRead, status_code=status.HTTP_201_CREATED)
async def post_test_run(payload: TestRunCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_test_run(db, payload)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.get("/test-runs/{test_run_id}", response_model=TestRunRead)
async def read_test_run(test_run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await get_test_run(db, test_run_id)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.get(
    "/test-runs/{test_run_id}/requirements",
    response_model=list[RequirementRead],
)
async def read_test_run_requirements(
    test_run_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await list_requirements_for_test_run(db, test_run_id)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.post(
    "/test-runs/{test_run_id}/missions",
    response_model=MissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_mission(
    test_run_id: UUID,
    payload: MissionCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await create_mission(db, test_run_id, payload)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.get("/missions/{mission_id}", response_model=MissionRead)
async def read_mission(mission_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await get_mission(db, mission_id)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.post("/missions/{mission_id}/execute", response_model=MissionExecutionRead)
async def post_execute_mission(
    mission_id: UUID,
    payload: MissionExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        execution = await execute_mission(
            db,
            mission_id,
            workspace=payload.workspace,
            provider=payload.provider,
        )
        return MissionExecutionRead(
            mission=execution.mission,
            attempt=execution.attempt,
            proposals=execution.proposals,
            requirements=execution.requirements,
        )
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc
