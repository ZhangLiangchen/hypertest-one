"""Add immutable HTTPS read intents/observations without executing any request."""
import sqlalchemy as sa

from alembic import op

revision = "0028_cloud_http_operations"
down_revision = "0027_project_memory"
branch_labels = None
depends_on = None
TABLES = ("cloud_http_operations", "cloud_http_observations")


def upgrade():
    for statement in CREATE_SQL.split(";"):
        if statement.strip():
            op.execute(sa.text(statement))
    op.execute(sa.text(GUARD))
    for table in TABLES:
        op.execute(sa.text(f"CREATE TRIGGER http_history_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_http_history()"))


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("HTTPS operation history prevents destructive downgrade")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute(sa.text("DROP FUNCTION hypertest_guard_http_history()"))


CREATE_SQL = r"""
CREATE TABLE cloud_http_operations (
 id UUID PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
 project_id UUID NOT NULL, task_id UUID NOT NULL, attempt_id UUID NOT NULL,
 config_id UUID NOT NULL, work_grant_id UUID NOT NULL REFERENCES cloud_work_grants(id) ON DELETE RESTRICT,
 worker_id VARCHAR(255) NOT NULL, generation BIGINT NOT NULL,
 operation_key VARCHAR(96) NOT NULL, resource_key VARCHAR(64) NOT NULL, target VARCHAR(512) NOT NULL,
 request_digest VARCHAR(64) NOT NULL, request JSONB NOT NULL, state VARCHAR(16) NOT NULL,
 sent_at TIMESTAMPTZ NOT NULL, hard_deadline TIMESTAMPTZ NOT NULL,
 UNIQUE(attempt_id, operation_key), UNIQUE(project_id,task_id,attempt_id,id,request_digest),
 FOREIGN KEY(project_id,task_id) REFERENCES cloud_tasks(project_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(task_id,attempt_id) REFERENCES cloud_attempts(task_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(project_id,config_id) REFERENCES project_cloud_config_revisions(project_id,id) ON DELETE RESTRICT,
 CHECK(generation > 0 AND hard_deadline > sent_at),
 CHECK(request_digest ~ '^[a-f0-9]{64}$'), CHECK(state = 'SENT')
);
CREATE TABLE cloud_http_observations (
 id UUID PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
 project_id UUID NOT NULL, task_id UUID NOT NULL, attempt_id UUID NOT NULL,
 operation_id UUID NOT NULL, request_digest VARCHAR(64) NOT NULL,
 worker_id VARCHAR(255) NOT NULL, generation BIGINT NOT NULL,
 state VARCHAR(16) NOT NULL, observation_digest VARCHAR(64) NOT NULL, observation JSONB NOT NULL,
 UNIQUE(operation_id,observation_digest),
 FOREIGN KEY(project_id,task_id,attempt_id,operation_id,request_digest)
 REFERENCES cloud_http_operations(project_id,task_id,attempt_id,id,request_digest) ON DELETE RESTRICT,
 CHECK(generation > 0), CHECK(state IN ('OBSERVED','UNKNOWN')),
 CHECK(observation_digest ~ '^[a-f0-9]{64}$')
);
CREATE UNIQUE INDEX uq_cloud_http_observed ON cloud_http_observations(operation_id) WHERE state = 'OBSERVED';
"""

