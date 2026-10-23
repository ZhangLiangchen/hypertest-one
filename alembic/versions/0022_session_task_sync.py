"""ADR-018 additive session task management; no execution or legacy rewrites."""
import sqlalchemy as sa

from alembic import op

revision = "0022_session_task_sync"
down_revision = "0021_native_intake"
branch_labels = None
depends_on = None

TABLES = ["session_tasks", "session_case_revisions", "session_report_revisions", "session_sync_receipts"]


def upgrade():
    for statement in CREATE_SQL.split(";\n"):
        if statement.strip():
            op.execute(sa.text(statement))
    op.drop_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", type_="check")
    op.create_check_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", "jsonb_typeof(scopes)='array' AND jsonb_array_length(scopes)>0 AND scopes <@ '[\"task:submit\",\"task:sync\",\"run:read\",\"evidence:read\",\"report:read\",\"run:execute\"]'::jsonb")
    op.execute(sa.text(GUARD))
    for table in TABLES:
        op.execute(sa.text(f"CREATE TRIGGER session_task_history_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_session_tasks()"))


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Session task history prevents destructive downgrade")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM interactive_integration_grants WHERE scopes ? 'task:sync')")):
        raise RuntimeError("Explicit task:sync grants prevent scope downgrade")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION hypertest_guard_session_tasks()")
    op.drop_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", type_="check")
    op.create_check_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", "jsonb_typeof(scopes)='array' AND jsonb_array_length(scopes)>0 AND scopes <@ '[\"task:submit\",\"run:read\",\"evidence:read\",\"report:read\",\"run:execute\"]'::jsonb")

CREATE_SQL = r"""
CREATE TABLE session_tasks (
	project_id UUID NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	session_id VARCHAR(512) NOT NULL, 
	owner_actor_ref VARCHAR(255) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	objective TEXT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	plan_markdown TEXT NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	version BIGINT NOT NULL, 
	last_synced_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_session_task_identity UNIQUE (provider, session_id), 
	CHECK (version > 0), 
	CHECK (status IN ('DRAFT','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED')), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')), 
	CHECK (source = 'AGENT_REPORTED'), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);
CREATE TABLE session_case_revisions (
	task_id UUID NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	revision BIGINT NOT NULL, 
	task_version BIGINT NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	steps JSONB NOT NULL, 
	expected TEXT NOT NULL, 
	actual TEXT NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	implementation_ref TEXT, 
	source VARCHAR(32) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_session_case_revision UNIQUE (task_id, key, revision), 
	CHECK (revision > 0 AND task_version > 0), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')), 
	CHECK (source = 'AGENT_REPORTED'), 
	FOREIGN KEY(task_id) REFERENCES session_tasks (id) ON DELETE RESTRICT
);
CREATE TABLE session_report_revisions (
	task_id UUID NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	revision BIGINT NOT NULL, 
	task_version BIGINT NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	markdown TEXT NOT NULL, 
	artifact_uri TEXT, 
	source_ref TEXT, 
	reported_result VARCHAR(16) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_session_report_revision UNIQUE (task_id, key, revision), 
	CHECK (revision > 0 AND task_version > 0), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')), 
	CHECK (source = 'AGENT_REPORTED'), 
	FOREIGN KEY(task_id) REFERENCES session_tasks (id) ON DELETE RESTRICT
);
CREATE TABLE session_sync_receipts (
	task_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	actor_ref VARCHAR(255) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	input_digest VARCHAR(64) NOT NULL, 
	task_version BIGINT NOT NULL, 
	request_payload JSONB NOT NULL, 
	task_snapshot JSONB NOT NULL, 
	response JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_session_sync_key UNIQUE (actor_ref, project_id, idempotency_key), 
	CONSTRAINT uq_session_sync_version UNIQUE (task_id, task_version), 
	CHECK (task_version > 0), 
	FOREIGN KEY(task_id) REFERENCES session_tasks (id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);
"""

GUARD = r"""
CREATE FUNCTION hypertest_guard_session_tasks() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent session_tasks%ROWTYPE;
        next_revision BIGINT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'session task history is retained';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF TG_TABLE_NAME <> 'session_tasks' THEN
      RAISE EXCEPTION 'session task revisions and receipts are immutable';
    END IF;
    IF NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id OR NEW.provider <> OLD.provider
       OR NEW.session_id <> OLD.session_id OR NEW.owner_actor_ref <> OLD.owner_actor_ref
       OR NEW.created_at <> OLD.created_at OR NEW.source <> OLD.source
       OR NEW.version <> OLD.version + 1 THEN
      RAISE EXCEPTION 'session identity is immutable and version must increase by one';
    END IF;
  END IF;
  IF TG_TABLE_NAME = 'session_tasks' THEN
    IF TG_OP = 'INSERT' AND NEW.version <> 1 THEN
      RAISE EXCEPTION 'session tasks begin at version one';
    END IF;
  ELSE
    SELECT * INTO STRICT parent FROM session_tasks WHERE id=NEW.task_id;
    IF NEW.task_version <> parent.version THEN
      RAISE EXCEPTION 'revision must belong to the current task version';
    END IF;
    IF TG_TABLE_NAME = 'session_sync_receipts' THEN
      IF NEW.project_id <> parent.project_id THEN
        RAISE EXCEPTION 'sync receipt Project must match task';
      END IF;
    ELSIF TG_TABLE_NAME = 'session_case_revisions' THEN
      SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_case_revisions
        WHERE task_id=NEW.task_id AND key=NEW.key;
      IF NEW.revision <> next_revision THEN
        RAISE EXCEPTION 'case revision must increase by one';
      END IF;
    ELSIF TG_TABLE_NAME = 'session_report_revisions' THEN
      SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_report_revisions
        WHERE task_id=NEW.task_id AND key=NEW.key;
      IF NEW.revision <> next_revision THEN
        RAISE EXCEPTION 'report revision must increase by one';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$
"""
