"""Retire replaced SessionTask data without touching shared Project or Memory data."""
from alembic import op

revision = "0034_remove_legacy_session_tasks"
down_revision = "0033_project_repositories"
branch_labels = None
depends_on = None


def upgrade():
    # These rows contain snapshots and metadata of the retired SessionTask.
    # Do not delete shared Memory entries even when their provenance references
    # an old report: Memory is an independent, user-published domain.
    op.execute("DELETE FROM audit_events WHERE entity_type = 'SessionTask'")
    op.execute("DELETE FROM outbox_events WHERE aggregate_type = 'SessionTask'")
    # A single RESTRICT statement ensures every FK-referencing table belongs to
    # this explicit list. PostgreSQL TRUNCATE bypasses row-only immutable-history
    # triggers without disabling any trigger or modifying unrelated tables.
    op.execute("""
        TRUNCATE TABLE
            session_tasks,
            session_task_management_revisions,
            session_case_revisions,
            session_report_revisions,
            session_sync_receipts,
            session_task_operation_receipts,
            session_task_sources,
            session_task_participants,
            session_contribution_revisions,
            session_task_publications,
            session_collaboration_receipts
        RESTRICT
    """)


def downgrade():
    raise RuntimeError("Removed SessionTask data cannot be reconstructed")
