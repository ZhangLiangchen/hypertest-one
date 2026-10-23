"""Precreated Local tasks and one-time source binding, without fake Agent sync."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0024_local_task_binding"
down_revision = "0023_project_task_management"
branch_labels = None
depends_on = None


def upgrade():
    for name, type_ in (("provider", sa.String(64)), ("session_id", sa.String(512)),
                         ("owner_actor_ref", sa.String(255)), ("source", sa.String(32)),
                         ("last_synced_at", sa.DateTime(timezone=True))):
        op.alter_column("session_tasks", name, existing_type=type_, nullable=True)
    for column in (
        sa.Column("binding_state", sa.String(16), nullable=False, server_default="BOUND"),
        sa.Column("binding_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("creator_actor_ref", sa.String(255)),
        sa.Column("intended_actor_ref", sa.String(255)),
        sa.Column("bound_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("session_tasks", column)
    op.create_check_constraint("ck_session_binding_state", "session_tasks", "binding_state IN ('UNBOUND','BOUND')")
    op.create_check_constraint("ck_session_binding_identity", "session_tasks",
        "(binding_state='UNBOUND' AND binding_required AND creator_actor_ref IS NOT NULL AND provider IS NULL AND session_id IS NULL AND owner_actor_ref IS NULL AND source IS NULL AND last_synced_at IS NULL AND bound_at IS NULL) OR (binding_state='BOUND' AND provider IS NOT NULL AND session_id IS NOT NULL AND owner_actor_ref IS NOT NULL AND (NOT binding_required OR (bound_at IS NOT NULL AND intended_actor_ref IS NOT NULL AND owner_actor_ref=intended_actor_ref)))")
    op.create_check_constraint("ck_session_sync_source", "session_tasks",
        "(source IS NULL AND last_synced_at IS NULL) OR (source IS NOT NULL AND source='AGENT_REPORTED' AND last_synced_at IS NOT NULL)")
    # PostgreSQL named the earlier unnamed action check. Discover that specific
    # check rather than depending on a generated name or touching other checks.
    checks = sa.inspect(op.get_bind()).get_check_constraints("session_task_management_revisions")
    for check in checks:
        if "action" in check["sqltext"]:
            op.drop_constraint(check["name"], "session_task_management_revisions", type_="check")
    op.create_check_constraint("ck_session_management_action", "session_task_management_revisions",
                               "action IN ('CREATE','AUTHORIZE','UPDATE','DELETE','RESTORE')")
    op.create_table("session_task_operation_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("session_tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_ref", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("task_version", sa.BigInteger(), nullable=False),
        sa.Column("task_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_ref", "project_id", "idempotency_key", name="uq_session_operation_key"),
        sa.UniqueConstraint("task_id", "task_version", name="uq_session_operation_version"),
        sa.CheckConstraint("operation IN ('CREATE','BIND')", name="ck_session_operation"),
        sa.CheckConstraint("task_version > 0"))
    op.execute(GUARD)
    op.execute("CREATE TRIGGER session_task_history_guard BEFORE INSERT OR UPDATE OR DELETE ON session_task_operation_receipts FOR EACH ROW EXECUTE FUNCTION hypertest_guard_session_tasks()")


def downgrade():
    db = op.get_bind()
    if db.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM session_task_operation_receipts) OR EXISTS (SELECT 1 FROM session_tasks WHERE binding_required OR binding_state='UNBOUND')")):
        raise RuntimeError("Local task binding history prevents destructive downgrade")
    op.drop_table("session_task_operation_receipts")
    op.drop_constraint("ck_session_management_action", "session_task_management_revisions", type_="check")
    op.create_check_constraint("ck_session_management_action", "session_task_management_revisions", "action IN ('UPDATE','DELETE','RESTORE')")
    op.drop_constraint("ck_session_sync_source", "session_tasks", type_="check")
    op.drop_constraint("ck_session_binding_identity", "session_tasks", type_="check")
    op.drop_constraint("ck_session_binding_state", "session_tasks", type_="check")
    for name in ("bound_at", "intended_actor_ref", "creator_actor_ref", "binding_required", "binding_state"):
        op.drop_column("session_tasks", name)
    for name in ("provider", "session_id", "owner_actor_ref", "source", "last_synced_at"):
        op.alter_column("session_tasks", name, nullable=False)
    # Restore the previous function without modifying its append-only tables.
    op.execute(LEGACY_GUARD)


GUARD = r"""
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

# The previous implementation uses only columns present before this migration.
LEGACY_GUARD = r"""
CREATE OR REPLACE FUNCTION hypertest_guard_session_tasks() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent session_tasks%ROWTYPE; next_revision BIGINT;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'session task history is retained'; END IF;
 IF TG_OP='UPDATE' THEN
  IF TG_TABLE_NAME<>'session_tasks' THEN RAISE EXCEPTION 'session task revisions and receipts are immutable'; END IF;
  IF NEW.id<>OLD.id OR NEW.project_id<>OLD.project_id OR NEW.provider<>OLD.provider OR NEW.session_id<>OLD.session_id OR NEW.owner_actor_ref<>OLD.owner_actor_ref OR NEW.created_at<>OLD.created_at OR NEW.source<>OLD.source OR NEW.version<>OLD.version+1 THEN RAISE EXCEPTION 'session identity is immutable and version must increase by one'; END IF;
 END IF;
 IF TG_TABLE_NAME='session_tasks' THEN
  IF TG_OP='INSERT' AND NEW.version<>1 THEN RAISE EXCEPTION 'session tasks begin at version one'; END IF;
 ELSE
  SELECT * INTO STRICT parent FROM session_tasks WHERE id=NEW.task_id;
  IF NEW.task_version<>parent.version THEN RAISE EXCEPTION 'revision must belong to the current task version'; END IF;
  IF TG_TABLE_NAME='session_sync_receipts' AND NEW.project_id<>parent.project_id THEN RAISE EXCEPTION 'sync receipt Project must match task'; END IF;
  IF TG_TABLE_NAME='session_case_revisions' THEN
   SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_case_revisions WHERE task_id=NEW.task_id AND key=NEW.key;
   IF NEW.revision<>next_revision THEN RAISE EXCEPTION 'case revision must increase by one'; END IF;
  ELSIF TG_TABLE_NAME='session_report_revisions' THEN
   SELECT COALESCE(MAX(revision),0)+1 INTO next_revision FROM session_report_revisions WHERE task_id=NEW.task_id AND key=NEW.key;
   IF NEW.revision<>next_revision THEN RAISE EXCEPTION 'report revision must increase by one'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$
"""
