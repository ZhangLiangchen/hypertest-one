"""Add ephemeral, non-secret Cloud Worker authentication observations."""
from alembic import op

revision = "0040_cloud_agent_auth"
down_revision = "0039_cloud_task_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloud_agent_auth_observations (
        worker_id varchar(64) PRIMARY KEY,
        status varchar(16) NOT NULL CHECK (status IN ('VALID','INVALID','UNKNOWN')),
        checked_at timestamptz NOT NULL
    )""")


def downgrade():
    op.execute("DROP TABLE cloud_agent_auth_observations")
