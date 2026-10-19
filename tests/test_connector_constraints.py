"""Real PostgreSQL device scopes and real WebSocket durable-mailbox delivery."""
import asyncio
import socket
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_run_bindings import bound_run as _server_bound_run
from websockets.asyncio.client import connect

from hypertest.config import get_settings
from hypertest.connector.client import RemoteBridgeClient
from hypertest.connector.protocol import TRANSPORT, digest
from hypertest.connector.security import authenticate_device
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.connector import ConnectorRequest, HarnessDeviceGrant, HarnessNode
from hypertest.harness_bridge.protocol import PROFILE, PROTOCOL, BridgeError
from hypertest.main import app

server_bound_run = _server_bound_run


@pytest.fixture
async def paired_device(monkeypatch):
    monkeypatch.setattr(get_settings(),'connector_operator_key','test-operator-key')
    monkeypatch.setattr(get_settings(),'connector_allow_insecure_loopback',True)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://localhost') as client:
        response=await client.post('/api/v1/harness-nodes/pair',headers={'X-Hypertest-Operator-Key':'test-operator-key'},
            json={'node_key':'test-node-'+uuid4().hex,'display_name':'Test Mac'})
        assert response.status_code==201,response.text
        yield response.json()


async def test_device_pair_requires_explicit_operator_and_preserves_only_hash(paired_device):
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://localhost') as client:
        assert (await client.get('/api/v1/harness-nodes')).status_code==401
        response=await client.get('/api/v1/harness-nodes',headers={'X-Hypertest-Operator-Key':'test-operator-key'})
        assert paired_device['device_token'] not in response.text and 'token_hash' not in response.text
    async with AsyncSessionLocal() as db:
        node,grant=await authenticate_device(db,paired_device['device_token'])
        assert str(node.id)==paired_device['node']['id']
        assert len(grant.token_hash)==64 and grant.token_hash!=paired_device['device_token']
        assert grant.operator_identity_id=='local-operator'


async def test_device_rotation_revokes_old_execution_but_retains_cleanup_identity(paired_device):
    node_id=paired_device['node']['id']
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://localhost') as client:
        response=await client.post(f'/api/v1/harness-nodes/{node_id}/rotate',
            headers={'X-Hypertest-Operator-Key':'test-operator-key'},json={'expires_in_days':1})
        assert response.status_code==200,response.text
        fresh=response.json()
    async with AsyncSessionLocal() as db:
        with pytest.raises(BridgeError,match='DEVICE_AUTHORIZATION_REVOKED'):
            await authenticate_device(db,paired_device['device_token'])
        node,old=await authenticate_device(db,paired_device['device_token'],allow_revoked=True)
        assert old.status=='REVOKED'
        assert (await authenticate_device(db,fresh['device_token']))[0].id==node.id


async def test_device_identity_and_revocation_are_database_protected(paired_device):
    from uuid import UUID
    async with AsyncSessionLocal() as db:
        node=await db.get(HarnessNode,UUID(paired_device['node']['id']))
        node.node_key='replacement-'+uuid4().hex
        with pytest.raises(DBAPIError,match='node identity is immutable'):
            await db.commit()
        await db.rollback()
        grant=await db.get(HarnessDeviceGrant,UUID(paired_device['grant_id']))
        grant.status,grant.revoked_at='REVOKED',datetime.now(UTC)
        await db.commit()
        grant.status='ACTIVE'
        with pytest.raises(DBAPIError,match='terminal device grant cannot reactivate'):
            await db.commit()
        await db.rollback()
        grant=await db.get(HarnessDeviceGrant,UUID(paired_device['grant_id']))
        await db.delete(grant)
        with pytest.raises(DBAPIError,match='history cannot be deleted'):
            await db.commit()
        await db.rollback()


