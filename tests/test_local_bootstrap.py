"""Real PostgreSQL source/Harness admission; environment resolution is a barrier double."""
import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_environment_binding import binding
from test_source_transfer_api import authorize
from test_source_transfer_api import repository as _repository
from test_source_transfer_api import transfer_fixture as _transfer_fixture

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.application import bootstrap, controller
from hypertest.application.services import ConflictError
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.connector import HarnessNode, NodeProjectCapability
from hypertest.domain.jobs import DurableJob
from hypertest.domain.models import SourceSnapshot, utcnow
from hypertest.domain.models import TestRun as CanonicalRun
from hypertest.main import app

repository = _repository
transfer_fixture = _transfer_fixture


@pytest.fixture
async def local_bootstrap_source(transfer_fixture):
    fixture = transfer_fixture
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        authorization = await authorize(client, fixture)
        assert authorization.status_code == 200, authorization.text
        accepted = await client.put(f"/api/v1/source-transfers/{fixture['row_id']}/content",
            headers={"Authorization": "Bearer " + fixture["token"], "X-Source-Upload-Token": authorization.json()["upload_token"]},
            content=fixture["content"])
        assert accepted.status_code == 200, accepted.text
    async with AsyncSessionLocal() as db:
        db.add(NodeProjectCapability(node_id=fixture["node_id"], project_id=fixture["project_id"], capability="harness",
            constraints={}, operator_identity_id="fixture-operator"))
        await db.commit()
    return fixture


def local_request(fixture, **changes):
    return RunBootstrap(repository_url=fixture["origin"], commit_sha=fixture["receipt"]["commit_sha"],
        prd_text="The fixed application prints pinned output.", harness_mode="LOCAL_CONNECTOR",
        harness_node_id=fixture["node_id"], source_bundle_transfer_id=fixture["row_id"],
        idempotency_key="local-bootstrap", **changes)


async def test_source_role_revocation_during_environment_resolution_rejects_freeze(local_bootstrap_source, monkeypatch):
    fixture = local_bootstrap_source
    entered, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(get_settings(), "execution_mode", "direct")

    async def resolve(request):
        entered.set()
        await release.wait()
        return binding(request)

    monkeypatch.setattr(bootstrap, "resolve_environment", resolve)

    async def attempt():
        async with AsyncSessionLocal() as db:
            return await bootstrap.bootstrap_run(db, fixture["project_id"],
                local_request(fixture, environment={"profile_id": "python-pytest-v1"}))

    task = asyncio.create_task(attempt())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        async with AsyncSessionLocal() as db:
            role = await db.get(NodeProjectCapability, fixture["scope_id"])
            role.status, role.revoked_at = "REVOKED", utcnow()
            await db.commit()
        release.set()
        with pytest.raises(RuntimeError, match="(?i)source|capability|authorization|scope"):
            await task
        async with AsyncSessionLocal() as db:
            assert not await db.scalar(select(func.count()).select_from(CanonicalRun).where(CanonicalRun.project_id == fixture["project_id"]))
            assert not await db.scalar(select(func.count()).select_from(SourceSnapshot).where(SourceSnapshot.project_id == fixture["project_id"]))
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_bootstrap_idempotency_freezes_original_local_node_and_source(local_bootstrap_source):
    fixture = local_bootstrap_source
    async with AsyncSessionLocal() as db:
        run = await bootstrap.bootstrap_run(db, fixture["project_id"], local_request(fixture))
        same = await bootstrap.bootstrap_run(db, fixture["project_id"], local_request(fixture))
        assert same.id == run.id
        other = HarnessNode(node_key="alternate-" + uuid7().hex, owner_identity_id="fixture-operator", display_name="Other Mac")
        db.add(other)
        await db.commit()
        changed = local_request(fixture).model_copy(update={"harness_node_id": other.id})
        with pytest.raises(ConflictError, match="different Harness selection"):
            await bootstrap.bootstrap_run(db, fixture["project_id"], changed)
        await db.rollback()
        server = local_request(fixture).model_copy(update={"harness_mode": "SERVER_HOST", "harness_node_id": None,
            "source_bundle_transfer_id": None})
        with pytest.raises(ConflictError, match="different Harness selection"):
            await bootstrap.bootstrap_run(db, fixture["project_id"], server)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(CanonicalRun).where(CanonicalRun.project_id == fixture["project_id"])) == 1


@pytest.mark.parametrize("include_null_profile", [True, False])
async def test_local_api_job_cannot_choose_server_legacy_before_binding(local_bootstrap_source, monkeypatch, include_null_profile):
    fixture = local_bootstrap_source
    monkeypatch.setattr(get_settings(), "harness_mode", "legacy")
    monkeypatch.setattr(get_settings(), "execution_mode", "direct")
    async def forbidden(*args, **kwargs):
        pytest.fail("a local selection must never invoke the server compatibility controller")
    monkeypatch.setattr(controller, "advance_run", forbidden)
    async with AsyncSessionLocal() as db:
        run = await bootstrap.bootstrap_run(db, fixture["project_id"], local_request(fixture))
        run_id = run.id
    payload = {"workspace": "."}
    if include_null_profile:
        payload["execution_profile"] = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        response = await client.post(f"/api/v1/test-runs/{run_id}/jobs", json={
            "operation": "ADVANCE_RUN", "idempotency_key": "reject-local-legacy", "payload": payload})
        assert response.status_code in {202, 409}, response.text
        if response.status_code == 202:
            job = response.json()
            assert job["payload"]["execution_profile"] == "run-persistent-harness/v1"
            # The fixture Worker is not running. Cancel only this test's queued
            # task through the real API so no active work remains after the test.
            cancelled = await client.post(f"/api/v1/jobs/{job['id']}/cancel")
            assert cancelled.status_code == 202, cancelled.text
        else:
            async with AsyncSessionLocal() as db:
                assert not await db.scalar(select(func.count()).select_from(DurableJob).where(DurableJob.test_run_id == run_id))


