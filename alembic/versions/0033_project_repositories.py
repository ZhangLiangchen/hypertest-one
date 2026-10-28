"""Project repository roles and immutable Local task source selections."""
import sqlalchemy as sa

from alembic import op

revision = "0033_project_repositories"
down_revision = "0032_cli_archive_uploader"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("test_framework_repository_url", sa.Text(), nullable=True))
    op.add_column("local_archive_tasks", sa.Column("sut_repository_url", sa.Text(), nullable=True))
    op.add_column("local_archive_tasks", sa.Column("test_framework_repository_url", sa.Text(), nullable=True))
    op.add_column("local_archive_tasks", sa.Column("sut_branch", sa.String(255), nullable=True))
    op.add_column("local_archive_tasks", sa.Column("framework_branch", sa.String(255), nullable=True))
    op.execute("""
        CREATE FUNCTION hypertest_guard_archive_task_sources() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.sut_repository_url IS DISTINCT FROM OLD.sut_repository_url
            OR NEW.test_framework_repository_url IS DISTINCT FROM OLD.test_framework_repository_url
            OR NEW.sut_branch IS DISTINCT FROM OLD.sut_branch
            OR NEW.framework_branch IS DISTINCT FROM OLD.framework_branch THEN
              RAISE EXCEPTION 'Local archive task sources are immutable';
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER archive_task_sources_guard BEFORE UPDATE ON local_archive_tasks
        FOR EACH ROW EXECUTE FUNCTION hypertest_guard_archive_task_sources()
    """)


def downgrade():
    raise RuntimeError("Project and task source history must be preserved; destructive downgrade is unsupported")
