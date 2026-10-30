"""Add an independent immutable original-identity and action-send ledger."""
import sqlalchemy as sa

from alembic import op

revision = "0037_cloud_action_ledger"
down_revision = "0036_cli_global_authorization"
branch_labels = None
depends_on = None
TABLES = ("cloud_action_identities", "cloud_action_sends", "cloud_action_observations")


def upgrade():
    for statement in CREATE_SQL.split(";"):
        if statement.strip():
            op.execute(sa.text(statement))
    op.execute(sa.text(GUARD))
    for table in TABLES:
        op.execute(sa.text(f"CREATE TRIGGER cloud_action_history_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_cloud_action_history()"))


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cloud action history prevents destructive downgrade")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute(sa.text("DROP FUNCTION hypertest_guard_cloud_action_history()"))


CREATE_SQL = r"""
CREATE TABLE cloud_action_identities (
 id UUID PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
 project_id UUID NOT NULL, task_id UUID NOT NULL, attempt_id UUID NOT NULL, config_id UUID NOT NULL,
 work_grant_id UUID NOT NULL REFERENCES cloud_work_grants(id) ON DELETE RESTRICT,
 worker_id VARCHAR(255) NOT NULL, generation BIGINT NOT NULL,
 operation_key VARCHAR(96) NOT NULL, action_key VARCHAR(64) NOT NULL,
 client_ref VARCHAR(96) NOT NULL, unique_ref VARCHAR(96) NOT NULL, target VARCHAR(512) NOT NULL,
 plan_sha256 VARCHAR(64) NOT NULL, hard_deadline TIMESTAMPTZ NOT NULL,
 UNIQUE(task_id,action_key), UNIQUE(attempt_id,operation_key), UNIQUE(project_id,client_ref), UNIQUE(project_id,unique_ref),
 UNIQUE(project_id,task_id,attempt_id,id),
 FOREIGN KEY(project_id,task_id) REFERENCES cloud_tasks(project_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(task_id,attempt_id) REFERENCES cloud_attempts(task_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(project_id,config_id) REFERENCES project_cloud_config_revisions(project_id,id) ON DELETE RESTRICT,
 CHECK(generation > 0 AND hard_deadline > created_at), CHECK(plan_sha256 ~ '^[a-f0-9]{64}$')
);
CREATE TABLE cloud_action_sends (
 id UUID PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
 project_id UUID NOT NULL, task_id UUID NOT NULL, attempt_id UUID NOT NULL,
 identity_id UUID NOT NULL, body_sha256 VARCHAR(64) NOT NULL, state VARCHAR(16) NOT NULL,
 UNIQUE(identity_id), UNIQUE(project_id,task_id,attempt_id,id),
 FOREIGN KEY(project_id,task_id,attempt_id,identity_id)
 REFERENCES cloud_action_identities(project_id,task_id,attempt_id,id) ON DELETE RESTRICT,
 CHECK(body_sha256 ~ '^[a-f0-9]{64}$'), CHECK(state = 'SENT')
);
CREATE TABLE cloud_action_observations (
 id UUID PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
 project_id UUID NOT NULL, task_id UUID NOT NULL, attempt_id UUID NOT NULL,
 send_id UUID NOT NULL, state VARCHAR(32) NOT NULL, observation_sha256 VARCHAR(64) NOT NULL,
 observation JSONB NOT NULL, UNIQUE(send_id,observation_sha256),
 FOREIGN KEY(project_id,task_id,attempt_id,send_id)
 REFERENCES cloud_action_sends(project_id,task_id,attempt_id,id) ON DELETE RESTRICT,
 CHECK(state IN ('HTTP_OBSERVED','UNKNOWN','BUSINESS_TERMINAL')), CHECK(observation_sha256 ~ '^[a-f0-9]{64}$')
);
CREATE UNIQUE INDEX uq_cloud_action_http_observed ON cloud_action_observations(send_id) WHERE state='HTTP_OBSERVED';
CREATE UNIQUE INDEX uq_cloud_action_terminal_observed ON cloud_action_observations(send_id) WHERE state='BUSINESS_TERMINAL';
"""

