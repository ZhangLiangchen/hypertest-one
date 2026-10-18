"""Durable clarification and paused job reservations, without rewriting history.

Revision ID: 0009_mission_inputs
Revises: 0008_job_ownership
"""
import sqlalchemy as sa

from alembic import op

revision = "0009_mission_inputs"
down_revision = "0008_job_ownership"
branch_labels = None
depends_on = None


def _job_index(waiting: bool) -> None:
    op.drop_index("uq_durable_job_active_run", table_name="durable_jobs")
    states = "'QUEUED','RUNNING','CANCEL_REQUESTED'" + (",'WAITING_INPUT'" if waiting else "")
    op.create_index("uq_durable_job_active_run", "durable_jobs", ["test_run_id"], unique=True,
                    postgresql_where=sa.text(f"status IN ({states})"))


def _status_constraints(waiting: bool) -> None:
    for table, name, values in (
        ("durable_jobs", "ck_durable_job_status", "'QUEUED','RUNNING','SUCCEEDED','FAILED','CANCEL_REQUESTED','CANCELLED','INTERRUPTED'"),
        ("agent_sessions", "ck_agent_sessions_status", "'CREATED','RUNNING','CLOSED','FAILED'"),
    ):
        op.drop_constraint(name, table, type_="check")
        if waiting:
            values += ",'WAITING_INPUT'"
        op.create_check_constraint(name, table, f"status IN ({values})")


