"""ADR-019 additive Cloud state and independent grants; preserve Local history.

DDL frozen from the 2026-10-22 domain snapshot
94ad9c8dd736130ae8757fc288d5fc7334d3416da4445423247831ee9a1eba91.
No runtime/SDK/model import or execution is part of this migration.
"""
import re

import sqlalchemy as sa

from alembic import op

revision = "0025_cloud_tasks"
down_revision = "0024_local_task_binding"
branch_labels = None
depends_on = None

OLD_SCOPES = ["task:submit", "task:sync", "run:read", "evidence:read", "report:read", "run:execute"]
CLOUD_SCOPES = ["cloud:configure", "credential:manage", "cloud:dispatch", "cloud:control", "cloud:read"]


def _scope_check(scopes):
    import json
    return ("jsonb_typeof(scopes)='array' AND jsonb_array_length(scopes)>0 AND scopes <@ '"
            + json.dumps(scopes) + "'::jsonb")


def upgrade():
    for statement in CREATE_SQL.split(";"):
        if statement.strip():
            op.execute(sa.text(statement))
    op.create_unique_constraint("uq_cloud_receipt_task_version", "cloud_operation_receipts", ["task_id", "accepted_version"])
    op.drop_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", type_="check")
    op.create_check_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", _scope_check(OLD_SCOPES + CLOUD_SCOPES))
    op.execute(sa.text(GUARD))
    for table in TABLES:
        op.execute(sa.text(f"CREATE TRIGGER cloud_history_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_cloud_history()"))


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cloud history prevents destructive downgrade")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM interactive_integration_grants WHERE scopes ?| ARRAY['cloud:configure','credential:manage','cloud:dispatch','cloud:control','cloud:read'])")):
        raise RuntimeError("Cloud grants prevent scope downgrade")
    op.drop_constraint("fk_cloud_latest_attempt", "cloud_tasks", type_="foreignkey")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute(sa.text("DROP FUNCTION hypertest_guard_cloud_history()"))
    op.drop_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", type_="check")
    op.create_check_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", _scope_check(OLD_SCOPES))


