"""Protect operator-issued original-action observation authorizations."""
import sqlalchemy as sa

from alembic import op

revision = "0038_action_recovery"
down_revision = "0037_cloud_action_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
    CREATE FUNCTION hypertest_guard_action_recovery_receipt() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.operation = 'AUTHORIZE_ACTION_OBSERVATION'
         OR (TG_OP = 'UPDATE' AND NEW.operation = 'AUTHORIZE_ACTION_OBSERVATION') THEN
        RAISE EXCEPTION 'Cloud action recovery authorizations are immutable';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END;
    $$
    """))
    op.execute(sa.text("""CREATE TRIGGER cloud_action_recovery_receipt_guard
        BEFORE UPDATE OR DELETE ON cloud_operation_receipts FOR EACH ROW
        EXECUTE FUNCTION hypertest_guard_action_recovery_receipt()"""))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM cloud_operation_receipts WHERE operation = 'AUTHORIZE_ACTION_OBSERVATION')")):
        raise RuntimeError("Cloud action recovery authorization history must be retained")
    op.execute(sa.text("DROP TRIGGER cloud_action_recovery_receipt_guard ON cloud_operation_receipts"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_action_recovery_receipt()"))
