"""Bounded durable mailbox recovery; uncertain deliveries are never requeued."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.connector.protocol import MAX_QUEUE
from hypertest.domain.connector import ConnectorRequest


async def expire_requests(db: AsyncSession, node_id: UUID, *, now: datetime,
                          connection_generation: int) -> int:
    """Fence requests orphaned by a caller/API crash without repeating work.

    Unsent management queries may wait for reconnection. Every already-consumed
    delivery and every execution intent belongs to its original connection.
    The caller commits this update together with node/mailbox admission state.
    """
    stale_generation=and_(
        ConnectorRequest.connection_generation.is_distinct_from(connection_generation),
        or_(ConnectorRequest.status=='SENT',ConnectorRequest.authority!='management'),
    )
    rows=(await db.scalars(select(ConnectorRequest).where(
        ConnectorRequest.node_id==node_id,
        ConnectorRequest.status.in_(['QUEUED','SENT']),
        or_(ConnectorRequest.expires_at<=now,stale_generation),
    ).order_by(ConnectorRequest.created_at,ConnectorRequest.id)
        .with_for_update(skip_locked=True).limit(MAX_QUEUE))).all()
    for row in rows:
        row.status='UNKNOWN'
        row.error_code='DELIVERY_EXPIRED' if row.expires_at<=now else 'CONNECTION_REPLACED'
        row.finished_at=now
    if rows:
        await db.flush()
    return len(rows)
