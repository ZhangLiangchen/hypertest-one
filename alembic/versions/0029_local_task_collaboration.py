"""Explicit multi-session Local collaboration and immutable accepted snapshots."""
import sqlalchemy as sa

from alembic import op

revision = "0029_local_task_collaboration"
down_revision = "0028_cloud_http_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("session_tasks", sa.Column("collaboration_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("session_tasks", sa.Column("primary_participant_id", sa.Uuid()))
    op.add_column("session_tasks", sa.Column("primary_generation", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_task_collaboration_mode", "session_tasks", "(collaboration_enabled AND binding_state='BOUND' AND primary_generation>0) OR (NOT collaboration_enabled AND primary_generation=0 AND primary_participant_id IS NULL)")
    op.execute(r"""
CREATE TABLE session_task_sources (
	provider VARCHAR(64) NOT NULL,
	session_id VARCHAR(512) NOT NULL,
	task_id UUID NOT NULL,
	PRIMARY KEY (provider, session_id),
	FOREIGN KEY(task_id) REFERENCES session_tasks (id) ON DELETE RESTRICT
)

""")
    op.execute(r"""
CREATE TABLE session_task_participants (
	task_id UUID NOT NULL,
	project_id UUID NOT NULL,
	provider VARCHAR(64) NOT NULL,
	session_id VARCHAR(512) NOT NULL,
	actor_ref VARCHAR(255) NOT NULL,
	role VARCHAR(16) NOT NULL,
	status VARCHAR(16) NOT NULL,
	assignment TEXT NOT NULL,
	initial_binding BOOLEAN NOT NULL,
	task_version BIGINT NOT NULL,
	authorized_at TIMESTAMP WITH TIME ZONE NOT NULL,
	joined_at TIMESTAMP WITH TIME ZONE,
	revoked_at TIMESTAMP WITH TIME ZONE,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_task_participant_source UNIQUE (task_id, provider, session_id),
	CHECK (status IN ('AUTHORIZED','ACTIVE','REVOKED')),
	CHECK (role IN ('PRIMARY','CONTRIBUTOR')),
	CHECK (role <> 'PRIMARY' OR status='ACTIVE'),
	CHECK (task_version > 0),
	FOREIGN KEY(task_id) REFERENCES session_tasks (id) ON DELETE RESTRICT,
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)

""")
    op.execute(r"""
CREATE TABLE session_contribution_revisions (
	task_id UUID NOT NULL,
	participant_id UUID NOT NULL,
	kind VARCHAR(16) NOT NULL,
	stable_key VARCHAR(128) NOT NULL,
	revision BIGINT NOT NULL,
	task_version BIGINT NOT NULL,
	content JSONB NOT NULL,
	actor_ref VARCHAR(255) NOT NULL,
	provider VARCHAR(64) NOT NULL,
	session_id VARCHAR(512) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_contribution_revision UNIQUE (task_id, participant_id, kind, stable_key, revision),
	CHECK (revision > 0 AND task_version > 0),
	CHECK (kind IN ('PLAN','CASE','REPORT','REVIEW')),
	FOREIGN KEY(task_id) REFERENCES session_tasks (id) ON DELETE RESTRICT,
	FOREIGN KEY(participant_id) REFERENCES session_task_participants (id) ON DELETE RESTRICT
)

""")
    op.execute(r"""
CREATE TABLE session_task_publications (
	task_id UUID NOT NULL,
	participant_id UUID NOT NULL,
	task_version BIGINT NOT NULL,
	primary_generation BIGINT NOT NULL,
	summary JSONB NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_task_publication_version UNIQUE (task_id, task_version),
	CHECK (primary_generation > 0 AND task_version > 0),
	FOREIGN KEY(task_id) REFERENCES session_tasks (id) ON DELETE RESTRICT,
	FOREIGN KEY(participant_id) REFERENCES session_task_participants (id) ON DELETE RESTRICT
)

""")
    op.execute(r"""
CREATE TABLE session_collaboration_receipts (
	task_id UUID NOT NULL,
	project_id UUID NOT NULL,
	actor_ref VARCHAR(255) NOT NULL,
	operation VARCHAR(16) NOT NULL,
	idempotency_key VARCHAR(128) NOT NULL,
	input_digest VARCHAR(64) NOT NULL,
	task_version BIGINT NOT NULL,
	provider VARCHAR(64),
	session_id VARCHAR(512),
	participant_id UUID,
	request_payload JSONB NOT NULL,
	task_snapshot JSONB NOT NULL,
	collaboration_snapshot JSONB NOT NULL,
	response JSONB NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_collaboration_key UNIQUE (actor_ref, project_id, idempotency_key),
	CONSTRAINT uq_collaboration_version UNIQUE (task_id, task_version),
	CHECK (operation IN ('ENABLE','AUTHORIZE','JOIN','REVOKE','CONTRIBUTE','PUBLISH','HANDOFF')),
	CHECK (task_version > 0),
	FOREIGN KEY(task_id) REFERENCES session_tasks (id) ON DELETE RESTRICT,
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT,
	FOREIGN KEY(participant_id) REFERENCES session_task_participants (id) ON DELETE RESTRICT
)

""")
    op.execute("CREATE UNIQUE INDEX uq_task_active_primary ON session_task_participants(task_id) WHERE role='PRIMARY' AND status='ACTIVE'")
    op.execute("INSERT INTO session_task_sources(provider,session_id,task_id) SELECT provider,session_id,id FROM session_tasks WHERE binding_state='BOUND'")
    op.execute(SESSION_GUARD)
    op.execute(SOURCE_GUARD)
    op.execute(MEMBER_GUARD)
    op.execute(PRIMARY_GUARD)
    for table in ("session_tasks", "session_task_participants"):
        op.execute(f"CREATE TRIGGER session_source_guard AFTER INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_reserve_session_source()")
    op.execute("CREATE TRIGGER session_source_immutable BEFORE UPDATE OR DELETE ON session_task_sources FOR EACH ROW EXECUTE FUNCTION hypertest_guard_collaboration()")
    for table in ("session_task_participants", "session_contribution_revisions", "session_task_publications", "session_collaboration_receipts"):
        op.execute(f"CREATE TRIGGER collaboration_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_collaboration()")
    for table in ("session_tasks", "session_task_participants"):
        op.execute(f"CREATE CONSTRAINT TRIGGER collaboration_primary_guard AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hypertest_check_task_primary()")


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM session_collaboration_receipts) OR EXISTS (SELECT 1 FROM session_tasks WHERE collaboration_enabled)")):
        raise RuntimeError("Local collaboration history prevents destructive downgrade")
    op.execute("DROP TRIGGER collaboration_primary_guard ON session_tasks")
    op.execute("DROP TRIGGER session_source_guard ON session_tasks")
    for name in ("session_collaboration_receipts", "session_task_publications", "session_contribution_revisions", "session_task_participants", "session_task_sources"):
        op.drop_table(name)
    for name in ("hypertest_check_task_primary()", "hypertest_guard_collaboration()", "hypertest_reserve_session_source()"):
        op.execute("DROP FUNCTION " + name)
    op.drop_constraint("ck_task_collaboration_mode", "session_tasks", type_="check")
    for name in ("primary_generation", "primary_participant_id", "collaboration_enabled"):
        op.drop_column("session_tasks", name)
    op.execute(OLD_SESSION_GUARD)

SESSION_GUARD = r"""
CREATE OR REPLACE FUNCTION hypertest_guard_session_tasks() RETURNS trigger LANGUAGE plpgsql AS $$
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
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.creator_actor_ref IS DISTINCT FROM OLD.creator_actor_ref
       OR NEW.binding_required IS DISTINCT FROM OLD.binding_required
       OR NEW.version <> OLD.version + 1 THEN
      RAISE EXCEPTION 'session identity is immutable and version must increase by one';
    END IF;
    IF OLD.collaboration_enabled AND NOT NEW.collaboration_enabled THEN
      RAISE EXCEPTION 'collaboration cannot downgrade to legacy full sync';
    END IF;
    IF NEW.primary_generation < OLD.primary_generation OR NEW.primary_generation > OLD.primary_generation+1 THEN
      RAISE EXCEPTION 'primary generation must be monotonic';
    END IF;
    IF NEW.primary_participant_id IS DISTINCT FROM OLD.primary_participant_id AND NEW.primary_generation <> OLD.primary_generation+1 THEN
      RAISE EXCEPTION 'primary switch requires next generation';
    END IF;
    IF OLD.binding_state='BOUND' AND (NEW.binding_state IS DISTINCT FROM OLD.binding_state
       OR NEW.provider IS DISTINCT FROM OLD.provider OR NEW.session_id IS DISTINCT FROM OLD.session_id
       OR NEW.owner_actor_ref IS DISTINCT FROM OLD.owner_actor_ref OR NEW.bound_at IS DISTINCT FROM OLD.bound_at
       OR NEW.intended_actor_ref IS DISTINCT FROM OLD.intended_actor_ref) THEN
      RAISE EXCEPTION 'bound source identity is immutable';
    END IF;
    IF OLD.binding_state='UNBOUND' AND NEW.binding_state='BOUND' AND
       (OLD.deleted_at IS NOT NULL OR NEW.intended_actor_ref IS NULL
        OR NEW.intended_actor_ref IS DISTINCT FROM OLD.intended_actor_ref
        OR NEW.owner_actor_ref IS DISTINCT FROM NEW.intended_actor_ref OR NEW.bound_at IS NULL
        OR NEW.source IS NOT NULL OR NEW.last_synced_at IS NOT NULL) THEN
      RAISE EXCEPTION 'binding requires one explicit source and intended actor without Agent sync';
    END IF;
    IF NEW.source IS DISTINCT FROM OLD.source AND NOT
       (OLD.source IS NULL AND NEW.source='AGENT_REPORTED' AND NEW.binding_state='BOUND'
        AND NEW.last_synced_at IS NOT NULL) THEN
      RAISE EXCEPTION 'sync source may only be filled by the first Agent sync';
    END IF;
    IF OLD.last_synced_at IS NOT NULL AND (NEW.last_synced_at IS NULL OR NEW.last_synced_at < OLD.last_synced_at) THEN
      RAISE EXCEPTION 'Agent sync time cannot regress';
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
    IF TG_TABLE_NAME IN ('session_sync_receipts','session_task_operation_receipts') THEN
      IF NEW.project_id <> parent.project_id THEN
        RAISE EXCEPTION 'receipt Project must match task';
      END IF;
    END IF;
    IF TG_TABLE_NAME IN ('session_sync_receipts','session_case_revisions','session_report_revisions') AND
       (parent.binding_state <> 'BOUND' OR parent.source IS NULL OR parent.last_synced_at IS NULL) THEN
      RAISE EXCEPTION 'Agent assets require an actually synchronized bound task';
    END IF;
    IF TG_TABLE_NAME = 'session_case_revisions' THEN
      SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_case_revisions WHERE task_id=NEW.task_id AND key=NEW.key;
      IF NEW.revision <> next_revision THEN RAISE EXCEPTION 'case revision must increase by one'; END IF;
    ELSIF TG_TABLE_NAME = 'session_report_revisions' THEN
      SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_report_revisions WHERE task_id=NEW.task_id AND key=NEW.key;
      IF NEW.revision <> next_revision THEN RAISE EXCEPTION 'report revision must increase by one'; END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$
"""

OLD_SESSION_GUARD = r"""
CREATE OR REPLACE FUNCTION hypertest_guard_session_tasks() RETURNS trigger LANGUAGE plpgsql AS $$
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
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.creator_actor_ref IS DISTINCT FROM OLD.creator_actor_ref
       OR NEW.binding_required IS DISTINCT FROM OLD.binding_required
       OR NEW.version <> OLD.version + 1 THEN
      RAISE EXCEPTION 'session identity is immutable and version must increase by one';
    END IF;
    IF OLD.binding_state='BOUND' AND (NEW.binding_state IS DISTINCT FROM OLD.binding_state
       OR NEW.provider IS DISTINCT FROM OLD.provider OR NEW.session_id IS DISTINCT FROM OLD.session_id
       OR NEW.owner_actor_ref IS DISTINCT FROM OLD.owner_actor_ref OR NEW.bound_at IS DISTINCT FROM OLD.bound_at
       OR NEW.intended_actor_ref IS DISTINCT FROM OLD.intended_actor_ref) THEN
      RAISE EXCEPTION 'bound source identity is immutable';
    END IF;
    IF OLD.binding_state='UNBOUND' AND NEW.binding_state='BOUND' AND
       (OLD.deleted_at IS NOT NULL OR NEW.intended_actor_ref IS NULL
        OR NEW.intended_actor_ref IS DISTINCT FROM OLD.intended_actor_ref
        OR NEW.owner_actor_ref IS DISTINCT FROM NEW.intended_actor_ref OR NEW.bound_at IS NULL
        OR NEW.source IS NOT NULL OR NEW.last_synced_at IS NOT NULL) THEN
      RAISE EXCEPTION 'binding requires one explicit source and intended actor without Agent sync';
    END IF;
    IF NEW.source IS DISTINCT FROM OLD.source AND NOT
       (OLD.source IS NULL AND NEW.source='AGENT_REPORTED' AND NEW.binding_state='BOUND'
        AND NEW.last_synced_at IS NOT NULL) THEN
      RAISE EXCEPTION 'sync source may only be filled by the first Agent sync';
    END IF;
    IF OLD.last_synced_at IS NOT NULL AND (NEW.last_synced_at IS NULL OR NEW.last_synced_at < OLD.last_synced_at) THEN
      RAISE EXCEPTION 'Agent sync time cannot regress';
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
    IF TG_TABLE_NAME IN ('session_sync_receipts','session_task_operation_receipts') THEN
      IF NEW.project_id <> parent.project_id THEN
        RAISE EXCEPTION 'receipt Project must match task';
      END IF;
    END IF;
    IF TG_TABLE_NAME IN ('session_sync_receipts','session_case_revisions','session_report_revisions') AND
       (parent.binding_state <> 'BOUND' OR parent.source IS NULL OR parent.last_synced_at IS NULL) THEN
      RAISE EXCEPTION 'Agent assets require an actually synchronized bound task';
    END IF;
    IF TG_TABLE_NAME = 'session_case_revisions' THEN
      SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_case_revisions WHERE task_id=NEW.task_id AND key=NEW.key;
      IF NEW.revision <> next_revision THEN RAISE EXCEPTION 'case revision must increase by one'; END IF;
    ELSIF TG_TABLE_NAME = 'session_report_revisions' THEN
      SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_report_revisions WHERE task_id=NEW.task_id AND key=NEW.key;
      IF NEW.revision <> next_revision THEN RAISE EXCEPTION 'report revision must increase by one'; END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$
"""

SOURCE_GUARD = r"""
CREATE FUNCTION hypertest_reserve_session_source() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reserved UUID; target UUID;
BEGIN
  IF TG_TABLE_NAME='session_tasks' THEN
    IF NEW.binding_state<>'BOUND' THEN RETURN NEW; END IF;
    target := NEW.id;
  ELSE
    IF NEW.status<>'ACTIVE' THEN RETURN NEW; END IF;
    target := NEW.task_id;
  END IF;
  INSERT INTO session_task_sources(provider,session_id,task_id)
    VALUES(NEW.provider,NEW.session_id,target) ON CONFLICT DO NOTHING;
  SELECT task_id INTO STRICT reserved FROM session_task_sources
    WHERE provider=NEW.provider AND session_id=NEW.session_id;
  IF reserved<>target THEN RAISE EXCEPTION 'session source belongs to another task' USING ERRCODE='23505'; END IF;
  RETURN NEW;
END $$
"""

MEMBER_GUARD = r"""
CREATE FUNCTION hypertest_guard_collaboration() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent session_tasks%ROWTYPE; member session_task_participants%ROWTYPE; next_revision BIGINT;
BEGIN
  IF TG_OP='DELETE' OR TG_TABLE_NAME='session_task_sources' THEN
    RAISE EXCEPTION 'collaboration source and acceptance history is retained';
  END IF;
  IF TG_OP='UPDATE' AND TG_TABLE_NAME<>'session_task_participants' THEN
    RAISE EXCEPTION 'collaboration revisions and receipts are immutable';
  END IF;
  SELECT * INTO STRICT parent FROM session_tasks WHERE id=NEW.task_id FOR UPDATE;
  IF NOT parent.collaboration_enabled OR parent.version<>NEW.task_version THEN
    RAISE EXCEPTION 'collaboration material requires the current enabled task version';
  END IF;
  IF TG_TABLE_NAME='session_task_participants' THEN
    IF NEW.project_id<>parent.project_id OR NEW.actor_ref<>parent.owner_actor_ref THEN
      RAISE EXCEPTION 'member Project and actor must match task';
    END IF;
    IF TG_OP='UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.task_id IS DISTINCT FROM OLD.task_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id OR NEW.actor_ref IS DISTINCT FROM OLD.actor_ref
       OR NEW.provider IS DISTINCT FROM OLD.provider OR NEW.session_id IS DISTINCT FROM OLD.session_id
       OR NEW.initial_binding IS DISTINCT FROM OLD.initial_binding OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.task_version<=OLD.task_version) THEN
      RAISE EXCEPTION 'participant source is immutable and change requires a new task version';
    END IF;
    IF NEW.initial_binding AND (NEW.provider<>parent.provider OR NEW.session_id<>parent.session_id) THEN
      RAISE EXCEPTION 'initial participant must retain original bound source';
    END IF;
  ELSE
    IF TG_TABLE_NAME='session_collaboration_receipts' THEN
      IF NEW.participant_id IS NOT NULL THEN
        SELECT * INTO STRICT member FROM session_task_participants WHERE id=NEW.participant_id;
        IF member.task_id<>parent.id OR member.actor_ref<>NEW.actor_ref OR member.provider IS DISTINCT FROM NEW.provider
           OR member.session_id IS DISTINCT FROM NEW.session_id OR member.status<>'ACTIVE' THEN
          RAISE EXCEPTION 'member receipt requires exact active submitting source';
        END IF;
      ELSIF NEW.provider IS NOT NULL OR NEW.session_id IS NOT NULL THEN
        RAISE EXCEPTION 'operator receipt cannot claim member source';
      END IF;
      IF NEW.project_id<>parent.project_id THEN RAISE EXCEPTION 'receipt Project mismatch'; END IF;
      IF (NEW.task_snapshot->>'version')::bigint<>NEW.task_version THEN RAISE EXCEPTION 'receipt snapshot version mismatch'; END IF;
    END IF;
    IF TG_TABLE_NAME IN ('session_contribution_revisions','session_task_publications') THEN
      SELECT * INTO STRICT member FROM session_task_participants WHERE id=NEW.participant_id;
      IF member.task_id<>parent.id OR member.status<>'ACTIVE' THEN
        RAISE EXCEPTION 'material requires an active member of this task';
      END IF;
      IF TG_TABLE_NAME='session_contribution_revisions' THEN
        IF NEW.actor_ref<>member.actor_ref OR NEW.provider<>member.provider OR NEW.session_id<>member.session_id THEN
          RAISE EXCEPTION 'contribution source must match member';
        END IF;
        SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_contribution_revisions
          WHERE task_id=NEW.task_id AND participant_id=NEW.participant_id AND kind=NEW.kind AND stable_key=NEW.stable_key;
        IF NEW.revision<>next_revision THEN RAISE EXCEPTION 'contribution revision must increase by one'; END IF;
      ELSE
        IF parent.primary_participant_id<>member.id OR member.role<>'PRIMARY' OR NEW.primary_generation<>parent.primary_generation THEN
          RAISE EXCEPTION 'publication requires current primary and generation';
        END IF;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$
"""

PRIMARY_GUARD = r"""
CREATE FUNCTION hypertest_check_task_primary() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent session_tasks%ROWTYPE; member session_task_participants%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='session_tasks' THEN
    SELECT * INTO STRICT parent FROM session_tasks WHERE id=NEW.id;
  ELSE
    SELECT * INTO STRICT parent FROM session_tasks WHERE id=NEW.task_id;
  END IF;
  IF parent.collaboration_enabled THEN
    IF parent.primary_participant_id IS NOT NULL THEN
      SELECT * INTO member FROM session_task_participants WHERE id=parent.primary_participant_id;
      IF member.id IS NULL OR member.task_id<>parent.id OR member.status<>'ACTIVE' OR member.role<>'PRIMARY' THEN
        RAISE EXCEPTION 'current primary must be an active primary member of the same task';
      END IF;
    ELSIF EXISTS (SELECT 1 FROM session_task_participants WHERE task_id=parent.id AND role='PRIMARY' AND status='ACTIVE') THEN
      RAISE EXCEPTION 'primary participant must be explicitly selected';
    END IF;
  END IF;
  RETURN NULL;
END $$
"""
