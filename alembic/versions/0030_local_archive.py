"""Independent explicit Local archives. Old session and Cloud history is untouched."""
import sqlalchemy as sa

from alembic import op

revision = "0030_local_archive"
down_revision = "0029_local_task_collaboration"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(r"""
CREATE TABLE local_archive_tasks (
	project_id UUID NOT NULL, 
	creator_actor_ref VARCHAR(255) NOT NULL, 
	owner_uploader_actor_ref VARCHAR(255), 
	title VARCHAR(512) NOT NULL, 
	objective TEXT NOT NULL, 
	version BIGINT NOT NULL, 
	archive_version BIGINT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, id), 
	CHECK (version>0 AND archive_version>0), 
	CHECK (status IN ('DRAFT','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED')), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED')), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)

""")
    op.execute(r"""
CREATE TABLE local_archive_subtasks (
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	authorized_uploader_actor_ref VARCHAR(255), 
	title VARCHAR(512) NOT NULL, 
	objective TEXT NOT NULL, 
	archive_version BIGINT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id, task_id) REFERENCES local_archive_tasks (project_id, id) ON DELETE RESTRICT, 
	UNIQUE (project_id, task_id, id), 
	CHECK (archive_version>0), 
	CHECK (status IN ('DRAFT','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED')), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED'))
)

""")
    op.execute(r"""
CREATE TABLE local_archive_snapshots (
	archive_version BIGINT NOT NULL, 
	document JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	target_kind VARCHAR(16) NOT NULL, 
	subtask_id UUID, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id, task_id) REFERENCES local_archive_tasks (project_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id, task_id, subtask_id) REFERENCES local_archive_subtasks (project_id, task_id, id) ON DELETE RESTRICT, 
	CHECK ((target_kind='TASK' AND subtask_id IS NULL) OR (target_kind='SUBTASK' AND subtask_id IS NOT NULL)), 
	UNIQUE (project_id, task_id, id), 
	CHECK (archive_version>0)
)

""")
    op.execute('CREATE UNIQUE INDEX uq_archive_root_snapshot ON local_archive_snapshots (task_id, archive_version) WHERE subtask_id IS NULL')
    op.execute('CREATE UNIQUE INDEX uq_archive_child_snapshot ON local_archive_snapshots (subtask_id, archive_version) WHERE subtask_id IS NOT NULL')
    op.execute(r"""
CREATE TABLE local_archive_submissions (
	profile VARCHAR(64) NOT NULL, 
	operation VARCHAR(32) NOT NULL, 
	uploader_actor_ref VARCHAR(255) NOT NULL, 
	client_instance_id UUID NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	request_payload JSONB NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	expected_archive_version BIGINT NOT NULL, 
	outcome VARCHAR(16) NOT NULL, 
	accepted_version BIGINT NOT NULL, 
	snapshot_id UUID NOT NULL, 
	response JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	target_kind VARCHAR(16) NOT NULL, 
	subtask_id UUID, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id, task_id) REFERENCES local_archive_tasks (project_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id, task_id, subtask_id) REFERENCES local_archive_subtasks (project_id, task_id, id) ON DELETE RESTRICT, 
	CHECK ((target_kind='TASK' AND subtask_id IS NULL) OR (target_kind='SUBTASK' AND subtask_id IS NOT NULL)), 
	UNIQUE (project_id, task_id, id), 
	CONSTRAINT uq_archive_submission_key UNIQUE (project_id, uploader_actor_ref, operation, idempotency_key), 
	FOREIGN KEY(project_id, task_id, snapshot_id) REFERENCES local_archive_snapshots (project_id, task_id, id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CHECK (expected_archive_version>0 AND accepted_version>0), 
	CHECK (operation='ARCHIVE'), 
	CHECK (outcome IN ('ACCEPTED','UNCHANGED')), 
	CHECK ((outcome='ACCEPTED' AND accepted_version=expected_archive_version+1) OR (outcome='UNCHANGED' AND accepted_version=expected_archive_version))
)

""")
    op.execute(r"""
CREATE TABLE local_archive_asset_revisions (
	submission_id UUID NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	stable_key VARCHAR(128) NOT NULL, 
	revision BIGINT NOT NULL, 
	archive_version BIGINT NOT NULL, 
	uploader_actor_ref VARCHAR(255) NOT NULL, 
	content JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	target_kind VARCHAR(16) NOT NULL, 
	subtask_id UUID, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id, task_id) REFERENCES local_archive_tasks (project_id, id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id, task_id, subtask_id) REFERENCES local_archive_subtasks (project_id, task_id, id) ON DELETE RESTRICT, 
	CHECK ((target_kind='TASK' AND subtask_id IS NULL) OR (target_kind='SUBTASK' AND subtask_id IS NOT NULL)), 
	FOREIGN KEY(project_id, task_id, submission_id) REFERENCES local_archive_submissions (project_id, task_id, id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CHECK (kind IN ('PLAN','CASE','REPORT')), 
	CHECK (revision>0 AND archive_version>0)
)

""")
    op.execute('CREATE UNIQUE INDEX uq_archive_root_asset ON local_archive_asset_revisions (task_id, kind, stable_key, revision) WHERE subtask_id IS NULL')
    op.execute('CREATE UNIQUE INDEX uq_archive_child_asset ON local_archive_asset_revisions (subtask_id, kind, stable_key, revision) WHERE subtask_id IS NOT NULL')
    op.execute(r"""
CREATE TABLE local_archive_publications (
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	task_version BIGINT NOT NULL, 
	root_archive_version BIGINT NOT NULL, 
	subtask_versions JSONB NOT NULL, 
	asset_revision_ids JSONB NOT NULL, 
	omitted_subtask_ids JSONB NOT NULL, 
	incomplete_subtask_ids JSONB NOT NULL, 
	summary TEXT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	reported_result VARCHAR(16) NOT NULL, 
	actor_ref VARCHAR(255) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id, task_id) REFERENCES local_archive_tasks (project_id, id) ON DELETE RESTRICT, 
	UNIQUE (task_id, task_version), 
	CHECK (task_version>0 AND root_archive_version>0), 
	CHECK (status IN ('DRAFT','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED')), 
	CHECK (reported_result IN ('NOT_RUN','PASS','FAIL','ERROR','SKIPPED','UNKNOWN','BLOCKED'))
)

""")
    op.execute(r"""
CREATE TABLE local_archive_operations (
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	actor_ref VARCHAR(255) NOT NULL, 
	operation VARCHAR(32) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	request_payload JSONB NOT NULL, 
	task_version BIGINT NOT NULL, 
	response JSONB NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id, task_id) REFERENCES local_archive_tasks (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT uq_archive_management_key UNIQUE (project_id, actor_ref, idempotency_key), 
	UNIQUE (task_id, task_version), 
	CHECK (task_version>0), 
	CHECK (operation IN ('CREATE','UPDATE','SUBTASK_CREATE','AUTHORIZE','PUBLISH'))
)

""")
    op.execute(GUARD)
    for table in ("local_archive_tasks", "local_archive_subtasks", "local_archive_snapshots", "local_archive_submissions", "local_archive_asset_revisions", "local_archive_publications", "local_archive_operations"):
        op.execute(f"CREATE TRIGGER archive_history_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_local_archive()")
    op.execute(OWNER_GUARD)
    for table in ("local_archive_tasks", "local_archive_subtasks"):
        op.execute(f"CREATE CONSTRAINT TRIGGER archive_owner_guard AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hypertest_check_archive_owners()")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM local_archive_tasks)")):
        raise RuntimeError("Local archive history prevents destructive downgrade")
    for table in ("local_archive_operations", "local_archive_publications", "local_archive_asset_revisions", "local_archive_submissions", "local_archive_snapshots", "local_archive_subtasks", "local_archive_tasks"):
        op.drop_table(table)
    op.execute("DROP FUNCTION hypertest_guard_local_archive()")
    op.execute("DROP FUNCTION hypertest_check_archive_owners()")


