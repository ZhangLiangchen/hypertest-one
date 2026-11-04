"""Persist task conversation independently of accepted testing artifacts."""
import sqlalchemy as sa
from alembic import op

revision = "0047_cloud_conversation"
down_revision = "0046_native_session_restore"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("cloud_conversation_heads",
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("cloud_tasks.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("cursor", sa.BigInteger(), nullable=False))
    op.create_table("cloud_conversation_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("cursor", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("operation_key", sa.String(128)),
        sa.Column("event_key", sa.String(128)),
        sa.Column("event_seq", sa.BigInteger()),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("actor_ref", sa.String(255), nullable=False),
        sa.Column("sdk_message_id", sa.String(255)),
        sa.Column("state", sa.String(24)),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "operation_key"),
        sa.UniqueConstraint("attempt_id", "generation", "event_key"),
        sa.CheckConstraint("generation > 0 AND cursor > 0"),
        sa.CheckConstraint("role IN ('ASSISTANT','USER','SYSTEM')"),
        sa.CheckConstraint("status IN ('RECORDED','QUEUED','DELIVERING','DELIVERED','UNKNOWN','REJECTED','CANCELLED')"))
    op.create_index("ix_cloud_conversation_cursor", "cloud_conversation_messages", ["task_id", "cursor"])


def downgrade():
    op.drop_table("cloud_conversation_messages")
    op.drop_table("cloud_conversation_heads")