async def test_local_selection_rejects_manual_api_and_direct_legacy_controller(local_bootstrap_source, monkeypatch):
    fixture = local_bootstrap_source
    monkeypatch.setattr(get_settings(), "harness_mode", "legacy")
    monkeypatch.setattr(get_settings(), "execution_mode", "direct")
    async def forbidden(*args, **kwargs):
        pytest.fail("manual local request reached legacy Agent, Runner, or planner")
    monkeypatch.setattr("hypertest.api.delivery_routes.advance_run", forbidden)
    monkeypatch.setattr("hypertest.api.routes.plan_next_mission", forbidden)
    monkeypatch.setattr(controller.DockerRunner, "fingerprint", forbidden)
    monkeypatch.setattr(controller, "execute_mission", forbidden)
    async with AsyncSessionLocal() as db:
        run = await bootstrap.bootstrap_run(db, fixture["project_id"], local_request(fixture))
        run_id = run.id
        with pytest.raises(ConflictError, match="cannot use the server compatibility controller"):
            await controller.advance_run(db, run.id, workspace=".")
        await db.rollback()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        advanced = await client.post(f"/api/v1/test-runs/{run_id}/advance", json={"workspace": ".", "execution_profile": None})
        assert advanced.status_code == 409, advanced.text
        planned = await client.post(f"/api/v1/test-runs/{run_id}/plan-next")
        assert planned.status_code == 409, planned.text


async def test_sibling_artifact_and_workspace_roots_admit_local_first_binding(local_bootstrap_source, monkeypatch):
    """Real HTTPS acceptance, bootstrap, queue and Worker; fake only node I/O."""
    from test_persistent_runtime import FakeBridge
    from test_run_bindings import own_job

    from hypertest.application import persistent
    from hypertest.application.jobs import cancel_job
    from hypertest.application.persistent_workspace import workspace_path
    from hypertest.domain.bindings import RunExecutionBinding
    from hypertest.domain.connector import RunHarnessPlacement
    from hypertest.domain.harness import RunHarnessState
    from hypertest.domain.harness_selection import RunHarnessSelection
    from hypertest.domain.jobs import JobStatus
    from hypertest.domain.source_transfer import SourceBundleTransfer
    from hypertest.harness_bridge.protocol import PROFILE
    from hypertest.worker import run_claimed_job

    fixture = local_bootstrap_source
    settings = get_settings()
    assert Path(settings.artifact_root).parent == Path(settings.workspace_root).parent
    assert Path(settings.artifact_root) != Path(settings.workspace_root)
    bridge = FakeBridge()
    installs = []

    async def run_client(db, run_id):
        selection = await db.get(RunHarnessSelection, run_id)
        node = await db.get(HarnessNode, selection.node_id)
        return bridge, node.node_key, selection

    async def capabilities():
        async with AsyncSessionLocal() as db:
            node = await db.get(HarnessNode, fixture["node_id"])
            return {"profile": PROFILE, "host_id": node.node_key}

    async def request(operation, payload, *, management=False):
        assert operation == "install_workspace" and payload["create"] is True and not management
        installs.append(payload)
        return {"installed": True}

    async def fingerprint(_):
        return "controlled-runner-preflight-test-double"

    async def cleanup(*args, **kwargs):
        return {}

    bridge.capabilities, bridge.request = capabilities, request
    monkeypatch.setattr(persistent, "run_client", run_client)
    monkeypatch.setattr(persistent.DockerRunner, "fingerprint", fingerprint)
    monkeypatch.setattr("hypertest.worker.cleanup_job_resources", cleanup)
    monkeypatch.setattr(settings, "execution_mode", "direct")
    monkeypatch.setattr(settings, "harness_mode", "bridge")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        created = await client.post(f"/api/v1/projects/{fixture['project_id']}/runs/bootstrap",
            json=local_request(fixture).model_dump(mode="json"))
        assert created.status_code == 201, created.text
        run_id = UUID(created.json()["id"])
        queued = await client.post(f"/api/v1/test-runs/{run_id}/jobs", json={"operation": "ADVANCE_RUN",
            "idempotency_key": "sibling-roots-first-binding", "payload": {"execution_profile": PROFILE,
                "prepare_workspace": True, "backend": "docker"}})
        assert queued.status_code == 202, queued.text
        job_id = UUID(queued.json()["id"])
    async with AsyncSessionLocal() as db:
        job = await db.get(DurableJob, job_id)
        await own_job(db, job)
    result = await run_claimed_job(job)
    assert result.status is JobStatus.WAITING_INPUT, (result.error_code, result.error_message)
    async with AsyncSessionLocal() as db:
        binding = await db.scalar(select(RunExecutionBinding).where(RunExecutionBinding.test_run_id == run_id))
        state = await db.get(RunHarnessState, binding.id)
        placement = await db.scalar(select(RunHarnessPlacement).where(RunHarnessPlacement.binding_id == binding.id))
        transfer = await db.get(SourceBundleTransfer, fixture["row_id"])
        assert placement.node_id == fixture["node_id"]
        assert state.source_workspace == transfer.server_workspace
        assert Path(state.source_workspace).is_relative_to(Path(settings.workspace_root))
        assert not Path(state.source_workspace).is_relative_to(Path(settings.artifact_root))
        assert workspace_path(binding.workspace_id).joinpath("app.py").read_text() == "print('pinned')\n"
        assert len(installs) == len(bridge.created) == len(bridge.started) == 1
        await cancel_job(db, job_id)
