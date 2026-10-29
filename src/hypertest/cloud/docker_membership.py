"""Single-Worker lock and closed-original admission for Docker Attempts."""
from __future__ import annotations

import fcntl
import os
import re
import stat
from pathlib import Path
from uuid import UUID

from sqlalchemy import or_, select, text

from hypertest.domain.cloud_tasks import CloudOperationReceipt

from .docker_attempt_spec import ResourceLimit, check_aggregate, create_body, verify_inspect
from .errors import CloudBlocked

_HEX = re.compile(r"[a-f0-9]{64}\Z")
_VOLUME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_OPERATIONS = ("CONFIRM_CONTAINER_ID", "OBSERVE_CONTAINER_STOP", "OBSERVE_CONTAINER_NEVER_STARTED")
_MAX_INTENTS = 4096


def _blocked() -> CloudBlocked:
    return CloudBlocked("DOCKER_MEMBERS_UNCONFIRMED", "Original Docker Attempt members require reconciliation")


class DockerWorkerLock:
    """A nonblocking lock on a verified Worker-only private directory.

    The deployment must map the same private volume into every instance of the
    one Compose service. The caller holds this object for the Worker's lifetime.
    """

    def __init__(self, private_root: Path):
        self.fd = None
        root = None
        try:
            path = Path(private_root).absolute()
            if os.geteuid() == 0 or path.resolve(strict=True) != path:
                raise ValueError
            root = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(root)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError
            fd = os.open("docker-worker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                    raise ValueError
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fd = fd
            except BaseException:
                os.close(fd)
                raise
        except (OSError, ValueError):
            raise _blocked() from None
        finally:
            if root is not None:
                os.close(root)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _closed_originals(rows: list[tuple[str, dict]], *, worker_id: str, volume_name: str) -> dict[str, tuple[dict, str]]:
    """Match immutable create/confirm/terminal observations, refusing unknowns."""
    intents = {}
    observations = {}
    for operation, response in rows:
        if not isinstance(response, dict):
            raise _blocked()
        if operation == "PREPARE_CONTAINER_CREATE":
            intent = response.get("container_create_intent")
            try:
                spec = intent["spec"]
                create_body(spec)
                scope = spec["scope"]
                key = intent["operation_key"]
                is_member = (spec["envelope"]["worker_id"] == worker_id
                             or spec["mounts"][0]["Source"] == volume_name)
                if not is_member:
                    continue
                if (not isinstance(key, str) or key in intents or intent["spec_sha256"] != spec["spec_sha256"]
                        or any(intent[name] != scope[name] for name in ("project_id", "task_id", "attempt_id", "generation"))):
                    raise ValueError
                intents[key] = intent
            except (KeyError, TypeError, IndexError, ValueError):
                raise _blocked() from None
        elif operation in _OPERATIONS:
            entry = response.get("container_observation")
            if not isinstance(entry, dict) or not isinstance(entry.get("create_operation_key"), str):
                raise _blocked()
            observations.setdefault(entry["create_operation_key"], []).append(entry)
    closed = {}
    for key, intent in intents.items():
        entries = observations.get(key, [])
        confirms = [item for item in entries if item.get("state") == "CONFIRMED"]
        terminals = [item for item in entries if item.get("state") in {"STOPPED", "NEVER_STARTED"}]
        if len(confirms) != 1 or len(terminals) != 1:
            raise _blocked()
        confirm, terminal = confirms[0], terminals[0]
        cid = confirm.get("container_id")
        if (not isinstance(cid, str) or _HEX.fullmatch(cid) is None or cid in closed
                or any(item.get("container_id") != cid or item.get("attempt_id") != intent["attempt_id"]
                       or item.get("task_id") != intent["task_id"] or item.get("project_id") != intent["project_id"]
                       or item.get("source") != "DOCKER_ENGINE_INSPECT" or item.get("spec_sha256") != intent["spec_sha256"]
                       or item.get("generation") != intent["generation"] for item in (confirm, terminal))):
            raise _blocked()
        closed[cid] = (intent["spec"], terminal["state"])
    return closed


async def admit_members(*, engine, sessions, lock: DockerWorkerLock, worker_id: str, volume_name: str,
                        worker_limit: ResourceLimit, attempt_limit: ResourceLimit, current_create_key: str | None = None,
                        current_spec: dict | None = None, current_container_id: str | None = None) -> dict[str, ResourceLimit]:
    """Prove this serial Worker's old Attempt identities are closed.

    The caller must independently verify the Engine and current Compose Worker,
    including that ``lock`` and ``volume_name`` use the configured shared volumes.
    Only this Worker's and its shared volume's Attempt domain is considered.
    """
    if (not isinstance(lock, DockerWorkerLock) or lock.fd is None or not isinstance(worker_id, str)
            or _HEX.fullmatch(worker_id) is None or not isinstance(volume_name, str)
            or _VOLUME.fullmatch(volume_name) is None or not isinstance(worker_limit, ResourceLimit)
            or not isinstance(attempt_limit, ResourceLimit)):
        raise _blocked()
    if ((current_create_key is None) != (current_spec is None)
            or (current_container_id is not None and (current_spec is None or not isinstance(current_container_id, str)
                                                        or _HEX.fullmatch(current_container_id) is None))):
        raise _blocked()
    response = CloudOperationReceipt.response
    scope = response["container_create_intent"]["spec"]
    try:
        async with sessions() as db:
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            query = select(CloudOperationReceipt.operation, response, CloudOperationReceipt.attempt_id).where(
                CloudOperationReceipt.operation == "PREPARE_CONTAINER_CREATE",
                or_(scope["envelope"]["worker_id"].astext == worker_id,
                    scope["mounts"][0]["Source"].astext == volume_name)).limit(_MAX_INTENTS + 1)
            creates = list((await db.execute(query)).all())
            if len(creates) > _MAX_INTENTS:
                raise _blocked()
            attempt_ids = [attempt for _, _, attempt in creates]
            if any(not isinstance(value, UUID) for value in attempt_ids):
                raise _blocked()
            following = []
            if attempt_ids:
                query = select(CloudOperationReceipt.operation, response).where(
                    CloudOperationReceipt.attempt_id.in_(attempt_ids), CloudOperationReceipt.operation.in_(_OPERATIONS)
                ).limit(3 * _MAX_INTENTS + 1)
                following = list((await db.execute(query)).all())
            if len(following) > 3 * _MAX_INTENTS:
                raise _blocked()
        rows = [(op, row) for op, row, _ in creates] + following
        if current_create_key is not None:
            current = [row.get("container_create_intent") for op, row in rows
                       if op == "PREPARE_CONTAINER_CREATE" and row.get("container_create_intent", {}).get("operation_key") == current_create_key]
            if (len(current) != 1 or current[0].get("spec") != current_spec
                    or current_spec["envelope"]["worker_id"] != worker_id
                    or current_spec["mounts"][0]["Source"] != volume_name):
                raise ValueError
            current_observations = [row.get("container_observation") for op, row in rows
                if op in _OPERATIONS and row.get("container_observation", {}).get("create_operation_key") == current_create_key]
            if current_container_id is None:
                if current_observations:
                    raise ValueError
            elif (len(current_observations) != 1 or current_observations[0].get("state") != "CONFIRMED"
                  or current_observations[0].get("container_id") != current_container_id
                  or current_observations[0].get("spec_sha256") != current_spec["spec_sha256"]):
                raise ValueError
            rows = [(op, row) for op, row in rows if not (
                op == "PREPARE_CONTAINER_CREATE" and row.get("container_create_intent", {}).get("operation_key") == current_create_key
                or op in _OPERATIONS and row.get("container_observation", {}).get("create_operation_key") == current_create_key)]
        closed = _closed_originals(rows,
                                   worker_id=worker_id, volume_name=volume_name)
        found_current = False
        for cid in await engine.list_attempts():
            raw = await engine.inspect_container(cid)
            labels = raw["Config"]["Labels"]
            mounts = raw["HostConfig"]["Mounts"] or []
            if not isinstance(labels, dict) or not isinstance(mounts, list):
                raise ValueError
            relevant = labels.get("hypertest.cloud.worker_id") == worker_id or any(
                isinstance(m, dict) and m.get("Type") == "volume" and m.get("Source") == volume_name for m in mounts)
            if not relevant:
                continue
            if current_container_id is not None and cid == current_container_id:
                inspected = verify_inspect(current_spec, container_id=cid, observed=raw)
                if inspected["status"] != "created" or inspected["running"] or inspected["pid"] != 0:
                    raise ValueError
                found_current = True
                continue
            if cid not in closed:
                raise ValueError
        if current_container_id is not None and not found_current:
            raise ValueError
            original_spec, terminal_state = closed[cid]
            inspected = verify_inspect(original_spec, container_id=cid, observed=raw)
            expected = "created" if terminal_state == "NEVER_STARTED" else "exited"
            if inspected["running"] or inspected["pid"] != 0 or inspected["status"] != expected:
                raise ValueError
        existing = {worker_id: worker_limit}
        check_aggregate(worker_id=worker_id, existing=existing, attempt=attempt_limit)
        return existing
    except CloudBlocked:
        raise
    except Exception:
        raise _blocked() from None
