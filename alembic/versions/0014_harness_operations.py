"""Operational persistent Harness calls, reports and runtime dispatch. No historical backfill."""
import re

import sqlalchemy as sa

from alembic import op

revision = "0014_harness_operations"
down_revision = "0013_run_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text('CREATE TABLE run_harness_states (\n\tbinding_id UUID NOT NULL, \n\tfirst_job_id UUID NOT NULL, \n\tsource_workspace TEXT NOT NULL, \n\tmax_steps INTEGER NOT NULL, \n\ttimeout_seconds INTEGER NOT NULL, \n\tharness_budget_seconds INTEGER DEFAULT 3600 NOT NULL, \n\tactive_mission_id UUID, \n\tactive_attempt_id UUID, \n\tlast_call_id VARCHAR(128), \n\tlast_job_id UUID, \n\tlast_call_epoch INTEGER, \n\tpending_input JSONB, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (binding_id), \n\tCONSTRAINT ck_harness_budgets CHECK (max_steps BETWEEN 1 AND 32 AND timeout_seconds BETWEEN 1 AND 3600 AND harness_budget_seconds BETWEEN 1 AND 7200), \n\tFOREIGN KEY(binding_id) REFERENCES run_execution_bindings (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(first_job_id) REFERENCES durable_jobs (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(active_mission_id) REFERENCES missions (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(active_attempt_id) REFERENCES mission_attempts (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(last_job_id) REFERENCES durable_jobs (id) ON DELETE RESTRICT\n)'))
    op.execute(sa.text("CREATE TABLE run_tool_calls (\n\tid UUID NOT NULL, \n\tbinding_id UUID NOT NULL, \n\tdurable_job_id UUID NOT NULL, \n\tbinding_epoch INTEGER NOT NULL, \n\ttool_name VARCHAR(64) NOT NULL, \n\tidempotency_key VARCHAR(255) NOT NULL, \n\tinput_sha256 VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tresult JSONB, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_run_tool_identity UNIQUE (binding_id, idempotency_key), \n\tCONSTRAINT ck_run_tool_status CHECK (status IN ('STARTED','SUCCEEDED','FAILED','UNKNOWN')), \n\tFOREIGN KEY(binding_id) REFERENCES run_execution_bindings (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(durable_job_id) REFERENCES durable_jobs (id) ON DELETE RESTRICT\n)"))
    op.execute(sa.text('CREATE TABLE run_reports (\n\tid UUID NOT NULL, \n\ttest_run_id UUID NOT NULL, \n\tbinding_id UUID NOT NULL, \n\tdurable_job_id UUID NOT NULL, \n\tidempotency_key VARCHAR(255) NOT NULL, \n\tenvelope JSONB NOT NULL, \n\tartifact_uri TEXT NOT NULL, \n\tcontent_sha256 VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_run_report_identity UNIQUE (binding_id, idempotency_key), \n\tFOREIGN KEY(test_run_id) REFERENCES test_runs (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(binding_id) REFERENCES run_execution_bindings (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(durable_job_id) REFERENCES durable_jobs (id) ON DELETE RESTRICT\n)'))
    op.execute(sa.text("CREATE TABLE runtime_control_requests (\n\tid UUID NOT NULL, \n\toperation VARCHAR(32) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tresult JSONB, \n\terror_code VARCHAR(64), \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_control_operation CHECK (operation IN ('CAPABILITIES','ENVIRONMENTS','RESOLVE_ENVIRONMENT','CLEANUP_JOB','RECOVER_BINDING')), \n\tCONSTRAINT ck_control_status CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','UNKNOWN'))\n)"))
    op.execute(sa.text('CREATE INDEX ix_runtime_control_requests_status ON runtime_control_requests (status)'))
    op.execute(sa.text('CREATE TABLE gitlab_issue_operations (\n\tid UUID NOT NULL, \n\tbinding_id UUID NOT NULL, \n\ttest_run_id UUID NOT NULL, \n\tfinding_id UUID NOT NULL, \n\tdurable_job_id UUID NOT NULL, \n\tinput_sha256 VARCHAR(64) NOT NULL, \n\tdraft JSONB NOT NULL, \n\t"authorization" JSONB NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tissue_iid INTEGER, \n\tissue_url TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_gitlab_finding_issue UNIQUE (binding_id, finding_id), \n\tCONSTRAINT ck_gitlab_operation_status CHECK (status IN (\'PENDING\',\'UNKNOWN\',\'SUCCEEDED\',\'REJECTED\')), \n\tFOREIGN KEY(binding_id) REFERENCES run_execution_bindings (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(test_run_id) REFERENCES test_runs (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(finding_id) REFERENCES findings (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(durable_job_id) REFERENCES durable_jobs (id) ON DELETE RESTRICT\n)'))

    for statement in re.split(r";\s*(?=CREATE (?:FUNCTION|TRIGGER))", GUARDS):
        op.execute(sa.text(statement))


