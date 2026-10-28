"""Scoped interactive HTTPS facade. Public MCP never receives these credentials."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.interactive_schemas import (
    PROFILE,
    RegisterIntegration,
)
from hypertest.application import interactive as app
from hypertest.application.jobs import JobLeaseLost
from hypertest.application.services import ConflictError, NotFoundError
from hypertest.connector.security import require_operator, token_hash
from hypertest.db.session import get_db
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveExecutionGrant,
    InteractiveIntegrationGrant,
)
from hypertest.domain.models import Project
from hypertest.harness_bridge.protocol import BridgeError
from hypertest.runner.artifacts import ArtifactIntegrityError

router = APIRouter(prefix="/interactive", tags=["interactive"])


def bearer(request: Request, authorization: str | None = Header(default=None)) -> str:
    from hypertest.config import get_settings

    if request.url.scheme != "https" and not (
        get_settings().connector_allow_insecure_loopback
        and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "Interactive credentials require HTTPS")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Interactive bearer required")
    return authorization[7:]


def controlled_errors(func):
    # Route signatures must remain visible to FastAPI.
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except NotFoundError as exc:
            raise HTTPException(404, str(exc)) from None
        except (ConflictError, JobLeaseLost, ArtifactIntegrityError) as exc:
            raise HTTPException(409, str(exc)) from None
        except BridgeError as exc:
            raise HTTPException(403, exc.code) from None
        except IntegrityError:
            raise HTTPException(
                409, "Operation conflicts with immutable ownership or input"
            ) from None
        except ValidationError:
            raise HTTPException(
                422, "Tool arguments do not match the strict input schema"
            ) from None

    return wrapper


@router.get("/capabilities")
async def capabilities():
    return {"profile": PROFILE, "local_sync_retired": True,
            "local_archive_profile": "local-artifact-archive/v1alpha1",
            "tools": [], "execution_tools": [], "legacy_run_retired": True}


@router.post("/registrations", status_code=201)
@controlled_errors
async def register(
    payload: RegisterIntegration,
    operator: str = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    import secrets

    if not await db.scalar(select(Project).where(Project.id == payload.project_id, Project.deleted_at.is_(None))
                           .with_for_update(read=True).execution_options(populate_existing=True)):
        raise NotFoundError("Project not found")
    actor = await db.scalar(
        select(InteractiveActorIdentity)
        .where(InteractiveActorIdentity.actor_ref == payload.actor_ref)
        .with_for_update()
    )
    if actor is None:
        actor = InteractiveActorIdentity(actor_ref=payload.actor_ref, registered_by=operator)
        db.add(actor)
        await db.flush()
    if actor.status != "ACTIVE":
        raise ConflictError("Actor registration was revoked")
    client = await db.get(InteractiveClientRegistration, (actor.id, payload.client_instance_id))
    if client is None:
        client = InteractiveClientRegistration(
            actor_identity_id=actor.id,
            client_instance_id=payload.client_instance_id,
            registered_by=operator,
        )
        db.add(client)
        await db.flush()
    if client.status != "ACTIVE":
        raise ConflictError("Client registration was revoked")
    secret = secrets.token_urlsafe(48)
    clock = await app.now(db)
    grant = InteractiveIntegrationGrant(
        actor_identity_id=actor.id,
        client_instance_id=client.client_instance_id,
        project_id=payload.project_id,
        scopes=payload.scopes,
        token_hash=token_hash(secret),
        registered_by=operator,
        not_before=clock,
        expires_at=clock + timedelta(days=payload.expires_in_days),
    )
    db.add(grant)
    await db.flush()
    app.event(
        db, grant, "interactive.integration.registered", "InteractiveIntegrationGrant", grant.id
    )
    await db.commit()
    return {
        "grant_id": str(grant.id),
        "actor_identity_id": str(actor.id),
        "client_instance_id": str(client.client_instance_id),
        "project_id": str(grant.project_id),
        "scopes": grant.scopes,
        "integration_token": secret,
        "expires_at": grant.expires_at,
    }


@router.post("/grants/{grant_id}/revoke")
@controlled_errors
async def revoke(
    grant_id: UUID, operator: str = Depends(require_operator), db: AsyncSession = Depends(get_db)
):
    grant = await db.get(InteractiveIntegrationGrant, grant_id, with_for_update=True)
    if not grant:
        raise NotFoundError("Interactive grant not found")
    if grant.status == "ACTIVE":
        grant.status, grant.revoked_at, grant.row_version = (
            "REVOKED",
            await app.now(db),
            grant.row_version + 1,
        )
        rows = await db.scalars(
            select(InteractiveExecutionGrant).where(
                InteractiveExecutionGrant.integration_grant_id == grant.id,
                InteractiveExecutionGrant.status == "ACTIVE",
            )
        )
        for short in rows:
            short.status, short.row_version = "REVOKED", short.row_version + 1
        app.event(
            db,
            grant,
            "interactive.integration.revoked",
            "InteractiveIntegrationGrant",
            grant.id,
            extra={"operator": operator},
        )
        await db.commit()
    return {"grant_id": str(grant.id), "status": grant.status}