@pytest.fixture
async def websocket_server():
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
    config=uvicorn.Config(app,log_level='error',lifespan='off')
    server=uvicorn.Server(config)
    task=asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(.01)
    try:
        yield f'ws://127.0.0.1:{port}/api/v1/harness-connectors/ws'
    finally:
        server.should_exit=True
        await task
        sock.close()


async def ws_hello(url,device):
    ws=await connect(url,additional_headers={'Authorization':'Bearer '+device['device_token']})
    await ws.send(__import__('json').dumps({'type':'hello','node_id':device['node']['id'],'transport':TRANSPORT,
        'protocol':PROTOCOL,'profile':PROFILE,'capabilities':{
            'transport':'hypertest.harness-bridge/v1alpha1','protocol':PROTOCOL,'profile':PROFILE,
            'host_id':device['node']['node_key'],'provider':'fixture','native_shell':False,
            'native_filesystem':False,'persistent_session':True,'management_recovery':True,
            'domain_tools':[],'max_concurrent':2}}))
    ack=__import__('json').loads(await ws.recv())
    assert ack['type']=='hello_ack'
    return ws


async def test_real_websocket_consumes_durable_request_before_delivery_and_never_replays(paired_device,websocket_server):
    import json
    from uuid import UUID
    ws=await ws_hello(websocket_server,paired_device)
    client=RemoteBridgeClient(paired_device['node']['id'],timeout=2)
    response_task=asyncio.create_task(client.capabilities())
    message=json.loads(await ws.recv())
    assert message['operation']=='capabilities' and message['authority']=='management'
    request_id=UUID(message['request_id'])
    async with AsyncSessionLocal() as db:
        # A separate session/process sees SENT before any local side effect.
        persisted=await db.get(ConnectorRequest,request_id)
        assert persisted.status=='SENT'
        assert persisted.payload=={} and persisted.sent_at is not None
        generation=persisted.connection_generation
    await ws.close()
    with pytest.raises(BridgeError) as uncertain:
        await response_task
    assert uncertain.value.code=='OUTCOME_UNKNOWN'
    reconnected=await ws_hello(websocket_server,paired_device)
    async with AsyncSessionLocal() as db:
        persisted=await db.get(ConnectorRequest,request_id)
        assert persisted.status=='UNKNOWN' and persisted.connection_generation==generation
        persisted.status='QUEUED'
        with pytest.raises(DBAPIError,match='terminal connector request cannot replay'):
            await db.commit()
        await db.rollback()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(reconnected.recv(),.15)
    next_request=asyncio.create_task(client.capabilities())
    next_message=json.loads(await reconnected.recv())
    assert next_message['request_id']!=message['request_id']
    await reconnected.send(json.dumps({'type':'response','request_id':next_message['request_id'],'ok':True,
        'result':{'transport':'hypertest.harness-bridge/v1alpha1','persistent_session':True,
                  'protocol':PROTOCOL,'profile':PROFILE,'host_id':paired_device['node']['node_key'],
                  'provider':'fixture','domain_tools':[],'management_recovery':True,
                  'native_shell':False,'native_filesystem':False,'max_concurrent':2}}))
    assert (await next_request)['persistent_session'] is True
    await reconnected.close()


async def test_connector_mailbox_forbids_untyped_shell_even_through_direct_sql(paired_device):
    from uuid import UUID
    async with AsyncSessionLocal() as db:
        db.add(ConnectorRequest(node_id=UUID(paired_device['node']['id']),operation='shell',authority='management',
            payload={'command':'echo ignored'},input_sha256=digest({'command':'echo ignored'}),
            expires_at=datetime.now(UTC)+timedelta(seconds=20)))
        with pytest.raises(DBAPIError,match='invalid typed connector request'):
            await db.commit()
        await db.rollback()
        assert await db.scalar(text('SELECT 1'))==1


