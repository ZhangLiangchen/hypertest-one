"""Transactional, idempotent audit/outbox records for mission control decisions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.domain.enums import MissionStatus
from hypertest.domain.models import AuditEvent, Mission, MissionAttempt, OutboxEvent, TestRun

_MISSION_EVENTS = {
    "mission.created", "mission.completed", "mission.cancelled", "mission.expired",
}
_PROVIDER_PAYLOAD_KEYS = {
    "provider_metadata", "provider_logs", "event_types", "stdout", "stderr", "logs",
    "result_payload", "object_payload", "error_message",
}


async def record_mission_event(
    session: AsyncSession,
    mission: Mission,
    action: str,
    attempt: MissionAttempt | None = None,
    metadata: dict[str, Any] | None = None,
    before_status: MissionStatus | str | None = None,
    *,
    actor_type: str = "SYSTEM",
    actor_ref: str | None = "hypertest",
) -> bool:
    """Add one paired event to the caller's transaction; never commit it here.

    Callers serialize mission mutations using the TestRun/Mission locks. Terminal
    mission decisions have one mission-wide key, attempt events use the attempt
    identity, and user retry requests use the resulting mission row version.
    Metadata contains domain reasons/counts, never provider logs or raw results.
    """

    if not action.startswith("mission."):
        raise ValueError("mission lifecycle actions must use the mission namespace")
    details = dict(metadata or {})
    if details.keys() & _PROVIDER_PAYLOAD_KEYS:
        raise ValueError("mission lifecycle events cannot contain provider payloads or logs")
    # Assign IDs in the same transaction before constructing stable event keys.
    if mission.id is None or (attempt is not None and attempt.id is None):
        await session.flush()
    supplied_key = details.pop("event_key", None)
    if action in _MISSION_EVENTS:
        suffix = "mission"
    elif attempt is not None:
        suffix = str(attempt.id)
    else:
        suffix = f"version:{mission.row_version}"
    event_key = str(supplied_key or f"{mission.id}:{action}:{suffix}")
    for pending in session.new:
        if (isinstance(pending, AuditEvent) and pending.entity_id == mission.id
                and pending.action == action
                and (action in _MISSION_EVENTS
                     or (pending.event_metadata or {}).get("event_key") == event_key)):
            return False
    query = select(AuditEvent.id).where(
        AuditEvent.entity_type == "Mission", AuditEvent.entity_id == mission.id,
        AuditEvent.action == action,
    )
    if action not in _MISSION_EVENTS:
        query = query.where(AuditEvent.event_metadata["event_key"].as_string() == event_key)
    if await session.scalar(query.limit(1)) is not None:
        return False
    run = await session.get(TestRun, mission.test_run_id)
    if run is None:
        raise RuntimeError("mission lifecycle event requires its canonical test run")
    state: dict[str, Any] = {
        "mission_id": str(mission.id), "mission_key": mission.key,
        "test_run_id": str(run.id), "mission_type": mission.mission_type.value,
        "status": mission.status.value, "row_version": mission.row_version,
        "attempt_id": str(attempt.id) if attempt is not None else None,
        "attempt_no": attempt.attempt_no if attempt is not None else None,
        "attempt_status": attempt.status.value if attempt is not None else None,
    }
    payload = {**details, **state, "event_key": event_key,
               "actor_type": actor_type, "actor_ref": actor_ref}
    session.add(AuditEvent(
        project_id=run.project_id, test_run_id=run.id,
        actor_type=actor_type, actor_ref=actor_ref,
        action=action, entity_type="Mission", entity_id=mission.id,
        before_state={"status": str(before_status)} if before_status is not None else None,
        after_state=state,
        event_metadata={**details, "attempt_id": state["attempt_id"], "event_key": event_key},
    ))
    session.add(OutboxEvent(
        aggregate_type="Mission", aggregate_id=mission.id,
        event_type=action, payload=payload,
    ))
    return True
