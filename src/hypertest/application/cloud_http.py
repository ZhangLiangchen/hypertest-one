"""Private fenced authority for bounded HTTPS reads; never performs network I/O."""
from __future__ import annotations

import base64
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from hypertest.common.ids import uuid7
from hypertest.connector.security import token_hash
from hypertest.domain.cloud_http import CloudHttpObservation, CloudHttpOperation
from hypertest.domain.cloud_tasks import CloudAttempt, CloudWorkGrant


def reject(code, status=409):
    raise HTTPException(status, code)


async def ensure_http_closed(db, *, task_id, attempt_id=None):
    observed = select(CloudHttpObservation.operation_id).where(CloudHttpObservation.state == "OBSERVED")
    query = select(CloudHttpOperation.id).where(CloudHttpOperation.task_id == task_id,
        CloudHttpOperation.id.not_in(observed))
    if attempt_id is not None:
        query = query.where(CloudHttpOperation.attempt_id == attempt_id)
    if await db.scalar(query.limit(1)):
        reject("HTTPS_REMOTE_OPERATIONS_UNRECONCILED")


async def live_operations(db, attempt_id):
    from .cloud_tasks import public
    rows = list(await db.scalars(select(CloudHttpOperation).where(
        CloudHttpOperation.attempt_id == attempt_id).order_by(CloudHttpOperation.id)))
    observations = list(await db.scalars(select(CloudHttpObservation).where(
        CloudHttpObservation.attempt_id == attempt_id).order_by(CloudHttpObservation.id)))
    result = []
    for row in rows:
        history = [item for item in observations if item.operation_id == row.id]
        accepted = next((item for item in history if item.state == "OBSERVED"), None)
        latest = accepted or (history[-1] if history else None)
        result.append({**public(row), "intent_state": row.state,
            "state": latest.state if latest else row.state,
            "observation": latest.observation if latest else None})
    return result


async def terminal_results(db, task_id):
    from .cloud_tasks import public
    rows = await db.scalars(select(CloudHttpObservation).where(
        CloudHttpObservation.task_id == task_id, CloudHttpObservation.state == "OBSERVED").order_by(CloudHttpObservation.id))
    return [public(row) for row in rows]


def authorize_environment(task, environment, now):
    from hypertest.cloud.http_profile import validate_profile
    profile = validate_profile(environment)
    authorization = task.inputs["authorization"]
    if ("environment:read" not in authorization["permitted_actions"]
            or profile.target not in authorization["targets"]
            or authorization["network_targets"] != [profile.target]):
        reject("HTTPS_EXACT_TARGET_AUTHORIZATION_REQUIRED", 403)
    expires = datetime.fromisoformat(authorization["expires_at"].replace("Z", "+00:00"))
    if now >= expires:
        reject("HTTPS_EXECUTION_AUTHORIZATION_EXPIRED", 403)
    if task.inputs.get("framework_runtime") is None:
        reject("HTTPS_FRAMEWORK_FREEZE_REQUIRED", 422)
    return profile