@pytest.fixture
async def scoped_binding(paired_device):
    """Relational fixtures verify DB scope, without claiming source-content acceptance."""
    from uuid import UUID

    from test_run_bindings import own_job

    from hypertest.api.schemas import (
        PolicySnapshotCreate,
        ProjectCreate,
        SourceSnapshotCreate,
        TestRunCreate,
    )
    from hypertest.application.bindings import create_run_binding
    from hypertest.application.jobs import submit_job
    from hypertest.application.services import (
        create_policy_snapshot,
        create_project,
        create_source_snapshot,
        create_test_run,
    )
    from hypertest.common.ids import uuid7
    from hypertest.domain.connector import NodeProjectCapability, RunHarnessPlacement
    from hypertest.domain.harness_selection import RunHarnessSelection
    from hypertest.domain.jobs import ACTIVE_JOB_STATUSES, DurableJob, JobStatus, JobType
    from hypertest.domain.source_transfer import SourceAcquisitionRequest, SourceBundleTransfer
    node_id=UUID(paired_device['node']['id'])
    commit=uuid4().hex+'a'*8
    async with AsyncSessionLocal() as db:
        node=await db.get(HarnessNode,node_id)
        node.presence,node.last_seen_at,node.connection_generation='ONLINE',datetime.now(UTC),1
        await db.commit()
        project=await create_project(db,ProjectCreate(key='CONNECTOR_'+uuid4().hex[:12].upper(),name='Connector scope fixture'))
        source=await create_source_snapshot(db,project.id,SourceSnapshotCreate(repository_url='https://example.invalid/scope.git',
            commit_sha=commit,prd_sha256='a'*64,configuration_sha256='b'*64))
        policy=await create_policy_snapshot(db,PolicySnapshotCreate(project_id=project.id,policy_version='connector-v1',content_sha256=digest({})))
        run=await create_test_run(db,TestRunCreate(project_id=project.id,source_snapshot_id=source.id,policy_snapshot_id=policy.id))
        harness=NodeProjectCapability(node_id=node_id,project_id=project.id,capability='harness',constraints={},operator_identity_id='local-operator')
        acquisition=NodeProjectCapability(node_id=node_id,project_id=project.id,capability='source_acquisition',
            constraints={'allowed_origins':[source.repository_url]},operator_identity_id='local-operator')
        db.add_all([harness,acquisition])
        await db.flush()
        request=SourceAcquisitionRequest(id=uuid7(),project_id=project.id,node_id=node_id,origin=source.repository_url,
            commit_sha=commit,ref=None,policy_version='operator-v1')
        db.add(request)
        await db.flush()
        transfer=SourceBundleTransfer(project_id=project.id,request_id=request.id,node_id=node_id,
            source_capability_id=acquisition.id,idempotency_key=str(uuid7()),origin=source.repository_url,
            commit_sha=commit,ref=None,policy_version='operator-v1',expires_at=datetime.now(UTC)+timedelta(minutes=5))
        db.add(transfer)
        await db.flush()
        transfer.status='VERIFYING'
        await db.flush()
        transfer.status,transfer.root_tree,transfer.object_format='ACCEPTED','d'*40,'sha1'
        transfer.bundle_sha256,transfer.bundle_size='e'*64,1
        transfer.manifest,transfer.acquisition_receipt={},{}
        transfer.bundle_path,transfer.server_workspace='/fixture/bundle','/fixture/workspace'
        transfer.accepted_at=datetime.now(UTC)
        await db.flush()
        db.add(RunHarnessSelection(test_run_id=run.id,mode='LOCAL_CONNECTOR',node_id=node_id,source_bundle_transfer_id=transfer.id))
        await db.commit()
        job=await submit_job(db,run.id,JobType.ADVANCE_RUN,payload={'workspace':'.','execution_profile':PROFILE},idempotency_key='connector-binding')
        token=await own_job(db,job)
        binding=await create_run_binding(db,run.id,job_id=job.id,lease_token=token,logical_worker_id=uuid7(),
            harness_host_id=paired_device['node']['node_key'],workspace_id=uuid7().hex)
        placement=RunHarnessPlacement(test_run_id=run.id,binding_id=binding.id,node_id=node_id,mode='LOCAL_CONNECTOR',
            source_transfer_kind='SOURCE_BUNDLE',source_bundle_transfer_id=transfer.id)
        db.add(placement)
        await db.commit()
        from hypertest.harness_bridge.protocol import ExecutionContext
        context=ExecutionContext(run_id=str(run.id),binding_id=str(binding.id),logical_worker_id=str(binding.logical_worker_id),
            session_id=str(binding.primary_agent_session_id),workspace_id=binding.workspace_id,harness_host_id=binding.harness_host_id,
            job_id=str(job.id),claim_token=str(token),binding_epoch=1,expires_at=time.time()+30)
        value={'node_id':node_id,'project_id':project.id,'binding_id':binding.id,'placement_id':placement.id,
            'capability_id':harness.id,'device_grant_id':UUID(paired_device['grant_id']),
            'job_id':job.id,'run_id':run.id,'transfer_id':transfer.id,'context':context}
    try:
        yield value
    finally:
        async with AsyncSessionLocal() as db:
            job=await db.get(DurableJob,value['job_id'])
            if job.status in ACTIVE_JOB_STATUSES:
                job.status,job.finished_at,job.lease_expires_at=JobStatus.FAILED,datetime.now(UTC),None
                await db.commit()


