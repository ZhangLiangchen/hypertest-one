"""Bind attempts and executions to their durable request without clock inference.

Revision ID: 0008_job_ownership
Revises: 0007_durable_jobs
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_job_ownership"
down_revision = "0007_durable_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("mission_attempts", "test_executions"):
        op.add_column(table, sa.Column("durable_job_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_durable_job", table, "durable_jobs", ["durable_job_id"], ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_durable_job_id", table, ["durable_job_id"])
    op.execute(sa.text("""
CREATE FUNCTION hypertest_guard_job_ownership() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_run uuid; owner_mission uuid; owner_operation text; work_run uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.durable_job_id IS DISTINCT FROM OLD.durable_job_id THEN
        RAISE EXCEPTION 'durable work ownership is immutable';
    END IF;
    IF NEW.durable_job_id IS NULL THEN RETURN NEW; END IF;
    SELECT test_run_id, mission_id, job_type INTO owner_run, owner_mission, owner_operation
        FROM durable_jobs WHERE id = NEW.durable_job_id;
    IF TG_TABLE_NAME = 'mission_attempts' THEN
        SELECT test_run_id INTO work_run FROM missions WHERE id = NEW.mission_id;
        IF owner_operation NOT IN ('ADVANCE_RUN', 'EXECUTE_MISSION')
            OR (owner_operation = 'EXECUTE_MISSION' AND owner_mission IS DISTINCT FROM NEW.mission_id)
        THEN RAISE EXCEPTION 'job cannot own this mission attempt'; END IF;
    ELSE
        work_run := NEW.test_run_id;
        IF owner_operation NOT IN ('ADVANCE_RUN', 'EXECUTE_TESTS') THEN
            RAISE EXCEPTION 'job cannot own this execution';
        END IF;
    END IF;
    IF owner_run IS NULL OR work_run IS DISTINCT FROM owner_run THEN
        RAISE EXCEPTION 'durable work and job must belong to the same test run';
    END IF;
    RETURN NEW;
END;
$$;
"""))
    op.execute(sa.text("""
CREATE TRIGGER mission_attempt_job_ownership BEFORE INSERT OR UPDATE OF durable_job_id, mission_id
ON mission_attempts FOR EACH ROW EXECUTE FUNCTION hypertest_guard_job_ownership();
"""))
    op.execute(sa.text("""
CREATE TRIGGER execution_job_ownership BEFORE INSERT OR UPDATE OF durable_job_id, test_run_id
ON test_executions FOR EACH ROW EXECUTE FUNCTION hypertest_guard_job_ownership();
"""))


def downgrade() -> None:
    for table in ("mission_attempts", "test_executions"):
        if op.get_bind().scalar(sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {table} WHERE durable_job_id IS NOT NULL)"
        )):
            raise RuntimeError("cannot discard durable work ownership history")
    op.execute(sa.text("DROP TRIGGER IF EXISTS execution_job_ownership ON test_executions"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS mission_attempt_job_ownership ON mission_attempts"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS hypertest_guard_job_ownership()"))
    for table in ("test_executions", "mission_attempts"):
        op.drop_index(f"ix_{table}_durable_job_id", table_name=table)
        op.drop_constraint(f"fk_{table}_durable_job", table, type_="foreignkey")
        op.drop_column(table, "durable_job_id")
