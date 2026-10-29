"""Compose the fixed Docker service, serial membership and Attempt adapter."""
from __future__ import annotations

from pathlib import Path

from .docker_attempt import DockerEngine
from .docker_attempt_spec import ResourceLimit
from .docker_membership import DockerWorkerLock, admit_members
from .docker_sandbox import DockerSandbox
from .docker_service_admission import DockerServiceProfile, inspect_docker_service
from .docker_workspace import DockerWorkspace
from .errors import CloudBlocked


class DockerRuntime:
    """One serial trusted Compose Worker; never constructed from Agent input."""

    def __init__(self, *, settings, profile: DockerServiceProfile, sessions, engine: DockerEngine,
                 attempt_limit: ResourceLimit):
        if not isinstance(profile, DockerServiceProfile) or not isinstance(attempt_limit, ResourceLimit):
            raise CloudBlocked("DOCKER_ADMISSION_UNAVAILABLE", "Docker service profile is unavailable")
        attempt_limit.validate()
        self.settings, self.profile, self.sessions, self.engine = settings, profile, sessions, engine
        self.attempt_limit = attempt_limit
        self.lock = None
        self.admission = None
        self.image_environment = None
        self.existing_limits = None

    async def admit(self):
        self.admission = self.image_environment = self.existing_limits = None
        observed = await inspect_docker_service(self.settings, self.profile, self.engine)
        if self.lock is None:
            self.lock = DockerWorkerLock(Path(self.profile.private_root))
        image = await self.engine.inspect_image(self.profile.image_id)
        try:
            rows = image["Config"]["Env"]
            if not isinstance(rows, list) or any(not isinstance(item, str) or "=" not in item for item in rows):
                raise ValueError
            pairs = [item.split("=", 1) for item in rows]
            environment = dict(pairs)
            if len(environment) != len(pairs):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise CloudBlocked("DOCKER_IMAGE_UNCONFIRMED", "Pinned image environment is unavailable") from None
        limits = await admit_members(engine=self.engine, sessions=self.sessions, lock=self.lock,
            worker_id=observed["worker_container_id"], volume_name=self.profile.shared_volume,
            worker_limit=observed["worker_limit"], attempt_limit=self.attempt_limit)
        self.admission, self.image_environment, self.existing_limits = observed, environment, limits

    def layout(self, task: dict, attempt: dict) -> DockerWorkspace:
        if self.admission is None or self.lock is None or self.lock.fd is None:
            raise CloudBlocked("DOCKER_ADMISSION_UNAVAILABLE", "Docker service membership is not admitted")
        return DockerWorkspace.create(Path(self.profile.shared_root), self.profile.shared_volume,
            project_id=task["project_id"], task_id=task["id"], attempt_id=attempt["id"], input_digest=task["input_digest"])

    def sandbox(self, *, layout, broker, reporter, private_root, policy, deadline_epoch, expected_sockets):
        if self.admission is None or self.lock is None or self.lock.fd is None:
            raise CloudBlocked("DOCKER_ADMISSION_UNAVAILABLE", "Docker service membership is not admitted")
        worker_id, worker_limit = self.admission["worker_container_id"], self.admission["worker_limit"]
        if (policy.aggregate_memory_bytes != 4 * 1024**3 or policy.aggregate_processes != 256
                or layout.volume_name != self.profile.shared_volume):
            raise CloudBlocked("DOCKER_ADMISSION_UNAVAILABLE", "Docker Attempt limits do not match the fixed profile")
        holder = {}

        async def observe_envelope():
            latest = await inspect_docker_service(self.settings, self.profile, self.engine)
            if latest["worker_container_id"] != worker_id or latest["worker_limit"] != worker_limit:
                raise CloudBlocked("DOCKER_MEMBERS_UNCONFIRMED", "Docker Worker identity or resource limits changed")
            sandbox = holder["sandbox"]
            current_id = sandbox._attempt.container_id if sandbox._attempt is not None else None
            return await admit_members(engine=self.engine, sessions=self.sessions, lock=self.lock,
                worker_id=worker_id, volume_name=self.profile.shared_volume, worker_limit=worker_limit,
                attempt_limit=self.attempt_limit, current_create_key=sandbox._create_key,
                current_spec=sandbox.spec, current_container_id=current_id)

        sandbox = DockerSandbox(engine=self.engine, layout=layout, broker=broker, reporter=reporter,
            private_root=private_root, image_id=self.profile.image_id, image_revision=self.profile.source_commit,
            image_environment=self.image_environment, worker_container_id=worker_id, existing_limits=self.existing_limits,
            attempt_limit=self.attempt_limit, observe_envelope=observe_envelope, deadline_epoch=deadline_epoch,
            expected_sockets=expected_sockets)
        holder["sandbox"] = sandbox
        return sandbox

    def close(self):
        if self.lock is not None:
            self.lock.close()
        self.admission = self.image_environment = self.existing_limits = None