class WorkerHttpAuthority:
    def __init__(self, sessions, *, task_id: str, attempt_id: str, identity):
        self.sessions = sessions
        self.task_id, self.attempt_id = UUID(task_id), UUID(attempt_id)
        self.identity = identity

    async def _task_attempt(self, db):
        from . import cloud_tasks as service
        task = await service._task(db, self.task_id, lock=True)
        attempt = await db.get(CloudAttempt, self.attempt_id, populate_existing=True)
        if attempt is None or attempt.task_id != task.id:
            reject("HTTPS_ATTEMPT_IDENTITY_MISMATCH")
        return task, attempt

    async def _original(self, db, operation_id):
        row = await db.get(CloudHttpOperation, UUID(str(operation_id)), populate_existing=True)
        if row is None or row.task_id != self.task_id or row.attempt_id != self.attempt_id:
            reject("HTTPS_OPERATION_NOT_FOUND_QUERY_ONLY", 404)
        grant = await db.get(CloudWorkGrant, row.work_grant_id, populate_existing=True)
        if (grant is None or grant.token_hash != token_hash(self.identity.work_token)
                or grant.worker_id != self.identity.worker_id or grant.worker_id != row.worker_id
                or grant.lease_generation != self.identity.generation or row.generation != self.identity.generation
                or grant.attempt_id != row.attempt_id or grant.project_id != row.project_id):
            reject("HTTPS_ORIGINAL_OPERATION_OWNER_REQUIRED", 403)
        return row

    async def _profile(self, db, task, attempt):
        from . import cloud_tasks as service
        service.enabled()
        if not service.get_settings().cloud_https_enabled:
            reject("HTTPS_EXECUTION_DISABLED", 503)
        await service.worker_authority(db, task, attempt, self.identity)
        if attempt.status != "RUNNING":
            reject("HTTPS_START_REQUIRES_RUNNING_ATTEMPT")
        config = await service._configuration(db, task.project_id, task.config_id)
        if (not task.frozen_manifest or task.frozen_manifest["config_id"] != str(config.id)
                or task.frozen_manifest["configuration"] != config.configuration):
            reject("HTTPS_FROZEN_CONFIGURATION_MISMATCH")
        return authorize_environment(task, config.configuration["environment"], await service.clock(db))

    async def _record(self, db, row, *, allow_send=False):
        observation = await db.scalar(select(CloudHttpObservation).where(
            CloudHttpObservation.operation_id == row.id).order_by(
                (CloudHttpObservation.state == "OBSERVED").desc(), CloudHttpObservation.created_at.desc(), CloudHttpObservation.id.desc()).limit(1))
        return {"id": str(row.id), "operation_key": row.operation_key, "resource_key": row.resource_key,
            "request": row.request, "request_digest": row.request_digest,
            "state": observation.state if observation else row.state, "allow_send": allow_send,
            "response": observation.observation if observation else None}

    async def prepare_start(self, key, resource_key):
        from hypertest.cloud.http_operations import request_document
        from hypertest.cloud.http_profile import digest

        from . import cloud_tasks as service
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", key):
            reject("HTTPS_OPERATION_KEY_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            previous = await db.scalar(select(CloudHttpOperation).where(
                CloudHttpOperation.attempt_id == attempt.id, CloudHttpOperation.operation_key == key))
            if previous:
                row = await self._original(db, previous.id)
                if row.resource_key != resource_key:
                    reject("HTTPS_OPERATION_KEY_CONFLICT")
                return await self._record(db, row)
            profile = await self._profile(db, task, attempt)
            resource = profile.resource(resource_key)
            await service._reject_secrets(db, task.project_id, [key, resource_key])
            from .cloud_ssh import ensure_remote_closed
            await ensure_remote_closed(db, task_id=task.id)
            count = await db.scalar(select(func.count()).select_from(CloudHttpOperation).where(
                CloudHttpOperation.attempt_id == attempt.id))
            if count >= profile.max_operations:
                reject("HTTPS_OPERATION_LIMIT_EXHAUSTED")
            hold = attempt.runtime_metadata.get("budget_reservation", {})
            seconds = hold.get("reserved_seconds")
            if hold.get("state") != "HELD" or type(seconds) is not int or seconds < 1 or attempt.started_at is None:
                reject("HTTPS_RUNNING_BUDGET_RESERVATION_REQUIRED")
            runtime = attempt.runtime_metadata.get("https", {})
            absolute = runtime.get("hard_deadline_epoch")
            if runtime.get("profile") != "HTTPS_CONTROLLED_API_V1" or type(absolute) is not int:
                reject("HTTPS_FIXED_RUNTIME_DEADLINE_REQUIRED")
            now = await service.clock(db)
            deadline = int(min(attempt.started_at + timedelta(seconds=seconds),
                datetime.fromisoformat(task.inputs["authorization"]["expires_at"].replace("Z", "+00:00")),
                datetime.fromtimestamp(absolute, UTC),
                now + timedelta(seconds=resource.timeout_seconds)).timestamp())
            if deadline <= now.timestamp():
                reject("HTTPS_TASK_DEADLINE_EXHAUSTED")
            grant = await db.scalar(select(CloudWorkGrant).where(CloudWorkGrant.token_hash == token_hash(self.identity.work_token)))
            operation_id = uuid7()
            request = request_document(operation_id=str(operation_id), task_id=str(task.id), attempt_id=str(attempt.id),
                generation=self.identity.generation, target=profile.target, catalog_sha256=profile.catalog_sha256,
                resource=resource.document(), hard_deadline=deadline)
            row = CloudHttpOperation(id=operation_id, project_id=task.project_id, task_id=task.id, attempt_id=attempt.id,
                config_id=task.config_id, work_grant_id=grant.id, worker_id=self.identity.worker_id, generation=self.identity.generation,
                operation_key=key, resource_key=resource_key, target=profile.target, request_digest=digest(request),
                request=request, state="SENT", sent_at=now, hard_deadline=datetime.fromtimestamp(deadline, UTC))
            db.add(row)
            await db.flush()
            record = await self._record(db, row, allow_send=True)
            await db.commit()  # Committed before any DNS, connection or request.
            return record

    async def get_operation(self, operation_id):
        async with self.sessions() as db:
            await self._task_attempt(db)
            return await self._record(db, await self._original(db, operation_id))

    async def get_operation_by_key(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", key):
            reject("HTTPS_OPERATION_KEY_INVALID", 422)
        async with self.sessions() as db:
            await self._task_attempt(db)
            row = await db.scalar(select(CloudHttpOperation).where(
                CloudHttpOperation.attempt_id == self.attempt_id, CloudHttpOperation.operation_key == key))
            if row is None:
                reject("HTTPS_OPERATION_NOT_FOUND_QUERY_ONLY", 404)
            return await self._record(db, await self._original(db, row.id))

    async def admit_send(self, operation_id):
        from . import cloud_tasks as service
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            row = await self._original(db, operation_id)
            profile = await self._profile(db, task, attempt)
            if (row.request["catalog_sha256"] != profile.catalog_sha256
                    or row.request["resource"] != profile.resource(row.resource_key).document()
                    or row.target != profile.target or await service.clock(db) >= row.hard_deadline):
                reject("HTTPS_SEND_AUTHORITY_EXPIRED")

    async def record_response(self, operation_id, value):
        from hypertest.cloud.http_operations import project_response
        from hypertest.cloud.http_profile import digest

        from . import cloud_tasks as service
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            row = await self._original(db, operation_id)
            response = project_response(value, row.request)
            body = base64.b64decode(response["body_base64"], validate=True)
            if response["state"] == "OBSERVED":
                await self._profile(db, task, attempt)
                await service._reject_secrets(db, task.project_id, body.decode("utf-8", errors="replace"))
            metadata = {key: item for key, item in response.items() if key != "body_base64"}
            checksum = digest(metadata)
            previous = await db.scalar(select(CloudHttpObservation).where(
                CloudHttpObservation.operation_id == row.id, CloudHttpObservation.state == "OBSERVED"))
            if previous:
                if previous.observation_digest != checksum:
                    reject("HTTPS_OBSERVED_RESULT_IMMUTABLE")
                return await self._record(db, row)
            if not await db.scalar(select(CloudHttpObservation.id).where(
                    CloudHttpObservation.operation_id == row.id, CloudHttpObservation.observation_digest == checksum)):
                db.add(CloudHttpObservation(project_id=row.project_id, task_id=row.task_id, attempt_id=row.attempt_id,
                    operation_id=row.id, request_digest=row.request_digest, worker_id=row.worker_id, generation=row.generation,
                    state=response["state"], observation_digest=checksum, observation=metadata))
                await db.flush()
            record = await self._record(db, row)
            await db.commit()
            return record

    async def validate_output(self, body):
        from . import cloud_tasks as service
        if not isinstance(body, bytes) or len(body) > 262144:
            reject("HTTPS_OUTPUT_LIMIT_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            await self._profile(db, task, attempt)
            await service._reject_secrets(db, task.project_id, body.decode("utf-8", errors="replace"))

    async def remote_closed(self):
        async with self.sessions() as db:
            await self._task_attempt(db)
            try:
                await ensure_http_closed(db, task_id=self.task_id)
            except HTTPException:
                return False
            return True
