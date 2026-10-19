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
