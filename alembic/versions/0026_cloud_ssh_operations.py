"""Add fixed SSH intent/observation/result history; no external operation.

DDL compiled remotely with PostgreSQL dialect from frozen domain SHA
4ed24fd1567681fa263507aab2b010cb6e18b0cd1f64df413d69bfd4f4bfc657.
Compiler output SHA7e860c9e4ac2b2b255e14b52541160829816a0bfb4ea46f2a322fea6cb799ec4.

Formal integration changes only revision/parent and source whitespace formatting;
the original isolated migration and accepted source pins remain unchanged.
"""
import sqlalchemy as sa

from alembic import op

revision = "0026_cloud_ssh_operations"
down_revision = "0025_cloud_tasks"
branch_labels = None
depends_on = None
TABLES = ["cloud_remote_operations", "cloud_remote_observations", "cloud_remote_operation_results"]


def upgrade():
    for statement in CREATE_SQL.split(";"):
        if statement.strip():
            op.execute(sa.text(statement))
    op.execute(sa.text(GUARD))
    for table in TABLES:
        op.execute(sa.text(f"CREATE TRIGGER ssh_history_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_ssh_history()"))


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("SSH operation history prevents destructive downgrade")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute(sa.text("DROP FUNCTION hypertest_guard_ssh_history()"))


CREATE_SQL = r"""
CREATE TABLE cloud_remote_operations (
 project_id UUID NOT NULL, task_id UUID NOT NULL, attempt_id UUID NOT NULL,
 config_id UUID NOT NULL, credential_version_id UUID NOT NULL, work_grant_id UUID NOT NULL,
 worker_id VARCHAR(255) NOT NULL, generation BIGINT NOT NULL,
 operation_key VARCHAR(96) NOT NULL, action_key VARCHAR(64) NOT NULL, target VARCHAR(512) NOT NULL,
 request_digest VARCHAR(64) NOT NULL, request JSONB NOT NULL, state VARCHAR(32) NOT NULL,
 sent_at TIMESTAMP WITH TIME ZONE NOT NULL, hard_deadline TIMESTAMP WITH TIME ZONE NOT NULL,
 last_sequence BIGINT NOT NULL, id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (id), UNIQUE (task_id, attempt_id, operation_key),
 UNIQUE (task_id, attempt_id, id, request_digest),
 FOREIGN KEY(project_id, task_id) REFERENCES cloud_tasks(project_id, id) ON DELETE RESTRICT,
 FOREIGN KEY(task_id, attempt_id) REFERENCES cloud_attempts(task_id, id) ON DELETE RESTRICT,
 FOREIGN KEY(project_id, config_id) REFERENCES project_cloud_config_revisions(project_id, id) ON DELETE RESTRICT,
 FOREIGN KEY(project_id, credential_version_id) REFERENCES project_credential_versions(project_id, id) ON DELETE RESTRICT,
 FOREIGN KEY(work_grant_id) REFERENCES cloud_work_grants(id) ON DELETE RESTRICT,
 CHECK(generation > 0 AND last_sequence >= 0 AND hard_deadline > sent_at),
 CHECK(request_digest ~ '^[a-f0-9]{64}$'),
 CHECK(state IN ('SENT','RUNNING','STOP_REQUESTED','COMPLETED','FAILED','CANCELLED','UNKNOWN'))
);
CREATE TABLE cloud_remote_observations (
 project_id UUID NOT NULL, task_id UUID NOT NULL, attempt_id UUID NOT NULL, operation_id UUID NOT NULL,
 request_digest VARCHAR(64) NOT NULL, sequence BIGINT NOT NULL,
 observation_digest VARCHAR(64) NOT NULL, observation JSONB NOT NULL,
 worker_id VARCHAR(255) NOT NULL, generation BIGINT NOT NULL, authority_mode VARCHAR(16) NOT NULL,
 id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY(id), UNIQUE(operation_id, sequence), UNIQUE(operation_id, observation_digest),
 UNIQUE(task_id, attempt_id, operation_id, request_digest, id),
 FOREIGN KEY(project_id, task_id) REFERENCES cloud_tasks(project_id, id) ON DELETE RESTRICT,
 FOREIGN KEY(task_id, attempt_id, operation_id, request_digest)
 REFERENCES cloud_remote_operations(task_id, attempt_id, id, request_digest) ON DELETE RESTRICT,
 CHECK(sequence > 0 AND generation > 0), CHECK(observation_digest ~ '^[a-f0-9]{64}$'),
 CHECK(authority_mode IN ('CURRENT','CLEANUP'))
);
CREATE TABLE cloud_remote_operation_results (
 project_id UUID NOT NULL, task_id UUID NOT NULL, attempt_id UUID NOT NULL, operation_id UUID NOT NULL,
 request_digest VARCHAR(64) NOT NULL, observation_id UUID NOT NULL, terminal_state VARCHAR(32) NOT NULL,
 request JSONB NOT NULL, observation JSONB NOT NULL, id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY(id), UNIQUE(operation_id), UNIQUE(observation_id),
 FOREIGN KEY(project_id, task_id) REFERENCES cloud_tasks(project_id, id) ON DELETE RESTRICT,
 FOREIGN KEY(task_id, attempt_id, operation_id, request_digest, observation_id)
 REFERENCES cloud_remote_observations(task_id, attempt_id, operation_id, request_digest, id) ON DELETE RESTRICT,
 CHECK(terminal_state IN ('COMPLETED','FAILED','CANCELLED'))
);
"""

