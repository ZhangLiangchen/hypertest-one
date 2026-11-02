"""Freeze a separate, immutable execution manifest for explicit retries."""
from alembic import op

revision = "0042_attempt_manifest"
down_revision = "0041_cloud_live_questions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE cloud_attempts ADD COLUMN execution_manifest jsonb")
    op.execute("""CREATE FUNCTION hypertest_guard_attempt_execution_manifest() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.execution_manifest IS DISTINCT FROM OLD.execution_manifest THEN
        RAISE EXCEPTION 'attempt execution manifest is immutable';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_attempt_execution_manifest BEFORE UPDATE ON cloud_attempts
      FOR EACH ROW EXECUTE FUNCTION hypertest_guard_attempt_execution_manifest()""")


def downgrade():
    op.execute("DROP TRIGGER guard_attempt_execution_manifest ON cloud_attempts")
    op.execute("DROP FUNCTION hypertest_guard_attempt_execution_manifest()")
    op.execute("ALTER TABLE cloud_attempts DROP COLUMN execution_manifest")
