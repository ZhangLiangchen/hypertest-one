"""Keep original recovery available after a cancelled task leaves the directory."""
import sqlalchemy as sa

from alembic import op

revision = "0043_deleted_cloud_recovery"
down_revision = "0042_attempt_manifest"
branch_labels = None
depends_on = None

_OLD = """AND (to_jsonb(NEW) - ARRAY['version','updated_at']) = (to_jsonb(OLD) - ARRAY['version','updated_at'])) THEN
      RAISE EXCEPTION 'deleted cloud task is immutable';"""
_NEW = """AND (to_jsonb(NEW) - ARRAY['version','updated_at']) = (to_jsonb(OLD) - ARRAY['version','updated_at']))
       AND NOT (OLD.status = 'RECOVERY_REQUIRED'
                AND NEW.status IN ('RECOVERY_REQUIRED','FAILED','CANCELLED')
                AND NEW.version = OLD.version + 1
                AND (to_jsonb(NEW) - ARRAY['status','version','updated_at']) =
                    (to_jsonb(OLD) - ARRAY['status','version','updated_at'])
                AND EXISTS (SELECT 1 FROM cloud_attempts a WHERE a.id = OLD.latest_attempt_id
                    AND a.checkpoint->>'cancellation_requested' = 'true'
                    AND a.lease_owner IS NULL AND a.lease_token_hash IS NULL AND a.lease_expires_at IS NULL)
                AND NOT EXISTS (SELECT 1 FROM cloud_work_grants g WHERE g.attempt_id = OLD.latest_attempt_id
                    AND g.revoked_at IS NULL)) THEN
      RAISE EXCEPTION 'deleted cloud task is immutable';"""


def _change_guard(old, new):
    connection = op.get_bind()
    definition = connection.scalar(sa.text("SELECT pg_get_functiondef('hypertest_guard_cloud_history()'::regprocedure)"))
    if definition.count(old) != 1:
        raise RuntimeError("Unexpected Cloud history guard; refusing to change it")
    connection.exec_driver_sql(definition.replace(old, new))


def upgrade():
    _change_guard(_OLD, _NEW)


def downgrade():
    if op.get_bind().scalar(sa.text("""SELECT EXISTS (SELECT 1 FROM cloud_task_deletions d
            JOIN cloud_tasks t ON t.id = d.task_id WHERE t.status = 'RECOVERY_REQUIRED'
            OR t.version > d.accepted_version)""")):
        raise RuntimeError("Deleted Cloud recovery requires the recovery guard")
    _change_guard(_NEW, _OLD)
