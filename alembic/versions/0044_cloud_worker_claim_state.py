"""Bounded, monotonic native Worker claim recovery without saved capabilities."""
import sqlalchemy as sa

from alembic import op

revision = "0044_cloud_worker_claim_state"
down_revision = "0043_deleted_cloud_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloud_worker_claim_states (
      worker_id varchar(128) PRIMARY KEY,
      sequence bigint NOT NULL CHECK (sequence >= 0),
      request_key varchar(128), request_digest varchar(64),
      kind varchar(16) NOT NULL CHECK (kind IN ('EMPTY','ATTEMPT','RESOLUTION','ABANDONED')),
      closed boolean NOT NULL,
      project_id uuid, task_id uuid, attempt_id uuid, resolution_id uuid, generation bigint,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      FOREIGN KEY (project_id, task_id) REFERENCES cloud_tasks(project_id, id) ON DELETE RESTRICT,
      FOREIGN KEY (task_id, attempt_id) REFERENCES cloud_attempts(task_id, id) ON DELETE RESTRICT,
      FOREIGN KEY (task_id, resolution_id) REFERENCES cloud_input_resolutions(task_id, id) ON DELETE RESTRICT,
      CHECK ((sequence = 0 AND request_key IS NULL AND request_digest IS NULL AND kind = 'EMPTY' AND closed)
        OR (sequence > 0 AND request_key IS NOT NULL AND request_digest IS NOT NULL AND request_digest ~ '^[a-f0-9]{64}$')),
      CHECK ((kind IN ('EMPTY','ABANDONED') AND closed AND project_id IS NULL AND task_id IS NULL
          AND attempt_id IS NULL AND resolution_id IS NULL AND generation IS NULL)
        OR (kind = 'ATTEMPT' AND project_id IS NOT NULL AND task_id IS NOT NULL AND attempt_id IS NOT NULL
          AND resolution_id IS NULL AND generation IS NOT NULL AND generation > 0)
        OR (kind = 'RESOLUTION' AND project_id IS NOT NULL AND task_id IS NOT NULL AND attempt_id IS NULL
          AND resolution_id IS NOT NULL AND generation IS NOT NULL AND generation = 1))
    )""")
    op.execute("""CREATE FUNCTION hypertest_guard_worker_claim_state() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'worker claim high-water mark cannot be deleted';
      ELSIF TG_OP = 'INSERT' THEN
        IF NEW.sequence <> 0 THEN
          RAISE EXCEPTION 'worker claim state must start at sequence zero';
        END IF;
      ELSE
        IF NEW.worker_id <> OLD.worker_id OR NEW.created_at <> OLD.created_at THEN
          RAISE EXCEPTION 'worker claim identity is immutable';
        END IF;
        IF NEW.sequence = OLD.sequence THEN
          IF (to_jsonb(NEW) - ARRAY['closed','updated_at']) <> (to_jsonb(OLD) - ARRAY['closed','updated_at'])
              OR (OLD.closed AND NOT NEW.closed) THEN
            RAISE EXCEPTION 'original worker claim cannot change or reopen';
          END IF;
        ELSIF NEW.sequence <> OLD.sequence + 1 OR NOT OLD.closed THEN
          RAISE EXCEPTION 'worker claim sequence must advance once from a closed claim';
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_worker_claim_state BEFORE INSERT OR UPDATE OR DELETE
      ON cloud_worker_claim_states FOR EACH ROW EXECUTE FUNCTION hypertest_guard_worker_claim_state()""")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM cloud_worker_claim_states WHERE sequence > 0)")):
        raise RuntimeError("Worker claim high-water marks cannot be discarded by downgrade")
    op.execute("DROP TABLE cloud_worker_claim_states")
    op.execute("DROP FUNCTION hypertest_guard_worker_claim_state()")
