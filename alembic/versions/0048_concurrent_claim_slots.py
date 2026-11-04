"""Independent native Worker slots, retaining every legacy high-water mark."""
from alembic import op

revision = "0048_concurrent_claim_slots"
down_revision = "0047_cloud_conversation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE cloud_worker_claim_states ADD COLUMN slot_id varchar(64) NOT NULL DEFAULT 'legacy'")
    op.execute("ALTER TABLE cloud_worker_claim_states DROP CONSTRAINT cloud_worker_claim_states_pkey")
    op.execute("ALTER TABLE cloud_worker_claim_states ADD PRIMARY KEY (worker_id, slot_id)")
    op.execute("""CREATE OR REPLACE FUNCTION hypertest_guard_worker_claim_state() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'worker claim high-water mark cannot be deleted';
      ELSIF TG_OP = 'INSERT' THEN
        IF NEW.sequence <> 0 THEN
          RAISE EXCEPTION 'worker claim state must start at sequence zero';
        END IF;
      ELSE
        IF NEW.worker_id <> OLD.worker_id OR NEW.slot_id <> OLD.slot_id OR NEW.created_at <> OLD.created_at THEN
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


def downgrade():
    # A single row cannot retain independent slot histories.
    raise RuntimeError("Concurrent Worker claim high-water marks cannot be collapsed")