async def test_dispatch_grant_hides_original_secret_and_fences_stale_claim(scoped_binding):
    from dataclasses import replace

    from hypertest.domain.connector import HarnessDispatchGrant
    bound=scoped_binding
    client=RemoteBridgeClient(bound['node_id'],timeout=2)
    response=asyncio.create_task(client.create_session(bound['context']))
    row=None
    for _ in range(50):
        async with AsyncSessionLocal() as db:
            row=await db.scalar(select(ConnectorRequest).where(ConnectorRequest.node_id==bound['node_id'],ConnectorRequest.operation=='create_session'))
            if row:
                grant=await db.get(HarnessDispatchGrant,row.dispatch_grant_id)
                assert grant.binding_id==bound['binding_id'] and grant.binding_epoch==1
                assert grant.claim_identity==row.payload['context']['claim_token']
                assert bound['context'].claim_token not in str(row.payload)
                row.status,row.sent_at,row.connection_generation='SENT',datetime.now(UTC),1
                await db.commit()
                row.status,row.result,row.finished_at='SUCCEEDED',{'session_id':bound['context'].session_id},datetime.now(UTC)
                await db.commit()
                break
        await asyncio.sleep(.02)
    assert row is not None
    assert (await response)['session_id']==bound['context'].session_id
    for changed in [replace(bound['context'],binding_epoch=2),replace(bound['context'],claim_token=str(uuid4()))]:
        with pytest.raises(BridgeError,match='STALE_CLAIM'):
            await client.create_session(changed)


async def test_database_rejects_forged_dispatch_even_with_valid_relational_ids(scoped_binding):
    from hypertest.connector.protocol import claim_identity
    from hypertest.domain.connector import HarnessDispatchGrant
    bound=scoped_binding
    ctx=bound['context']
    for override in [{'binding_epoch':2},{'claim_identity':'f'*64},{'expires_at':datetime.now(UTC)+timedelta(hours=1)}]:
        async with AsyncSessionLocal() as db:
            values={'node_id':bound['node_id'],'project_id':bound['project_id'],'placement_id':bound['placement_id'],
                'binding_id':bound['binding_id'],'session_id':__import__('uuid').UUID(ctx.session_id),
                'job_id':bound['job_id'],'device_grant_id':bound['device_grant_id'],'capability_id':bound['capability_id'],
                'workspace_id':ctx.workspace_id,'claim_identity':claim_identity(str(bound['node_id']),ctx.claim_token),
                'binding_epoch':1,'call_id':'fixture-call','operation':'execute',
                'not_before':datetime.now(UTC),'expires_at':datetime.now(UTC)+timedelta(seconds=20),**override}
            db.add(HarnessDispatchGrant(**values))
            with pytest.raises(DBAPIError,match='current binding claim'):
                await db.commit()
            await db.rollback()