GUARD = r"""
CREATE FUNCTION hypertest_guard_http_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 intent cloud_http_operations%ROWTYPE;
 owner cloud_work_grants%ROWTYPE;
 attempt cloud_attempts%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'HTTPS intents and observations are immutable';
 END IF;
 IF TG_TABLE_NAME = 'cloud_http_operations' THEN
  SELECT * INTO STRICT owner FROM cloud_work_grants WHERE id=NEW.work_grant_id;
  IF owner.project_id <> NEW.project_id OR owner.attempt_id IS DISTINCT FROM NEW.attempt_id
     OR owner.worker_id <> NEW.worker_id OR owner.lease_generation <> NEW.generation
     OR NEW.request->>'profile' IS DISTINCT FROM 'hypertest-https-controlled-api/v1'
     OR NEW.request->>'operation_id' IS DISTINCT FROM NEW.id::text
     OR NEW.request->>'task_id' IS DISTINCT FROM NEW.task_id::text
     OR NEW.request->>'attempt_id' IS DISTINCT FROM NEW.attempt_id::text
     OR NEW.request->>'generation' IS DISTINCT FROM NEW.generation::text
     OR NEW.request->>'target' IS DISTINCT FROM NEW.target
     OR NEW.request->'resource'->>'key' IS DISTINCT FROM NEW.resource_key
     OR NEW.request->>'hard_deadline' IS DISTINCT FROM (extract(epoch FROM NEW.hard_deadline)::bigint)::text THEN
   RAISE EXCEPTION 'HTTPS SENT identity must match its original grant and frozen request';
  END IF;
 ELSE
  SELECT * INTO STRICT intent FROM cloud_http_operations WHERE id=NEW.operation_id;
  IF NEW.worker_id <> intent.worker_id OR NEW.generation <> intent.generation
     OR jsonb_typeof(NEW.observation) IS DISTINCT FROM 'object'
     OR NOT NEW.observation ?& ARRAY['profile','operation_id','request_digest','state','http_status','body_sha256','byte_count','reason','observed_at']
     OR NEW.observation - ARRAY['profile','operation_id','request_digest','state','http_status','body_sha256','byte_count','reason','observed_at'] <> '{}'::jsonb
     OR NEW.observation->>'profile' IS DISTINCT FROM 'hypertest-https-response/v1'
     OR NEW.observation->>'operation_id' IS DISTINCT FROM intent.id::text
     OR NEW.observation->>'request_digest' IS DISTINCT FROM intent.request_digest
     OR NEW.observation->>'state' IS DISTINCT FROM NEW.state
     OR NEW.observation ? 'body_base64'
     OR NEW.observation->>'body_sha256' IS NULL OR NEW.observation->>'body_sha256' !~ '^[a-f0-9]{64}$'
     OR jsonb_typeof(NEW.observation->'byte_count') IS DISTINCT FROM 'number'
     OR NEW.observation->>'byte_count' !~ '^(0|[1-9][0-9]{0,12})$'
     OR jsonb_typeof(NEW.observation->'observed_at') IS DISTINCT FROM 'number'
     OR NEW.observation->>'observed_at' !~ '^[1-9][0-9]{0,12}$'
     OR (NEW.observation->>'observed_at')::bigint > extract(epoch FROM clock_timestamp()) + 5
     OR (NEW.observation->>'observed_at')::bigint < extract(epoch FROM intent.sent_at) - 1
     OR jsonb_typeof(NEW.observation->'reason') IS DISTINCT FROM 'string'
     OR (NEW.observation->>'byte_count')::bigint < 0
     OR (NEW.observation->>'byte_count')::bigint > (intent.request->'resource'->>'response_limit_bytes')::bigint THEN
   RAISE EXCEPTION 'HTTPS observation must match its original request without raw body';
  END IF;
  IF NEW.state = 'OBSERVED' THEN
   SELECT * INTO STRICT attempt FROM cloud_attempts WHERE id=intent.attempt_id;
   IF attempt.lease_generation <> intent.generation OR attempt.lease_owner IS DISTINCT FROM intent.worker_id
      OR attempt.status <> 'RUNNING' OR attempt.lease_expires_at <= clock_timestamp()
      OR jsonb_typeof(NEW.observation->'http_status') IS DISTINCT FROM 'number'
      OR (NEW.observation->>'http_status')::int NOT BETWEEN 200 AND 599
      OR ((NEW.observation->>'http_status')::int BETWEEN 300 AND 399 AND NEW.observation->>'reason' IS DISTINCT FROM 'REDIRECT_REFUSED')
      OR ((NEW.observation->>'http_status')::int NOT BETWEEN 300 AND 399 AND NEW.observation->>'reason' IS DISTINCT FROM 'RESPONSE_OBSERVED') THEN
    RAISE EXCEPTION 'HTTPS accepted response requires a current fenced Worker';
   END IF;
  ELSIF NEW.observation->'http_status' IS DISTINCT FROM 'null'::jsonb
     OR (NEW.observation->>'byte_count')::bigint <> 0
     OR NEW.observation->>'body_sha256' IS DISTINCT FROM 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
     OR NEW.observation->>'reason' NOT IN ('OUTPUT_LIMIT','TRANSPORT_UNKNOWN','AUTHORITY_LOST','OUTPUT_REJECTED') THEN
   RAISE EXCEPTION 'HTTPS UNKNOWN cannot claim a response or return bytes';
  END IF;
 END IF;
 RETURN NEW;
END;
$$
"""
