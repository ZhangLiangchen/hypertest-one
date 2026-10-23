"""Recoverable Project/SessionTask management with separate human history."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023_project_task_management"
down_revision = "0022_session_task_sync"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("session_tasks", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("session_tasks", sa.Column("last_managed_at", sa.DateTime(timezone=True)))
    op.create_table("session_task_management_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("session_tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_version", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("actor_ref", sa.String(255), nullable=False),
        sa.Column("task_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "task_version", name="uq_session_management_version"),
        sa.CheckConstraint("task_version > 0"),
        sa.CheckConstraint("action IN ('UPDATE','DELETE','RESTORE')"))
    # Existing guard already checks parent version and rejects any UPDATE/DELETE
    # of non-task history tables. Reuse it without relaxing earlier protection.
    op.execute("CREATE TRIGGER session_task_history_guard BEFORE INSERT OR UPDATE OR DELETE ON session_task_management_revisions FOR EACH ROW EXECUTE FUNCTION hypertest_guard_session_tasks()")


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM session_task_management_revisions)")):
        raise RuntimeError("Management history prevents destructive downgrade")
    if db.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM projects WHERE deleted_at IS NOT NULL)")):
        raise RuntimeError("Deleted Projects prevent destructive downgrade")
    op.drop_table("session_task_management_revisions")
    op.drop_column("session_tasks", "last_managed_at")
    op.drop_column("session_tasks", "deleted_at")
    op.drop_column("projects", "deleted_at")