CREATE_SQL = r"""
CREATE TABLE project_cloud_config_revisions (
	project_id UUID NOT NULL, 
	revision BIGINT NOT NULL, 
	configuration JSONB NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	created_by VARCHAR(255) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, revision), 
	UNIQUE (project_id, id), 
	CHECK (revision > 0), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);

CREATE TABLE project_credentials (
	project_id UUID NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	label VARCHAR(255) NOT NULL, 
	purpose VARCHAR(255) NOT NULL, 
	allowed_targets JSONB NOT NULL, 
	allowed_actions JSONB NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	version BIGINT NOT NULL, 
	created_by VARCHAR(255) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, id), 
	CHECK (version > 0), 
	CHECK (status IN ('ACTIVE','REVOKED')), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);

CREATE TABLE cloud_tasks (
	project_id UUID NOT NULL, 
	owner_actor_ref VARCHAR(255) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	config_id UUID NOT NULL, 
	inputs JSONB NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	version BIGINT NOT NULL, 
	frozen_manifest JSONB, 
	input_digest VARCHAR(64), 
	latest_attempt_id UUID, 
	related_task_id UUID, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, id), 
	CHECK (version > 0), 
	CHECK (status IN ('DRAFT','QUEUED','PREPARING','RUNNING','WAITING_INPUT','RECOVERY_REQUIRED','COMPLETED','FAILED','CANCELLED')), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')), 
	FOREIGN KEY(project_id, config_id) REFERENCES project_cloud_config_revisions (project_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	FOREIGN KEY(related_task_id) REFERENCES cloud_tasks (id) ON DELETE RESTRICT
);

CREATE TABLE project_credential_versions (
	project_id UUID NOT NULL, 
	credential_id UUID NOT NULL, 
	version BIGINT NOT NULL, 
	encrypted_secret JSONB NOT NULL, 
	key_id VARCHAR(128) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	created_by VARCHAR(255) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (credential_id, version), 
	UNIQUE (project_id, id), 
	FOREIGN KEY(project_id, credential_id) REFERENCES project_credentials (project_id, id) ON DELETE RESTRICT, 
	CHECK (version > 0)
);

CREATE TABLE cloud_attempts (
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	attempt_no BIGINT NOT NULL, 
	input_digest VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	queued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	reason TEXT, 
	lease_owner VARCHAR(255), 
	lease_token_hash VARCHAR(64), 
	lease_generation BIGINT NOT NULL, 
	lease_expires_at TIMESTAMP WITH TIME ZONE, 
	workspace_id VARCHAR(512), 
	runtime_namespace VARCHAR(512), 
	dsh_home VARCHAR(512), 
	checkpoint JSONB NOT NULL, 
	runtime_metadata JSONB NOT NULL, 
	usage_seconds BIGINT NOT NULL, 
	cost_microunits BIGINT NOT NULL, 
	authorization_grant_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (task_id, attempt_no), 
	UNIQUE (task_id, id), 
	UNIQUE (project_id, id), 
	FOREIGN KEY(project_id, task_id) REFERENCES cloud_tasks (project_id, id) ON DELETE RESTRICT, 
	CHECK (attempt_no > 0 AND lease_generation >= 0 AND usage_seconds >= 0 AND cost_microunits >= 0), 
	CHECK (status IN ('QUEUED','PREPARING','RUNNING','WAITING_INPUT','RECOVERY_REQUIRED','COMPLETED','FAILED','CANCELLED')), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')), 
	FOREIGN KEY(authorization_grant_id) REFERENCES interactive_integration_grants (id) ON DELETE RESTRICT
);

CREATE TABLE cloud_config_credentials (
	config_id UUID NOT NULL, 
	credential_version_id UUID NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	project_id UUID NOT NULL, 
	PRIMARY KEY (config_id, credential_version_id, role), 
	FOREIGN KEY(project_id, config_id) REFERENCES project_cloud_config_revisions (project_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id, credential_version_id) REFERENCES project_credential_versions (project_id, id) ON DELETE RESTRICT
);

CREATE TABLE cloud_input_resolutions (
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	operation_key VARCHAR(128) NOT NULL, 
	source_draft_version BIGINT NOT NULL, 
	accepted_task_version BIGINT, 
	source_digest VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	result JSONB, 
	digest VARCHAR(64), 
	worker_id VARCHAR(255), 
	lease_token_hash VARCHAR(64), 
	lease_expires_at TIMESTAMP WITH TIME ZONE, 
	accepted_at TIMESTAMP WITH TIME ZONE, 
	requested_by VARCHAR(255) NOT NULL, 
	grant_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (task_id, operation_key), 
	UNIQUE (task_id, id), 
	UNIQUE (project_id, id), 
	FOREIGN KEY(project_id, task_id) REFERENCES cloud_tasks (project_id, id) ON DELETE RESTRICT, 
	CHECK (status IN ('PENDING','RESOLVING','ACCEPTED','FAILED','RECOVERY_REQUIRED')), 
	FOREIGN KEY(grant_id) REFERENCES interactive_integration_grants (id) ON DELETE RESTRICT
);

CREATE TABLE cloud_artifacts (
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	media_type VARCHAR(128) NOT NULL, 
	byte_count BIGINT NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	content BYTEA NOT NULL, 
	verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (task_id, id), 
	FOREIGN KEY(project_id, task_id) REFERENCES cloud_tasks (project_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(task_id, attempt_id) REFERENCES cloud_attempts (task_id, id) ON DELETE RESTRICT, 
	CHECK (byte_count >= 0 AND sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE cloud_delegations (
	task_id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	task_version BIGINT NOT NULL, 
	delegation_key VARCHAR(128) NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	responsibility TEXT NOT NULL, 
	native_ref VARCHAR(512), 
	status VARCHAR(16) NOT NULL, 
	terminal_observation JSONB, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (attempt_id, delegation_key), 
	UNIQUE (task_id, id), 
	FOREIGN KEY(task_id, attempt_id) REFERENCES cloud_attempts (task_id, id) ON DELETE RESTRICT, 
	CHECK (status IN ('RUNNING','COMPLETED','FAILED','CANCELLED','UNKNOWN'))
);

CREATE TABLE cloud_input_requests (
	task_id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	task_version BIGINT NOT NULL, 
	question_key VARCHAR(128) NOT NULL, 
	question TEXT NOT NULL, 
	options JSONB NOT NULL, 
	checkpoint JSONB NOT NULL, 
	required_action VARCHAR(255) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (attempt_id, question_key), 
	UNIQUE (task_id, id), 
	FOREIGN KEY(task_id, attempt_id) REFERENCES cloud_attempts (task_id, id) ON DELETE RESTRICT
);

CREATE TABLE cloud_operation_receipts (
	project_id UUID NOT NULL, 
	task_id UUID, 
	attempt_id UUID, 
	operation_key VARCHAR(128) NOT NULL, 
	operation VARCHAR(64) NOT NULL, 
	actor_ref VARCHAR(255) NOT NULL, 
	input_digest VARCHAR(64) NOT NULL, 
	expected_version BIGINT NOT NULL, 
	accepted_version BIGINT NOT NULL, 
	response JSONB NOT NULL, 
	task_snapshot JSONB, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, operation_key), 
	FOREIGN KEY(project_id, task_id) REFERENCES cloud_tasks (project_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(task_id, attempt_id) REFERENCES cloud_attempts (task_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);

CREATE TABLE cloud_run_records (
	task_id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	task_version BIGINT NOT NULL, 
	run_key VARCHAR(128) NOT NULL, 
	execution JSONB NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (attempt_id, run_key), 
	UNIQUE (task_id, id), 
	FOREIGN KEY(task_id, attempt_id) REFERENCES cloud_attempts (task_id, id) ON DELETE RESTRICT, 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED'))
);

CREATE TABLE cloud_work_grants (
	project_id UUID NOT NULL, 
	attempt_id UUID, 
	resolution_id UUID, 
	token_hash VARCHAR(64) NOT NULL, 
	worker_id VARCHAR(255) NOT NULL, 
	lease_generation BIGINT NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id, attempt_id) REFERENCES cloud_attempts (project_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id, resolution_id) REFERENCES cloud_input_resolutions (project_id, id) ON DELETE RESTRICT, 
	CHECK ((attempt_id IS NOT NULL)::int + (resolution_id IS NOT NULL)::int = 1), 
	CHECK (expires_at > created_at), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	UNIQUE (token_hash)
);

CREATE TABLE cloud_asset_revisions (
	task_id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	revision BIGINT NOT NULL, 
	task_version BIGINT NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	markdown TEXT NOT NULL, 
	details JSONB NOT NULL, 
	artifact_id UUID, 
	reported_result VARCHAR(16) NOT NULL, 
	source JSONB NOT NULL, 
	content_digest VARCHAR(64) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (task_id, kind, key, revision), 
	UNIQUE (task_id, id), 
	FOREIGN KEY(task_id, attempt_id) REFERENCES cloud_attempts (task_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(task_id, artifact_id) REFERENCES cloud_artifacts (task_id, id) ON DELETE RESTRICT, 
	CHECK (kind IN ('ANALYSIS','DESIGN','CASE','IMPLEMENTATION','REPORT')), 
	CHECK (revision > 0 AND task_version > 0), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED'))
);

CREATE TABLE cloud_input_answers (
	task_id UUID NOT NULL, 
	question_id UUID NOT NULL, 
	task_version BIGINT NOT NULL, 
	answer TEXT NOT NULL, 
	answered_by VARCHAR(255) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id, question_id) REFERENCES cloud_input_requests (task_id, id) ON DELETE RESTRICT
);

CREATE TABLE cloud_run_artifacts (
	run_id UUID NOT NULL, 
	artifact_id UUID NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	task_id UUID NOT NULL, 
	PRIMARY KEY (run_id, artifact_id, role), 
	FOREIGN KEY(task_id, run_id) REFERENCES cloud_run_records (task_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(task_id, artifact_id) REFERENCES cloud_artifacts (task_id, id) ON DELETE RESTRICT
);

CREATE TABLE cloud_asset_references (
	asset_id UUID NOT NULL, 
	referenced_asset_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	PRIMARY KEY (asset_id, referenced_asset_id), 
	FOREIGN KEY(task_id, asset_id) REFERENCES cloud_asset_revisions (task_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(task_id, referenced_asset_id) REFERENCES cloud_asset_revisions (task_id, id) ON DELETE RESTRICT
);

CREATE TABLE cloud_delegation_assets (
	task_id UUID NOT NULL, 
	delegation_id UUID NOT NULL, 
	asset_id UUID NOT NULL, 
	PRIMARY KEY (delegation_id, asset_id), 
	FOREIGN KEY(task_id, delegation_id) REFERENCES cloud_delegations (task_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(task_id, asset_id) REFERENCES cloud_asset_revisions (task_id, id) ON DELETE RESTRICT
);

CREATE TABLE cloud_run_cases (
	task_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	case_revision_id UUID NOT NULL, 
	actual TEXT NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, case_revision_id), 
	FOREIGN KEY(task_id, run_id) REFERENCES cloud_run_records (task_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(task_id, case_revision_id) REFERENCES cloud_asset_revisions (task_id, id) ON DELETE RESTRICT, 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED'))
);

CREATE UNIQUE INDEX uq_cloud_unfinished_attempt ON cloud_attempts (task_id) WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED');

ALTER TABLE cloud_tasks ADD CONSTRAINT fk_cloud_latest_attempt FOREIGN KEY(id, latest_attempt_id) REFERENCES cloud_attempts (task_id, id) ON DELETE RESTRICT;


"""
TABLES = re.findall(r"CREATE TABLE ([a-z_]+)", CREATE_SQL)