def downgrade() -> None:
    for name in ['gitlab_issue_operations', 'runtime_control_requests', 'run_reports', 'run_tool_calls', 'run_harness_states']:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {name})")):
            raise RuntimeError("retained Harness operational history prevents destructive downgrade")
    for name in ['gitlab_issue_operations', 'runtime_control_requests', 'run_reports', 'run_tool_calls', 'run_harness_states']:
        op.drop_table(name)

    for name in ["harness_state", "run_tool_call", "run_report", "runtime_control", "gitlab_operation"]:
        op.execute(sa.text(f"DROP FUNCTION hypertest_guard_{name}()"))


GUARDS = r"""
CREATE FUNCTION hypertest_guard_harness_state() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound run_execution_bindings%ROWTYPE; attempt_mission uuid; attempt_session uuid;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'harness checkpoint history cannot be deleted'; END IF;
    IF TG_OP='UPDATE' AND
       (NEW.binding_id,NEW.first_job_id,NEW.source_workspace,NEW.max_steps,NEW.timeout_seconds,NEW.harness_budget_seconds,NEW.created_at) IS DISTINCT FROM
       (OLD.binding_id,OLD.first_job_id,OLD.source_workspace,OLD.max_steps,OLD.timeout_seconds,OLD.harness_budget_seconds,OLD.created_at) THEN
        RAISE EXCEPTION 'harness initial configuration is immutable';
    END IF;
    SELECT * INTO bound FROM run_execution_bindings WHERE id=NEW.binding_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'harness state requires a binding'; END IF;
    IF NOT EXISTS (SELECT 1 FROM durable_jobs WHERE id=NEW.first_job_id AND test_run_id=bound.test_run_id AND job_type='ADVANCE_RUN') THEN
        RAISE EXCEPTION 'harness first job must belong to its run';
    END IF;
    IF length(btrim(NEW.source_workspace))=0 THEN RAISE EXCEPTION 'harness source workspace cannot be blank'; END IF;
    IF (NEW.active_mission_id IS NULL) <> (NEW.active_attempt_id IS NULL) THEN
        RAISE EXCEPTION 'harness active mission and attempt must be paired';
    END IF;
    IF NEW.active_mission_id IS NOT NULL THEN
        SELECT mission_id,agent_session_id INTO attempt_mission,attempt_session FROM mission_attempts WHERE id=NEW.active_attempt_id;
        IF attempt_mission IS DISTINCT FROM NEW.active_mission_id OR attempt_session IS DISTINCT FROM bound.primary_agent_session_id
           OR NOT EXISTS (SELECT 1 FROM missions WHERE id=NEW.active_mission_id AND test_run_id=bound.test_run_id) THEN
            RAISE EXCEPTION 'harness active attempt ownership mismatch';
        END IF;
    END IF;
    IF num_nonnulls(NEW.last_call_id,NEW.last_job_id,NEW.last_call_epoch) NOT IN (0,3) THEN
        RAISE EXCEPTION 'harness call checkpoint requires call job and epoch together';
    END IF;
    IF NEW.last_job_id IS NOT NULL AND (NEW.last_call_epoch < 1 OR NEW.last_call_epoch > bound.binding_epoch
       OR length(btrim(NEW.last_call_id))=0
       OR NOT EXISTS (SELECT 1 FROM durable_jobs WHERE id=NEW.last_job_id AND test_run_id=bound.test_run_id)) THEN
        RAISE EXCEPTION 'harness call checkpoint ownership mismatch';
    END IF;
    IF NEW.pending_input IS NOT NULL AND (jsonb_typeof(NEW.pending_input)<>'object' OR octet_length(NEW.pending_input::text)>65536) THEN
        RAISE EXCEPTION 'harness pending input must be a bounded object';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER harness_state_guard BEFORE INSERT OR UPDATE OR DELETE ON run_harness_states
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_harness_state();
CREATE FUNCTION hypertest_guard_run_tool_call() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound run_execution_bindings%ROWTYPE;
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'tool call history cannot be deleted'; END IF;
    IF TG_OP='UPDATE' THEN
        IF (to_jsonb(NEW)-ARRAY['status','result','finished_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','result','finished_at']) THEN
            RAISE EXCEPTION 'tool call identity and input are immutable';
        END IF;
        IF OLD.status IN ('SUCCEEDED','FAILED') THEN RAISE EXCEPTION 'terminal tool call history is immutable'; END IF;
        IF NOT ((OLD.status='STARTED' AND NEW.status IN ('UNKNOWN','SUCCEEDED','FAILED')) OR
                (OLD.status='UNKNOWN' AND NEW.status IN ('UNKNOWN','SUCCEEDED','FAILED'))) THEN
            RAISE EXCEPTION 'invalid tool call transition';
        END IF;
    ELSIF NEW.status<>'STARTED' THEN RAISE EXCEPTION 'tool call must begin started'; END IF;
    SELECT * INTO bound FROM run_execution_bindings WHERE id=NEW.binding_id;
    IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM durable_jobs WHERE id=NEW.durable_job_id AND test_run_id=bound.test_run_id) THEN
        RAISE EXCEPTION 'tool call job ownership mismatch';
    END IF;
    IF NEW.binding_epoch < 1 OR NEW.binding_epoch > bound.binding_epoch OR (TG_OP='INSERT' AND NEW.binding_epoch<>bound.binding_epoch) THEN
        RAISE EXCEPTION 'tool call epoch is not current';
    END IF;
    IF NEW.input_sha256 !~ '^[a-f0-9]{64}$' OR length(btrim(NEW.tool_name))=0 OR length(btrim(NEW.idempotency_key))=0 THEN
        RAISE EXCEPTION 'tool call requires bounded identity and input digest';
    END IF;
    IF NEW.tool_name='__bridge_call__' THEN
        IF NEW.result IS NULL OR jsonb_typeof(NEW.result)<>'object'
           OR jsonb_typeof(NEW.result->'reserved_seconds') IS DISTINCT FROM 'number'
           OR (NEW.result->>'reserved_seconds') !~ '^[0-9]+$'
           OR (NEW.result->>'reserved_seconds')::numeric NOT BETWEEN 1 AND 7200
           OR jsonb_typeof(NEW.result->'call_id') IS DISTINCT FROM 'string'
           OR length(btrim(NEW.result->>'call_id'))=0 THEN
            RAISE EXCEPTION 'bridge call requires a bounded time reservation and identity';
        END IF;
        IF TG_OP='UPDATE' AND
           (NEW.result->'reserved_seconds',NEW.result->'call_id') IS DISTINCT FROM
           (OLD.result->'reserved_seconds',OLD.result->'call_id') THEN
            RAISE EXCEPTION 'bridge call reservation and identity are immutable';
        END IF;
        IF NEW.status IN ('STARTED','UNKNOWN') AND NEW.result ? 'elapsed_seconds' THEN
            RAISE EXCEPTION 'unverified bridge call cannot release reserved time';
        END IF;
        IF NEW.status IN ('SUCCEEDED','FAILED') AND
           (jsonb_typeof(NEW.result->'elapsed_seconds') IS DISTINCT FROM 'number'
            OR (NEW.result->>'elapsed_seconds')::numeric NOT BETWEEN 0 AND (NEW.result->>'reserved_seconds')::numeric
            OR jsonb_typeof(NEW.result->'native_status') IS DISTINCT FROM 'string') THEN
            RAISE EXCEPTION 'bridge call terminal outcome requires verified elapsed time and native status';
        END IF;
    END IF;
    IF (NEW.status='STARTED' AND (NEW.finished_at IS NOT NULL OR (NEW.tool_name<>'__bridge_call__' AND NEW.result IS NOT NULL))) OR
       (NEW.status IN ('SUCCEEDED','FAILED') AND (NEW.finished_at IS NULL OR NEW.result IS NULL)) OR
       (NEW.result IS NOT NULL AND jsonb_typeof(NEW.result)<>'object') THEN
        RAISE EXCEPTION 'tool call outcome does not match its state';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_tool_call_guard BEFORE INSERT OR UPDATE OR DELETE ON run_tool_calls
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_run_tool_call();
CREATE FUNCTION hypertest_guard_run_report() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'run report history is append-only'; END IF;
    IF NOT EXISTS (SELECT 1 FROM run_execution_bindings WHERE id=NEW.binding_id AND test_run_id=NEW.test_run_id)
       OR NOT EXISTS (SELECT 1 FROM durable_jobs WHERE id=NEW.durable_job_id AND test_run_id=NEW.test_run_id) THEN
        RAISE EXCEPTION 'run report ownership mismatch';
    END IF;
    IF NEW.content_sha256 !~ '^[a-f0-9]{64}$' OR NEW.artifact_uri IS DISTINCT FROM ('sha256:'||NEW.content_sha256)
       OR jsonb_typeof(NEW.envelope)<>'object' OR length(btrim(NEW.idempotency_key))=0 THEN
        RAISE EXCEPTION 'run report requires an immutable content address and envelope';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_report_guard BEFORE INSERT OR UPDATE OR DELETE ON run_reports
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_run_report();
CREATE FUNCTION hypertest_guard_runtime_control() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'runtime control history cannot be deleted'; END IF;
    IF TG_OP='UPDATE' THEN
        IF (NEW.id,NEW.operation,NEW.payload,NEW.created_at,NEW.expires_at) IS DISTINCT FROM
           (OLD.id,OLD.operation,OLD.payload,OLD.created_at,OLD.expires_at) THEN
            RAISE EXCEPTION 'runtime control request identity is immutable';
        END IF;
        IF OLD.status IN ('SUCCEEDED','FAILED','UNKNOWN') THEN RAISE EXCEPTION 'terminal runtime control history is immutable'; END IF;
        IF NOT ((OLD.status='QUEUED' AND NEW.status IN ('RUNNING','UNKNOWN')) OR
                (OLD.status='RUNNING' AND NEW.status IN ('SUCCEEDED','FAILED','UNKNOWN'))) THEN
            RAISE EXCEPTION 'invalid runtime control transition';
        END IF;
        IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN
            RAISE EXCEPTION 'runtime control start time is immutable';
        END IF;
    ELSIF NEW.status<>'QUEUED' THEN RAISE EXCEPTION 'runtime control must begin queued'; END IF;
    IF jsonb_typeof(NEW.payload)<>'object' OR (NEW.result IS NOT NULL AND jsonb_typeof(NEW.result)<>'object')
       OR NEW.expires_at <= NEW.created_at THEN RAISE EXCEPTION 'invalid runtime control envelope'; END IF;
    IF (NEW.status='QUEUED' AND (NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL OR NEW.result IS NOT NULL OR NEW.error_code IS NOT NULL))
       OR (NEW.status='RUNNING' AND (NEW.started_at IS NULL OR NEW.finished_at IS NOT NULL OR NEW.result IS NOT NULL OR NEW.error_code IS NOT NULL))
       OR (NEW.status IN ('SUCCEEDED','FAILED') AND (NEW.started_at IS NULL OR NEW.finished_at IS NULL))
       OR (NEW.status='UNKNOWN' AND NEW.finished_at IS NULL) THEN
        RAISE EXCEPTION 'runtime control outcome does not match its state';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER runtime_control_guard BEFORE INSERT OR UPDATE OR DELETE ON runtime_control_requests
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_runtime_control();
CREATE FUNCTION hypertest_guard_gitlab_operation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'GitLab operation history cannot be deleted'; END IF;
    IF TG_OP='UPDATE' THEN
        IF (to_jsonb(NEW)-ARRAY['status','issue_iid','issue_url','updated_at']) IS DISTINCT FROM
           (to_jsonb(OLD)-ARRAY['status','issue_iid','issue_url','updated_at']) THEN
            RAISE EXCEPTION 'GitLab draft authorization and ownership are immutable';
        END IF;
        IF OLD.status IN ('SUCCEEDED','REJECTED') THEN RAISE EXCEPTION 'terminal GitLab operation history is immutable'; END IF;
        IF NOT ((OLD.status='PENDING' AND NEW.status IN ('UNKNOWN','SUCCEEDED','REJECTED')) OR
                (OLD.status='UNKNOWN' AND NEW.status IN ('UNKNOWN','SUCCEEDED','REJECTED'))) THEN
            RAISE EXCEPTION 'invalid GitLab operation transition';
        END IF;
    ELSIF NEW.status<>'PENDING' THEN RAISE EXCEPTION 'GitLab operation must begin pending'; END IF;
    IF NOT EXISTS (SELECT 1 FROM run_execution_bindings WHERE id=NEW.binding_id AND test_run_id=NEW.test_run_id)
       OR NOT EXISTS (SELECT 1 FROM durable_jobs WHERE id=NEW.durable_job_id AND test_run_id=NEW.test_run_id)
       OR NOT EXISTS (SELECT 1 FROM findings WHERE id=NEW.finding_id AND test_run_id=NEW.test_run_id) THEN
        RAISE EXCEPTION 'GitLab operation ownership mismatch';
    END IF;
    IF NEW.input_sha256 !~ '^[a-f0-9]{64}$' OR jsonb_typeof(NEW.draft)<>'object' OR jsonb_typeof(NEW.authorization)<>'object' THEN
        RAISE EXCEPTION 'GitLab operation requires an input digest draft and authorization';
    END IF;
    IF (NEW.status='SUCCEEDED' AND (NEW.issue_iid IS NULL OR NEW.issue_iid<1 OR NEW.issue_url IS NULL OR NEW.issue_url !~ '^https://[^/]+/.+/issues/[0-9]+$'))
       OR (NEW.status<>'SUCCEEDED' AND (NEW.issue_iid IS NOT NULL OR NEW.issue_url IS NOT NULL)) THEN
        RAISE EXCEPTION 'GitLab issue reference does not match its state';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER gitlab_operation_guard BEFORE INSERT OR UPDATE OR DELETE ON gitlab_issue_operations
FOR EACH ROW EXECUTE FUNCTION hypertest_guard_gitlab_operation();
"""
