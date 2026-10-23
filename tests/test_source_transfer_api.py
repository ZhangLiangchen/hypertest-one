"""Real PostgreSQL + HTTPS ASGI receiver tests with real Git fixture objects."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_source_transfer_bundle import prepare
from test_source_transfer_bundle import repository as _repository

from hypertest.api.schemas import ProjectCreate, SourceSnapshotCreate
from hypertest.api.source_transfer_schemas import SourceTransferCreate
from hypertest.application.services import ConflictError, create_project, create_source_snapshot
from hypertest.application.source_transfer import (
    accepted_transfer,
    create_transfer,
    link_snapshot,
)
from hypertest.common.ids import public_key, uuid7
from hypertest.config import get_settings
from hypertest.connector.security import token_hash
from hypertest.connector.source import canonical
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.connector import HarnessDeviceGrant, HarnessNode, NodeProjectCapability
from hypertest.domain.source_transfer import SourceBundleTransfer, SourceTransferSnapshot
from hypertest.main import app

repository = _repository


@pytest.fixture
async def transfer_fixture(repository, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "connector_operator_key", "test-source-operator")
    # Production mounts these as siblings. Nesting Artifact Store under the
    # workspace would hide an incorrectly placed accepted source checkout.
    monkeypatch.setattr(get_settings(), "workspace_root", str(tmp_path / "workspaces"))
    _, _, local = prepare(repository, tmp_path)
    wire = json.loads(local.bundle_path.read_bytes())
    # Origin authenticity is delegated to the authorized fixture adapter; these
    # tests independently check bytes, device identity and project source role.
    origin = "https://approved-source.example.invalid/team/private.git"
    wire["manifest"]["origin"] = origin
    content = canonical(wire)
    token = "source-device-" + uuid4().hex
    async with AsyncSessionLocal() as db:
        project = await create_project(db, ProjectCreate(key=public_key("SRC"), name="Source transfer fixture", repository_url=origin))
        node = HarnessNode(id=uuid7(), node_key="source-fixture-" + uuid4().hex, display_name="Fixture", owner_identity_id="fixture-operator")
        db.add(node)
        await db.flush()
        device = HarnessDeviceGrant(id=uuid7(), node_id=node.id, token_hash=token_hash(token), key_version="fixture-v1",
            operator_identity_id="fixture-operator", not_before=datetime.now(UTC)-timedelta(seconds=1), expires_at=datetime.now(UTC)+timedelta(hours=1))
        scope = NodeProjectCapability(id=uuid7(),node_id=node.id, project_id=project.id, capability="source_acquisition",
            constraints={"allowed_origins":[origin]}, policy_version="fixture-v1",operator_identity_id="fixture-operator")
        db.add_all([device,scope])
        await db.commit()
        payload = SourceTransferCreate(request_id=uuid7(),node_id=node.id,idempotency_key="fixture-"+uuid4().hex,
            origin=origin,commit_sha=wire["manifest"]["commit_sha"],policy_version="fixture-v1")
        row = await create_transfer(db, project.id, payload)
        receipt = {"transfer_id":str(row.id),"request_id":str(row.request_id),"project_id":str(project.id),
            "node_id":str(node.id),"origin":origin,"ref":None,"commit_sha":row.commit_sha,"policy_version":"fixture-v1",
            "root_tree":wire["manifest"]["root_tree"],"bundle_sha256":hashlib.sha256(content).hexdigest(),
            "bundle_size":len(content),"result":"ACQUIRED"}
        return {"row_id":row.id,"project_id":project.id,"node_id":node.id,"scope_id":scope.id,"device_id":device.id,
                "payload":payload,"receipt":receipt,"content":content,"token":token,"origin":origin}


async def authorize(client, fixture):
    return await client.post(f"/api/v1/source-transfers/{fixture['row_id']}/authorize-upload",
        headers={"Authorization":"Bearer "+fixture["token"]},json=fixture["receipt"])


@pytest.mark.asyncio
async def test_authenticated_https_source_acceptance_and_immutable_snapshot_receipt(transfer_fixture):
    f = transfer_fixture
    async with AsyncClient(transport=ASGITransport(app=app),base_url="https://localhost") as client:
        assert (await client.get(f"/api/v1/source-transfers/{f['row_id']}")).status_code == 401
        assert (await client.post(f"/api/v1/source-transfers/{f['row_id']}/authorize-upload",json=f['receipt'])).status_code == 401
        upload = await authorize(client,f)
        assert upload.status_code == 200, upload.text
        headers = {"Authorization":"Bearer "+f["token"],"X-Source-Upload-Token":upload.json()["upload_token"]}
        accepted = await client.put(f"/api/v1/source-transfers/{f['row_id']}/content",headers=headers,content=f["content"])
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "ACCEPTED"
        assert accepted.json()["bundle_sha256"] == f["receipt"]["bundle_sha256"]
        replay = await client.put(f"/api/v1/source-transfers/{f['row_id']}/content",headers=headers,content=f["content"])
        assert replay.status_code == 200 and replay.json() == accepted.json()
    async with AsyncSessionLocal() as db:
        row = await accepted_transfer(db,f['row_id'],f['project_id'],f['node_id'],f['origin'],f['receipt']['commit_sha'])
        assert Path(row.server_workspace,"app.py").read_text() == "print('pinned')\n"
        assert Path(row.server_workspace).parent == Path(get_settings().workspace_root) / ".hypertest-source-checkouts"
        assert Path(row.bundle_path).is_relative_to(Path(get_settings().artifact_root))
        assert not Path(row.server_workspace).is_relative_to(Path(get_settings().artifact_root))
        snapshot = await create_source_snapshot(db, f['project_id'],SourceSnapshotCreate(repository_url=f['origin'],
            commit_sha=f['receipt']['commit_sha'],prd_sha256='a'*64,configuration_sha256='b'*64))
        await link_snapshot(db,row,snapshot.id)
        await db.commit()
        snapshot_id = snapshot.id
        assert await db.get(SourceTransferSnapshot,(row.id,snapshot_id)) is not None
        # SQL guards enforce history even if an application path is bypassed.
        with pytest.raises(DBAPIError,match="identity is immutable"):
            await db.execute(text("UPDATE source_bundle_transfers SET commit_sha=:sha WHERE id=:id"),{"sha":"c"*40,"id":f["row_id"]})
            await db.commit()
        await db.rollback()
        with pytest.raises(DBAPIError,match="append-only"):
            await db.execute(text("DELETE FROM source_transfer_snapshots WHERE transfer_id=:id"),{"id":f["row_id"]})
            await db.commit()
        await db.rollback()


@pytest.mark.asyncio
async def test_receipt_cannot_cross_device_project_request_or_policy(transfer_fixture):
    f = transfer_fixture
    async with AsyncClient(transport=ASGITransport(app=app),base_url="https://localhost") as client:
        for key, invalid in [("transfer_id",str(uuid4())),("request_id",str(uuid4())),("project_id",str(uuid4())),
                             ("node_id",str(uuid4())),("policy_version","wrong-policy"),("origin","https://other.invalid/repo")]:
            response=await client.post(f"/api/v1/source-transfers/{f['row_id']}/authorize-upload",
                headers={"Authorization":"Bearer "+f['token']},json={**f['receipt'],key:invalid})
            assert response.status_code == 409, (key,response.text)
        assert (await authorize(client,f)).status_code == 200
        assert (await authorize(client,f)).status_code == 409


@pytest.mark.asyncio
async def test_source_role_and_revoke_are_rechecked_after_grant(transfer_fixture):
    f = transfer_fixture
    async with AsyncClient(transport=ASGITransport(app=app),base_url="https://localhost") as client:
        grant=await authorize(client,f)
        assert grant.status_code == 200
        async with AsyncSessionLocal() as db:
            scope=await db.get(NodeProjectCapability,f['scope_id'])
            scope.status,scope.revoked_at,scope.row_version="REVOKED",datetime.now(UTC),scope.row_version+1
            await db.commit()
        response=await client.put(f"/api/v1/source-transfers/{f['row_id']}/content",
            headers={"Authorization":"Bearer "+f['token'],"X-Source-Upload-Token":grant.json()['upload_token']},content=f['content'])
        assert response.status_code == 403
        async with AsyncSessionLocal() as db:
            assert (await db.get(SourceBundleTransfer,f['row_id'])).status == "UPLOADING"


@pytest.mark.asyncio
async def test_digest_and_object_tampering_rejected_and_new_key_retry_only(transfer_fixture):
    f = transfer_fixture
    wire=json.loads(f['content'])
    wire['manifest']['files'][0]['path']='../escape'
    bad=canonical(wire)
    f['receipt']['bundle_size'],f['receipt']['bundle_sha256']=len(bad),hashlib.sha256(bad).hexdigest()
    async with AsyncClient(transport=ASGITransport(app=app),base_url="https://localhost") as client:
        grant=await authorize(client,f)
        assert grant.status_code == 200
        response=await client.put(f"/api/v1/source-transfers/{f['row_id']}/content",
            headers={"Authorization":"Bearer "+f['token'],"X-Source-Upload-Token":grant.json()['upload_token']},content=bad)
        assert response.status_code == 409, response.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(SourceBundleTransfer,f['row_id'])).status == "REJECTED"
        same=await create_transfer(db,f['project_id'],f['payload'])
        assert same.id == f['row_id'] and same.status == "REJECTED"
        conflict=f['payload'].model_copy(update={"commit_sha":"e"*40})
        with pytest.raises(ConflictError,match="immutable inputs"):
            await create_transfer(db,f['project_id'],conflict)
        await db.rollback()
        retry=await create_transfer(db,f['project_id'],f['payload'].model_copy(update={"idempotency_key":"explicit-new-"+uuid4().hex}))
        assert retry.id != f['row_id'] and retry.request_id == f['payload'].request_id


@pytest.mark.asyncio
async def test_https_transport_required_even_for_authenticated_device(transfer_fixture):
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://localhost") as client:
        assert (await authorize(client,transfer_fixture)).status_code == 400


@pytest.mark.asyncio
async def test_device_revoked_during_verification_cannot_accept_cached_identity(transfer_fixture, monkeypatch):
    import asyncio
    import threading

    import hypertest.application.source_transfer as service
    f = transfer_fixture
    loop=asyncio.get_running_loop()
    reached,release=asyncio.Event(),threading.Event()
    original=service.materialize
    def paused(source,target):
        result=original(source,target)
        loop.call_soon_threadsafe(reached.set)
        if not release.wait(10):
            raise RuntimeError("fixture verification pause timed out")
        return result
    monkeypatch.setattr(service,"materialize",paused)
    async with AsyncClient(transport=ASGITransport(app=app),base_url="https://localhost") as client:
        grant=await authorize(client,f)
        assert grant.status_code == 200
        upload=asyncio.create_task(client.put(f"/api/v1/source-transfers/{f['row_id']}/content",
            headers={"Authorization":"Bearer "+f['token'],"X-Source-Upload-Token":grant.json()['upload_token']},content=f['content']))
        try:
            await asyncio.wait_for(reached.wait(),10)
            async with AsyncSessionLocal() as db:
                device=await db.get(HarnessDeviceGrant,f['device_id'])
                device.status,device.revoked_at,device.row_version="REVOKED",datetime.now(UTC),device.row_version+1
                await db.commit()
        finally:
            release.set()
        rejected=await upload
        assert rejected.status_code == 409,rejected.text
    async with AsyncSessionLocal() as db:
        transfer=await db.get(SourceBundleTransfer,f['row_id'])
        assert transfer.status == "REJECTED" and transfer.server_workspace is None and transfer.accepted_at is None


@pytest.mark.parametrize("grant_before_delete", [False, True])
async def test_deleted_project_rejects_existing_source_mutations_but_retains_readback(
        transfer_fixture, grant_before_delete):
    f = transfer_fixture
    operator = {"X-Hypertest-Operator-Key": "test-source-operator"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        grant = await authorize(client, f) if grant_before_delete else None
        if grant is not None:
            assert grant.status_code == 200
        deleted = await client.delete(f"/api/v1/projects/{f['project_id']}", params={"expected_version": 1})
        assert deleted.status_code == 200, deleted.text
        rejected = await authorize(client, f)
        assert rejected.status_code == 403, rejected.text
        dispatch = await client.post(f"/api/v1/source-transfers/{f['row_id']}/dispatch", headers=operator)
        assert dispatch.status_code == 403, dispatch.text
        if grant is not None:
            upload = await client.put(f"/api/v1/source-transfers/{f['row_id']}/content", content=f["content"],
                headers={"Authorization": "Bearer " + f["token"],
                         "X-Source-Upload-Token": grant.json()["upload_token"]})
            assert upload.status_code == 403, upload.text
        original = await client.get(f"/api/v1/source-transfers/{f['row_id']}", headers=operator)
        assert original.status_code == 200 and original.json()["status"] == "UPLOADING"