def upgrade() -> None:
    op.alter_column("agent_sessions", "status", type_=sa.String(32), existing_type=sa.String(7), existing_nullable=False)
    _status_constraints(True)
    _job_index(True)
    op.create_table(
        "mission_input_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), sa.ForeignKey("test_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("mission_attempts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agent_session_id", sa.Uuid(), sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("durable_job_id", sa.Uuid(), sa.ForeignKey("durable_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("question_id", sa.String(128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("answer_idempotency_key", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("attempt_id", "question_id", name="uq_mission_input_question"),
        sa.UniqueConstraint("test_run_id", "key", name="uq_mission_input_key"),
        sa.CheckConstraint("status IN ('PENDING','ANSWERED','CONSUMED','CANCELLED')", name="ck_mission_input_status"),
        sa.CheckConstraint("row_version > 0", name="ck_mission_input_version"),
        sa.CheckConstraint("length(btrim(question)) > 0 AND length(question) <= 4096", name="ck_mission_input_question_text"),
        sa.CheckConstraint("answer IS NULL OR (length(btrim(answer)) > 0 AND length(answer) <= 12000)", name="ck_mission_input_answer_text"),
        sa.CheckConstraint("(answer IS NULL) = (answered_at IS NULL) AND (answer IS NULL) = (answer_idempotency_key IS NULL)", name="ck_mission_input_answer_fields"),
        sa.CheckConstraint("(status = 'PENDING' AND answer IS NULL AND consumed_at IS NULL AND cancelled_at IS NULL) OR (status = 'ANSWERED' AND answer IS NOT NULL AND consumed_at IS NULL AND cancelled_at IS NULL) OR (status = 'CONSUMED' AND answer IS NOT NULL AND consumed_at IS NOT NULL AND cancelled_at IS NULL) OR (status = 'CANCELLED' AND cancelled_at IS NOT NULL)", name="ck_mission_input_lifecycle"),
    )
    for column in ("test_run_id", "mission_id", "attempt_id", "durable_job_id"):
        op.create_index(f"ix_mission_input_requests_{column}", "mission_input_requests", [column])
    op.create_index("uq_mission_input_open_attempt", "mission_input_requests", ["attempt_id"], unique=True,
                    postgresql_where=sa.text("status IN ('PENDING','ANSWERED')"))
    op.execute(sa.text("""
CREATE OR REPLACE FUNCTION hypertest_guard_mission_input() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE attempt_mission uuid; attempt_job uuid; attempt_agent uuid; mission_run uuid; job_run uuid; agent_run uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'human input history is append-only'; END IF;
    IF TG_OP = 'INSERT' AND NEW.status <> 'PENDING' THEN
        RAISE EXCEPTION 'human input must begin pending';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (to_jsonb(NEW) - ARRAY['status','answer','answer_idempotency_key','answered_at','consumed_at','cancelled_at','row_version'])
            IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','answer','answer_idempotency_key','answered_at','consumed_at','cancelled_at','row_version']) THEN
            RAISE EXCEPTION 'human question and ownership are immutable';
        END IF;
        IF OLD.status IN ('CONSUMED','CANCELLED') THEN RAISE EXCEPTION 'closed human input history is immutable'; END IF;
        IF OLD.answer IS NOT NULL AND (NEW.answer, NEW.answer_idempotency_key, NEW.answered_at)
            IS DISTINCT FROM (OLD.answer, OLD.answer_idempotency_key, OLD.answered_at) THEN
            RAISE EXCEPTION 'human answer is immutable';
        END IF;
        IF NOT ((OLD.status = 'PENDING' AND NEW.status IN ('ANSWERED','CANCELLED'))
                OR (OLD.status = 'ANSWERED' AND NEW.status IN ('CONSUMED','CANCELLED'))) THEN
            RAISE EXCEPTION 'invalid human input transition';
        END IF;
        IF NEW.row_version <> OLD.row_version + 1 THEN RAISE EXCEPTION 'human input version must advance once'; END IF;
    END IF;
    SELECT mission_id,durable_job_id,agent_session_id INTO attempt_mission,attempt_job,attempt_agent
        FROM mission_attempts WHERE id=NEW.attempt_id;
    SELECT test_run_id INTO mission_run FROM missions WHERE id=NEW.mission_id;
    SELECT test_run_id INTO job_run FROM durable_jobs WHERE id=NEW.durable_job_id;
    SELECT test_run_id INTO agent_run FROM agent_sessions WHERE id=NEW.agent_session_id;
    IF attempt_mission IS DISTINCT FROM NEW.mission_id OR attempt_job IS DISTINCT FROM NEW.durable_job_id
       OR attempt_agent IS DISTINCT FROM NEW.agent_session_id OR mission_run IS DISTINCT FROM NEW.test_run_id
       OR job_run IS DISTINCT FROM NEW.test_run_id OR agent_run IS DISTINCT FROM NEW.test_run_id THEN RAISE EXCEPTION 'human input ownership mismatch'; END IF;
    IF jsonb_typeof(NEW.options::jsonb) <> 'array' OR jsonb_array_length(NEW.options::jsonb) > 8 THEN
        RAISE EXCEPTION 'human input options must be a bounded array';
    END IF;
    IF length(btrim(NEW.question_id)) < 1 OR length(NEW.question_id) > 128 THEN
        RAISE EXCEPTION 'human question identifier must be bounded and nonblank';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.options::jsonb) AS item(value)
        WHERE jsonb_typeof(value) <> 'string' OR length(btrim(value #>> '{}')) < 1
            OR length(value #>> '{}') > 256)
        OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(NEW.options::jsonb) AS item(value))
            <> jsonb_array_length(NEW.options::jsonb) THEN
        RAISE EXCEPTION 'human input options must be distinct bounded nonblank strings';
    END IF;
    IF NEW.answer_idempotency_key IS NOT NULL AND length(btrim(NEW.answer_idempotency_key)) < 1 THEN
        RAISE EXCEPTION 'human answer idempotency key must be nonblank';
    END IF;
    RETURN NEW;
END;
$$;
"""))
    op.execute(sa.text("""
CREATE TRIGGER mission_input_history BEFORE INSERT OR UPDATE OR DELETE ON mission_input_requests
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_mission_input();
"""))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM mission_input_requests) OR EXISTS (SELECT 1 FROM durable_jobs WHERE status='WAITING_INPUT') OR EXISTS (SELECT 1 FROM agent_sessions WHERE status='WAITING_INPUT')")):
        raise RuntimeError("cannot discard human input history or waiting work")
    op.execute(sa.text("DROP TRIGGER mission_input_history ON mission_input_requests"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_mission_input()"))
    op.drop_table("mission_input_requests")
    _job_index(False)
    _status_constraints(False)