async def test_database_freezes_placement_and_rejects_unaccepted_selection(scoped_binding):
    from hypertest.domain.connector import RunHarnessPlacement
    from hypertest.domain.harness_selection import RunHarnessSelection
    bound=scoped_binding
    async with AsyncSessionLocal() as db:
        placement=await db.get(RunHarnessPlacement,bound['placement_id'])
        placement.source_transfer_kind='SERVER_WORKSPACE'
        with pytest.raises(DBAPIError,match='placement is immutable'):
            await db.commit()
        await db.rollback()
        # Removing a retained admission choice is never a way to choose a new node.
        selected=await db.get(RunHarnessSelection,bound['run_id'])
        await db.delete(selected)
        with pytest.raises(DBAPIError,match='admission selection is immutable'):
            await db.commit()
        await db.rollback()


async def test_workspace_install_requires_current_execution_and_readonly_management(scoped_binding):
    bound=scoped_binding
    from dataclasses import replace

    from hypertest.domain.connector import HarnessDispatchGrant
    from hypertest.domain.source_transfer import SourceBundleTransfer
    async with AsyncSessionLocal() as db:
        transfer=await db.get(SourceBundleTransfer,bound['transfer_id'])
        payload={'project_id':str(bound['project_id']),'node_id':str(bound['node_id']),
            'transfer_id':str(transfer.id),'workspace_id':bound['context'].workspace_id,'run_id':str(bound['run_id']),
            'origin':transfer.origin,'commit_sha':transfer.commit_sha,'bundle_sha256':transfer.bundle_sha256,
            'root_tree':transfer.root_tree,'create':True,'context':bound['context'].to_dict()}
    client=RemoteBridgeClient(bound['node_id'],timeout=2)
    with pytest.raises(BridgeError,match='WORKSPACE_SCOPE_REJECTED'):
        await client.request('install_workspace',payload,management=True)
    bad={**payload,'context':replace(bound['context'],claim_token=str(uuid4())).to_dict()}
    with pytest.raises(BridgeError,match='STALE_CLAIM'):
        await client.request('install_workspace',bad)
    response=asyncio.create_task(client.request('install_workspace',payload))
    row=None
    for _ in range(50):
        async with AsyncSessionLocal() as db:
            row=await db.scalar(select(ConnectorRequest).where(ConnectorRequest.node_id==bound['node_id'],
                ConnectorRequest.operation=='install_workspace'))
            if row:
                assert row.authority=='execution' and row.dispatch_grant_id
                grant=await db.get(HarnessDispatchGrant,row.dispatch_grant_id)
                assert grant.operation=='install_workspace'
                assert bound['context'].claim_token not in str(row.payload)
                row.status,row.sent_at='SENT',datetime.now(UTC)
                await db.commit()
                row.status,row.result,row.finished_at='SUCCEEDED',{'workspace_id':payload['workspace_id'],'installed':True},datetime.now(UTC)
                await db.commit()
                break
        await asyncio.sleep(.02)
    assert row is not None and (await response)['installed'] is True
    # Read-only verification is separate from creating a local workspace.
    with pytest.raises(BridgeError,match='WORKSPACE_SCOPE_REJECTED'):
        await client.request('install_workspace',{**payload,'create':False})


