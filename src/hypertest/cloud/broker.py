"""Private DB-side Cloud Worker broker. Never imported into the SDK sandbox."""

from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from pydantic import TypeAdapter

from hypertest.api.cloud_schemas import CloudMutation
from hypertest.application import cloud_tasks as service

from .errors import CloudBlocked


class BrokerFailure(CloudBlocked):
    def __init__(self, status: int, code: str):
        self.status = status
        super().__init__(code, code)


class CloudBroker:
    def __init__(self, sessions, claim: dict, worker_id: str):
        self.sessions = sessions
        self.task_id = claim["task"]["id"]
        self.project_id = claim["task"]["project_id"]
        self.attempt_id = claim["attempt"]["id"]
        self.version = claim["task"]["version"]
        self.identity = service.WorkerIdentity(worker_id, claim["lease_token"],
            claim["generation"], claim["work_token"])
        self.actor_ref = "worker:" + worker_id
        self.writes_suspended = False

    def suspend_writes(self):
        self.writes_suspended = True

    def _require_writes(self):
        if self.writes_suspended:
            raise CloudBlocked("WORKER_WRITES_SUSPENDED", "Worker may only reconcile original operations after interruption")

    async def fence_for_recovery(self, reason, *, metadata=None):
        self.suspend_writes()
        async with self.sessions() as db:
            return await service.fence_attempt_for_recovery(db, UUID(self.task_id), UUID(self.attempt_id),
                self.identity, reason, metadata=metadata)

    async def assert_current(self):
        self._require_writes()
        async with self.sessions() as db:
            self._require_writes()
            task = await service._task(db, UUID(self.task_id), UUID(self.project_id))
            attempt = await service._attempt(db, task, UUID(self.attempt_id))
            await service.worker_authority(db, task, attempt, self.identity)

    async def renew(self, lease_seconds: int):
        self._require_writes()
        async with self.sessions() as db:
            return await service.renew_lease(db, UUID(self.attempt_id), self.identity.worker_id,
                self.identity.lease_token, self.identity.generation, self.identity.work_token,
                lease_seconds=lease_seconds)

    async def container_authority_deadline_ns(self):
        """Conservatively bound one guard heartbeat by freshly checked DB authority."""
        from sqlalchemy import select

        from hypertest.connector.security import token_hash
        from hypertest.domain.cloud_tasks import CloudWorkGrant
        from hypertest.domain.interactive import InteractiveIntegrationGrant

        self._require_writes()
        before = time.monotonic_ns()
        try:
            async with self.sessions() as db:
                task = await service._task(db, UUID(self.task_id), UUID(self.project_id), lock=True)
                attempt = await service._attempt(db, task, UUID(self.attempt_id))
                await service.worker_authority(db, task, attempt, self.identity)
                grant = await db.scalar(select(CloudWorkGrant).where(
                    CloudWorkGrant.token_hash == token_hash(self.identity.work_token)))
                config = await service._configuration(db, task.project_id, task.config_id)
                credentials = await service._credential_versions(db, config.configuration)
                dispatch = await db.get(InteractiveIntegrationGrant, attempt.authorization_grant_id) if attempt.authorization_grant_id else None
                now = await service.clock(db)
                auth = datetime.fromisoformat(task.inputs["authorization"]["expires_at"].replace("Z", "+00:00"))
                ends = [now + timedelta(seconds=3), attempt.lease_expires_at, grant.expires_at, auth]
                if dispatch and dispatch.expires_at is not None:
                    ends.append(dispatch.expires_at)
                ends.extend(version.expires_at for _, version, _ in credentials if version.expires_at is not None)
                remaining = (min(ends) - now).total_seconds()
                if remaining <= 0:
                    raise ValueError
                self._require_writes()
                return before + int(remaining * 1_000_000_000) - 250_000_000
        except (HTTPException, ValueError, TypeError, KeyError, AttributeError):
            raise CloudBlocked("WORKER_FENCED", "Current Cloud authority cannot authorize a container heartbeat") from None

    async def credentials(self):
        self._require_writes()
        async with self.sessions() as db:
            return await service.materialize_credentials(db, UUID(self.task_id), UUID(self.attempt_id), self.identity)

    async def submit(self, payload: dict):
        self._require_writes()
        typed = TypeAdapter(CloudMutation).validate_python(payload)
        if typed.operation in {"PREPARE_CONTAINER_CREATE", "CONFIRM_CONTAINER_ID", "PREPARE_CONTAINER_START", "OBSERVE_CONTAINER_STOP", "OBSERVE_CONTAINER_NEVER_STARTED"}:
            raise CloudBlocked("ENGINE_OBSERVATION_REQUIRED", "Container operations require the private Engine path")
        try:
            async with self.sessions() as db:
                self._require_writes()
                return await service.mutate(db, typed, self.actor_ref, worker=self.identity)
        except HTTPException as error:
            raise BrokerFailure(error.status_code, "CLOUD_OPERATION_REJECTED") from None

    async def prepare_container_create(self, *, operation_key, expected_version, container_name,
                                       image_id, spec_sha256, key_sha256, clock_sha256, recovery_sha256, recovery_root,
                                       hard_deadline, spec):
        """Record a proposed original identity; never create or confirm a container."""
        from .container_recovery import RecoveryIdentity, load_recovery_capability

        self._require_writes()
        identity = RecoveryIdentity(self.project_id, self.task_id, self.attempt_id, operation_key,
                                    self.identity.generation, self.identity.worker_id)
        load_recovery_capability(recovery_root, identity, recovery_sha256)
        typed = TypeAdapter(CloudMutation).validate_python({"operation": "PREPARE_CONTAINER_CREATE", "project_id": self.project_id,
            "task_id": self.task_id, "attempt_id": self.attempt_id, "operation_key": operation_key,
            "expected_version": expected_version, "container_name": container_name, "image_id": image_id,
            "spec_sha256": spec_sha256, "key_sha256": key_sha256, "clock_sha256": clock_sha256,
            "recovery_sha256": recovery_sha256, "hard_deadline": hard_deadline, "spec": spec})
        try:
            async with self.sessions() as db:
                self._require_writes()
                return await service.mutate(db, typed, self.actor_ref, worker=self.identity, container_recovery_provisioned=True)
        except HTTPException as error:
            raise BrokerFailure(error.status_code, "CLOUD_OPERATION_REJECTED") from None

    async def observe_container(self, *, engine, create_operation_key, container_id, operation_key,
                                expected_version, stopped, recovery=False, recovery_secret=None):
        """Query the Engine directly before recording the original container observation."""
        from .docker_attempt_spec import verify_inspect

        if not recovery:
            self._require_writes()
        if type(stopped) is not bool or type(recovery) is not bool or (recovery and not stopped):
            raise CloudBlocked("ENGINE_OBSERVATION_INVALID", "Container observation mode is invalid")
        intent_receipt = await self.receipt(create_operation_key)
        intent = intent_receipt.get("container_create_intent", {})
        raw = await engine.inspect_raw()
        try:
            observation = verify_inspect(intent["spec"], container_id=container_id, observed=raw)
        except (ValueError, KeyError, TypeError):
            raise CloudBlocked("ENGINE_IDENTITY_MISMATCH", "Engine observation does not match the original spec") from None
        expected_status = "exited" if stopped else "created"
        if observation["status"] != expected_status or observation["running"] or observation["pid"] != 0:
            raise CloudBlocked("ENGINE_STATE_UNCONFIRMED", "Original container state is not confirmed")
        operation = "OBSERVE_CONTAINER_STOP" if stopped else "CONFIRM_CONTAINER_ID"
        typed = TypeAdapter(CloudMutation).validate_python({"operation": operation, "project_id": self.project_id,
            "task_id": self.task_id, "attempt_id": self.attempt_id, "operation_key": operation_key,
            "expected_version": expected_version, "create_operation_key": create_operation_key,
            "container_id": container_id, "spec_sha256": intent["spec_sha256"],
            "engine_status": observation["status"], "exit_code": observation["exit_code"]})
        try:
            async with self.sessions() as db:
                if not recovery:
                    self._require_writes()
                return await service.mutate(db, typed, self.actor_ref, worker=self.identity, container_observed=True,
                    container_recovery=recovery, container_recovery_secret=recovery_secret)
        except HTTPException as error:
            raise BrokerFailure(error.status_code, "CLOUD_OPERATION_REJECTED") from None

    async def prepare_container_start(self, *, engine, create_operation_key, container_id, operation_key, expected_version):
        """Freeze the single original start intent after a fresh Engine identity read."""
        from .docker_attempt_spec import verify_inspect

        self._require_writes()
        intent_receipt = await self.receipt(create_operation_key)
        intent = intent_receipt.get("container_create_intent", {})
        raw = await engine.inspect_raw()
        try:
            observation = verify_inspect(intent["spec"], container_id=container_id, observed=raw)
        except (ValueError, KeyError, TypeError):
            raise CloudBlocked("ENGINE_IDENTITY_MISMATCH", "Engine observation does not match the original spec") from None
        if observation["status"] != "created" or observation["running"] or observation["pid"] != 0:
            raise CloudBlocked("ENGINE_STATE_UNCONFIRMED", "Original container state is not confirmed")
        typed = TypeAdapter(CloudMutation).validate_python({"operation": "PREPARE_CONTAINER_START",
            "project_id": self.project_id, "task_id": self.task_id, "attempt_id": self.attempt_id,
            "operation_key": operation_key, "expected_version": expected_version,
            "create_operation_key": create_operation_key, "container_id": container_id, "spec_sha256": intent["spec_sha256"]})
        try:
            async with self.sessions() as db:
                self._require_writes()
                return await service.mutate(db, typed, self.actor_ref, worker=self.identity, container_observed=True)
        except HTTPException as error:
            raise BrokerFailure(error.status_code, "CLOUD_OPERATION_REJECTED") from None

    async def recover_created_container(self, *, engine, create_operation_key, operation_key, expected_version,
                                        recovery_root, confirmed_id=None):
        """Only read the original name/ID and append a never-started recovery observation.

        First call with no ID binds the observed original ID. A later call with
        that confirmed ID rechecks it by ID and records NEVER_STARTED. Neither
        call may create, start, or remove a container.
        """
        from .container_recovery import RecoveryIdentity, load_recovery_capability
        from .docker_attempt_spec import verify_inspect

        receipt = await self.receipt(create_operation_key)
        intent = receipt.get("container_create_intent", {})
        identity = RecoveryIdentity(self.project_id, self.task_id, self.attempt_id, create_operation_key,
                                    self.identity.generation, self.identity.worker_id)
        capability = load_recovery_capability(recovery_root, identity, intent.get("recovery_sha256", ""))
        by_name = await engine.inspect_raw()
        if confirmed_id is not None:
            try:
                verify_inspect(intent["spec"], container_id=confirmed_id, observed=by_name)
            except (ValueError, KeyError, TypeError):
                raise CloudBlocked("ENGINE_IDENTITY_MISMATCH", "Original name no longer identifies the confirmed container") from None
            raw = await engine.inspect_raw_id(confirmed_id)
        else:
            raw = by_name
        container_id = raw.get("Id") if isinstance(raw, dict) else None
        try:
            observation = verify_inspect(intent["spec"], container_id=container_id, observed=raw)
            state = raw["State"]
            if (confirmed_id is not None and container_id != confirmed_id or observation["status"] != "created"
                    or observation["running"] or observation["pid"] != 0 or observation["exit_code"] != 0
                    or state["StartedAt"] != "0001-01-01T00:00:00Z"
                    or state["FinishedAt"] != "0001-01-01T00:00:00Z" or raw["RestartCount"] != 0):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise CloudBlocked("ENGINE_STATE_UNCONFIRMED", "Original container was not confirmed never started") from None
        operation = "CONFIRM_CONTAINER_ID" if confirmed_id is None else "OBSERVE_CONTAINER_NEVER_STARTED"
        typed = TypeAdapter(CloudMutation).validate_python({"operation": operation, "project_id": self.project_id,
            "task_id": self.task_id, "attempt_id": self.attempt_id, "operation_key": operation_key,
            "expected_version": expected_version, "create_operation_key": create_operation_key,
            "container_id": container_id, "spec_sha256": intent["spec_sha256"], "engine_status": "created", "exit_code": 0})
        try:
            async with self.sessions() as db:
                return await service.mutate(db, typed, self.actor_ref, worker=self.identity, container_observed=True,
                    container_recovery=True, container_recovery_secret=capability.secret)
        except HTTPException as error:
            raise BrokerFailure(error.status_code, "CLOUD_OPERATION_REJECTED") from None

    async def validate_payload(self, payload: dict):
        """Reject known secret material before any durable private request copy."""
        values = [payload]
        if payload.get("operation") == "UPLOAD_ARTIFACT":
            raw = base64.b64decode(payload["content_base64"], validate=True)
            values.append(raw.decode("utf-8", errors="replace"))
        await self.assert_current()
        async with self.sessions() as db:
            await service._reject_secrets(db, UUID(self.project_id), values)

    async def receipt(self, key: str):
        # Original owner reads may survive a fence. This never grants new work.
        try:
            async with self.sessions() as db:
                return await service.receipt_view(db, UUID(self.project_id), key, self.actor_ref)
        except HTTPException as error:
            raise BrokerFailure(error.status_code, "CLOUD_RECEIPT_UNAVAILABLE") from None

    async def page(self, *, version: int, offset: int, limit: int):
        async with self.sessions() as db:
            return await service.read_task(db, UUID(self.task_id), project_id=UUID(self.project_id),
                version=version, offset=offset, limit=limit)

    async def artifact(self, artifact_id: str) -> bytes:
        chunks, offset, total = [], 0, None
        while True:
            async with self.sessions() as db:
                page = await service.artifact_bytes(db, UUID(self.project_id), UUID(self.task_id),
                    UUID(artifact_id), offset=offset, length=65536)
            if page.get("offset") != offset:
                raise CloudBlocked("ARTIFACT_READBACK_MISMATCH", "Artifact chunks are not contiguous")
            if total is None:
                total = page["byte_count"]
            if page.get("byte_count") != total or total > 8 * 1024 * 1024:
                raise CloudBlocked("ARTIFACT_READBACK_LIMIT", "Artifact identity or size changed")
            content = base64.b64decode(page["content_base64"], validate=True)
            chunks.append(content)
            offset += len(content)
            if page.get("next_offset") != offset:
                raise CloudBlocked("ARTIFACT_READBACK_MISMATCH", "Artifact chunk offsets differ")
            if page.get("complete"):
                if offset != total:
                    raise CloudBlocked("ARTIFACT_READBACK_MISMATCH", "Artifact original is incomplete")
                return b"".join(chunks)
            if not content:
                raise CloudBlocked("ARTIFACT_READBACK_MISMATCH", "Artifact readback made no progress")
