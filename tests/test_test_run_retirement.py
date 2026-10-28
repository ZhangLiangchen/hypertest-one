"""Retire legacy Run data while preserving unrelated operational domains."""
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_run_bindings import bound_run as bound_run
from test_test_design import create_run

from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.delivery import Evidence
from hypertest.domain.enums import EvidenceType, TrustLevel
from hypertest.domain.harness import RunReport
from hypertest.domain.jobs import DurableJob, JobStatus, JobType, WorkerHeartbeat
from hypertest.domain.local_archive import LocalArchiveTask
from hypertest.domain.memory import MemoryEntry
from hypertest.domain.models import AuditEvent, OutboxEvent, Project
from hypertest.domain.models import TestRun as LegacyTestRun
from hypertest.main import app


async def test_run_execution_api_is_retired():
    run = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        for method, url in (
            ("POST", "/api/v1/test-runs"),
            ("POST", f"/api/v1/projects/{uuid4()}/runs/bootstrap"),
            ("GET", f"/api/v1/test-runs/{run}"),
            ("POST", f"/api/v1/test-runs/{run}/jobs"),
            ("GET", f"/api/v1/test-runs/{run}/reports"),
            ("POST", "/api/v1/interactive/submissions"),
            ("POST", "/api/v1/interactive/executions/bind"),
        ):
            assert (await client.request(method, url, json={})).status_code in (404, 405)
        capabilities = (await client.get("/api/v1/interactive/capabilities")).json()
        assert capabilities["legacy_run_retired"] is True
        assert capabilities["tools"] == capabilities["execution_tools"] == []
        assert (await client.get("/api/v1/health")).status_code == 200


async def test_run_migration_is_scoped_and_refuses_unknown_foreign_keys(bound_run):
    async with AsyncSessionLocal() as db:
        run = await create_run(db)
        project_id, run_id = run.project_id, run.id
        job = DurableJob(key="RETIREJOB-" + uuid4().hex, project_id=project_id, test_run_id=run_id,
                         job_type=JobType.ADVANCE_RUN, status=JobStatus.QUEUED,
                         idempotency_key=str(uuid4()), payload={})
        archive = LocalArchiveTask(project_id=project_id, creator_actor_ref="operator:synthetic",
            title="keep", objective="", version=1, archive_version=1, status="DRAFT", reported_result="NOT_RUN", updated_at=datetime.now(UTC))
        memory = MemoryEntry(project_id=project_id, owner_actor_ref="operator:synthetic", version=1,
                             status="CANDIDATE", source={"mode": "LOCAL_ARCHIVE"})
        evidence = Evidence(key="EV-" + uuid4().hex, test_run_id=run_id, evidence_type=EvidenceType.LOG,
                            trust_level=TrustLevel.AGENT_REPORTED, sha256="a" * 64,
                            collector="synthetic", source="synthetic", artifact_uri="synthetic://report")
        report = RunReport(test_run_id=bound_run["run_id"], binding_id=bound_run["binding_id"],
                           durable_job_id=bound_run["job_id"], idempotency_key="fixture", envelope={},
                           artifact_uri="sha256:"+"a" * 64, content_sha256="a" * 64)
        db.add_all([job, archive, memory, evidence, report])
        await db.flush()
        heartbeat = WorkerHeartbeat(worker_id="synthetic-run-" + uuid4().hex, active_job_id=job.id)
        db.add_all([heartbeat,
            AuditEvent(project_id=project_id, test_run_id=run_id, actor_type="USER", actor_ref="synthetic",
                       action="synthetic", entity_type="TestRun", entity_id=run_id),
            AuditEvent(project_id=project_id, actor_type="USER", actor_ref="synthetic",
                       action="synthetic", entity_type="Project", entity_id=project_id),
            OutboxEvent(aggregate_type="TestRun", aggregate_id=run_id, event_type="synthetic", payload={}),
            OutboxEvent(aggregate_type="Project", aggregate_id=project_id, event_type="synthetic", payload={}),
        ])
        await db.commit()
        archive_id, memory_id, worker_id, evidence_id, report_id = archive.id, memory.id, heartbeat.worker_id, evidence.id, report.id

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0035_retire_legacy_test_runs.py"
    spec = importlib.util.spec_from_file_location("retire_run_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with AsyncSessionLocal() as db:
        conn = await db.connection()
        def apply(sync_conn):
            with Operations.context(MigrationContext.configure(sync_conn)):
                module.upgrade()
        savepoint = await db.begin_nested()
        await db.execute(text("CREATE TABLE unexpected_run_link (run_id UUID REFERENCES test_runs(id))"))
        with pytest.raises(DBAPIError):
            await conn.run_sync(apply)
        await savepoint.rollback()
        assert await db.get(LegacyTestRun, run_id)
        await conn.run_sync(apply)
        assert (await db.execute(text("SELECT count(*) FROM test_runs"))).scalar_one() == 0
        assert (await db.execute(text("SELECT count(*) FROM durable_jobs"))).scalar_one() == 0
        assert not await db.get(Evidence, evidence_id)
        assert not await db.get(RunReport, report_id)
        assert await db.get(Project, project_id)
        assert await db.get(LocalArchiveTask, archive_id)
        assert await db.get(MemoryEntry, memory_id)
        assert (await db.get(WorkerHeartbeat, worker_id)).active_job_id is None
        assert await db.scalar(select(AuditEvent.id).where(AuditEvent.entity_type == "Project", AuditEvent.entity_id == project_id))
        assert not await db.scalar(select(AuditEvent.id).where(AuditEvent.test_run_id == run_id))
        assert await db.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_type == "Project", OutboxEvent.aggregate_id == project_id))
        assert not await db.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_type == "TestRun", OutboxEvent.aggregate_id == run_id))
        for table, constraint in (("audit_events", "audit_events_test_run_id_fkey"),
                                  ("worker_heartbeats", "worker_heartbeats_active_job_id_fkey"),
                                  ("connector_requests", "connector_requests_dispatch_grant_id_fkey")):
            assert (await db.execute(text("SELECT count(*) FROM pg_constraint WHERE conrelid=cast(:table as regclass) AND conname=:name"),
                                     {"table": table, "name": constraint})).scalar_one() == 1
        await db.rollback()
