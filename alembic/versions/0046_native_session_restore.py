"""Add one-shot original native session inspection records."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0046_native_session_restore"
down_revision = "0045_local_archive_status"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cloud_native_session_restores",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("expected_version", sa.BigInteger(), nullable=False),
        sa.Column("original_anchor_key", sa.String(128), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("original_generation", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("claim_key", sa.String(128)),
        sa.Column("token_hash", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("observation", postgresql.JSONB()),
        sa.UniqueConstraint("project_id", "request_key"),
        sa.UniqueConstraint("attempt_id"),
        sa.UniqueConstraint("worker_id", "claim_key"),
        sa.ForeignKeyConstraint(["project_id", "task_id"], ["cloud_tasks.project_id", "cloud_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id", "attempt_id"], ["cloud_attempts.task_id", "cloud_attempts.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("state IN ('PENDING','STARTED','RESTORED','FAILED','UNKNOWN','CANCELLED')"),
        sa.CheckConstraint("original_generation > 0 AND expected_version > 0"),
        sa.CheckConstraint("identity_digest ~ '^[a-f0-9]{64}$' AND input_digest ~ '^[a-f0-9]{64}$'"),
        sa.CheckConstraint("(state = 'PENDING' AND claim_key IS NULL AND token_hash IS NULL AND started_at IS NULL AND expires_at IS NULL AND finished_at IS NULL) OR (state = 'CANCELLED' AND claim_key IS NULL AND token_hash IS NULL AND started_at IS NULL AND expires_at IS NULL AND finished_at IS NOT NULL) OR (state IN ('STARTED','UNKNOWN') AND claim_key IS NOT NULL AND token_hash IS NOT NULL AND started_at IS NOT NULL AND expires_at IS NOT NULL AND finished_at IS NULL) OR (state IN ('RESTORED','FAILED') AND claim_key IS NOT NULL AND token_hash IS NOT NULL AND started_at IS NOT NULL AND expires_at IS NOT NULL AND finished_at IS NOT NULL)"),
    )
    op.create_table(
        "cloud_native_inspection_claim_states",
        sa.Column("worker_id", sa.String(128), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("request_key", sa.String(128)),
        sa.Column("request_digest", sa.String(64)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False),
        sa.Column("inspection_id", sa.Uuid(), sa.ForeignKey("cloud_native_session_restores.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 0"),
        sa.CheckConstraint("kind IN ('EMPTY','INSPECTION','ABANDONED')"),
        sa.CheckConstraint("(sequence = 0 AND request_key IS NULL AND request_digest IS NULL AND kind = 'EMPTY' AND closed) OR (sequence > 0 AND request_key IS NOT NULL AND request_digest ~ '^[a-f0-9]{64}$')"),
        sa.CheckConstraint("(kind IN ('EMPTY','ABANDONED') AND closed AND inspection_id IS NULL) OR (kind = 'INSPECTION' AND inspection_id IS NOT NULL)"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM cloud_native_session_restores)")):
        raise RuntimeError("Original native session restore records prevent incompatible downgrade")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM cloud_native_inspection_claim_states WHERE sequence > 0)")):
        raise RuntimeError("Native inspection claim history prevents incompatible downgrade")
    op.drop_table("cloud_native_inspection_claim_states")
    op.drop_table("cloud_native_session_restores")
