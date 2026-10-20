"""New MCP submissions keep their frozen budget on the original managed path."""
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from test_persistent_runtime import binding_rows
from test_persistent_runtime import runtime_context as _runtime_context
from test_snapshot_harness import source_snapshot as _source_snapshot

from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveIntegrationGrant,
    InteractiveSubmissionReceipt,
    RunExecutionSelection,
)
from hypertest.domain.jobs import JobStatus
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.worker import run_claimed_job

runtime_context = _runtime_context
source_snapshot = _source_snapshot


async def test_cloud_managed_worker_uses_submission_budget_instead_of_server_default(runtime_context, monkeypatch):
    context = runtime_context
    monkeypatch.setattr(get_settings(), "harness_max_seconds", 1200)
    async with AsyncSessionLocal() as db:
        run = await db.get(CanonicalRun, context["run_id"])
        actor = InteractiveActorIdentity(actor_ref="budget-" + uuid4().hex, registered_by="fixture")
        db.add(actor)
        await db.flush()
        client_id = uuid4()
        db.add(InteractiveClientRegistration(actor_identity_id=actor.id,
            client_instance_id=client_id, registered_by="fixture"))
        await db.flush()
        clock = await db.scalar(select(func.clock_timestamp()))
        grant = InteractiveIntegrationGrant(actor_identity_id=actor.id, client_instance_id=client_id,
            project_id=run.project_id, scopes=["task:submit"], token_hash=uuid4().hex + uuid4().hex,
            registered_by="fixture", not_before=clock, expires_at=clock + timedelta(hours=1))
        db.add(grant)
        db.add(RunExecutionSelection(test_run_id=run.id, execution_mode="CLOUD",
            execution_driver="PLATFORM_MANAGED", harness_mode="SERVER_HOST",
            harness_host_id=get_settings().bridge_host_id))
        await db.flush()
        db.add(InteractiveSubmissionReceipt(grant_id=grant.id, actor_identity_id=actor.id,
            client_instance_id=client_id, project_id=run.project_id, submission_key="frozen-budget",
            input_digest="a" * 64, input_manifest={"budget": {"harness_budget_seconds": 17}},
            status="ACCEPTED", test_run_id=run.id, initial_durable_job_id=context["job"].id))
        await db.commit()
    finished = await run_claimed_job(context["job"])
    assert finished.status is JobStatus.WAITING_INPUT
    async with AsyncSessionLocal() as db:
        _, _, state = await binding_rows(db, context)
        assert state.harness_budget_seconds == 17
        assert len(context["bridge"].started) == 1
