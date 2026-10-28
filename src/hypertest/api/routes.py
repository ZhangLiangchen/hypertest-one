from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.schemas import (
    ManagementVersion,
    ProjectCreateRequest,
    ProjectRead,
    ProjectUpdate,
)
from hypertest.application.management import manage_project
from hypertest.application.runtime import MissionRuntimeError
from hypertest.application.services import (
    ConflictError,
    NotFoundError,
    create_project,
    get_project,
    list_projects,
)
from hypertest.db.session import get_db

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hypertest-one"}


def translate_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, MissionRuntimeError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def post_project(payload: ProjectCreateRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await create_project(db, payload)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc


@router.get("/projects", response_model=list[ProjectRead])
async def read_projects(include_deleted: bool = False, db: AsyncSession = Depends(get_db)):
    return await list_projects(db, include_deleted=include_deleted)


@router.patch("/projects/{project_id}", response_model=ProjectRead)
async def patch_project(project_id: UUID, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    return await manage_project(db, project_id, payload.expected_version,
        changes=payload.model_dump(exclude_unset=True, exclude={"expected_version"}))


@router.delete("/projects/{project_id}", response_model=ProjectRead)
async def delete_project(project_id: UUID, expected_version: int = Query(ge=1),
                         db: AsyncSession = Depends(get_db)):
    return await manage_project(db, project_id, expected_version, action="DELETE")


@router.post("/projects/{project_id}/restore", response_model=ProjectRead)
async def restore_project(project_id: UUID, payload: ManagementVersion,
                          db: AsyncSession = Depends(get_db)):
    return await manage_project(db, project_id, payload.expected_version, action="RESTORE")


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def read_project(project_id: UUID, include_deleted: bool = False, db: AsyncSession = Depends(get_db)):
    try:
        return await get_project(db, project_id, include_deleted=include_deleted)
    except RuntimeError as exc:
        raise translate_domain_error(exc) from exc