async def test_database_rejects_pending_source_or_revoked_acquisition_role(scoped_binding):
    from hypertest.api.schemas import TestRunCreate
    from hypertest.application.services import create_test_run
    from hypertest.domain.connector import NodeProjectCapability
    from hypertest.domain.harness_selection import RunHarnessSelection
    from hypertest.domain.models import TestRun
    from hypertest.domain.source_transfer import SourceBundleTransfer
    bound=scoped_binding
    async with AsyncSessionLocal() as db:
        original=await db.get(TestRun,bound['run_id'])
        run=await create_test_run(db,TestRunCreate(project_id=original.project_id,
            source_snapshot_id=original.source_snapshot_id,policy_snapshot_id=original.policy_snapshot_id))
        run_id=run.id
        accepted=await db.get(SourceBundleTransfer,bound['transfer_id'])
        capability_id=accepted.source_capability_id
        pending=SourceBundleTransfer(project_id=accepted.project_id,request_id=accepted.request_id,node_id=accepted.node_id,
            source_capability_id=capability_id,idempotency_key=str(uuid4()),origin=accepted.origin,
            commit_sha=accepted.commit_sha,ref=accepted.ref,policy_version=accepted.policy_version,
            expires_at=datetime.now(UTC)+timedelta(minutes=5))
        db.add(pending)
        await db.commit()
        pending_id=pending.id
        db.add(RunHarnessSelection(test_run_id=run_id,mode='LOCAL_CONNECTOR',node_id=bound['node_id'],source_bundle_transfer_id=pending_id))
        with pytest.raises(DBAPIError,match='accepted same-project source'):
            await db.commit()
        await db.rollback()
        source_capability=await db.get(NodeProjectCapability,capability_id)
        source_capability.status,source_capability.revoked_at='REVOKED',datetime.now(UTC)
        await db.commit()
        db.add(RunHarnessSelection(test_run_id=run_id,mode='LOCAL_CONNECTOR',node_id=bound['node_id'],source_bundle_transfer_id=bound['transfer_id']))
        with pytest.raises(DBAPIError,match='accepted same-project source'):
            await db.commit()
        await db.rollback()


async def test_platform_worker_claims_original_local_placement_after_recovery(scoped_binding,monkeypatch):
    from uuid import uuid4

    from hypertest.application.bindings import activate_run_binding
    from hypertest.application.jobs import claim_job, submit_job
    from hypertest.domain.jobs import DurableJob, JobStatus, JobType
    bound=scoped_binding
    monkeypatch.setattr(get_settings(),'bridge_host_id','a-different-server-host')
    async with AsyncSessionLocal() as db:
        old=await db.get(DurableJob,bound['job_id'])
        await activate_run_binding(db,bound['binding_id'],1,job_id=old.id,lease_token=old.lease_token,
            provider_session_id=str(uuid4()))
        old.status,old.finished_at,old.lease_expires_at=JobStatus.FAILED,datetime.now(UTC),None
        await db.commit()
        retry=await submit_job(db,bound['run_id'],JobType.ADVANCE_RUN,
            payload={'execution_profile':PROFILE,'workspace':'.'},idempotency_key='claim-local-resume')
        retry_id=retry.id
    try:
        async with AsyncSessionLocal() as db:
            claimed=await claim_job(db,'platform-local-recovery-worker')
            assert claimed is not None and claimed.id==retry_id
            assert claimed.test_run_id==bound['run_id'] and claimed.status==JobStatus.RUNNING
    finally:
        async with AsyncSessionLocal() as db:
            retry=await db.get(DurableJob,retry_id)
            retry.status,retry.finished_at,retry.lease_expires_at=JobStatus.FAILED,datetime.now(UTC),None
            await db.commit()


async def test_local_claim_support_preserves_foreign_server_host_fencing(server_bound_run,monkeypatch):
    from hypertest.application.jobs import claim_job, submit_job
    from hypertest.domain.jobs import DurableJob, JobStatus, JobType
    bound=server_bound_run
    monkeypatch.setattr(get_settings(),'bridge_host_id','a-different-server-host')
    async with AsyncSessionLocal() as db:
        old=await db.get(DurableJob,bound['job_id'])
        old.status,old.finished_at,old.lease_expires_at=JobStatus.FAILED,datetime.now(UTC),None
        await db.commit()
        queued=await submit_job(db,bound['run_id'],JobType.ADVANCE_RUN,
            payload={'execution_profile':PROFILE,'workspace':'.'},idempotency_key='foreign-server-fence')
        queued_id=queued.id
    try:
        async with AsyncSessionLocal() as db:
            assert await claim_job(db,'other-platform-host') is None
            queued=await db.get(DurableJob,queued_id)
            assert queued.status==JobStatus.QUEUED and queued.lease_token is None
    finally:
        async with AsyncSessionLocal() as db:
            queued=await db.get(DurableJob,queued_id)
            queued.status,queued.finished_at=JobStatus.CANCELLED,datetime.now(UTC)
            queued.cancel_requested_at=queued.finished_at
            await db.commit()


