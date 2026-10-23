"""ADR-017 additive native intake; never rewrites legacy state."""
import sqlalchemy as sa

from alembic import op

revision = "0021_native_intake"
down_revision = "0020_interactive_tool_inbox"
branch_labels = None
depends_on = None

TABLES = ['native_test_runs', 'native_cases', 'native_contributors', 'native_conclusions', 'native_execution_records', 'native_handoffs', 'native_conclusion_executions', 'native_execution_cases', 'native_materials', 'native_verifications', 'native_operations']


def upgrade():
    for statement in CREATE_SQL.split(";\n"):
        if statement.strip():
            op.execute(sa.text(statement))
    op.execute(sa.text(GUARDS))
    for name in TABLES:
        op.execute(sa.text(f"CREATE TRIGGER native_history_guard BEFORE INSERT OR UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_native()"))


def downgrade():
    for name in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {name})")):
            raise RuntimeError("native history prevents destructive downgrade")
    for name in reversed(TABLES):
        op.drop_table(name)
    op.execute("DROP FUNCTION hypertest_guard_native()")

CREATE_SQL = r"""
CREATE TABLE native_test_runs (
	project_id UUID NOT NULL, 
	profile VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	proposal_digest VARCHAR(64) NOT NULL, 
	proposal JSONB NOT NULL, 
	policy_version VARCHAR(64) NOT NULL, 
	actor_ref VARCHAR(255) NOT NULL, 
	generation BIGINT NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, idempotency_key), 
	CHECK (generation > 0), 
	CHECK (profile = 'native-framework-intake/v1alpha1'), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);
CREATE TABLE native_cases (
	run_id UUID NOT NULL, 
	case_key VARCHAR(128) NOT NULL, 
	accepted_payload JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, case_key), 
	FOREIGN KEY(run_id) REFERENCES native_test_runs (id) ON DELETE RESTRICT
);
CREATE TABLE native_contributors (
	run_id UUID NOT NULL, 
	actor_ref VARCHAR(255) NOT NULL, 
	session_ref VARCHAR(512) NOT NULL, 
	generation BIGINT NOT NULL, 
	writer_token_hash VARCHAR(64) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, generation), 
	CHECK (generation > 0), 
	FOREIGN KEY(run_id) REFERENCES native_test_runs (id) ON DELETE RESTRICT
);
CREATE TABLE native_conclusions (
	run_id UUID NOT NULL, 
	contributor_id UUID NOT NULL, 
	policy_version VARCHAR(64) NOT NULL, 
	decision VARCHAR(16) NOT NULL, 
	state_digest VARCHAR(64) NOT NULL, 
	reasons JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (decision IN ('UNKNOWN','BLOCKED')), 
	FOREIGN KEY(run_id) REFERENCES native_test_runs (id) ON DELETE RESTRICT, 
	FOREIGN KEY(contributor_id) REFERENCES native_contributors (id) ON DELETE RESTRICT
);
CREATE TABLE native_execution_records (
	run_id UUID NOT NULL, 
	contributor_id UUID NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	retry_of_execution_id UUID, 
	observation JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, idempotency_key), 
	FOREIGN KEY(run_id) REFERENCES native_test_runs (id) ON DELETE RESTRICT, 
	FOREIGN KEY(contributor_id) REFERENCES native_contributors (id) ON DELETE RESTRICT, 
	FOREIGN KEY(retry_of_execution_id) REFERENCES native_execution_records (id) ON DELETE RESTRICT
);
CREATE TABLE native_handoffs (
	run_id UUID NOT NULL, 
	from_contributor_id UUID NOT NULL, 
	to_contributor_id UUID NOT NULL, 
	from_generation BIGINT NOT NULL, 
	to_generation BIGINT NOT NULL, 
	actor_ref VARCHAR(255) NOT NULL, 
	state_digest VARCHAR(64) NOT NULL, 
	state_artifact_uri VARCHAR(80) NOT NULL, 
	remaining_work JSONB NOT NULL, 
	reason VARCHAR(4000) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, to_generation), 
	CHECK (to_generation = from_generation + 1), 
	FOREIGN KEY(run_id) REFERENCES native_test_runs (id) ON DELETE RESTRICT, 
	FOREIGN KEY(from_contributor_id) REFERENCES native_contributors (id) ON DELETE RESTRICT, 
	FOREIGN KEY(to_contributor_id) REFERENCES native_contributors (id) ON DELETE RESTRICT
);
CREATE TABLE native_conclusion_executions (
	conclusion_id UUID NOT NULL, 
	execution_id UUID NOT NULL, 
	PRIMARY KEY (conclusion_id, execution_id), 
	FOREIGN KEY(conclusion_id) REFERENCES native_conclusions (id) ON DELETE RESTRICT, 
	FOREIGN KEY(execution_id) REFERENCES native_execution_records (id) ON DELETE RESTRICT
);
CREATE TABLE native_execution_cases (
	execution_id UUID NOT NULL, 
	case_id UUID NOT NULL, 
	observed_result VARCHAR(16) NOT NULL, 
	PRIMARY KEY (execution_id, case_id), 
	CHECK (observed_result IN ('PASS','FAIL','ERROR','SKIPPED','UNKNOWN')), 
	FOREIGN KEY(execution_id) REFERENCES native_execution_records (id) ON DELETE RESTRICT, 
	FOREIGN KEY(case_id) REFERENCES native_cases (id) ON DELETE RESTRICT
);
CREATE TABLE native_materials (
	run_id UUID NOT NULL,
	execution_id UUID,
	name VARCHAR(255) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	format VARCHAR(32) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	artifact_uri VARCHAR(80) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (execution_id, name), 
	CHECK (size_bytes BETWEEN 0 AND 2097152), 
	FOREIGN KEY(run_id) REFERENCES native_test_runs (id) ON DELETE RESTRICT,
	FOREIGN KEY(execution_id) REFERENCES native_execution_records (id) ON DELETE RESTRICT
);
CREATE TABLE native_verifications (
	execution_id UUID NOT NULL, 
	verifier_version VARCHAR(64) NOT NULL, 
	provenance VARCHAR(32) NOT NULL, 
	checks JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (provenance = 'UNVERIFIED'), 
	FOREIGN KEY(execution_id) REFERENCES native_execution_records (id) ON DELETE RESTRICT
);
CREATE TABLE native_operations (
	run_id UUID NOT NULL, 
	contributor_id UUID NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	input_digest VARCHAR(64) NOT NULL, 
	payload JSONB NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	result JSONB NOT NULL, 
	reconciled_material_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, idempotency_key), 
	CHECK (status IN ('SUCCEEDED','UNKNOWN','RESOLVED')), 
	FOREIGN KEY(run_id) REFERENCES native_test_runs (id) ON DELETE RESTRICT, 
	FOREIGN KEY(contributor_id) REFERENCES native_contributors (id) ON DELETE RESTRICT, 
	FOREIGN KEY(reconciled_material_id) REFERENCES native_materials (id) ON DELETE RESTRICT
);
"""

