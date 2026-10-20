"""Immutable admission choices before a native Run binding exists."""
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from hypertest.db.base import Base


class RunHarnessSelection(Base):
    __tablename__ = "run_harness_selections"
    __table_args__ = (CheckConstraint("mode = 'LOCAL_CONNECTOR'", name="ck_harness_selection_mode"),)

    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32))
    node_id: Mapped[UUID] = mapped_column(ForeignKey("harness_nodes.id", ondelete="RESTRICT"))
    source_bundle_transfer_id: Mapped[UUID] = mapped_column(ForeignKey("source_bundle_transfers.id", ondelete="RESTRICT"))


async def get_execution_selection(session, run_id: UUID):
    """None means unchanged pre-ADR-016 PLATFORM_MANAGED behavior."""
    from hypertest.domain.interactive import RunExecutionSelection

    return await session.get(RunExecutionSelection, run_id)


async def create_execution_selection(
    session, run_id: UUID, *, execution_mode: str, execution_driver: str,
    node_id: UUID | None = None, source_bundle_transfer_id: UUID | None = None,
    harness_host_id: str | None = None,
):
    """Freeze only new admission choices; caller owns the transaction."""
    from sqlalchemy import select

    from hypertest.application.services import ConflictError, NotFoundError
    from hypertest.config import get_settings
    from hypertest.domain.connector import HarnessNode
    from hypertest.domain.interactive import RunExecutionSelection
    from hypertest.domain.models import TestRun

    run = await session.scalar(select(TestRun).where(TestRun.id == run_id).with_for_update())
    if run is None:
        raise NotFoundError("test run not found")
    if execution_mode == "CLOUD":
        if execution_driver != "PLATFORM_MANAGED" or source_bundle_transfer_id is not None:
            raise ConflictError("cloud execution requires the platform-managed server Harness")
        mode = "SERVER_HOST"
        host = harness_host_id or get_settings().bridge_host_id
    elif execution_mode == "LOCAL":
        if execution_driver not in {"PLATFORM_MANAGED", "INTERACTIVE_MCP"} or not node_id or not source_bundle_transfer_id:
            raise ConflictError("local execution requires an explicit node and accepted source")
        node = await session.get(HarnessNode, node_id)
        if node is None or node.registration_status != "ACTIVE" or node.node_kind != "LOCAL_CONNECTOR":
            raise ConflictError("local execution node is unavailable")
        mode, host = "LOCAL_CONNECTOR", node.node_key
        prior = await session.get(RunHarnessSelection, run_id)
        if prior is None or (prior.node_id, prior.source_bundle_transfer_id) != (node_id, source_bundle_transfer_id):
            raise ConflictError("execution choice must preserve the accepted source and Harness selection")
    else:
        raise ConflictError("unsupported execution mode")
    if node_id is not None and execution_mode == "CLOUD":
        node = await session.get(HarnessNode, node_id)
        if node is None or node.node_kind != "SERVER_HOST" or node.registration_status != "ACTIVE":
            raise ConflictError("server execution node is unavailable")
        host = node.node_key
    requested = (execution_mode, execution_driver, mode, node_id, source_bundle_transfer_id, host)
    existing = await get_execution_selection(session, run_id)
    if existing is not None:
        actual = (existing.execution_mode, existing.execution_driver, existing.harness_mode,
                  existing.node_id, existing.source_bundle_transfer_id, existing.harness_host_id)
        if requested != actual:
            raise ConflictError("execution mode, driver and node are immutable")
        return existing
    selected = RunExecutionSelection(test_run_id=run_id, execution_mode=execution_mode,
        execution_driver=execution_driver, harness_mode=mode, node_id=node_id,
        source_bundle_transfer_id=source_bundle_transfer_id, harness_host_id=host)
    session.add(selected)
    await session.flush()
    return selected
