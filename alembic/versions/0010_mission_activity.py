"""Bounded safe mission activity observations.

Revision ID: 0010_mission_activity
Revises: 0009_mission_inputs
"""
import sqlalchemy as sa

from alembic import op

revision = "0010_mission_activity"
down_revision = "0009_mission_inputs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_activity_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *[sa.Column(name, sa.Uuid(), sa.ForeignKey(target + ".id", ondelete="RESTRICT"), nullable=False)
          for name, target in (("test_run_id", "test_runs"), ("durable_job_id", "durable_jobs"),
                               ("mission_id", "missions"), ("attempt_id", "mission_attempts"),
                               ("agent_session_id", "agent_sessions"))],
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("claim_no", sa.Integer(), nullable=False),
        sa.Column("window_id", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("retention_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.UniqueConstraint("attempt_id", "claim_no", "window_id", "source", "kind", name="uq_activity_window"),
        sa.CheckConstraint("count > 0 AND claim_no > 0", name="ck_activity_positive_counts"),
        sa.CheckConstraint("last_observed_at >= recorded_at", name="ck_activity_time_order"),
        sa.CheckConstraint("source IN ('PROVIDER','CONTROL_PLANE')", name="ck_activity_source"),
        sa.CheckConstraint("(source='PROVIDER' AND kind IN ('SIGNAL_RECEIVED','TURN_STARTED','TURN_COMPLETED','MODEL_ACTIVITY','TOOL_STARTED','TOOL_COMPLETED','FILE_ACTIVITY','ERROR')) OR (source='CONTROL_PLANE' AND kind IN ('MISSION_STARTED','RESUMED','RESULT_SUBMITTED','MISSION_FINISHED','ERROR'))", name="ck_activity_source_kind"),
        sa.CheckConstraint("kind IN ('SIGNAL_RECEIVED','TURN_STARTED','TURN_COMPLETED','MODEL_ACTIVITY','TOOL_STARTED','TOOL_COMPLETED','FILE_ACTIVITY','MISSION_STARTED','RESUMED','RESULT_SUBMITTED','MISSION_FINISHED','ERROR')", name="ck_activity_kind"),
    )
    op.create_index("ix_activity_job_cursor", "mission_activity_events", ["durable_job_id", "recorded_at", "id"])
    op.create_index("ix_activity_attempt_recent", "mission_activity_events", ["attempt_id", "recorded_at", "id"])
    op.execute(sa.text("""
CREATE FUNCTION hypertest_guard_activity_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (to_jsonb(NEW) - ARRAY['count','last_observed_at','retention_truncated']) IS DISTINCT FROM
           (to_jsonb(OLD) - ARRAY['count','last_observed_at','retention_truncated'])
           OR NEW.count < OLD.count OR NEW.last_observed_at < OLD.last_observed_at
           OR (OLD.retention_truncated AND NOT NEW.retention_truncated) THEN
            RAISE EXCEPTION 'activity identity and observations cannot be rewritten';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mission_attempts a JOIN missions m ON m.id=a.mission_id
          JOIN durable_jobs j ON j.id=a.durable_job_id
          JOIN agent_sessions s ON s.id=a.agent_session_id
        WHERE a.id=NEW.attempt_id AND a.mission_id=NEW.mission_id
          AND a.agent_session_id=NEW.agent_session_id AND a.durable_job_id=NEW.durable_job_id
          AND m.test_run_id=NEW.test_run_id AND j.test_run_id=NEW.test_run_id
          AND s.test_run_id=NEW.test_run_id AND NEW.claim_no<=j.attempts
    ) THEN RAISE EXCEPTION 'activity ownership does not match the durable attempt'; END IF;
    RETURN NEW;
END;
$$;
"""))
    op.execute(sa.text("CREATE TRIGGER activity_identity BEFORE INSERT OR UPDATE ON mission_activity_events FOR EACH ROW EXECUTE FUNCTION hypertest_guard_activity_identity()"))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM mission_activity_events)")):
        raise RuntimeError("retained activity history prevents destructive downgrade")
    op.execute(sa.text("DROP TRIGGER activity_identity ON mission_activity_events"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_activity_identity()"))
    op.drop_table("mission_activity_events")
