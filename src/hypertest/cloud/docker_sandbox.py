"""Trusted Worker's single-Attempt Docker adapter and original-key lifecycle."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from pathlib import Path

from .clock_domain import clock_domain_digest
from .container_recovery import RecoveryIdentity, create_recovery_capability
from .docker_attempt import DockerAttempt
from .docker_attempt_spec import build_spec
from .errors import CloudBlocked


class DockerSandbox:
    """Compose preverified Engine/volume admission with the current Cloud broker.

    ``observe_envelope`` must freshly enumerate all relevant Engine members and
    return verified limits. Callers keep reporter operations serialized: start
    occurs before collection; stop occurs only after collection is suspended.
    This object does not configure Compose, admit a Worker, or grant network.
    """

    def __init__(self, *, engine, layout, broker, reporter, private_root: Path,
                 image_id: str, image_revision: str, image_environment: dict,
                 worker_container_id: str, existing_limits: dict, attempt_limit,
                 observe_envelope, deadline_epoch: int, expected_sockets: tuple[str, ...]):
        self.engine, self.layout, self.broker, self.reporter = engine, layout, broker, reporter
        self.private_root, self.observe_envelope = Path(private_root), observe_envelope
        self._lock = asyncio.Lock()
        self._attempt = None
        self._stopped = None
        self._key = secrets.token_bytes(32)
        self._create_key = "docker-create:" + broker.attempt_id
        self._confirm_key = "docker-confirm:" + broker.attempt_id
        self._start_key = "docker-start:" + broker.attempt_id
        self._stop_key = "docker-stop:" + broker.attempt_id
        name = "hypertest-attempt-" + broker.attempt_id.replace("-", "") + "-" + secrets.token_hex(16)
        self.spec = build_spec(project_id=broker.project_id, task_id=broker.task_id, attempt_id=broker.attempt_id,
            generation=broker.identity.generation, container_name=name, image_id=image_id,
            image_revision=image_revision, image_environment=image_environment, volume_name=layout.volume_name,
            mounts=layout.mount_specs(expected_sockets=expected_sockets), key_sha256=hashlib.sha256(self._key).hexdigest(),
            clock_sha256=clock_domain_digest(), deadline_epoch=deadline_epoch, attempt_limit=attempt_limit,
            worker_id=worker_container_id, existing_limits=existing_limits)

    async def _accepted(self, call, *, key: str, operation: str, expected_version: int,
                        record_name: str, expected_record: dict) -> dict:
        try:
            receipt = await call()
        except (Exception, asyncio.CancelledError) as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            # Only ask for this exact original operation, never replay it.
            try:
                receipt = await self.broker.receipt(key)
            except Exception:
                raise CloudBlocked("DOCKER_RECEIPT_UNCONFIRMED", "Original container operation needs reconciliation") from None
        record = receipt.get(record_name) if isinstance(receipt, dict) else None
        if (not isinstance(receipt, dict) or receipt.get("status") != "ACCEPTED"
                or receipt.get("operation") != operation or receipt.get("operation_key") != key
                or receipt.get("project_id") != self.broker.project_id or receipt.get("task_id") != self.broker.task_id
                or receipt.get("attempt_id") != self.broker.attempt_id
                or receipt.get("version") != expected_version + 1 or not isinstance(record, dict)
                or any(record.get(field) != value for field, value in expected_record.items())):
            raise CloudBlocked("DOCKER_RECEIPT_MISMATCH", "Original container operation receipt does not match")
        self.reporter.version = receipt["version"]
        return receipt

    async def start(self, config: dict):
        async with self._lock:
            if self._attempt is not None:
                raise CloudBlocked("DOCKER_ORIGINAL_OPERATION_QUERY_ONLY", "An original container cannot be started again")
            if config.get("native_delegation") is not None or self.reporter.pending():
                raise CloudBlocked("DOCKER_ADMISSION_UNAVAILABLE", "Container execution requires an idle report stream and no native delegation")
            if self.spec["scope"]["deadline_epoch"] <= time.time():
                raise CloudBlocked("RUNTIME_BUDGET_EXHAUSTED", "The original container deadline has expired")
            recovery_root = self.private_root / "container-recovery"
            recovery_root.mkdir(mode=0o700)
            recovery = create_recovery_capability(recovery_root, RecoveryIdentity(
                project_id=self.broker.project_id, task_id=self.broker.task_id, attempt_id=self.broker.attempt_id,
                create_key=self._create_key, generation=self.broker.identity.generation, worker_id=self.broker.identity.worker_id))
            scope = self.spec["scope"]
            version = self.reporter.version

            async def create_intent():
                return await self.broker.prepare_container_create(operation_key=self._create_key, expected_version=version,
                    container_name=self.spec["container_name"], image_id=self.spec["image_id"],
                    spec_sha256=self.spec["spec_sha256"], key_sha256=scope["key_sha256"], clock_sha256=scope["clock_sha256"],
                    recovery_sha256=recovery.sha256, recovery_root=recovery_root, hard_deadline=scope["deadline_epoch"], spec=self.spec)

            receipt = await self._accepted(create_intent, key=self._create_key,
                operation="PREPARE_CONTAINER_CREATE", expected_version=version, record_name="container_create_intent",
                expected_record={"operation_key": self._create_key, "spec_sha256": self.spec["spec_sha256"],
                                 "recovery_sha256": recovery.sha256, "state": "UNCONFIRMED"})

            async def bind_id(container_id, _raw):
                current = self.reporter.version
                async def submit():
                    return await self.broker.observe_container(engine=self._attempt, create_operation_key=self._create_key,
                        container_id=container_id, operation_key=self._confirm_key, expected_version=current, stopped=False)
                await self._accepted(submit, key=self._confirm_key, operation="CONFIRM_CONTAINER_ID", expected_version=current,
                    record_name="container_observation", expected_record={"create_operation_key": self._create_key,
                    "container_id": container_id, "spec_sha256": self.spec["spec_sha256"], "state": "CONFIRMED"})

            async def prepare_start(container_id, _raw):
                current = self.reporter.version
                async def submit():
                    return await self.broker.prepare_container_start(engine=self._attempt, create_operation_key=self._create_key,
                        container_id=container_id, operation_key=self._start_key, expected_version=current)
                await self._accepted(submit, key=self._start_key, operation="PREPARE_CONTAINER_START", expected_version=current,
                    record_name="container_start_intent", expected_record={"create_operation_key": self._create_key,
                    "container_id": container_id, "spec_sha256": self.spec["spec_sha256"], "state": "SENT"})

            self._attempt = DockerAttempt(engine=self.engine, spec=self.spec, intent=receipt["container_create_intent"],
                key=self._key, bind_id=bind_id, prepare_start=prepare_start,
                authority_window=self.broker.container_authority_deadline_ns, observe_envelope=self.observe_envelope)
            return await self._attempt.start(config)

    async def stop(self):
        async with self._lock:
            if self._stopped is not None:
                return self._stopped
            if self._attempt is None:
                # No Engine create can occur before the single attempt is set.
                return {"local_processes_stopped": True, "runtime_started": False}
            observed = await self._attempt.stop()
            if self.broker.writes_suspended or self.reporter.pending():
                raise CloudBlocked("DOCKER_STOP_RECEIPT_PENDING", "Original stopped container requires recovery reconciliation")
            version = self.reporter.version

            async def submit():
                return await self.broker.observe_container(engine=self._attempt, create_operation_key=self._create_key,
                    container_id=self._attempt.container_id, operation_key=self._stop_key, expected_version=version, stopped=True)

            await self._accepted(submit, key=self._stop_key, operation="OBSERVE_CONTAINER_STOP", expected_version=version,
                record_name="container_observation", expected_record={"create_operation_key": self._create_key,
                "container_id": self._attempt.container_id, "spec_sha256": self.spec["spec_sha256"], "state": "STOPPED"})
            self._stopped = observed
            return observed