GUARDS = r"""
CREATE FUNCTION hypertest_guard_native() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_run uuid; child_run uuid; contributor_generation bigint;
BEGIN
 IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'native history is append-only'; END IF;
 IF TG_OP = 'UPDATE' THEN
   IF to_jsonb(NEW) = to_jsonb(OLD) THEN RETURN NEW; END IF;
   IF TG_TABLE_NAME = 'native_test_runs' THEN
    IF
      (to_jsonb(NEW)-'generation') = (to_jsonb(OLD)-'generation') AND
      NEW.generation = OLD.generation+1 AND EXISTS (
        SELECT 1 FROM native_contributors c WHERE c.run_id=NEW.id AND c.generation=NEW.generation
      ) AND EXISTS (
        SELECT 1 FROM native_handoffs h WHERE h.run_id=NEW.id AND h.to_generation=NEW.generation
      ) THEN RETURN NEW;
    END IF;
   END IF;
   IF TG_TABLE_NAME = 'native_operations' THEN
    IF OLD.status='UNKNOWN' AND NEW.status='RESOLVED'
      AND (to_jsonb(NEW)-'status'-'result'-'reconciled_material_id') =
          (to_jsonb(OLD)-'status'-'result'-'reconciled_material_id')
      AND NEW.reconciled_material_id IS NOT NULL AND
      (SELECT run_id FROM native_materials WHERE id=NEW.reconciled_material_id)=NEW.run_id THEN RETURN NEW;
    END IF;
   END IF;
   RAISE EXCEPTION 'native history is append-only';
 END IF;
 IF TG_TABLE_NAME IN ('native_execution_records','native_conclusions','native_operations') THEN
   SELECT run_id,generation INTO parent_run,contributor_generation FROM native_contributors WHERE id=NEW.contributor_id;
   IF parent_run IS DISTINCT FROM NEW.run_id OR contributor_generation IS DISTINCT FROM
      (SELECT generation FROM native_test_runs WHERE id=NEW.run_id) THEN
     RAISE EXCEPTION 'native contributor is outside current run generation';
   END IF;
 END IF;
 IF TG_TABLE_NAME='native_execution_records' THEN
  IF NEW.retry_of_execution_id IS NOT NULL THEN
   IF (SELECT run_id FROM native_execution_records WHERE id=NEW.retry_of_execution_id) IS DISTINCT FROM NEW.run_id THEN
      RAISE EXCEPTION 'native retry belongs to another run'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='native_execution_cases' THEN
   SELECT run_id INTO parent_run FROM native_execution_records WHERE id=NEW.execution_id;
   SELECT run_id INTO child_run FROM native_cases WHERE id=NEW.case_id;
   IF parent_run IS DISTINCT FROM child_run THEN RAISE EXCEPTION 'native case belongs to another run'; END IF;
 END IF;
 IF TG_TABLE_NAME='native_conclusion_executions' THEN
   SELECT run_id INTO parent_run FROM native_execution_records WHERE id=NEW.execution_id;
   SELECT run_id INTO child_run FROM native_conclusions WHERE id=NEW.conclusion_id;
   IF parent_run IS DISTINCT FROM child_run THEN RAISE EXCEPTION 'native conclusion belongs to another run'; END IF;
 END IF;
 IF TG_TABLE_NAME='native_handoffs' THEN
   IF NOT EXISTS (SELECT 1 FROM native_contributors c WHERE c.id=NEW.from_contributor_id
       AND c.run_id=NEW.run_id AND c.generation=NEW.from_generation) OR
      NOT EXISTS (SELECT 1 FROM native_contributors c WHERE c.id=NEW.to_contributor_id
       AND c.run_id=NEW.run_id AND c.generation=NEW.to_generation) THEN
      RAISE EXCEPTION 'native handoff contributor mismatch'; END IF;
 END IF;
 IF TG_TABLE_NAME='native_materials' THEN
  IF NEW.sha256 !~ '^[a-f0-9]{64}$' OR
      NEW.artifact_uri <> 'sha256:' || NEW.sha256 THEN
   RAISE EXCEPTION 'native material content address mismatch';
  END IF;
  IF NEW.execution_id IS NOT NULL AND
      (SELECT run_id FROM native_execution_records WHERE id=NEW.execution_id) IS DISTINCT FROM NEW.run_id THEN
      RAISE EXCEPTION 'native material belongs to another run'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""
