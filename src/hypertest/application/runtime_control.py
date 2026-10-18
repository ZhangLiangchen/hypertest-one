"""Narrow PostgreSQL requests from unprivileged API to trusted execution Worker."""
from __future__ import annotations

import asyncio
import shutil
from datetime import timedelta
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import ConflictError
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.domain.harness import RuntimeControlRequest


async def request_control(session: AsyncSession, operation: str, payload: dict,
                          *, wait: bool = True) -> dict:
    if operation not in {"CAPABILITIES", "ENVIRONMENTS", "RESOLVE_ENVIRONMENT", "CLEANUP_JOB", "RECOVER_BINDING"}:
        raise ValueError("unsupported execution control operation")
    duration = get_settings().runtime_control_timeout_seconds
    now = await session.scalar(select(func.clock_timestamp()))
    request = RuntimeControlRequest(id=uuid7(), operation=operation, payload=payload,
                                    expires_at=now + timedelta(seconds=duration), status="QUEUED")
    session.add(request)
    await session.commit()
    if not wait:
        return {"request_id": str(request.id), "status": "QUEUED"}
    request_id = request.id
    deadline = asyncio.get_running_loop().time() + duration
    while asyncio.get_running_loop().time() < deadline:
        request = await session.scalar(select(RuntimeControlRequest).where(RuntimeControlRequest.id == request_id)
                                       .execution_options(populate_existing=True))
        await session.commit()
        if request.status == "SUCCEEDED":
            return request.result or {}
        if request.status in {"FAILED", "UNKNOWN"}:
            raise ConflictError(f"execution component request failed: {request.error_code}")
        await asyncio.sleep(0.15)
    raise ConflictError("execution component did not confirm the operation; inspect request status before retry")


async def dispatch_control(session: AsyncSession, operation: str, payload: dict) -> dict:
    from hypertest.runner.environments import environment_catalog, resolve_environment

    if operation == "ENVIRONMENTS":
        return {"profiles": await environment_catalog()}
    if operation == "RESOLVE_ENVIRONMENT":
        from hypertest.domain.environments import EnvironmentRequest
        return {"binding": await resolve_environment(EnvironmentRequest.model_validate(payload))}
    if operation == "CAPABILITIES":
        from hypertest.application.jobs import get_worker_status
        from hypertest.runner.backends import DockerRunner

        settings = get_settings()
        providers, backends, profile = [], [], {}
        if settings.harness_mode == "bridge":
            from hypertest.application.persistent import bridge_client

            profile = {"execution_profile": "run-persistent-harness/v1", "harness_bridge": "UNAVAILABLE"}
            try:
                capabilities = await bridge_client().capabilities()
                if (capabilities.get("profile") == "run-persistent-harness/v1"
                        and capabilities.get("host_id") == settings.bridge_host_id):
                    providers, profile["harness_bridge"] = ["codex"], "READY"
            except (RuntimeError, OSError, ValueError):
                pass
        else:
            providers = ["codex"] if shutil.which(settings.codex_binary) else []
        try:
            await DockerRunner().fingerprint()
            backends = ["docker"]
        except (RuntimeError, OSError, ValueError):
            pass
        if settings.harness_mode == "legacy" and settings.runner_allow_local:
            backends.append("local")
        return {"agent_providers": providers, "runner_backends": backends,
                "workspace_root": settings.workspace_root, "runner_image": settings.runner_image,
                "mode": "single_operator", **profile, "worker": await get_worker_status(session)}
    if operation == "CLEANUP_JOB":
        from hypertest.application.jobs import cleanup_job_resources, get_job
        from hypertest.domain.jobs import ACTIVE_JOB_STATUSES
        job = await get_job(session, UUID(payload["job_id"]))
        if job.status in ACTIVE_JOB_STATUSES:
            raise ConflictError("cleanup requires a terminated job")
        await session.commit()
        return await cleanup_job_resources(session, job, on_worker=True)
    if operation == "RECOVER_BINDING":
        from hypertest.application.persistent import recover_binding
        return await recover_binding(session, UUID(payload["binding_id"]),
                                     expected_epoch=payload["expected_epoch"],
                                     expected_row_version=payload["expected_row_version"])
    raise ValueError("unsupported execution control operation")


async def process_control_request(session_factory) -> bool:
    async with session_factory() as session:
        now = await session.scalar(select(func.clock_timestamp()))
        # Crashed requests are observable unknowns, never silently re-executed.
        expired = await session.scalars(select(RuntimeControlRequest).where(
            RuntimeControlRequest.status.in_(["QUEUED", "RUNNING"]), RuntimeControlRequest.expires_at <= now)
            .with_for_update(skip_locked=True))
        for item in expired:
            item.status, item.error_code, item.finished_at = "UNKNOWN", "CONTROL_DEADLINE_EXPIRED", now
        request = await session.scalar(select(RuntimeControlRequest).where(
            RuntimeControlRequest.status == "QUEUED", RuntimeControlRequest.expires_at > now)
            .order_by(RuntimeControlRequest.created_at).with_for_update(skip_locked=True).limit(1))
        if request is None:
            await session.commit()
            return False
        deadline_start = asyncio.get_running_loop().time()
        now = await session.scalar(select(func.clock_timestamp()))
        if request.expires_at <= now:
            request.status, request.error_code, request.finished_at = "UNKNOWN", "CONTROL_DEADLINE_EXPIRED", now
            await session.commit()
            return True
        request_id, operation, payload = request.id, request.operation, dict(request.payload)
        deadline = deadline_start + (request.expires_at - now).total_seconds()
        request.status, request.started_at = "RUNNING", now
        await session.commit()
    result, error, outcome_unknown = None, None, False
    try:
        # Queue time belongs to the original deadline; claiming cannot extend it.
        async with asyncio.timeout_at(deadline):
            async with session_factory() as session:
                result = await dispatch_control(session, operation, payload)
    except TimeoutError:
        # Cancelling the coroutine cannot prove a host operation had no effect.
        error, outcome_unknown = "CONTROL_DEADLINE_EXPIRED", True
    except Exception as exc:
        # Operational errors have bounded categories, never arbitrary subprocess output.
        category = getattr(exc, "code", None)
        error = (category if isinstance(category, str) else type(exc).__name__.upper())[:64]
        outcome_unknown = error == "OUTCOME_UNKNOWN"
    async with session_factory() as session:
        request = await session.scalar(select(RuntimeControlRequest).where(RuntimeControlRequest.id == request_id).with_for_update())
        if request.status == "RUNNING":
            finished_at = await session.scalar(select(func.clock_timestamp()))
            if finished_at >= request.expires_at:
                error, outcome_unknown = "CONTROL_DEADLINE_EXPIRED", True
            request.status = "UNKNOWN" if outcome_unknown else "FAILED" if error else "SUCCEEDED"
            request.result = None if outcome_unknown else jsonable_encoder(result)
            request.error_code, request.finished_at = error, finished_at
            await session.commit()
    return True


async def serve_runtime_control(session_factory, stopping: asyncio.Event) -> None:
    while not stopping.is_set():
        try:
            processed = await process_control_request(session_factory)
        except Exception:
            processed = False
        if not processed:
            try:
                await asyncio.wait_for(stopping.wait(), timeout=0.25)
            except TimeoutError:
                pass
