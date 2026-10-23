"""Private DB-side Cloud Worker broker. Never imported into the SDK sandbox."""

from __future__ import annotations

import base64
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

    async def assert_current(self):
        async with self.sessions() as db:
            task = await service._task(db, UUID(self.task_id), UUID(self.project_id))
            attempt = await service._attempt(db, task, UUID(self.attempt_id))
            await service.worker_authority(db, task, attempt, self.identity)

    async def renew(self, lease_seconds: int):
        async with self.sessions() as db:
            return await service.renew_lease(db, UUID(self.attempt_id), self.identity.worker_id,
                self.identity.lease_token, self.identity.generation, self.identity.work_token,
                lease_seconds=lease_seconds)

    async def credentials(self):
        async with self.sessions() as db:
            return await service.materialize_credentials(db, UUID(self.task_id), UUID(self.attempt_id), self.identity)

    async def submit(self, payload: dict):
        typed = TypeAdapter(CloudMutation).validate_python(payload)
        try:
            async with self.sessions() as db:
                return await service.mutate(db, typed, self.actor_ref, worker=self.identity)
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
