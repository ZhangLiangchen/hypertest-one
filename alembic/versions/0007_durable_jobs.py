"""Durable operational jobs, fenced worker leases, and worker liveness.

Revision ID: 0007_durable_jobs
Revises: 0006_immutable_contracts
"""
import sqlalchemy as sa

from alembic import op

revision = "0007_durable_jobs"
down_revision = "0006_immutable_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "durable_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), sa.ForeignKey("test_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="RESTRICT")),
        sa.Column("retry_of_job_id", sa.Uuid(), sa.ForeignKey("durable_jobs.id", ondelete="RESTRICT")),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("worker_id", sa.String(255)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("test_run_id", "key", name="uq_durable_job_key"),
        sa.UniqueConstraint("test_run_id", "idempotency_key", name="uq_durable_job_idempotency"),
        sa.CheckConstraint("attempts >= 0", name="ck_durable_job_attempts"),
        sa.CheckConstraint("(job_type = 'EXECUTE_MISSION') = (mission_id IS NOT NULL)", name="ck_durable_job_mission"),
        sa.CheckConstraint("job_type IN ('ADVANCE_RUN','EXECUTE_MISSION','EXECUTE_TESTS','EVALUATE_GATE','PREPARE_WORKSPACE')", name="ck_durable_job_type"),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCEL_REQUESTED','CANCELLED','INTERRUPTED')", name="ck_durable_job_status"),
    )
    for column in ("project_id", "test_run_id", "mission_id"):
        op.create_index(f"ix_durable_jobs_{column}", "durable_jobs", [column])
    op.create_index("ix_durable_job_claim", "durable_jobs", ["status", "created_at"])
    op.create_index("uq_durable_job_active_run", "durable_jobs", ["test_run_id"], unique=True,
                    postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING', 'CANCEL_REQUESTED')"))
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(255), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_job_id", sa.Uuid(), sa.ForeignKey("durable_jobs.id", ondelete="RESTRICT")),
    )
    op.create_index("ix_worker_heartbeats_last_seen_at", "worker_heartbeats", ["last_seen_at"])
    op.execute(sa.text("""
CREATE FUNCTION hypertest_guard_job_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'durable job history is append-only';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['status','result','error_code','error_message','attempts',
        'lease_token','worker_id','heartbeat_at','lease_expires_at','updated_at',
        'started_at','finished_at','cancel_requested_at']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status','result','error_code','error_message','attempts',
        'lease_token','worker_id','heartbeat_at','lease_expires_at','updated_at',
        'started_at','finished_at','cancel_requested_at']) THEN
        RAISE EXCEPTION 'job input is immutable; submit a new job';
    END IF;
    IF OLD.status IN ('SUCCEEDED','FAILED','CANCELLED','INTERRUPTED') AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION 'terminal job is immutable; submit an explicit retry';
    END IF;
    RETURN NEW;
END;
$$;
"""))
    op.execute(sa.text("CREATE TRIGGER durable_job_history BEFORE UPDATE OR DELETE ON durable_jobs FOR EACH ROW EXECUTE FUNCTION hypertest_guard_job_inputs()"))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM durable_jobs)")):
        raise RuntimeError("cannot downgrade durable job history")
    op.drop_table("worker_heartbeats")
    op.execute(sa.text("DROP TRIGGER durable_job_history ON durable_jobs"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_job_inputs()"))
    op.drop_table("durable_jobs")
