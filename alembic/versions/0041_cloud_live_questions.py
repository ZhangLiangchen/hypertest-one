"""Add fenced live SDK question state, separate from paused input."""
from alembic import op

revision = "0041_cloud_live_questions"
down_revision = "0040_cloud_agent_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloud_live_questions (
        id uuid PRIMARY KEY, created_at timestamptz NOT NULL,
        project_id uuid NOT NULL, task_id uuid NOT NULL, attempt_id uuid NOT NULL,
        generation bigint NOT NULL CHECK (generation > 0),
        request_id varchar(255) NOT NULL, session_id varchar(255) NOT NULL, request_digest varchar(64) NOT NULL,
        questions jsonb NOT NULL, status varchar(16) NOT NULL
          CHECK (status IN ('OPEN','ANSWERED','DELIVERING','DELIVERED','CANCELLED','UNKNOWN')),
        expires_at timestamptz NOT NULL, answer jsonb,
        answer_operation_key varchar(128), answer_digest varchar(64), answered_by varchar(255),
        FOREIGN KEY (project_id, task_id) REFERENCES cloud_tasks(project_id, id) ON DELETE RESTRICT,
        FOREIGN KEY (task_id, attempt_id) REFERENCES cloud_attempts(task_id, id) ON DELETE RESTRICT,
        FOREIGN KEY (project_id, attempt_id) REFERENCES cloud_attempts(project_id, id) ON DELETE RESTRICT,
        CHECK (((answer IS NULL AND answer_operation_key IS NULL AND answer_digest IS NULL AND answered_by IS NULL)
             OR (answer IS NOT NULL AND answer_operation_key IS NOT NULL AND answer_digest IS NOT NULL AND answered_by IS NOT NULL))
             AND (status NOT IN ('ANSWERED','DELIVERING','DELIVERED') OR answer IS NOT NULL)
             AND (status <> 'OPEN' OR answer IS NULL)),
        UNIQUE (project_id, answer_operation_key),
        UNIQUE (attempt_id, generation, request_id)
    )""")
    op.execute("CREATE INDEX ix_cloud_live_questions_task ON cloud_live_questions (project_id, task_id, created_at)")


def downgrade():
    op.execute("DROP TABLE cloud_live_questions")
