"""Protect immutable input snapshots and dispatched Mission contracts.

Revision ID: 0006_immutable_contracts
Revises: 0005_delivery
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_immutable_contracts"
down_revision = "0005_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guards apply to existing history without changing any snapshot or contract.
    op.execute(
        sa.text("""
CREATE FUNCTION hypertest_guard_input_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '% is immutable; preserve input history', TG_TABLE_NAME;
    END IF;
    IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION '% is immutable; create a new snapshot', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END;
$$;
""")
    )
    for table in ("source_snapshots", "policy_snapshots"):
        op.execute(
            sa.text(f"""
CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION hypertest_guard_input_snapshot();
""")
        )
    op.execute(
        sa.text("""
CREATE FUNCTION hypertest_guard_mission_contract() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status != 'CREATED' THEN
            RAISE EXCEPTION 'mission contract is immutable; preserve mission history';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status != 'CREATED' THEN
        IF NEW.status = 'CREATED' THEN
            RAISE EXCEPTION 'mission contract is immutable; cannot return to CREATED';
        END IF;
        IF jsonb_build_array(NEW.id, NEW.key, NEW.test_run_id, NEW.mission_type,
                NEW.priority, NEW.objective, NEW.protocol_version, NEW.spec::jsonb,
                NEW.spec_sha256, NEW.idempotency_key, NEW.created_by, NEW.created_at)
           IS DISTINCT FROM
           jsonb_build_array(OLD.id, OLD.key, OLD.test_run_id, OLD.mission_type,
                OLD.priority, OLD.objective, OLD.protocol_version, OLD.spec::jsonb,
                OLD.spec_sha256, OLD.idempotency_key, OLD.created_by, OLD.created_at) THEN
            RAISE EXCEPTION 'mission contract is immutable; cancel and create a new mission';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
""")
    )
    op.execute(
        sa.text("""
CREATE TRIGGER mission_contract_immutable BEFORE UPDATE OR DELETE ON missions
    FOR EACH ROW EXECUTE FUNCTION hypertest_guard_mission_contract();
""")
    )


def downgrade() -> None:
    # Reversing this migration only removes guards; canonical history is preserved.
    op.execute(sa.text("DROP TRIGGER mission_contract_immutable ON missions"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_mission_contract()"))
    for table in ("source_snapshots", "policy_snapshots"):
        op.execute(sa.text(f"DROP TRIGGER {table}_immutable ON {table}"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_input_snapshot()"))
