"""Admit the isolated HTTP-test profile without changing existing bindings.

Revision ID: 0012_api_environment_v2
Revises: 0011_execution_environments
"""
import sqlalchemy as sa

from alembic import op

revision = "0012_api_environment_v2"
down_revision = "0011_execution_environments"
branch_labels = None
depends_on = None


def _constraint(profiles: str) -> str:
    return (
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
        f"AND environment_definition->'request'->>'profile_id' IN ({profiles}) "
        "AND environment_definition ?& ARRAY['schema_version','image_id','image_os',"
        "'image_architecture','dependency_lock_sha256','launcher_sha256','dependencies','request']), false)"
    )


def _replace(profiles: str) -> None:
    op.drop_constraint("ck_source_environment_binding", "source_snapshots", type_="check")
    op.create_check_constraint("ck_source_environment_binding", "source_snapshots", _constraint(profiles))


def upgrade() -> None:
    _replace("'python-pytest-v1','python-api-v1','python-api-v2'")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM source_snapshots "
        "WHERE environment_definition->'request'->>'profile_id' = 'python-api-v2')"
    )):
        raise RuntimeError("API v2 environment history prevents destructive downgrade")
    _replace("'python-pytest-v1','python-api-v1'")
