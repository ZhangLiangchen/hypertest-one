"""ADR-022 additive project experience Gateway; no task/result migration."""
import sqlalchemy as sa

from alembic import op

revision = "0027_project_memory"
down_revision = "0026_cloud_ssh_operations"
branch_labels = None
depends_on = None

TABLES = ["memory_project_mappings", "memory_entries", "memory_revisions", "memory_operations"]
OLD_SCOPES = '["task:submit","task:sync","run:read","evidence:read","report:read","run:execute","cloud:configure","credential:manage","cloud:dispatch","cloud:control","cloud:read"]'
NEW_SCOPES = OLD_SCOPES[:-1] + ',"memory:read","memory:propose","memory:publish"]'


def scopes_constraint(value):
    op.execute(sa.text("ALTER TABLE interactive_integration_grants DROP CONSTRAINT ck_interactive_integration_scopes"))
    op.execute(sa.text("ALTER TABLE interactive_integration_grants ADD CONSTRAINT ck_interactive_integration_scopes CHECK (jsonb_typeof(scopes)='array' AND jsonb_array_length(scopes)>0 AND scopes <@ '" + value + "'::jsonb)"))


def upgrade():
    for statement in CREATE_SQL.split(";"):
        if statement.strip():
            op.execute(sa.text(statement))
    scopes_constraint(NEW_SCOPES)
    op.execute(sa.text(GUARD))
    for table in TABLES:
        op.execute(sa.text(f"CREATE TRIGGER memory_history_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_memory_history()"))


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Memory history prevents destructive downgrade")
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM interactive_integration_grants WHERE scopes ?| array['memory:read','memory:propose','memory:publish'])")):
        raise RuntimeError("Memory grants prevent destructive downgrade")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute(sa.text("DROP FUNCTION hypertest_guard_memory_history()"))
    scopes_constraint(OLD_SCOPES)


CREATE_SQL = r"""

CREATE TABLE memory_project_mappings (
	project_id UUID NOT NULL,
	namespace VARCHAR(128) NOT NULL,
	scope_id VARCHAR(255),
	enabled BOOLEAN NOT NULL,
	version BIGINT NOT NULL,
	status VARCHAR(16) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (project_id),
	UNIQUE (namespace),
	UNIQUE (scope_id),
	CHECK (version > 0),
	CHECK (status IN ('PENDING','READY','UNKNOWN')),
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)

;

CREATE TABLE memory_entries (
	project_id UUID NOT NULL,
	owner_actor_ref VARCHAR(255) NOT NULL,
	version BIGINT NOT NULL,
	status VARCHAR(16) NOT NULL,
	source JSONB NOT NULL,
	pending_operation_id UUID,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (project_id, id),
	CHECK (version > 0),
	CHECK (status IN ('CANDIDATE','PENDING','PUBLISHED','RETRACTED')),
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)

;

CREATE TABLE memory_revisions (
	entry_id UUID NOT NULL,
	version BIGINT NOT NULL,
	status VARCHAR(16) NOT NULL,
	title VARCHAR(255) NOT NULL,
	content TEXT NOT NULL,
	applicability TEXT NOT NULL,
	observed_at TIMESTAMP WITH TIME ZONE,
	expires_at TIMESTAMP WITH TIME ZONE,
	publication_note TEXT NOT NULL,
	confirmed_by VARCHAR(255),
	content_digest VARCHAR(64) NOT NULL,
	upstream_ref JSONB,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (entry_id, version),
	CHECK (version > 0),
	CHECK (status IN ('CANDIDATE','PUBLISHED','RETRACTED')),
	FOREIGN KEY(entry_id) REFERENCES memory_entries (id) ON DELETE RESTRICT
)

;

CREATE TABLE memory_operations (
	project_id UUID NOT NULL,
	operation_key VARCHAR(128) NOT NULL,
	operation VARCHAR(32) NOT NULL,
	actor_ref VARCHAR(255) NOT NULL,
	grant_id UUID,
	expected_version BIGINT NOT NULL,
	input_digest VARCHAR(64) NOT NULL,
	request JSONB NOT NULL,
	entry_id UUID,
	target_version BIGINT NOT NULL,
	state VARCHAR(16) NOT NULL,
	marker VARCHAR(128) NOT NULL,
	upstream_ref JSONB,
	response JSONB NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (project_id, operation_key),
	CHECK (expected_version >= 0 AND target_version = expected_version + 1),
	CHECK (state IN ('SENT','UNKNOWN','ACCEPTED')),
	CHECK (operation IN ('CONFIGURE','CREATE_CANDIDATE','PUBLISH','REVISE','RETRACT')),
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT,
	FOREIGN KEY(grant_id) REFERENCES interactive_integration_grants (id) ON DELETE RESTRICT,
	FOREIGN KEY(project_id, entry_id) REFERENCES memory_entries (project_id, id) ON DELETE RESTRICT
)

;
"""

GUARD = r"""
CREATE FUNCTION hypertest_guard_memory_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Memory history cannot be deleted';
 END IF;
 IF TG_TABLE_NAME='memory_revisions' THEN
  RAISE EXCEPTION 'Memory accepted revisions are immutable';
 ELSIF TG_TABLE_NAME='memory_operations' THEN
  IF OLD.state='ACCEPTED' OR
     (to_jsonb(NEW)-ARRAY['state','upstream_ref','response']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['state','upstream_ref','response']) OR
     (OLD.state='UNKNOWN' AND NEW.state='SENT') THEN
   RAISE EXCEPTION 'Memory operation intent, accepted receipt and dispatch identity are immutable';
  END IF;
 ELSIF TG_TABLE_NAME='memory_entries' THEN
  IF (to_jsonb(NEW)-ARRAY['version','status','pending_operation_id','updated_at']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['version','status','pending_operation_id','updated_at']) OR
     NEW.version<OLD.version OR NEW.version>OLD.version+1 OR
     (OLD.status='RETRACTED' AND NEW.status<>'RETRACTED') THEN
   RAISE EXCEPTION 'Memory source, ownership and retained history are immutable';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['scope_id','version','enabled','status']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['scope_id','version','enabled','status']) OR
     (OLD.scope_id IS NOT NULL AND NEW.scope_id IS DISTINCT FROM OLD.scope_id) OR
     NEW.version<OLD.version OR NEW.version>OLD.version+1 THEN
   RAISE EXCEPTION 'Memory Project mapping and existing Scope identity are immutable';
  END IF;
 END IF;
 RETURN NEW;
END;
$$
"""