GUARD = r"""
CREATE FUNCTION hypertest_guard_local_archive() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous_revision BIGINT;
        original local_archive_submissions%ROWTYPE;
        frozen local_archive_snapshots%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'Local archive history is retained';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF TG_TABLE_NAME NOT IN ('local_archive_tasks','local_archive_subtasks') THEN
      RAISE EXCEPTION 'Local archive revisions, snapshots, submissions and receipts are immutable';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
      RAISE EXCEPTION 'Local archive identity is immutable';
    END IF;
    IF TG_TABLE_NAME='local_archive_tasks' THEN
      IF NEW.creator_actor_ref IS DISTINCT FROM OLD.creator_actor_ref THEN
        RAISE EXCEPTION 'Local archive creator is immutable';
      END IF;
      IF NOT ((NEW.version=OLD.version+1 AND NEW.archive_version=OLD.archive_version)
           OR (NEW.version=OLD.version AND NEW.archive_version=OLD.archive_version+1)) THEN
        RAISE EXCEPTION 'Management and root archive versions advance independently by one';
      END IF;
      IF NEW.version=OLD.version AND (NEW.title IS DISTINCT FROM OLD.title
         OR NEW.objective IS DISTINCT FROM OLD.objective OR NEW.status IS DISTINCT FROM OLD.status
         OR NEW.reported_result IS DISTINCT FROM OLD.reported_result
         OR NEW.owner_uploader_actor_ref IS DISTINCT FROM OLD.owner_uploader_actor_ref) THEN
        RAISE EXCEPTION 'Root uploads cannot mutate management fields';
      END IF;
      IF NEW.owner_uploader_actor_ref IS DISTINCT FROM OLD.owner_uploader_actor_ref
         AND EXISTS(SELECT 1 FROM local_archive_submissions WHERE task_id=OLD.id) THEN
        RAISE EXCEPTION 'Accepted archive owner is immutable';
      END IF;
    ELSE
      IF NEW.task_id IS DISTINCT FROM OLD.task_id OR NEW.archive_version NOT IN (OLD.archive_version,OLD.archive_version+1) THEN
        RAISE EXCEPTION 'Subtask identity and archive version are immutable or monotonic';
      END IF;
      IF NEW.archive_version=OLD.archive_version AND (NEW.status IS DISTINCT FROM OLD.status
         OR NEW.reported_result IS DISTINCT FROM OLD.reported_result) THEN
        RAISE EXCEPTION 'Subtask results require a new archive version';
      END IF;
    END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='local_archive_tasks' THEN
    IF NEW.version<>1 OR NEW.archive_version<>1 OR NEW.status<>'DRAFT' OR NEW.reported_result<>'NOT_RUN' THEN
      RAISE EXCEPTION 'Archive tasks start at version one without reported results';
    END IF;
  ELSIF TG_TABLE_NAME='local_archive_subtasks' THEN
    IF NEW.archive_version<>1 OR NEW.status<>'DRAFT' OR NEW.reported_result<>'NOT_RUN' THEN
      RAISE EXCEPTION 'Archive subtasks start at version one without reported results';
    END IF;
  ELSIF TG_TABLE_NAME='local_archive_snapshots' THEN
    IF NEW.document->>'profile'<>'local-artifact-archive/v1alpha1'
       OR NEW.document->>'task_id' IS DISTINCT FROM NEW.task_id::text
       OR NEW.document->>'project_id' IS DISTINCT FROM NEW.project_id::text
       OR NEW.document->>'target_kind' IS DISTINCT FROM NEW.target_kind
       OR NEW.document->>'subtask_id' IS DISTINCT FROM NEW.subtask_id::text
       OR NEW.document->>'archive_version' IS DISTINCT FROM NEW.archive_version::text THEN
      RAISE EXCEPTION 'Archive snapshot target mismatch';
    END IF;
  ELSIF TG_TABLE_NAME='local_archive_submissions' THEN
    SELECT * INTO frozen FROM local_archive_snapshots WHERE id=NEW.snapshot_id;
    IF NOT FOUND OR frozen.project_id<>NEW.project_id OR frozen.task_id<>NEW.task_id
       OR frozen.subtask_id IS DISTINCT FROM NEW.subtask_id OR frozen.target_kind<>NEW.target_kind
       OR frozen.archive_version<>NEW.accepted_version THEN
      RAISE EXCEPTION 'Submission must reference its exact accepted archive snapshot';
    END IF;
    IF NEW.profile<>'local-artifact-archive/v1alpha1'
       OR NEW.request_payload->>'project_id' IS DISTINCT FROM NEW.project_id::text
       OR NEW.request_payload->>'task_id' IS DISTINCT FROM NEW.task_id::text
       OR NEW.request_payload->>'subtask_id' IS DISTINCT FROM NEW.subtask_id::text THEN
      RAISE EXCEPTION 'Submission request target mismatch';
    END IF;
  ELSIF TG_TABLE_NAME='local_archive_asset_revisions' THEN
    SELECT * INTO original FROM local_archive_submissions WHERE id=NEW.submission_id;
    IF NOT FOUND OR original.project_id<>NEW.project_id OR original.task_id<>NEW.task_id
       OR original.subtask_id IS DISTINCT FROM NEW.subtask_id OR original.target_kind<>NEW.target_kind
       OR original.uploader_actor_ref<>NEW.uploader_actor_ref OR original.accepted_version<>NEW.archive_version
       OR original.outcome<>'ACCEPTED' THEN
      RAISE EXCEPTION 'Asset revision must belong to its exact accepting submission';
    END IF;
    SELECT COALESCE(MAX(revision),0) INTO previous_revision FROM local_archive_asset_revisions
      WHERE task_id=NEW.task_id AND subtask_id IS NOT DISTINCT FROM NEW.subtask_id
        AND kind=NEW.kind AND stable_key=NEW.stable_key;
    IF NEW.revision<>previous_revision+1 OR NEW.content->>'kind' IS DISTINCT FROM NEW.kind
       OR NEW.content->>'stable_key' IS DISTINCT FROM NEW.stable_key THEN
      RAISE EXCEPTION 'Asset revisions append sequentially within their exact target';
    END IF;
  END IF;
  RETURN NEW;
END $$;
"""

OWNER_GUARD = r"""
CREATE FUNCTION hypertest_check_archive_owners() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root_id UUID;
BEGIN
  IF TG_TABLE_NAME='local_archive_tasks' THEN root_id=NEW.id; ELSE root_id=NEW.task_id; END IF;
  IF EXISTS(SELECT 1 FROM local_archive_subtasks child JOIN local_archive_tasks parent ON parent.id=child.task_id
       WHERE child.task_id=root_id AND child.authorized_uploader_actor_ref IS NOT NULL
         AND child.authorized_uploader_actor_ref IS DISTINCT FROM parent.owner_uploader_actor_ref) THEN
    RAISE EXCEPTION 'Subtask uploader must be its task owner';
  END IF;
  RETURN NULL;
END $$;
"""
