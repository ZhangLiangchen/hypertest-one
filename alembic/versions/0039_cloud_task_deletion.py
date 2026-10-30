"""Add versioned Cloud Task tombstones without rewriting task history."""
import sqlalchemy as sa
from alembic import op

revision = "0039_cloud_task_deletion"
down_revision = "0038_action_recovery"
branch_labels = None
depends_on = None

_OLD = "IF OLD.status = 'CANCELLED' AND OLD.frozen_manifest IS NULL AND NEW IS DISTINCT FROM OLD THEN"
_NEW = """IF EXISTS (SELECT 1 FROM cloud_task_deletions d WHERE d.task_id = OLD.id)
       AND NOT (NEW.version = OLD.version + 1
                AND EXISTS (SELECT 1 FROM cloud_task_deletions d WHERE d.task_id = OLD.id AND d.accepted_version = NEW.version)
                AND (to_jsonb(NEW) - ARRAY['version','updated_at']) = (to_jsonb(OLD) - ARRAY['version','updated_at'])) THEN
      RAISE EXCEPTION 'deleted cloud task is immutable';
    END IF;
    IF OLD.status = 'CANCELLED' AND OLD.frozen_manifest IS NULL AND NEW IS DISTINCT FROM OLD
       AND NOT (NEW.version = OLD.version + 1
                AND EXISTS (SELECT 1 FROM cloud_task_deletions d WHERE d.task_id = OLD.id AND d.accepted_version = NEW.version)
                AND (to_jsonb(NEW) - ARRAY['version','updated_at']) = (to_jsonb(OLD) - ARRAY['version','updated_at'])) THEN"""


def _change_guard(old, new):
    connection = op.get_bind()
    definition = connection.scalar(sa.text("SELECT pg_get_functiondef('hypertest_guard_cloud_history()'::regprocedure)"))
    if definition.count(old) != 1:
        raise RuntimeError("Unexpected Cloud history guard; refusing to change it")
    connection.exec_driver_sql(definition.replace(old, new))


def upgrade():
    op.execute("""CREATE TABLE cloud_task_deletions (
        task_id uuid PRIMARY KEY, project_id uuid NOT NULL, deleted_at timestamptz NOT NULL,
        deleted_by varchar(255) NOT NULL, accepted_version bigint NOT NULL CHECK (accepted_version > 1),
        FOREIGN KEY (project_id, task_id) REFERENCES cloud_tasks (project_id, id) ON DELETE RESTRICT
    )""")
    op.execute("""CREATE TRIGGER cloud_task_deletions_immutable BEFORE UPDATE OR DELETE ON cloud_task_deletions
        FOR EACH ROW EXECUTE FUNCTION hypertest_guard_cloud_history()""")
    _change_guard(_OLD, _NEW)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM cloud_task_deletions)")):
        raise RuntimeError("Cloud Task deletion history must be retained")
    _change_guard(_NEW, _OLD)
    op.execute("DROP TABLE cloud_task_deletions")
