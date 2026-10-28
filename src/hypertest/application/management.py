"""Web management intents. Soft deletion preserves canonical identities and history."""
from fastapi import HTTPException
from sqlalchemy import func, select

from hypertest.application.record_helpers import public
from hypertest.config import get_settings
from hypertest.domain.cloud_tasks import CloudTask
from hypertest.domain.local_archive import LocalArchiveTask
from hypertest.domain.models import AuditEvent, OutboxEvent, Project
from hypertest.domain.native import NativeTestRun


def record_change(db, row, before, action, *, version, actor_ref=None):
    actor = actor_ref or "web:" + get_settings().connector_operator_identity
    entity = "Project"
    event = "project." + action.lower()
    metadata = {"version": version, "source": "LOCAL_BINDING" if action == "BIND" else "WEB_MANAGEMENT"}
    db.add(AuditEvent(project_id=row.id,
        actor_type="USER", actor_ref=actor, action=event, entity_type=entity,
        entity_id=row.id, before_state=before, after_state=public(row), event_metadata=metadata))
    db.add(OutboxEvent(aggregate_type=entity, aggregate_id=row.id, event_type=event,
                       payload={**metadata, "action": action}))
    return actor


async def manage_project(db, project_id, expected_version, *, changes=None, action="UPDATE"):
    # All child admissions hold a shared/exclusive Project lock until commit.
    # This exclusive lock makes the dependency check and tombstone atomic.
    row = await db.scalar(select(Project).where(Project.id == project_id)
                          .with_for_update().execution_options(populate_existing=True))
    if row is None or (row.deleted_at is not None and action != "RESTORE"):
        raise HTTPException(404, "Project not found")
    if row.row_version != expected_version:
        raise HTTPException(409, "Project version is stale; refresh before changing it")
    if action == "RESTORE" and row.deleted_at is None:
        raise HTTPException(409, "Project is not deleted")
    if action == "DELETE":
        dependencies = []
        for model, label in ((LocalArchiveTask, "local archive tasks"),
                             (CloudTask, "cloud tasks"),
                             (NativeTestRun, "native test runs")):
            query = select(func.count()).select_from(model).where(model.project_id == row.id)
            count = await db.scalar(query)
            if count:
                dependencies.append(f"{count} {label}")
        if dependencies:
            raise HTTPException(409, "Project cannot be deleted: " + ", ".join(dependencies)
                                + "; archive the Project to retain task/run history")
    before = public(row)
    if action == "UPDATE":
        changes = changes or {}
        if all(getattr(row, key) == value for key, value in changes.items()):
            return row
        for key, value in changes.items():
            setattr(row, key, value)
    else:
        row.deleted_at = (await db.scalar(select(func.clock_timestamp()))) if action == "DELETE" else None
    row.row_version += 1
    row.updated_at = await db.scalar(select(func.clock_timestamp()))
    record_change(db, row, before, action, version=row.row_version)
    await db.commit()
    return row
