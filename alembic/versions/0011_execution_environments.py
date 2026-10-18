"""Freeze controlled Runner environments without reinterpreting old inputs.

Revision ID: 0011_execution_environments
Revises: 0010_mission_activity
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_execution_environments"
down_revision = "0010_mission_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows retain NULL. The existing whole-row immutable trigger also
    # protects this column, with no historical hash or binding backfill.
    op.add_column("source_snapshots", sa.Column("environment_definition", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_source_environment_binding", "source_snapshots",
        "environment_definition IS NULL OR COALESCE(("
        "jsonb_typeof(environment_definition) = 'object' "
        "AND environment_definition->>'schema_version' = 'hypertest.environment/v1' "
        "AND environment_definition->>'image_id' ~ '^sha256:[0-9a-f]{64}$' "
        "AND environment_definition->>'dependency_lock_sha256' ~ '^[0-9a-f]{64}$' "
        "AND environment_definition->>'launcher_sha256' ~ '^[0-9a-f]{64}$' "
        "AND jsonb_typeof(environment_definition->'dependencies') = 'object' "
        "AND jsonb_typeof(environment_definition->'request') = 'object' "
        "AND environment_definition->>'image_os' = 'linux' "
        "AND length(environment_definition->>'image_architecture') > 0 "
        "AND environment_definition->'request'->>'profile_id' IN ('python-pytest-v1','python-api-v1') "
        "AND environment_definition ?& ARRAY['schema_version','image_id','image_os',"
        "'image_architecture','dependency_lock_sha256','launcher_sha256','dependencies','request']), false)",
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM source_snapshots WHERE environment_definition IS NOT NULL)"
    )):
        raise RuntimeError("bound environment history prevents destructive downgrade")
    op.drop_constraint("ck_source_environment_binding", "source_snapshots", type_="check")
    op.drop_column("source_snapshots", "environment_definition")
