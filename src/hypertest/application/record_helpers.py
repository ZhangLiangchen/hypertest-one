"""Shared project lookup and JSON-safe row projections."""
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from hypertest.domain.models import Project


def public(row):
    def convert(value):
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value
    return {column.name: convert(getattr(row, column.name)) for column in row.__table__.columns}


async def project(db, project_id, *, include_deleted=False, lock=False):
    query = select(Project).where(Project.id == project_id)
    if lock:
        query = query.with_for_update(read=True).execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None or (row.deleted_at is not None and not include_deleted):
        raise HTTPException(404, "Project not found")
    return row
