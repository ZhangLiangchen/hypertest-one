"""Allow explicit task status management without publishing a summary."""
import sqlalchemy as sa

from alembic import op

revision = "0045_local_archive_status"
down_revision = "0044_cloud_worker_claim_state"
branch_labels = None
depends_on = None

NAME = "ck_archive_management_operation"
LEGACY_OPERATIONS = "'CREATE','UPDATE','SUBTASK_CREATE','AUTHORIZE','PUBLISH'"


def upgrade():
    checks = [check for check in sa.inspect(op.get_bind()).get_check_constraints("local_archive_operations")
              if "operation" in check["sqltext"] and "PUBLISH" in check["sqltext"]]
    if len(checks) != 1:
        raise RuntimeError("Expected one archive management operation constraint")
    op.drop_constraint(checks[0]["name"], "local_archive_operations", type_="check")
    op.create_check_constraint(NAME, "local_archive_operations", f"operation IN ({LEGACY_OPERATIONS},'UPDATE_STATUS')")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM local_archive_operations WHERE operation='UPDATE_STATUS')")):
        raise RuntimeError("Status management history prevents incompatible downgrade")
    op.drop_constraint(NAME, "local_archive_operations", type_="check")
    op.create_check_constraint(NAME, "local_archive_operations", f"operation IN ({LEGACY_OPERATIONS})")
