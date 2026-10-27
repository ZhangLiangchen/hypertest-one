"""Stable dedicated CLI archive uploaders without rewriting historical identities."""
import sqlalchemy as sa

from alembic import op

revision = "0032_cli_archive_uploader"
down_revision = "0031_cli_authorization"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cli_archive_uploaders",
        sa.Column("operator_ref", sa.String(128), primary_key=True),
        sa.Column("actor_identity_id", sa.UUID(),
                  sa.ForeignKey("interactive_actor_identities.id", ondelete="RESTRICT"),
                  nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""
CREATE TRIGGER cli_archive_uploader_immutable BEFORE UPDATE OR DELETE ON cli_archive_uploaders
FOR EACH ROW EXECUTE FUNCTION reject_cli_receipt_mutation()
""")


def downgrade():
    raise RuntimeError("CLI uploader ownership must be preserved; destructive downgrade is unsupported")
