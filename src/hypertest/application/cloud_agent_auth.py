"""Non-secret, bounded projection of independent Worker authentication observations."""
import re
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from hypertest.domain.cloud_tasks import CloudAgentAuthObservation

FRESH_SECONDS = 180
RETENTION_DAYS = 1
_WORKER_ID = re.compile(r"cloud-worker-[0-9a-f]{32}\Z")
_HOST_WORKER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_STATUSES = frozenset({"VALID", "INVALID", "UNKNOWN"})


async def record_worker_auth_status(sessions, worker_id: str, status: str) -> None:
    """Worker-only write: store no identity, provider payload, secret, or error text."""
    if not isinstance(worker_id, str) or not _WORKER_ID.fullmatch(worker_id) or not isinstance(status, str) or status not in _STATUSES:
        raise ValueError("Invalid Worker authentication observation")
    async with sessions() as db:
        await store_worker_auth_status(db, worker_id, status)
        await db.commit()


async def store_worker_auth_status(db, worker_id: str, status: str) -> None:
    """Persist a bounded, nonsecret observation from an authenticated worker."""
    if not isinstance(worker_id, str) or not _HOST_WORKER_ID.fullmatch(worker_id) or status not in _STATUSES:
        raise ValueError("Invalid Worker authentication observation")
    statement = insert(CloudAgentAuthObservation).values(
        worker_id=worker_id, status=status, checked_at=func.clock_timestamp())
    statement = statement.on_conflict_do_update(index_elements=[CloudAgentAuthObservation.worker_id],
        set_={"status": status, "checked_at": func.clock_timestamp()})
    await db.execute(statement)
    await db.execute(delete(CloudAgentAuthObservation).where(
        CloudAgentAuthObservation.checked_at < func.clock_timestamp() - timedelta(days=RETENTION_DAYS)))


def project_status(rows, *, enabled: bool) -> dict:
    """Only a single recent Worker can represent this deployment's observation."""
    deepseek = {"status": "UNKNOWN", "checked_at": None}
    if enabled and len(rows) == 1:
        row = rows[0]
        if row.status in _STATUSES:
            deepseek = {"status": row.status, "checked_at": row.checked_at.isoformat()}
    return {"agents": {"deepseek": deepseek, "codex": {"status": "UNKNOWN", "checked_at": None},
                       "claude_code": {"status": "NOT_SUPPORTED", "checked_at": None}}}


async def read_auth_status(db, *, enabled: bool) -> dict:
    if not enabled:
        return project_status([], enabled=False)
    # DB time avoids trusting an individual Worker's wall clock; limit the
    # result because multiple recent instances must remain ambiguous.
    result = await db.execute(select(CloudAgentAuthObservation).where(
        CloudAgentAuthObservation.checked_at > func.clock_timestamp() - timedelta(seconds=FRESH_SECONDS),
        CloudAgentAuthObservation.checked_at <= func.clock_timestamp()).limit(2))
    return project_status(list(result.scalars()), enabled=True)
