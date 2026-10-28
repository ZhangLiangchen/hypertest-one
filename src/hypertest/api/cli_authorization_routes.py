"""Explicit CLI pairing and Operator-only Web consent."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.cli_authorization_schemas import (
    GrantRevoke,
    PairingApprove,
    PairingCreate,
    PairingRedeem,
)
from hypertest.api.interactive_routes import controlled_errors
from hypertest.application import cli_authorization as service
from hypertest.application.services import NotFoundError
from hypertest.config import get_settings
from hypertest.connector.security import require_operator
from hypertest.db.session import get_db
from hypertest.domain.cli_authorization import CliAuthorizationGrant

router = APIRouter(prefix="/cli-authorizations", tags=["cli-authorization"])


def require_tls(request: Request):
    if request.url.scheme != "https" and not (
        get_settings().connector_allow_insecure_loopback
        and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "CLI authorization requires HTTPS")


async def readable(db, request_id, request, proof, operator_key):
    row = await service.request_record(db, request_id)
    if operator_key is not None:
        await require_operator(operator_key)
    else:
        require_tls(request)
        service.check_proof(row, proof)
    return row


@router.post("/requests", status_code=201)
@controlled_errors
async def create(payload: PairingCreate, request: Request, db: AsyncSession = Depends(get_db)):
    require_tls(request)
    return await service.create(db, payload)


@router.get("/actors")
async def actors(_operator: str = Depends(require_operator)):
    raise HTTPException(410, "CLI_UPLOADER_SELECTION_RETIRED")


@router.get("/requests/by-key")
@controlled_errors
async def receipt(request: Request, request_id: UUID,
                  operation: Literal["CREATE", "APPROVE", "REDEEM", "REVOKE"],
                  idempotency_key: str = Query(min_length=1, max_length=128),
                  x_hypertest_pairing_proof: str | None = Header(default=None),
                  x_hypertest_operator_key: str | None = Header(default=None),
                  db: AsyncSession = Depends(get_db)):
    row = await readable(db, request_id, request, x_hypertest_pairing_proof, x_hypertest_operator_key)
    response = await service.prior(db, row, operation, idempotency_key)
    if response is None:
        raise NotFoundError("CLI_AUTHORIZATION_RECEIPT_NOT_FOUND")
    return response


@router.get("/requests/{request_id}")
@controlled_errors
async def read(request_id: UUID, request: Request,
               x_hypertest_pairing_proof: str | None = Header(default=None),
               x_hypertest_operator_key: str | None = Header(default=None),
               db: AsyncSession = Depends(get_db)):
    row = await readable(db, request_id, request, x_hypertest_pairing_proof, x_hypertest_operator_key)
    return await service.view(db, row)


@router.post("/requests/{request_id}/approve")
@controlled_errors
async def approve(request_id: UUID, payload: PairingApprove,
                  operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.approve(db, request_id, payload, operator)


@router.post("/requests/{request_id}/redeem")
@controlled_errors
async def redeem(request_id: UUID, payload: PairingRedeem, request: Request,
                 x_hypertest_pairing_proof: str | None = Header(default=None),
                 db: AsyncSession = Depends(get_db)):
    require_tls(request)
    return await service.redeem(db, request_id, payload, x_hypertest_pairing_proof)


@router.get("/grants")
@controlled_errors
async def grants(_operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.list_grants(db)


@router.post("/grants/{grant_id}/revoke")
@controlled_errors
async def revoke(grant_id: UUID, payload: GrantRevoke,
                 operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.revoke(db, grant_id, payload, operator)


@router.get("/grants/{grant_id}/operations/by-key")
@controlled_errors
async def revoke_receipt(grant_id: UUID, idempotency_key: str = Query(min_length=1, max_length=128),
                         _operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    mapping = await db.scalar(select(CliAuthorizationGrant).where(CliAuthorizationGrant.grant_id == grant_id))
    if mapping is None:
        raise NotFoundError("CLI_GRANT_NOT_FOUND")
    row = await service.request_record(db, mapping.request_id)
    response = await service.prior(db, row, "REVOKE", idempotency_key)
    if response is None or response["grant_id"] != str(grant_id):
        raise NotFoundError("CLI_AUTHORIZATION_RECEIPT_NOT_FOUND")
    return response


@router.post("/requests/{request_id}/revoke")
@controlled_errors
async def revoke_authorization(request_id: UUID, payload: GrantRevoke,
                               operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    return await service.revoke_authorization(db, request_id, payload, operator)
