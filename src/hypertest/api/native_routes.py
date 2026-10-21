"""Explicitly opt-in Operator API. Never exposed through legacy Agent tools."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application import native
from hypertest.connector.security import require_operator
from hypertest.db.session import get_db
from hypertest.domain.native import NativeOperation
from hypertest.native_protocol import (
    CreateNativeRun,
    NativeHandoff,
    NativeReconciliation,
    NativeUncertainty,
    NativeWrite,
    SubmitNativeExecution,
)

router = APIRouter(prefix="/native-runs", tags=["native-intake"])


@router.post("", status_code=201)
async def create(payload: CreateNativeRun, actor: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await native.create_native_run(db, payload, actor)


@router.get("/submissions/{project_id}/{key}")
async def submission(project_id: UUID, key: str, _actor: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await native.find_submission(db, project_id, key)


@router.get("/{run_id}")
async def state(run_id: UUID, _actor: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await native.run_view(db, run_id)


@router.post("/{run_id}/executions", status_code=201)
async def execution(run_id: UUID, payload: SubmitNativeExecution, actor: str = Depends(require_operator),
                    writer_key: str | None = Header(default=None, alias="X-Hypertest-Native-Writer-Key"),
                    db: AsyncSession = Depends(get_db)):
    return await native.submit_execution(db, run_id, payload, actor, writer_key)


@router.post("/{run_id}/evaluate")
async def evaluate(run_id: UUID, payload: NativeWrite, actor: str = Depends(require_operator),
                   writer_key: str | None = Header(default=None, alias="X-Hypertest-Native-Writer-Key"),
                   db: AsyncSession = Depends(get_db)):
    return await native.evaluate(db, run_id, payload, actor, writer_key)


@router.post("/{run_id}/handoffs", status_code=201)
async def handoff(run_id: UUID, payload: NativeHandoff, actor: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    # Operator management intentionally survives loss of the old writer key.
    return await native.handoff(db, run_id, payload, actor)


@router.post("/{run_id}/uncertainties", status_code=201)
async def uncertainty(run_id: UUID, payload: NativeUncertainty, actor: str = Depends(require_operator),
                      writer_key: str | None = Header(default=None, alias="X-Hypertest-Native-Writer-Key"),
                      db: AsyncSession = Depends(get_db)):
    return await native.uncertainty(db, run_id, payload, actor, writer_key)


@router.post("/{run_id}/uncertainties/{key}/reconcile")
async def reconcile(run_id: UUID, key: str, payload: NativeReconciliation,
                    actor: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await native.reconcile(db, run_id, key, payload, actor)


@router.get("/{run_id}/operations/{key}")
async def operation(run_id: UUID, key: str, _actor: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    await native.load_run(db, run_id)
    row = await db.scalar(select(NativeOperation).where(
        NativeOperation.run_id == run_id, NativeOperation.idempotency_key == key))
    if row is None:
        raise HTTPException(404, "Native operation not found; this does not authorize replay")
    return native.public(row)


@router.get("/{run_id}/materials/{material_id}")
async def material(run_id: UUID, material_id: UUID, _actor: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await native.read_material(db, run_id, material_id)


@router.get("/{run_id}/handoffs/{handoff_id}/state")
async def handoff_state(run_id: UUID, handoff_id: UUID, _actor: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await native.read_handoff_state(db, run_id, handoff_id)
