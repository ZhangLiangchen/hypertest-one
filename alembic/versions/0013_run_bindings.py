"""Persistent Run ownership and dual-scope questions; never backfill old sessions.

Revision ID: 0013_run_bindings
Revises: 0012_api_environment_v2
"""
import re

import sqlalchemy as sa

from alembic import op

revision = "0013_run_bindings"
down_revision = "0012_api_environment_v2"
branch_labels = None
depends_on = None


def _execute(sql: str) -> None:
    for statement in re.split(r";\s*(?=CREATE (?:FUNCTION|TRIGGER))", sql):
        op.execute(sa.text(statement))


def upgrade() -> None:
    op.create_table(
        "run_execution_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("test_run_id", sa.Uuid(), sa.ForeignKey("test_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("logical_worker_id", sa.Uuid(), nullable=False),
        sa.Column("primary_agent_session_id", sa.Uuid(), sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("harness_host_id", sa.String(255), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("binding_epoch", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("test_run_id", name="uq_run_binding_run"),
        sa.UniqueConstraint("logical_worker_id", name="uq_run_binding_worker"),
        sa.UniqueConstraint("primary_agent_session_id", name="uq_run_binding_session"),
        sa.CheckConstraint("binding_epoch > 0", name="ck_run_binding_epoch"),
        sa.CheckConstraint("row_version > 0", name="ck_run_binding_version"),
        sa.CheckConstraint("length(btrim(harness_host_id)) > 0", name="ck_run_binding_host"),
        sa.CheckConstraint("length(btrim(workspace_id)) > 0", name="ck_run_binding_workspace"),
        sa.CheckConstraint("status IN ('RESERVED','ACTIVE','WAITING_INPUT','RECOVERY_REQUIRED','CLOSED','FAILED','CANCELLED')", name="ck_run_binding_status"),
    )
    op.create_table(
        "run_input_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), sa.ForeignKey("test_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("binding_id", sa.Uuid(), sa.ForeignKey("run_execution_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agent_session_id", sa.Uuid(), sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("durable_job_id", sa.Uuid(), sa.ForeignKey("durable_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("context_mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="RESTRICT")),
        sa.Column("context_attempt_id", sa.Uuid(), sa.ForeignKey("mission_attempts.id", ondelete="RESTRICT")),
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
        sa.UniqueConstraint("binding_id", "question_id", name="uq_run_input_question"),
        sa.UniqueConstraint("test_run_id", "key", name="uq_run_input_key"),
        sa.CheckConstraint("status IN ('PENDING','ANSWERED','CONSUMED','CANCELLED')", name="ck_run_input_status"),
        sa.CheckConstraint("row_version > 0", name="ck_run_input_version"),
        sa.CheckConstraint("length(btrim(question)) > 0 AND length(question) <= 4096", name="ck_run_input_question_text"),
        sa.CheckConstraint("answer IS NULL OR (length(btrim(answer)) > 0 AND length(answer) <= 12000)", name="ck_run_input_answer_text"),
        sa.CheckConstraint("(answer IS NULL) = (answered_at IS NULL) AND (answer IS NULL) = (answer_idempotency_key IS NULL)", name="ck_run_input_answer_fields"),
        sa.CheckConstraint("(status = 'PENDING' AND answer IS NULL AND consumed_at IS NULL AND cancelled_at IS NULL) OR (status = 'ANSWERED' AND answer IS NOT NULL AND consumed_at IS NULL AND cancelled_at IS NULL) OR (status = 'CONSUMED' AND answer IS NOT NULL AND consumed_at IS NOT NULL AND cancelled_at IS NULL) OR (status = 'CANCELLED' AND cancelled_at IS NOT NULL)", name="ck_run_input_lifecycle"),
    )
    for column in ("test_run_id", "binding_id", "durable_job_id"):
        op.create_index(f"ix_run_input_requests_{column}", "run_input_requests", [column])
    op.create_index("uq_run_input_open_run", "run_input_requests", ["test_run_id"], unique=True,
                    postgresql_where=sa.text("status IN ('PENDING','ANSWERED')"))
    _execute("""
CREATE FUNCTION hypertest_guard_run_binding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE native_run uuid; native_workspace text;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'run binding history is immutable'; END IF;
    PERFORM id FROM test_runs WHERE id = NEW.test_run_id FOR UPDATE;
    IF TG_OP = 'INSERT' THEN
        IF NEW.binding_epoch <> 1 OR NEW.status <> 'RESERVED' OR NEW.row_version <> 1 THEN
            RAISE EXCEPTION 'run binding must start reserved at epoch/version one';
        END IF;
        IF EXISTS (SELECT 1 FROM agent_sessions WHERE test_run_id = NEW.test_run_id AND id <> NEW.primary_agent_session_id)
           OR EXISTS (SELECT 1 FROM mission_attempts a JOIN missions m ON m.id=a.mission_id WHERE m.test_run_id=NEW.test_run_id) THEN
            RAISE EXCEPTION 'legacy session history cannot be converted into a persistent run binding';
        END IF;
    ELSE
        IF to_jsonb(NEW) IS NOT DISTINCT FROM to_jsonb(OLD) THEN RETURN NEW; END IF;
        IF (to_jsonb(NEW) - ARRAY['status','binding_epoch','updated_at','row_version']) IS DISTINCT FROM
           (to_jsonb(OLD) - ARRAY['status','binding_epoch','updated_at','row_version']) THEN
            RAISE EXCEPTION 'run binding ownership is immutable';
        END IF;
        IF OLD.status IN ('CLOSED','FAILED','CANCELLED') THEN
            RAISE EXCEPTION 'terminal run binding is immutable';
        END IF;
        IF NOT (
            (OLD.status = 'RESERVED' AND NEW.status IN ('ACTIVE','RECOVERY_REQUIRED','CLOSED','FAILED','CANCELLED')) OR
            (OLD.status = 'ACTIVE' AND NEW.status IN ('WAITING_INPUT','RECOVERY_REQUIRED','CLOSED','FAILED','CANCELLED')) OR
            (OLD.status = 'WAITING_INPUT' AND NEW.status IN ('ACTIVE','RECOVERY_REQUIRED','CLOSED','FAILED','CANCELLED')) OR
            (OLD.status = 'RECOVERY_REQUIRED' AND NEW.status IN ('ACTIVE','CLOSED','FAILED','CANCELLED'))
        ) THEN RAISE EXCEPTION 'invalid run binding transition'; END IF;
        IF OLD.status = 'RECOVERY_REQUIRED' AND NEW.status = 'ACTIVE' THEN
            IF NEW.binding_epoch <> OLD.binding_epoch + 1 THEN RAISE EXCEPTION 'explicit recovery must advance epoch once'; END IF;
            IF EXISTS (SELECT 1 FROM durable_jobs WHERE test_run_id=NEW.test_run_id AND status IN ('QUEUED','RUNNING','WAITING_INPUT','CANCEL_REQUESTED')) THEN
                RAISE EXCEPTION 'explicit recovery requires all previous jobs to be terminal';
            END IF;
        ELSIF NEW.binding_epoch <> OLD.binding_epoch THEN
            RAISE EXCEPTION 'only explicit recovery may advance binding epoch';
        END IF;
        IF NEW.row_version <> OLD.row_version + 1 THEN RAISE EXCEPTION 'run binding version must advance once'; END IF;
    END IF;
    SELECT test_run_id, workspace_id INTO native_run, native_workspace FROM agent_sessions WHERE id=NEW.primary_agent_session_id;
    IF native_run IS DISTINCT FROM NEW.test_run_id OR native_workspace IS DISTINCT FROM NEW.workspace_id THEN
        RAISE EXCEPTION 'primary session does not match run binding';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_binding_history BEFORE INSERT OR UPDATE OR DELETE ON run_execution_bindings
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_run_binding();
""")
    _execute("""
CREATE FUNCTION hypertest_guard_bound_session() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound run_execution_bindings%ROWTYPE;
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM id FROM test_runs WHERE id=NEW.test_run_id FOR UPDATE;
        IF EXISTS (SELECT 1 FROM run_execution_bindings WHERE test_run_id=NEW.test_run_id) THEN
            RAISE EXCEPTION 'persistent run cannot create a replacement session';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO bound FROM run_execution_bindings WHERE primary_agent_session_id=OLD.id;
    IF NOT FOUND THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'bound session history is immutable'; END IF;
    IF (NEW.id,NEW.test_run_id,NEW.provider,NEW.harness,NEW.workspace_id,NEW.created_at) IS DISTINCT FROM
       (OLD.id,OLD.test_run_id,OLD.provider,OLD.harness,OLD.workspace_id,OLD.created_at) THEN
        RAISE EXCEPTION 'persistent primary session ownership is immutable';
    END IF;
    IF OLD.provider_session_id IS NOT NULL AND NEW.provider_session_id IS DISTINCT FROM OLD.provider_session_id THEN
        RAISE EXCEPTION 'persistent native session reference is immutable';
    END IF;
    IF NEW.provider_session_id IS NOT NULL AND length(btrim(NEW.provider_session_id))=0 THEN
        RAISE EXCEPTION 'persistent native session reference must be nonblank';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER bound_session_history BEFORE INSERT OR UPDATE OR DELETE ON agent_sessions
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_bound_session();
CREATE FUNCTION hypertest_guard_bound_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run_id uuid; bound run_execution_bindings%ROWTYPE;
BEGIN
    IF TG_OP='DELETE' THEN
        IF EXISTS (SELECT 1 FROM missions m JOIN run_execution_bindings b ON b.test_run_id=m.test_run_id WHERE m.id=OLD.mission_id) THEN
            RAISE EXCEPTION 'persistent attempt history cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP='UPDATE' AND (NEW.mission_id,NEW.agent_session_id) IS DISTINCT FROM (OLD.mission_id,OLD.agent_session_id)
       AND EXISTS (SELECT 1 FROM missions m JOIN run_execution_bindings b ON b.test_run_id=m.test_run_id WHERE m.id=OLD.mission_id) THEN
        RAISE EXCEPTION 'persistent attempt ownership is immutable';
    END IF;
    SELECT test_run_id INTO run_id FROM missions WHERE id=NEW.mission_id;
    PERFORM id FROM test_runs WHERE id=run_id FOR UPDATE;
    SELECT * INTO bound FROM run_execution_bindings WHERE test_run_id=run_id;
    IF NOT FOUND THEN RETURN NEW; END IF;
    IF NEW.agent_session_id IS DISTINCT FROM bound.primary_agent_session_id THEN
        RAISE EXCEPTION 'persistent attempt must use its run primary session';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status IN ('ACCEPTED','REJECTED','FAILED','CANCELLED') AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'completed persistent attempt cannot be reopened';
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.mission_id,NEW.agent_session_id) IS DISTINCT FROM (OLD.mission_id,OLD.agent_session_id) THEN
        RAISE EXCEPTION 'persistent attempt ownership is immutable';
    END IF;
    IF NEW.status IN ('CREATED','RUNNING','SUBMITTED') AND EXISTS (
        SELECT 1 FROM mission_attempts a JOIN missions m ON m.id=a.mission_id
        WHERE m.test_run_id=run_id AND a.id<>NEW.id AND a.status IN ('CREATED','RUNNING','SUBMITTED')
    ) THEN RAISE EXCEPTION 'persistent run allows only one active attempt'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER bound_attempt_owner BEFORE INSERT OR UPDATE OR DELETE ON mission_attempts
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_bound_attempt();
""")
    _execute("""
CREATE FUNCTION hypertest_guard_run_input() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound run_execution_bindings%ROWTYPE; job_run uuid; context_run uuid; context_status text; attempt_mission uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'run input history is append-only'; END IF;
    IF TG_OP = 'INSERT' AND NEW.status <> 'PENDING' THEN RAISE EXCEPTION 'run input must begin pending'; END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (to_jsonb(NEW) - ARRAY['status','answer','answer_idempotency_key','answered_at','consumed_at','cancelled_at','row_version']) IS DISTINCT FROM
           (to_jsonb(OLD) - ARRAY['status','answer','answer_idempotency_key','answered_at','consumed_at','cancelled_at','row_version']) THEN
            RAISE EXCEPTION 'run question and ownership are immutable';
        END IF;
        IF OLD.status IN ('CONSUMED','CANCELLED') THEN RAISE EXCEPTION 'closed run input history is immutable'; END IF;
        IF OLD.answer IS NOT NULL AND (NEW.answer,NEW.answer_idempotency_key,NEW.answered_at) IS DISTINCT FROM
                                     (OLD.answer,OLD.answer_idempotency_key,OLD.answered_at) THEN
            RAISE EXCEPTION 'run answer is immutable';
        END IF;
        IF NOT ((OLD.status='PENDING' AND NEW.status IN ('ANSWERED','CANCELLED')) OR
                (OLD.status='ANSWERED' AND NEW.status IN ('CONSUMED','CANCELLED'))) THEN
            RAISE EXCEPTION 'invalid run input transition';
        END IF;
        IF NEW.row_version <> OLD.row_version+1 THEN RAISE EXCEPTION 'run input version must advance once'; END IF;
    END IF;
    SELECT * INTO bound FROM run_execution_bindings WHERE id=NEW.binding_id;
    SELECT test_run_id INTO job_run FROM durable_jobs WHERE id=NEW.durable_job_id;
    IF bound.test_run_id IS DISTINCT FROM NEW.test_run_id OR bound.primary_agent_session_id IS DISTINCT FROM NEW.agent_session_id
       OR job_run IS DISTINCT FROM NEW.test_run_id THEN RAISE EXCEPTION 'run input ownership mismatch'; END IF;
    IF NEW.context_attempt_id IS NOT NULL THEN
        SELECT mission_id INTO attempt_mission FROM mission_attempts WHERE id=NEW.context_attempt_id AND status='ACCEPTED';
        IF attempt_mission IS NULL OR (NEW.context_mission_id IS NOT NULL AND attempt_mission <> NEW.context_mission_id) THEN
            RAISE EXCEPTION 'run input context must reference an accepted completed stage';
        END IF;
    END IF;
    IF COALESCE(NEW.context_mission_id,attempt_mission) IS NOT NULL THEN
        SELECT test_run_id,status INTO context_run,context_status FROM missions WHERE id=COALESCE(NEW.context_mission_id,attempt_mission);
        IF context_run IS DISTINCT FROM NEW.test_run_id OR context_status IS DISTINCT FROM 'COMPLETED' THEN
            RAISE EXCEPTION 'run input context must reference an accepted completed stage';
        END IF;
    END IF;
    IF TG_OP='INSERT' AND EXISTS (SELECT 1 FROM mission_attempts a JOIN missions m ON m.id=a.mission_id
        WHERE m.test_run_id=NEW.test_run_id AND a.status IN ('CREATED','RUNNING','SUBMITTED')) THEN
        RAISE EXCEPTION 'run input cannot bypass an active mission attempt';
    END IF;
    IF length(btrim(NEW.question_id)) < 1 OR length(NEW.question_id) > 128 THEN
        RAISE EXCEPTION 'run question identifier must be bounded and nonblank';
    END IF;
    IF jsonb_typeof(NEW.options::jsonb) <> 'array' OR jsonb_array_length(NEW.options::jsonb)>8 THEN
        RAISE EXCEPTION 'run input options must be a bounded array';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.options::jsonb) AS item(value)
        WHERE jsonb_typeof(value)<>'string' OR length(btrim(value #>> '{}'))<1 OR length(value #>> '{}')>256)
        OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(NEW.options::jsonb) AS item(value)) <> jsonb_array_length(NEW.options::jsonb) THEN
        RAISE EXCEPTION 'run input options must be distinct bounded nonblank strings';
    END IF;
    IF NEW.answer_idempotency_key IS NOT NULL AND length(btrim(NEW.answer_idempotency_key))<1 THEN
        RAISE EXCEPTION 'run answer idempotency key must be nonblank';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_input_history BEFORE INSERT OR UPDATE OR DELETE ON run_input_requests
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_run_input();
CREATE FUNCTION hypertest_guard_open_run_question() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Both tables acquire the same aggregate lock: concurrent cross-scope inserts
    -- serialize before checking the other table, even outside application code.
    PERFORM id FROM test_runs WHERE id=NEW.test_run_id FOR UPDATE;
    IF NEW.status IN ('PENDING','ANSWERED') AND (
       EXISTS (SELECT 1 FROM mission_input_requests WHERE test_run_id=NEW.test_run_id
               AND status IN ('PENDING','ANSWERED') AND (TG_TABLE_NAME<>'mission_input_requests' OR id<>NEW.id)) OR
       EXISTS (SELECT 1 FROM run_input_requests WHERE test_run_id=NEW.test_run_id
               AND status IN ('PENDING','ANSWERED') AND (TG_TABLE_NAME<>'run_input_requests' OR id<>NEW.id))
    ) THEN RAISE EXCEPTION 'run already has an open human input request'; END IF;
    IF TG_TABLE_NAME='mission_input_requests' AND EXISTS (
        SELECT 1 FROM run_execution_bindings WHERE test_run_id=NEW.test_run_id
          AND primary_agent_session_id<>NEW.agent_session_id
    ) THEN RAISE EXCEPTION 'mission input must use its run primary session'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER a_open_run_question BEFORE INSERT OR UPDATE ON run_input_requests
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_open_run_question();
CREATE TRIGGER a_open_run_question BEFORE INSERT OR UPDATE ON mission_input_requests
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_open_run_question();
""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM run_execution_bindings) OR EXISTS (SELECT 1 FROM run_input_requests)")):
        raise RuntimeError("cannot discard persistent binding or run input history")
    for trigger, table in (("a_open_run_question", "mission_input_requests"), ("a_open_run_question", "run_input_requests"),
                           ("run_input_history", "run_input_requests"), ("bound_attempt_owner", "mission_attempts"),
                           ("bound_session_history", "agent_sessions"), ("run_binding_history", "run_execution_bindings")):
        op.execute(sa.text(f"DROP TRIGGER {trigger} ON {table}"))
    for function in ("hypertest_guard_open_run_question", "hypertest_guard_run_input", "hypertest_guard_bound_attempt", "hypertest_guard_bound_session", "hypertest_guard_run_binding"):
        op.execute(sa.text(f"DROP FUNCTION {function}()"))
    op.drop_table("run_input_requests")
    op.drop_table("run_execution_bindings")