GUARD = r"""
CREATE FUNCTION hypertest_guard_cloud_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'cloud task history is retained';
  END IF;
  IF TG_TABLE_NAME = 'cloud_tasks' THEN
    IF NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id
       OR NEW.owner_actor_ref <> OLD.owner_actor_ref OR NEW.created_at <> OLD.created_at
       OR NEW.related_task_id IS DISTINCT FROM OLD.related_task_id
       OR NEW.version NOT IN (OLD.version, OLD.version+1) THEN
      RAISE EXCEPTION 'cloud task identity and monotonic version are immutable';
    END IF;
    IF OLD.frozen_manifest IS NOT NULL AND
       (NEW.frozen_manifest IS DISTINCT FROM OLD.frozen_manifest OR NEW.inputs IS DISTINCT FROM OLD.inputs
        OR NEW.config_id <> OLD.config_id OR NEW.input_digest IS DISTINCT FROM OLD.input_digest) THEN
      RAISE EXCEPTION 'dispatched cloud inputs are immutable';
    END IF;
    IF OLD.status = 'CANCELLED' AND OLD.frozen_manifest IS NULL AND NEW IS DISTINCT FROM OLD THEN
      RAISE EXCEPTION 'cancelled draft is terminal';
    END IF;
  ELSIF TG_TABLE_NAME = 'cloud_attempts' THEN
    IF NEW.id <> OLD.id OR NEW.task_id <> OLD.task_id OR NEW.project_id <> OLD.project_id
       OR NEW.attempt_no <> OLD.attempt_no OR NEW.input_digest <> OLD.input_digest
       OR NEW.created_at <> OLD.created_at OR NEW.queued_at <> OLD.queued_at
       OR NEW.lease_generation < OLD.lease_generation
       OR NEW.usage_seconds < OLD.usage_seconds OR NEW.cost_microunits < OLD.cost_microunits THEN
      RAISE EXCEPTION 'cloud attempt identity, generation and cumulative usage are immutable';
    END IF;
    IF OLD.status IN ('COMPLETED','FAILED','CANCELLED') AND NEW IS DISTINCT FROM OLD THEN
      RAISE EXCEPTION 'terminal cloud attempts are immutable';
    END IF;
  ELSIF TG_TABLE_NAME = 'cloud_input_resolutions' THEN
    IF OLD.status = 'ACCEPTED' AND NEW IS DISTINCT FROM OLD THEN
      RAISE EXCEPTION 'accepted input resolution is immutable';
    END IF;
    IF NEW.id <> OLD.id OR NEW.task_id <> OLD.task_id OR NEW.project_id <> OLD.project_id
       OR NEW.operation_key <> OLD.operation_key OR NEW.source_digest <> OLD.source_digest
       OR NEW.source_draft_version <> OLD.source_draft_version OR NEW.requested_by <> OLD.requested_by
       OR NEW.grant_id IS DISTINCT FROM OLD.grant_id OR NEW.created_at <> OLD.created_at THEN
      RAISE EXCEPTION 'input resolution source identity is immutable';
    END IF;
  ELSIF TG_TABLE_NAME = 'project_credentials' THEN
    IF NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id OR NEW.kind <> OLD.kind
       OR NEW.purpose <> OLD.purpose OR NEW.allowed_targets <> OLD.allowed_targets
       OR NEW.allowed_actions <> OLD.allowed_actions OR NEW.created_by <> OLD.created_by
       OR NEW.created_at <> OLD.created_at OR NEW.version <> OLD.version+1
       OR OLD.status = 'REVOKED' THEN
      RAISE EXCEPTION 'credential ownership, scope, revocation and versions are immutable';
    END IF;
  ELSIF TG_TABLE_NAME = 'cloud_work_grants' THEN
    IF NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id
       OR NEW.attempt_id IS DISTINCT FROM OLD.attempt_id OR NEW.resolution_id IS DISTINCT FROM OLD.resolution_id
       OR NEW.token_hash <> OLD.token_hash OR NEW.worker_id <> OLD.worker_id
       OR NEW.lease_generation <> OLD.lease_generation OR NEW.created_at <> OLD.created_at
       OR (OLD.revoked_at IS NOT NULL AND NEW IS DISTINCT FROM OLD) THEN
      RAISE EXCEPTION 'cloud work authority identity is immutable';
    END IF;
  ELSIF TG_TABLE_NAME = 'cloud_delegations' THEN
    IF NEW.id <> OLD.id OR NEW.task_id <> OLD.task_id OR NEW.attempt_id <> OLD.attempt_id
       OR NEW.delegation_key <> OLD.delegation_key OR NEW.provider <> OLD.provider
       OR NEW.responsibility <> OLD.responsibility OR NEW.created_at <> OLD.created_at
       OR (OLD.status IN ('COMPLETED','FAILED','CANCELLED') AND NEW IS DISTINCT FROM OLD) THEN
      RAISE EXCEPTION 'delegation identity and terminal observations are immutable';
    END IF;
  ELSE
    RAISE EXCEPTION 'cloud revisions, artifacts, runs, answers, receipts and relationships are immutable';
  END IF;
  RETURN NEW;
END $$
"""