GUARD = r"""
CREATE FUNCTION hypertest_guard_ssh_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 intent cloud_remote_operations%ROWTYPE;
 observed cloud_remote_observations%ROWTYPE;
 owner cloud_work_grants%ROWTYPE;
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'SSH operation history is append-only';
 END IF;
 IF TG_OP = 'UPDATE' THEN
  IF TG_TABLE_NAME <> 'cloud_remote_operations' THEN
   RAISE EXCEPTION 'SSH observations and terminal results are immutable';
  END IF;
  IF (to_jsonb(NEW) - ARRAY['state','last_sequence']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['state','last_sequence'])
     OR NEW.last_sequence <> OLD.last_sequence + 1
     OR OLD.state IN ('COMPLETED','FAILED','CANCELLED')
     OR (NEW.state = 'SENT' AND OLD.state <> 'SENT')
     OR (OLD.state = 'STOP_REQUESTED' AND NEW.state = 'RUNNING') THEN
   RAISE EXCEPTION 'SSH request identity, sequence and terminal state are immutable';
  END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME = 'cloud_remote_operations' THEN
  IF NEW.state <> 'SENT' OR NEW.last_sequence <> 0 THEN
   RAISE EXCEPTION 'SSH operation must first persist SENT';
  END IF;
  SELECT * INTO STRICT owner FROM cloud_work_grants WHERE id = NEW.work_grant_id;
  IF owner.project_id <> NEW.project_id OR owner.attempt_id IS DISTINCT FROM NEW.attempt_id
     OR owner.worker_id <> NEW.worker_id OR owner.lease_generation <> NEW.generation
     OR NEW.request->>'profile' IS DISTINCT FROM 'hypertest-ssh-fixed-diagnostics/v1'
     OR NEW.request->>'operation_id' IS DISTINCT FROM NEW.id::text
     OR NEW.request->>'task_id' IS DISTINCT FROM NEW.task_id::text
     OR NEW.request->>'attempt_id' IS DISTINCT FROM NEW.attempt_id::text
     OR NEW.request->>'generation' IS DISTINCT FROM NEW.generation::text
     OR NEW.request->>'target' IS DISTINCT FROM NEW.target
     OR NEW.request->'action'->>'key' IS DISTINCT FROM NEW.action_key
     OR NEW.request->>'hard_deadline' IS DISTINCT FROM (extract(epoch FROM NEW.hard_deadline)::bigint)::text THEN
   RAISE EXCEPTION 'SSH SENT request must match its original grant and immutable identity';
  END IF;
 ELSIF TG_TABLE_NAME = 'cloud_remote_observations' THEN
  SELECT * INTO STRICT intent FROM cloud_remote_operations WHERE id = NEW.operation_id;
  IF NEW.worker_id <> intent.worker_id OR NEW.generation <> intent.generation
     OR NEW.observation->>'operation_id' IS DISTINCT FROM intent.id::text
     OR NEW.observation->>'request_digest' IS DISTINCT FROM intent.request_digest
     OR NEW.observation->>'target' IS DISTINCT FROM intent.target THEN
   RAISE EXCEPTION 'SSH observation is not bound to the original intent and owner';
  END IF;
 ELSE
  SELECT * INTO STRICT intent FROM cloud_remote_operations WHERE id = NEW.operation_id;
  SELECT * INTO STRICT observed FROM cloud_remote_observations WHERE id = NEW.observation_id;
  IF NEW.request IS DISTINCT FROM intent.request OR NEW.observation IS DISTINCT FROM observed.observation
     OR NEW.observation->>'state' IS DISTINCT FROM NEW.terminal_state
     OR NEW.observation->'remote_stopped' IS DISTINCT FROM 'true'::jsonb
     OR NEW.observation->'remote_identity'->>'boot_id' IS NULL
     OR NEW.observation->'remote_identity'->>'invocation_id' IS NULL THEN
   RAISE EXCEPTION 'SSH terminal result requires exact observed stopped identity';
  END IF;
  IF EXISTS (SELECT 1 FROM cloud_remote_observations earlier WHERE earlier.operation_id = intent.id AND
      ((earlier.observation->'remote_identity'->>'boot_id' IS NOT NULL AND
         earlier.observation->'remote_identity'->>'boot_id' <> NEW.observation->'remote_identity'->>'boot_id') OR
       (earlier.observation->'remote_identity'->>'invocation_id' IS NOT NULL AND
         earlier.observation->'remote_identity'->>'invocation_id' <> NEW.observation->'remote_identity'->>'invocation_id'))) THEN
   RAISE EXCEPTION 'SSH terminal identity conflicts with original observations';
  END IF;
 END IF;
 RETURN NEW;
END;
$$
"""