async def test_expired_sent_orphans_release_mailbox_capacity_without_replay(paired_device):
    from uuid import UUID

    from hypertest.connector.protocol import MAX_QUEUE
    now=datetime.now(UTC)
    node_id=UUID(paired_device['node']['id'])
    async with AsyncSessionLocal() as db:
        orphans=[ConnectorRequest(node_id=node_id,operation='capabilities',authority='management',payload={},
            input_sha256=digest({}),created_at=now-timedelta(seconds=30),expires_at=now-timedelta(seconds=10))
            for _ in range(MAX_QUEUE)]
        db.add_all(orphans)
        await db.flush()
        for row in orphans:
            row.status,row.sent_at,row.connection_generation='SENT',now-timedelta(seconds=29),0
        await db.commit()
        orphan_ids={row.id for row in orphans}
    client=RemoteBridgeClient(node_id,timeout=2)
    task=asyncio.create_task(client.capabilities())
    new_id=None
    try:
        for _ in range(50):
            async with AsyncSessionLocal() as db:
                row=await db.scalar(select(ConnectorRequest).where(ConnectorRequest.node_id==node_id,
                    ConnectorRequest.status=='QUEUED'))
                if row:
                    new_id=row.id
                    assert new_id not in orphan_ids
                    assert all(item.status=='UNKNOWN' and item.error_code=='DELIVERY_EXPIRED' for item in
                        (await db.scalars(select(ConnectorRequest).where(ConnectorRequest.id.in_(orphan_ids)))).all())
                    row.status,row.sent_at,row.connection_generation='SENT',datetime.now(UTC),0
                    await db.commit()
                    row.status,row.result,row.finished_at='SUCCEEDED',{'fresh_query':True},datetime.now(UTC)
                    await db.commit()
                    break
            await asyncio.sleep(.02)
        assert new_id is not None and (await task)=={'fresh_query':True}
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)


@pytest.mark.parametrize('delivered',[False,True])
async def test_new_connection_fences_unexpired_old_generation_intent(scoped_binding,paired_device,websocket_server,delivered):
    bound=scoped_binding
    client=RemoteBridgeClient(bound['node_id'],timeout=10)
    task=asyncio.create_task(client.create_session(bound['context']))
    original_id=None
    for _ in range(50):
        async with AsyncSessionLocal() as db:
            row=await db.scalar(select(ConnectorRequest).where(ConnectorRequest.node_id==bound['node_id'],
                ConnectorRequest.operation=='create_session'))
            if row:
                original_id=row.id
                assert row.connection_generation==1
                if delivered:
                    row.status,row.sent_at='SENT',datetime.now(UTC)
                    await db.commit()
                break
        await asyncio.sleep(.02)
    assert original_id is not None
    # The originating caller/API disappears before its timeout/finally cleanup.
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    reconnected=await ws_hello(websocket_server,paired_device)
    try:
        async with AsyncSessionLocal() as db:
            row=await db.get(ConnectorRequest,original_id)
            assert row.status=='UNKNOWN' and row.error_code=='CONNECTION_REPLACED'
            assert row.connection_generation==1
            node=await db.get(HarnessNode,bound['node_id'])
            assert node.connection_generation==2
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(reconnected.recv(),.15)
    finally:
        await reconnected.close()
