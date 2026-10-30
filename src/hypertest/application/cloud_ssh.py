"""Private fenced SSH intent authority. This module never performs SSH or I/O.

The host runtime signs the returned short ticket admission and performs network
I/O after this transaction is closed. Agents receive none of this authority.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select

from hypertest.common.ids import uuid7
from hypertest.connector.security import token_hash
from hypertest.domain.cloud_tasks import (
    CloudAttempt,
    CloudRemoteObservation,
    CloudRemoteOperation,
    CloudRemoteOperationResult,
    CloudWorkGrant,
    ProjectCloudConfigRevision,
)

REMOTE_TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


def reject(code, status=409):
    raise HTTPException(status, code)


async def ensure_remote_closed(db, *, task_id, attempt_id=None):
    query = select(CloudRemoteOperation.id).outerjoin(CloudRemoteOperationResult,
        CloudRemoteOperationResult.operation_id == CloudRemoteOperation.id).where(
        CloudRemoteOperation.task_id == task_id, CloudRemoteOperationResult.id.is_(None))
    if attempt_id is not None:
        query = query.where(CloudRemoteOperation.attempt_id == attempt_id)
    if await db.scalar(query.limit(1)):
        reject("SSH_REMOTE_OPERATIONS_UNRECONCILED")
    from .cloud_http import ensure_http_closed
    await ensure_http_closed(db, task_id=task_id, attempt_id=attempt_id)
    from .cloud_actions import ensure_actions_closed
    await ensure_actions_closed(db, task_id=task_id, attempt_id=attempt_id)


async def terminal_results(db, task_id):
    from .cloud_tasks import public
    rows = await db.scalars(select(CloudRemoteOperationResult).where(
        CloudRemoteOperationResult.task_id == task_id).order_by(CloudRemoteOperationResult.id))
    return [public(row) for row in rows]


async def live_operations(db, attempt_id):
    from .cloud_tasks import public
    rows = await db.scalars(select(CloudRemoteOperation).where(
        CloudRemoteOperation.attempt_id == attempt_id).order_by(CloudRemoteOperation.id))
    # Only bounded request metadata. No private key, work token or ticket exists
    # in this table; this projection never becomes a historical Task snapshot.
    return [public(row) for row in rows]


def exact_target(environment):
    if environment.get("connection") == "HTTPS" and environment.get("https_access") is not None:
        from hypertest.cloud.http_profile import validate_profile
        return validate_profile(environment).target
    if environment.get("connection") == "SSH" and environment.get("ssh_access") is not None:
        from hypertest.cloud.ssh_profile import validate_profile
        return validate_profile(environment).target
    return environment.get("host")


def authorize_environment(task, environment, now, *, cleanup=False):
    from hypertest.cloud.ssh_profile import validate_profile
    profile = validate_profile(environment)
    authorization = task.inputs["authorization"]
    if ("environment:read" not in authorization["permitted_actions"]
            or profile.target not in authorization["targets"]
            or profile.target not in authorization["network_targets"]):
        reject("SSH_EXACT_TARGET_AUTHORIZATION_REQUIRED", 403)
    expires = datetime.fromisoformat(authorization["expires_at"].replace("Z", "+00:00"))
    if not cleanup and now >= expires:
        reject("SSH_EXECUTION_AUTHORIZATION_EXPIRED", 403)
    return profile


class WorkerSshAuthority:
    def __init__(self, sessions, *, task_id: str, attempt_id: str, identity):
        self.sessions = sessions
        self.task_id, self.attempt_id = UUID(task_id), UUID(attempt_id)
        self.identity = identity

    async def _task_attempt(self, db):
        from . import cloud_tasks as service
        task = await service._task(db, self.task_id, lock=True)
        attempt = await db.get(CloudAttempt, self.attempt_id, populate_existing=True)
        if attempt is None or attempt.task_id != task.id:
            reject("SSH_ATTEMPT_IDENTITY_MISMATCH")
        return task, attempt

    async def _operation(self, db, operation_id):
        row = await db.scalar(select(CloudRemoteOperation).where(
            CloudRemoteOperation.id == UUID(str(operation_id))).with_for_update())
        if row is None or row.task_id != self.task_id or row.attempt_id != self.attempt_id:
            reject("SSH_OPERATION_NOT_FOUND_QUERY_ONLY", 404)
        grant = await db.get(CloudWorkGrant, row.work_grant_id, populate_existing=True)
        # This is original-operation cleanup identity, not a replacement lease.
        # Expired/revoked grants cannot START again; they only identify the host
        # that already owns this exact intent for QUERY/STOP/append observation.
        if (grant is None or grant.token_hash != token_hash(self.identity.work_token)
                or grant.worker_id != self.identity.worker_id or grant.worker_id != row.worker_id
                or grant.lease_generation != self.identity.generation or row.generation != self.identity.generation
                or grant.attempt_id != row.attempt_id or grant.project_id != row.project_id):
            reject("SSH_ORIGINAL_OPERATION_OWNER_REQUIRED", 403)
        return row

    async def _profile(self, db, task, *, cleanup=False):
        from . import cloud_tasks as service
        now = await service.clock(db)
        if cleanup:
            config = await db.get(ProjectCloudConfigRevision, task.config_id)
            if config is None or config.project_id != task.project_id:
                reject("SSH_FROZEN_CONFIGURATION_MISMATCH")
            # Revoking an unrelated Git credential must not prevent a narrow
            # original-operation SSH cleanup. Its SSH credential still must be
            # ACTIVE, current, correctly scoped and unexpired for new transport.
            rows = await service._credential_versions(db, {"sut": {}, "framework": {},
                "environment": config.configuration["environment"]}, now=now)
            if any(version.project_id != task.project_id for _, version, _ in rows):
                reject("SSH_CREDENTIAL_PROJECT_MISMATCH", 403)
        else:
            config = await service._configuration(db, task.project_id, task.config_id)
        if (not task.frozen_manifest or str(config.id) != task.frozen_manifest["config_id"]
                or config.configuration != task.frozen_manifest["configuration"]):
            reject("SSH_FROZEN_CONFIGURATION_MISMATCH")
        environment = config.configuration["environment"]
        profile = authorize_environment(task, environment, now, cleanup=cleanup)
        if not environment.get("credential_version_id"):
            reject("SSH_CREDENTIAL_VERSION_REQUIRED")
        # _configuration checks current credential ACTIVE/expiry/type, exact
        # canonical target and allowed_actions on every new transport admission.
        return profile, environment, now

    def _record(self, row, attempt, *, allow_send=False, authority_mode=None, ticket_expires_at=None):
        return {"id": str(row.id), "operation_key": row.operation_key, "action_key": row.action_key,
            "project_id": str(row.project_id), "task_id": str(row.task_id), "attempt_id": str(row.attempt_id),
            "config_id": str(row.config_id), "credential_version_id": str(row.credential_version_id),
            "generation": row.generation, "target": row.target, "request": row.request,
            "request_digest": row.request_digest, "state": row.state, "allow_send": allow_send,
            "hard_deadline": int(row.hard_deadline.timestamp()),
            "lease_expires_at": int(attempt.lease_expires_at.timestamp()) if attempt.lease_expires_at else None,
            "ticket_generation": attempt.lease_generation,
            "ticket_expires_at": ticket_expires_at, "authority_mode": authority_mode}

    async def prepare_start(self, key, action_key):
        from hypertest.cloud.ssh_profile import digest, request_document

        from . import cloud_tasks as service
        if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", key) is None:
            reject("SSH_OPERATION_KEY_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            previous = await db.scalar(select(CloudRemoteOperation).where(
                CloudRemoteOperation.attempt_id == attempt.id, CloudRemoteOperation.operation_key == key))
            if previous:
                row = await self._operation(db, previous.id)
                if row.action_key != action_key:
                    reject("SSH_OPERATION_KEY_CONFLICT")
                return self._record(row, attempt)  # Never another START admission.
            service.enabled()
            if not getattr(service.get_settings(), "cloud_ssh_enabled", False):
                reject("SSH_EXECUTION_DISABLED", 503)
            await service.worker_authority(db, task, attempt, self.identity)
            if attempt.status != "RUNNING":
                reject("SSH_START_REQUIRES_RUNNING_ATTEMPT")
            profile, environment, now = await self._profile(db, task)
            action = profile.action(action_key)
            await service._reject_secrets(db, task.project_id, [key, action_key])
            await ensure_remote_closed(db, task_id=task.id)
            count = await db.scalar(select(func.count()).select_from(CloudRemoteOperation).where(
                CloudRemoteOperation.attempt_id == attempt.id))
            if count >= profile.max_operations:
                reject("SSH_OPERATION_LIMIT_EXHAUSTED")
            hold = attempt.runtime_metadata.get("budget_reservation", {})
            seconds = hold.get("reserved_seconds")
            if hold.get("state") != "HELD" or type(seconds) is not int or seconds < 1 or attempt.started_at is None:
                reject("SSH_RUNNING_BUDGET_RESERVATION_REQUIRED")
            runtime = attempt.runtime_metadata.get("ssh", {})
            absolute = runtime.get("hard_deadline_epoch")
            if runtime.get("profile") != "SSH_FIXED_DIAGNOSTICS_V1" or type(absolute) is not int:
                reject("SSH_FIXED_RUNTIME_DEADLINE_REQUIRED")
            authorization_end = datetime.fromisoformat(task.inputs["authorization"]["expires_at"].replace("Z", "+00:00"))
            deadline = int(min(datetime.fromtimestamp(absolute, UTC), attempt.started_at + timedelta(seconds=seconds), authorization_end,
                now + timedelta(seconds=action.timeout_seconds)).timestamp())
            if deadline <= now.timestamp():
                reject("SSH_TASK_DEADLINE_EXHAUSTED")
            grant = await db.scalar(select(CloudWorkGrant).where(
                CloudWorkGrant.token_hash == token_hash(self.identity.work_token)))
            operation_id = uuid7()
            request = request_document(operation_id=str(operation_id), task_id=str(task.id), attempt_id=str(attempt.id),
                generation=self.identity.generation, target=profile.target, helper_sha256=profile.helper_sha256,
                catalog_sha256=profile.catalog_sha256, action=action.document(), hard_deadline=deadline)
            row = CloudRemoteOperation(id=operation_id, project_id=task.project_id, task_id=task.id, attempt_id=attempt.id,
                config_id=task.config_id, credential_version_id=UUID(environment["credential_version_id"]),
                work_grant_id=grant.id, worker_id=self.identity.worker_id, generation=self.identity.generation,
                operation_key=key, action_key=action_key, target=profile.target, request_digest=digest(request),
                request=request, state="SENT", sent_at=now, hard_deadline=datetime.fromtimestamp(deadline, UTC), last_sequence=0)
            db.add(row)
            await db.flush()
            record = self._record(row, attempt, allow_send=True, authority_mode="CURRENT",
                ticket_expires_at=int(min(attempt.lease_expires_at, authorization_end,
                    datetime.fromtimestamp(deadline, UTC), now + timedelta(seconds=60)).timestamp()))
            await db.commit()  # The unique SENT record precedes any signing/SSH.
            return record

    async def get_operation(self, operation_id):
        async with self.sessions() as db:
            _, attempt = await self._task_attempt(db)
            row = await self._operation(db, operation_id)
            return self._record(row, attempt)

    async def admit_control(self, operation_id, verb):
        if verb not in {"QUERY", "STOP"}:
            reject("SSH_CLEANUP_CANNOT_START", 403)
        from . import cloud_tasks as service
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            row = await self._operation(db, operation_id)
            # Fencing the original work lease permits narrow cleanup, whereas
            # revoking Project authorization forbids every new SSH transport.
            await service._current_grant(db, attempt.authorization_grant_id, task.project_id)
            profile, environment, now = await self._profile(db, task, cleanup=True)
            if (profile.target != row.target or str(row.config_id) != str(task.config_id)
                    or str(row.credential_version_id) != environment["credential_version_id"]):
                reject("SSH_ORIGINAL_TARGET_CHANGED")
            try:
                await service.worker_authority(db, task, attempt, self.identity)
                mode = "CURRENT"
            except HTTPException:
                mode = "CLEANUP"
            return self._record(row, attempt, authority_mode=mode, ticket_expires_at=int((now + timedelta(seconds=60)).timestamp()))

    async def record_observation(self, operation_id, value):
        from hypertest.cloud.ssh_profile import digest, project_observation

        from . import cloud_tasks as service
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            row = await self._operation(db, operation_id)
            observation = project_observation(value, row.request)
            checksum = digest(observation)
            existing = await db.scalar(select(CloudRemoteObservation).where(
                CloudRemoteObservation.operation_id == row.id, CloudRemoteObservation.observation_digest == checksum))
            if existing:
                return self._record(row, attempt)
            if row.state in REMOTE_TERMINAL:
                reject("SSH_TERMINAL_RESULT_IMMUTABLE")
            if row.last_sequence >= 256:
                reject("SSH_OBSERVATION_LIMIT_EXHAUSTED")
            try:
                await service.worker_authority(db, task, attempt, self.identity)
                mode = "CURRENT"
            except HTTPException:
                mode = "CLEANUP"  # Metadata append only; no transport/materialization.
            previous = list(await db.scalars(select(CloudRemoteObservation).where(CloudRemoteObservation.operation_id == row.id)))
            identity = observation["remote_identity"]
            conflict = any(any(old.observation["remote_identity"][key] is not None
                and identity[key] is not None and old.observation["remote_identity"][key] != identity[key]
                for key in ("boot_id", "invocation_id")) for old in previous)
            row.last_sequence += 1
            observed = CloudRemoteObservation(id=uuid7(), project_id=row.project_id, task_id=row.task_id,
                attempt_id=row.attempt_id, operation_id=row.id, request_digest=row.request_digest,
                sequence=row.last_sequence, observation_digest=checksum, observation=observation,
                worker_id=self.identity.worker_id, generation=self.identity.generation, authority_mode=mode)
            db.add(observed)
            # State and sequence change in one flush. The database rejects a
            # second state-only UPDATE without the matching new observation.
            result = None
            if not conflict and observation["state"] in REMOTE_TERMINAL and observation["remote_stopped"] is True:
                row.state = observation["state"]
                result = CloudRemoteOperationResult(id=uuid7(), project_id=row.project_id, task_id=row.task_id,
                    attempt_id=row.attempt_id, operation_id=row.id, request_digest=row.request_digest,
                    observation_id=observed.id, terminal_state=row.state, request=row.request, observation=observation)
            elif conflict or observation["state"] in {"UNKNOWN", "NOT_FOUND"} or observation["state"] in REMOTE_TERMINAL:
                row.state = "UNKNOWN"
            elif observation["state"] in {"RUNNING", "STOP_REQUESTED"}:
                row.state = "STOP_REQUESTED" if row.state == "STOP_REQUESTED" else observation["state"]
            await db.flush()
            if result is not None:
                db.add(result)  # The immutable observation exists before its result trigger.
            await db.commit()
            return self._record(row, attempt)

    async def assert_current(self):
        from . import cloud_tasks as service
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            service.enabled()
            if not getattr(service.get_settings(), "cloud_ssh_enabled", False):
                reject("SSH_EXECUTION_DISABLED", 503)
            await service.worker_authority(db, task, attempt, self.identity)
            await self._profile(db, task)

    async def validate_output(self, stdout: bytes, stderr: bytes):
        from . import cloud_tasks as service
        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes) or max(len(stdout), len(stderr)) > 65536:
            reject("SSH_OUTPUT_LIMIT_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._task_attempt(db)
            # Safe stopped metadata may be appended after fencing. Returning
            # remote bytes to an Agent is a separate current-authority action.
            await service.worker_authority(db, task, attempt, self.identity)
            await self._profile(db, task)
            await service._reject_secrets(db, task.project_id,
                [stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")])

    async def remote_closed(self):
        async with self.sessions() as db:
            await self._task_attempt(db)
            try:
                await ensure_remote_closed(db, task_id=self.task_id)
            except HTTPException:
                return False
            return True
