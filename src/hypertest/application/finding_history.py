"""Bounded lifecycle projections, never a generic audit or Provider-log endpoint."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.application.services import NotFoundError
from hypertest.domain.enums import FindingResolution, FindingStatus
from hypertest.domain.models import AuditEvent, Finding

HISTORY_ACTIONS = tuple(f"finding.{action}" for action in (
    "accepted", "triaged", "invalid", "confirmed", "resolved", "closed", "reopened",
))
REASON_LIMIT = 2000


def _state(value: dict | None) -> dict | None:
    if not isinstance(value, dict):
        return None
    status, resolution, version = value.get("status"), value.get("resolution"), value.get("row_version")
    return {"status": status if isinstance(status, str) and status in FindingStatus else None,
            "resolution": resolution if isinstance(resolution, str) and resolution in FindingResolution else None,
            "row_version": version if type(version) is int and version > 0 else None}


async def read_finding_history(session: AsyncSession, finding_id: UUID, *, limit: int = 50) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError("Finding history limit must be between 1 and 100")
    finding = await session.get(Finding, finding_id)
    if finding is None:
        raise NotFoundError("finding not found")
    rows = list(await session.scalars(select(AuditEvent).where(
        AuditEvent.entity_type == "Finding", AuditEvent.entity_id == finding.id,
        AuditEvent.test_run_id == finding.test_run_id, AuditEvent.project_id == finding.project_id,
        AuditEvent.action.in_(HISTORY_ACTIONS),
    ).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1)))
    events = []
    for row in rows[:limit]:
        reason = row.event_metadata.get("reason") if isinstance(row.event_metadata, dict) else None
        reason = reason if isinstance(reason, str) else None
        events.append({"id": row.id, "created_at": row.created_at,
            "actor_type": row.actor_type if row.actor_type in {"USER", "AGENT", "SYSTEM", "RUNNER", "VERIFIER", "GATE"} else "UNKNOWN",
            "action": row.action, "before": _state(row.before_state), "after": _state(row.after_state),
            "reason": reason[:REASON_LIMIT] if reason else None,
            "reason_truncated": bool(reason and len(reason) > REASON_LIMIT)})
    return {"events": events, "truncated": len(rows) > limit}
