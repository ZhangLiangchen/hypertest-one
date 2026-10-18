from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.delivery_routes import _http_error
from hypertest.api.input_schemas import InputAnswer, InputAnswerRead, InputRequestRead
from hypertest.application.inputs import answer_input_request, get_input_request
from hypertest.application.services import get_test_run
from hypertest.db.session import get_db
from hypertest.domain.inputs import MissionInputRequest
from hypertest.domain.run_inputs import RunInputRequest

router = APIRouter()


@router.get("/test-runs/{run_id}/input-requests", response_model=list[InputRequestRead])
async def read_inputs(run_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        await get_test_run(db, run_id)
        mission_inputs = list(await db.scalars(select(MissionInputRequest).where(
            MissionInputRequest.test_run_id == run_id,
        ).order_by(MissionInputRequest.created_at, MissionInputRequest.id)))
        run_inputs = list(await db.scalars(select(RunInputRequest).where(
            RunInputRequest.test_run_id == run_id,
        ).order_by(RunInputRequest.created_at, RunInputRequest.id)))
        return sorted([*mission_inputs, *run_inputs], key=lambda request: (request.created_at, request.id))
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.get("/input-requests/{request_id}", response_model=InputRequestRead)
async def read_input(request_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await get_input_request(db, request_id)
    except RuntimeError as exc:
        raise _http_error(exc) from exc


@router.post("/input-requests/{request_id}/answer", response_model=InputAnswerRead, status_code=202)
async def post_answer(request_id: UUID, payload: InputAnswer, db: AsyncSession = Depends(get_db)):
    try:
        request, job = await answer_input_request(db, request_id, **payload.model_dump())
        return {"input_request": request, "job": job}
    except (RuntimeError, ValueError) as exc:
        raise _http_error(exc) from exc
