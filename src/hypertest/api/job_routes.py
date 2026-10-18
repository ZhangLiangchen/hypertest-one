from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.delivery_routes import _http_error
from hypertest.api.job_schemas import JobActivityRead, JobCreate, JobRead, JobRetry
from hypertest.application.activity import read_job_activity
from hypertest.application.jobs import cancel_job, get_job, retry_job, submit_job
from hypertest.application.services import get_test_run
from hypertest.db.session import get_db
from hypertest.domain.jobs import DurableJob

router = APIRouter()


@router.get("/jobs/{job_id}/activity", response_model=JobActivityRead)
async def get_job_activity(job_id: UUID, limit: int = Query(default=30, ge=1, le=100),
                           before: UUID | None = None, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        return await read_job_activity(db, job_id, limit=limit, before=before)
    except RuntimeError as exc:
        raise _http_error(exc) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Activity temporarily unavailable") from exc


@router.post("/test-runs/{run_id}/jobs", response_model=JobRead, status_code=202)
async def post_job(run_id: UUID, payload: JobCreate, db: AsyncSession = Depends(get_db)):
    try:
        from hypertest.config import get_settings
        from hypertest.domain.jobs import JobType
        options = dict(payload.payload)
        if (get_settings().harness_mode == "bridge" and payload.operation is JobType.ADVANCE_RUN
                and "execution_profile" not in options):
            old = await db.scalar(select(DurableJob).where(DurableJob.test_run_id == run_id,
                DurableJob.idempotency_key == payload.idempotency_key))
            if old is None or old.payload.get("execution_profile"):
                options["execution_profile"] = "run-persistent-harness/v1"
        return await submit_job(
            db, run_id, payload.operation, payload=options,
            idempotency_key=payload.idempotency_key, mission_id=payload.mission_id,
        )
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/test-runs/{run_id}/jobs", response_model=list[JobRead])
async def read_jobs(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_test_run(db, run_id)
        return list(await db.scalars(
            select(DurableJob).where(DurableJob.test_run_id == run_id)
            .order_by(DurableJob.created_at.desc(), DurableJob.id.desc())
        ))
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.get("/jobs/{job_id}", response_model=JobRead)
async def read_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await get_job(db, job_id)
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.post("/jobs/{job_id}/cancel", response_model=JobRead, status_code=202)
async def post_cancel_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await cancel_job(db, job_id)
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.post("/jobs/{job_id}/retry", response_model=JobRead, status_code=202)
async def post_retry_job(
    job_id: UUID, payload: JobRetry, db: AsyncSession = Depends(get_db)
):
    try:
        return await retry_job(db, job_id, idempotency_key=payload.idempotency_key)
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc
