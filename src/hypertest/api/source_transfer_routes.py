"""HTTPS object transport, separate from the bounded WSS control channel."""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.source_transfer_schemas import (
    SourceAcquisitionReceipt,
    SourceTransferCreate,
    SourceTransferRead,
)
from hypertest.application.services import ConflictError, NotFoundError
from hypertest.application.source_transfer import (
    accept_staged_upload,
    authorize_upload,
    create_transfer,
    dispatch_source,
    get_transfer,
    reserve_staging,
    validate_upload,
)
from hypertest.config import get_settings
from hypertest.connector.security import require_operator
from hypertest.connector.source import MAX_BUNDLE_BYTES, SourceBundleError
from hypertest.db.session import get_db
from hypertest.harness_bridge.protocol import BridgeError

router = APIRouter()


def _error(exc):
    if isinstance(exc, NotFoundError):
        return HTTPException(404, str(exc))
    if isinstance(exc, BridgeError):
        return HTTPException(403, exc.code)
    return HTTPException(409, str(exc))


def _token(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "source upload requires device authorization")
    return authorization[7:]


def _secure(request: Request):
    if request.url.scheme == "https":
        return
    if (get_settings().connector_allow_insecure_loopback
            and request.url.hostname in {"localhost", "127.0.0.1", "::1"}):
        return
    raise HTTPException(400, "source transfer requires HTTPS")


@router.post("/projects/{project_id}/source-transfers", response_model=SourceTransferRead, status_code=201,
             dependencies=[Depends(require_operator)])
async def request_source_transfer(project_id: UUID, payload: SourceTransferCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_transfer(db, project_id, payload)
    except (ValueError, RuntimeError) as exc:
        raise _error(exc) from exc


@router.get("/source-transfers/{transfer_id}", response_model=SourceTransferRead, dependencies=[Depends(require_operator)])
async def read_source_transfer(transfer_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await get_transfer(db, transfer_id)
    except RuntimeError as exc:
        raise _error(exc) from exc


@router.post("/source-transfers/{transfer_id}/dispatch", response_model=SourceTransferRead, dependencies=[Depends(require_operator)])
async def dispatch_source_transfer(transfer_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await dispatch_source(db, transfer_id)
    except (ValueError, RuntimeError) as exc:
        raise _error(exc) from exc


@router.post("/source-transfers/{transfer_id}/authorize-upload")
async def issue_source_upload_grant(transfer_id: UUID, payload: SourceAcquisitionReceipt, request: Request,
                                    authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    _secure(request)
    try:
        return await authorize_upload(db, transfer_id, payload, _token(authorization))
    except (ValueError, RuntimeError) as exc:
        raise _error(exc) from exc


@router.put("/source-transfers/{transfer_id}/content", response_model=SourceTransferRead)
async def upload_source(transfer_id: UUID, request: Request, authorization: str | None = Header(default=None),
                        x_source_upload_token: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    _secure(request)
    device_token = _token(authorization)
    staging = None
    try:
        row, grant = await validate_upload(db, transfer_id, device_token, x_source_upload_token)
        if row.status == "ACCEPTED":
            return row
        if row.status != "UPLOADING":
            raise ConflictError("source transfer is already verifying or terminal")
        bound = min(grant.bundle_size, MAX_BUNDLE_BYTES)
        advertised = request.headers.get("content-length")
        if advertised and (not advertised.isdecimal() or int(advertised) != bound):
            raise SourceBundleError("source upload Content-Length does not match grant")
        # Release read transaction before streaming from the network.
        await db.commit()
        descriptor, staging = await asyncio.to_thread(reserve_staging, bound)
        count = 0
        remaining = max(0.0, (grant.expires_at - datetime.now(UTC)).total_seconds())
        with os.fdopen(descriptor, "wb") as output:
            async with asyncio.timeout(min(remaining, 120)):
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > bound:
                        raise SourceBundleError("source upload exceeds approved length")
                    output.write(chunk)
        if count != bound:
            raise SourceBundleError("source upload did not provide the complete approved object")
        return await accept_staged_upload(db, transfer_id, staging, device_token, x_source_upload_token)
    except (ValueError, RuntimeError) as exc:
        raise _error(exc) from exc
    except TimeoutError as exc:
        raise HTTPException(408, "source upload grant expired during transfer") from exc
    finally:
        if staging:
            staging.unlink(missing_ok=True)