GUARD = r"""
CREATE FUNCTION hypertest_guard_cloud_action_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  owner cloud_work_grants%ROWTYPE;
  intent cloud_action_identities%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
   RAISE EXCEPTION 'Cloud action history is immutable';
 END IF;
 IF TG_TABLE_NAME = 'cloud_action_identities' THEN
   SELECT * INTO STRICT owner FROM cloud_work_grants WHERE id=NEW.work_grant_id;
   IF owner.project_id <> NEW.project_id OR owner.attempt_id IS DISTINCT FROM NEW.attempt_id
      OR owner.worker_id <> NEW.worker_id OR owner.lease_generation <> NEW.generation THEN
     RAISE EXCEPTION 'Cloud action identity must match its original grant';
   END IF;
 ELSIF TG_TABLE_NAME = 'cloud_action_sends' THEN
   SELECT * INTO STRICT intent FROM cloud_action_identities WHERE id=NEW.identity_id;
   IF NEW.created_at >= intent.hard_deadline THEN RAISE EXCEPTION 'Cloud action deadline expired'; END IF;
 ELSIF NEW.state = 'BUSINESS_TERMINAL' THEN
   IF jsonb_typeof(NEW.observation) IS DISTINCT FROM 'object'
      OR NOT NEW.observation ?& ARRAY['state','projection','order_response_sha256','details_response_sha256','observed_at']
      OR NEW.observation - ARRAY['state','projection','order_response_sha256','details_response_sha256','observed_at'] <> '{}'::jsonb
      OR NEW.observation->>'state' IS DISTINCT FROM 'BUSINESS_TERMINAL'
      OR NEW.observation->>'order_response_sha256' !~ '^[a-f0-9]{64}$'
      OR NEW.observation->>'details_response_sha256' !~ '^[a-f0-9]{64}$'
      OR jsonb_typeof(NEW.observation->'observed_at') IS DISTINCT FROM 'number'
      OR NEW.observation->>'observed_at' !~ '^[1-9][0-9]{0,12}$'
      OR (NEW.observation->>'observed_at')::bigint > extract(epoch FROM clock_timestamp()) + 5
      OR jsonb_typeof(NEW.observation->'projection') IS DISTINCT FROM 'object'
      OR NOT NEW.observation->'projection' ?& ARRAY['profile','client_order_id','order_id','business_status','business_terminal','details','chain_receipt','actual_trx_received']
      OR (NEW.observation->'projection') - ARRAY['profile','client_order_id','order_id','business_status','business_terminal','details','chain_receipt','actual_trx_received'] <> '{}'::jsonb
      OR NEW.observation->'projection'->'business_terminal' IS DISTINCT FROM 'true'::jsonb
      OR NEW.observation->'projection'->>'chain_receipt' IS DISTINCT FROM 'UNOBSERVED'
      OR NEW.observation->'projection'->>'actual_trx_received' IS DISTINCT FROM 'UNOBSERVED'
      OR jsonb_typeof(NEW.observation->'projection'->'details') IS DISTINCT FROM 'array'
      OR jsonb_array_length(NEW.observation->'projection'->'details') NOT BETWEEN 1 AND 128 THEN
     RAISE EXCEPTION 'Cloud action terminal observation is invalid';
   END IF;
 ELSE
   IF jsonb_typeof(NEW.observation) IS DISTINCT FROM 'object'
      OR NOT NEW.observation ?& ARRAY['state','http_status','body_sha256','byte_count','reason','observed_at']
      OR NEW.observation - ARRAY['state','http_status','body_sha256','byte_count','reason','observed_at'] <> '{}'::jsonb
      OR NEW.observation->>'state' IS DISTINCT FROM NEW.state
      OR NEW.observation->>'body_sha256' !~ '^[a-f0-9]{64}$'
      OR jsonb_typeof(NEW.observation->'byte_count') IS DISTINCT FROM 'number'
      OR NEW.observation->>'byte_count' !~ '^(0|[1-9][0-9]{0,6})$'
      OR (NEW.observation->>'byte_count')::bigint > 262144
      OR jsonb_typeof(NEW.observation->'observed_at') IS DISTINCT FROM 'number'
      OR NEW.observation->>'observed_at' !~ '^[1-9][0-9]{0,12}$'
      OR (NEW.observation->>'observed_at')::bigint > extract(epoch FROM clock_timestamp()) + 5
      OR jsonb_typeof(NEW.observation->'reason') IS DISTINCT FROM 'string'
      OR (NEW.state = 'HTTP_OBSERVED' AND (jsonb_typeof(NEW.observation->'http_status') IS DISTINCT FROM 'number'
          OR (NEW.observation->>'http_status')::int NOT BETWEEN 100 AND 599
          OR NEW.observation->>'reason' IS DISTINCT FROM 'RESPONSE_OBSERVED'))
      OR (NEW.state = 'UNKNOWN' AND (NEW.observation->'http_status' IS DISTINCT FROM 'null'::jsonb
          OR (NEW.observation->>'byte_count')::bigint <> 0
          OR NEW.observation->>'body_sha256' IS DISTINCT FROM 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
          OR NEW.observation->>'reason' NOT IN ('TRANSPORT_UNKNOWN','AUTHORITY_LOST','OUTPUT_REJECTED'))) THEN
     RAISE EXCEPTION 'Cloud action observation is invalid';
   END IF;
 END IF;
 RETURN NEW;
END;
$$
"""
