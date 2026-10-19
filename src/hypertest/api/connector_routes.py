"""Device pairing is explicitly operator-authorized; WSS is device-authenticated."""
from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.connector_schemas import CapabilityRequest, PairNodeRequest, RotateNodeRequest
from hypertest.config import get_settings
from hypertest.connector.mailbox import expire_requests
from hypertest.connector.protocol import ERROR_CODE, MAX_MESSAGE, TRANSPORT
from hypertest.connector.results import capabilities as normalize_capabilities
from hypertest.connector.results import normalize_result
from hypertest.connector.security import (
    authenticate_device,
    require_capability,
    require_operator,
    token_hash,
    validate_issue_request,
    validate_workspace_request,
)
from hypertest.db.session import AsyncSessionLocal, get_db
from hypertest.domain.connector import (
    ConnectorRequest,
    HarnessDeviceGrant,
    HarnessDispatchGrant,
    HarnessNode,
    NodeProjectCapability,
)
from hypertest.domain.models import AuditEvent, OutboxEvent, Project
from hypertest.harness_bridge.protocol import PROFILE, PROTOCOL, BridgeError, canonical

router = APIRouter()


def node_read(node: HarnessNode) -> dict:
    # Presence is an observation with a bounded freshness window, never authority.
    online = node.presence == 'ONLINE' and node.last_seen_at and datetime.now(UTC) - node.last_seen_at < timedelta(seconds=15)
    return {'id':str(node.id),'node_key':node.node_key,'owner_identity_id':node.owner_identity_id,
            'node_kind':node.node_kind,'display_name':node.display_name,'registration_status':node.registration_status,
            'presence':'ONLINE' if online else 'OFFLINE' if node.last_seen_at else 'UNKNOWN',
            'last_seen_at':node.last_seen_at,'connection_generation':node.connection_generation,
            'capabilities':node.capabilities}


def audit(db, node, action, *, project_id=None, metadata=None):
    # Pairing has no Project yet; operational outbox supplies the durable history.
    db.add(OutboxEvent(aggregate_type='HarnessNode',aggregate_id=node.id,event_type=action,
                       payload={'node_id':str(node.id),'owner_identity_id':node.owner_identity_id,**(metadata or {})}))
    if project_id:
        db.add(AuditEvent(project_id=project_id,actor_type='OPERATOR',actor_ref=node.owner_identity_id,
            action=action,entity_type='HarnessNode',entity_id=node.id,event_metadata=metadata or {}))


async def issue_device_grant(db, node, days: int, operator: str) -> tuple[HarnessDeviceGrant,str]:
    now = await db.scalar(select(func.clock_timestamp()))
    token = secrets.token_urlsafe(48)
    grant = HarnessDeviceGrant(node_id=node.id,token_hash=token_hash(token),key_version=secrets.token_hex(16),
        operator_identity_id=operator,not_before=now,expires_at=now+timedelta(days=days))
    db.add(grant)
    await db.flush()
    audit(db,node,'harness.device_grant.created',metadata={'grant_id':str(grant.id),'expires_at':grant.expires_at.isoformat()})
    return grant,token


@router.get('/harness-nodes', dependencies=[Depends(require_operator)])
async def list_nodes(db: AsyncSession = Depends(get_db)):
    return [node_read(node) for node in (await db.scalars(select(HarnessNode).order_by(HarnessNode.created_at))).all()]


@router.post('/harness-nodes/pair',status_code=201)
async def pair_node(payload: PairNodeRequest,operator: str = Depends(require_operator),db: AsyncSession = Depends(get_db)):
    if await db.scalar(select(HarnessNode.id).where(HarnessNode.node_key == payload.node_key)):
        raise HTTPException(409,'Stable node key already exists; rotate the existing device grant')
    node=HarnessNode(node_key=payload.node_key,display_name=payload.display_name,owner_identity_id=operator)
    db.add(node)
    await db.flush()
    grant,token=await issue_device_grant(db,node,payload.expires_in_days,operator)
    await db.commit()
    return {'node':node_read(node),'grant_id':str(grant.id),'device_token':token,'expires_at':grant.expires_at}


@router.post('/harness-nodes/{node_id}/rotate')
async def rotate_node(node_id: UUID,payload: RotateNodeRequest,operator: str = Depends(require_operator),db: AsyncSession = Depends(get_db)):
    node=await db.get(HarnessNode,node_id,with_for_update=True)
    if node is None or node.registration_status != 'ACTIVE':
        raise HTTPException(409,'Active device required')
    await revoke_grants(db,node_id)
    grant,token=await issue_device_grant(db,node,payload.expires_in_days,operator)
    await db.commit()
    return {'node':node_read(node),'grant_id':str(grant.id),'device_token':token,'expires_at':grant.expires_at}


async def revoke_grants(db,node_id):
    now=datetime.now(UTC)
    for row in (await db.scalars(select(HarnessDeviceGrant).where(HarnessDeviceGrant.node_id==node_id,HarnessDeviceGrant.status=='ACTIVE'))).all():
        row.status,row.revoked_at,row.row_version='REVOKED',now,row.row_version+1
    for row in (await db.scalars(select(HarnessDispatchGrant).where(HarnessDispatchGrant.node_id==node_id,HarnessDispatchGrant.status=='ACTIVE'))).all():
        row.status,row.row_version='REVOKED',row.row_version+1
    for row in (await db.scalars(select(ConnectorRequest).where(ConnectorRequest.node_id==node_id,ConnectorRequest.authority!='management',ConnectorRequest.status.in_(['QUEUED','SENT'])))).all():
        row.status,row.error_code,row.finished_at='UNKNOWN','DEVICE_AUTHORIZATION_REVOKED',now


@router.post('/harness-nodes/{node_id}/revoke')
async def revoke_node(node_id: UUID,operator: str = Depends(require_operator),db: AsyncSession = Depends(get_db)):
    node=await db.get(HarnessNode,node_id,with_for_update=True)
    if not node:
        raise HTTPException(404,'Node not found')
    if node.registration_status!='REVOKED':
        node.registration_status,node.row_version='REVOKED',node.row_version+1
        await revoke_grants(db,node_id)
        audit(db,node,'harness.node.revoked')
        await db.commit()
    return node_read(node)


@router.get('/harness-nodes/{node_id}/capabilities', dependencies=[Depends(require_operator)])
async def node_capabilities(node_id: UUID,db: AsyncSession = Depends(get_db)):
    scopes=(await db.scalars(select(NodeProjectCapability).where(NodeProjectCapability.node_id==node_id))).all()
    return [{'id':str(s.id),'project_id':str(s.project_id),'capability':s.capability,'constraints':s.constraints,
             'status':s.status,'policy_version':s.policy_version} for s in scopes]


@router.post('/harness-nodes/{node_id}/capabilities',status_code=201)
async def grant_capability(node_id: UUID,payload: CapabilityRequest,operator: str = Depends(require_operator),db: AsyncSession = Depends(get_db)):
    node=await db.get(HarnessNode,node_id)
    if node is None or node.registration_status!='ACTIVE' or not await db.get(Project,payload.project_id):
        raise HTTPException(409,'Active node and existing Project required')
    if len(canonical(payload.constraints)) > 32768:
        raise HTTPException(422,'Capability constraints too large')
    previous=await db.scalar(select(NodeProjectCapability).where(NodeProjectCapability.node_id==node_id,
        NodeProjectCapability.project_id==payload.project_id,NodeProjectCapability.capability==payload.capability,
        NodeProjectCapability.status=='ACTIVE'))
    if previous:
        raise HTTPException(409,'Revoke the existing capability before changing scope')
    scope=NodeProjectCapability(node_id=node_id,project_id=payload.project_id,capability=payload.capability,
        constraints=payload.constraints,policy_version=payload.policy_version,operator_identity_id=operator)
    db.add(scope)
    await db.flush()
    audit(db,node,'harness.capability.granted',project_id=payload.project_id,metadata={'capability_id':str(scope.id),'capability':scope.capability})
    await db.commit()
    return {'id':str(scope.id),'status':scope.status}


@router.post('/harness-nodes/{node_id}/capabilities/{capability_id}/revoke')
async def revoke_capability(node_id: UUID,capability_id: UUID,operator: str = Depends(require_operator),db: AsyncSession = Depends(get_db)):
    scope=await db.get(NodeProjectCapability,capability_id,with_for_update=True)
    if not scope or scope.node_id!=node_id:
        raise HTTPException(404,'Capability not found')
    if scope.status=='ACTIVE':
        scope.status,scope.revoked_at,scope.row_version='REVOKED',datetime.now(UTC),scope.row_version+1
        for grant in (await db.scalars(select(HarnessDispatchGrant).where(HarnessDispatchGrant.capability_id==scope.id,HarnessDispatchGrant.status=='ACTIVE'))).all():
            grant.status,grant.row_version='REVOKED',grant.row_version+1
        audit(db,await db.get(HarnessNode,node_id),'harness.capability.revoked',project_id=scope.project_id,metadata={'capability_id':str(scope.id)})
        await db.commit()
    return {'id':str(scope.id),'status':scope.status}


async def delivery_allowed(db,row,node,grant,now) -> bool:
    if row.expires_at <= now:
        return False
    if row.authority!='management' and row.connection_generation!=node.connection_generation:
        return False
    if row.authority=='management':
        # Only the fixed context of this request can reach Bridge management.
        if row.operation=='install_workspace':
            if row.payload.get('create') is not False:
                return False
            await validate_workspace_request(db,node.id,row.payload,create=False)
            return True
        if row.operation=='issue_query':
            await validate_issue_request(db,node.id,row.payload,create=False,now=now)
            return True
        return row.operation in {'capabilities','get_call','restore_session','interrupt','recover','close'}
    if node.registration_status!='ACTIVE' or grant.status!='ACTIVE' or not grant.not_before<=now<grant.expires_at:
        return False
    if row.authority=='integration':
        if row.operation=='issue_create':
            await validate_issue_request(db,node.id,row.payload,create=True,now=now)
        project_id=row.payload.get('project_id') or row.payload.get('hypertest_project_id')
        capability='source_acquisition' if row.operation in {'prepare_source','source_prepare','install_workspace'} else 'issue_executor'
        await require_capability(db,node.id,UUID(project_id),capability)
        return True
    if row.operation=='install_workspace':
        await validate_workspace_request(db,node.id,row.payload,create=True)
    dispatch=await db.get(HarnessDispatchGrant,row.dispatch_grant_id)
    if not dispatch or dispatch.status!='ACTIVE' or dispatch.expires_at<=now or dispatch.device_grant_id!=grant.id:
        return False
    from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
    from hypertest.domain.jobs import DurableJob, JobStatus
    binding=await db.get(RunExecutionBinding,dispatch.binding_id)
    job=await db.get(DurableJob,dispatch.job_id)
    scope=await require_capability(db,node.id,dispatch.project_id,'harness')
    from hypertest.connector.protocol import claim_identity
    return (scope.id==dispatch.capability_id and binding.binding_epoch==dispatch.binding_epoch
        and binding.status in {BindingStatus.ACTIVE,BindingStatus.RESERVED} and job.status==JobStatus.RUNNING
        and job.lease_token and job.lease_expires_at and job.lease_expires_at>now
        and claim_identity(str(node.id),str(job.lease_token))==dispatch.claim_identity)


@router.websocket('/harness-connectors/ws')
async def connector_socket(websocket: WebSocket):
    if websocket.url.scheme!='wss' and not (get_settings().connector_allow_insecure_loopback and websocket.url.hostname in {'127.0.0.1','localhost','::1'}):
        await websocket.close(code=4403)
        return
    token=websocket.headers.get('authorization','').removeprefix('Bearer ')
    try:
        async with AsyncSessionLocal() as db:
            node,grant=await authenticate_device(db,token,allow_revoked=True)
            node_id,grant_id=node.id,grant.id
    except BridgeError:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    generation=None
    receiver=None
    try:
        async with asyncio.timeout(10):
            first=await websocket.receive_json()
        if (len(canonical(first))>MAX_MESSAGE or first.get('type')!='hello'
            or first.get('transport')!=TRANSPORT or first.get('protocol')!=PROTOCOL
            or first.get('profile')!=PROFILE or first.get('node_id')!=str(node_id)
            or not isinstance(first.get('capabilities'),dict) or len(canonical(first['capabilities']))>32768):
            raise BridgeError('CAPABILITY_UNSUPPORTED')
        normalize_capabilities(first['capabilities'])
        async with AsyncSessionLocal() as db:
            node=await db.get(HarnessNode,node_id,with_for_update=True)
            if first['capabilities'].get('host_id')!=node.node_key:
                raise BridgeError('HOST_MISMATCH')
            node.connection_generation+=1
            generation=node.connection_generation
            node.row_version+=1
            node.presence,node.last_seen_at='ONLINE',datetime.now(UTC)
            await expire_requests(db,node_id,now=await db.scalar(select(func.clock_timestamp())),connection_generation=generation)
            node.capabilities=first['capabilities']
            await db.commit()
        await websocket.send_json({'type':'hello_ack','transport':TRANSPORT,'node_id':str(node_id),
            'connection_generation':generation,'heartbeat_seconds':5,'max_message':MAX_MESSAGE})
        receiver=asyncio.create_task(websocket.receive_json())
        last_seen=asyncio.get_running_loop().time()
        notified_revocation=False
        notified_calls=set()
        while True:
            if receiver.done():
                incoming=receiver.result()
                receiver=asyncio.create_task(websocket.receive_json())
                if len(canonical(incoming))>MAX_MESSAGE:
                    raise BridgeError('RESPONSE_TOO_LARGE')
                last_seen=asyncio.get_running_loop().time()
                async with AsyncSessionLocal() as db:
                    node=await db.get(HarnessNode,node_id,with_for_update=True)
                    if node.connection_generation!=generation:
                        raise BridgeError('CONNECTION_REPLACED')
                    node.last_seen_at=datetime.now(UTC)
                    if incoming.get('type')=='response':
                        await accept_response(db,node_id,generation,incoming)
                    await db.commit()
            if asyncio.get_running_loop().time()-last_seen>20:
                raise BridgeError('HEARTBEAT_EXPIRED')
            outgoing=None
            async with AsyncSessionLocal() as db:
                node=await db.get(HarnessNode,node_id)
                grant=await db.get(HarnessDeviceGrant,grant_id)
                now=await db.scalar(select(func.clock_timestamp()))
                if node.connection_generation!=generation:
                    raise BridgeError('CONNECTION_REPLACED')
                await expire_requests(db,node_id,now=now,connection_generation=generation)
                revoked=(node.registration_status!='ACTIVE' or grant.status!='ACTIVE' or grant.expires_at<=now)
                if revoked and not notified_revocation:
                    outgoing={'type':'revoked','reason':'DEVICE_AUTHORIZATION_REVOKED'}
                    notified_revocation=True
                revoked_grants=(await db.scalars(select(HarnessDispatchGrant).where(HarnessDispatchGrant.node_id==node_id,HarnessDispatchGrant.status=='REVOKED'))).all()
                revoked_calls={grant.call_id for grant in revoked_grants}-notified_calls
                if revoked_calls and outgoing is None:
                    outgoing={'type':'grants_revoked','call_ids':sorted(revoked_calls)}
                    notified_calls.update(revoked_calls)
                row=await db.scalar(select(ConnectorRequest).where(ConnectorRequest.node_id==node_id,
                    ConnectorRequest.status=='QUEUED').order_by(ConnectorRequest.created_at).with_for_update(skip_locked=True).limit(1))
                if row:
                    try:
                        allowed=await delivery_allowed(db,row,node,grant,now)
                    except (BridgeError,ValueError,TypeError):
                        allowed=False
                    if not allowed:
                        row.status,row.error_code,row.finished_at='UNKNOWN','AUTHORIZATION_EXPIRED',now
                    elif outgoing is None:
                        # Consume before network I/O. SENT is never resent after reconnect.
                        row.status,row.sent_at,row.connection_generation='SENT',now,generation
                        outgoing={'type':'request','transport':TRANSPORT,'request_id':str(row.id),
                            'node_id':str(node_id),'operation':row.operation,'authority':row.authority,
                            'payload':row.payload,'input_sha256':row.input_sha256,'expires_at':row.expires_at.timestamp(),
                            'create_once':row.operation=='issue_create'}
                await db.commit()
            if outgoing:
                await websocket.send_json(outgoing)
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect,BridgeError,TimeoutError,ValueError,TypeError,KeyError,RuntimeError):
        pass
    finally:
        if receiver:
            receiver.cancel()
            await asyncio.gather(receiver,return_exceptions=True)
        if generation is not None:
            async with AsyncSessionLocal() as db:
                node=await db.get(HarnessNode,node_id,with_for_update=True)
                if node.connection_generation==generation:
                    node.presence,node.row_version='OFFLINE',node.row_version+1
                rows=(await db.scalars(select(ConnectorRequest).where(ConnectorRequest.node_id==node_id,
                    ConnectorRequest.connection_generation==generation,ConnectorRequest.status.in_(['QUEUED','SENT'])))).all()
                for row in rows:
                    row.status,row.error_code,row.finished_at='UNKNOWN','CONNECTION_LOST',datetime.now(UTC)
                await db.commit()
        try:
            await websocket.close()
        except (RuntimeError,WebSocketDisconnect):
            pass


async def accept_response(db,node_id,generation,incoming):
    try:
        row=await db.get(ConnectorRequest,UUID(incoming['request_id']),with_for_update=True)
    except (ValueError,KeyError) as exc:
        raise BridgeError('INVALID_RESPONSE') from exc
    if not row or row.node_id!=node_id or row.connection_generation!=generation:
        raise BridgeError('RESPONSE_SCOPE_REJECTED')
    if row.status in {'SUCCEEDED','FAILED'}:
        return
    now=await db.scalar(select(func.clock_timestamp()))
    # Late integration results require a fresh query of their fixed operation.
    if row.status=='SENT' and row.expires_at<=now:
        row.status,row.error_code,row.finished_at='UNKNOWN','DELIVERY_EXPIRED',now
        return
    if row.status!='SENT':
        return
    node=await db.get(HarnessNode,node_id)
    grant=None
    if row.dispatch_grant_id:
        dispatch=await db.get(HarnessDispatchGrant,row.dispatch_grant_id)
        grant=await db.get(HarnessDeviceGrant,dispatch.device_grant_id)
    else:
        grant=await db.scalar(select(HarnessDeviceGrant).where(HarnessDeviceGrant.node_id==node_id,
            HarnessDeviceGrant.status=='ACTIVE').order_by(HarnessDeviceGrant.created_at.desc()).limit(1))
    try:
        allowed=grant is not None and await delivery_allowed(db,row,node,grant,now)
    except (BridgeError,ValueError,TypeError):
        allowed=False
    if row.authority=='management':
        allowed=True
    if not allowed:
        row.status,row.error_code,row.finished_at='UNKNOWN','STALE_RESPONSE',now
        return
    if incoming.get('ok') is True and isinstance(incoming.get('result'),dict):
        try:
            projected=normalize_result(row.operation,row.payload,incoming['result'],management=row.authority=='management')
            if row.operation=='capabilities' and projected.get('host_id')!=node.node_key:
                raise BridgeError('HOST_MISMATCH')
        except (BridgeError,ValueError,TypeError,KeyError) as exc:
            row.status,row.error_code='FAILED',exc.code if isinstance(exc,BridgeError) else 'INVALID_CONNECTOR_RESULT'
        else:
            row.status,row.result='SUCCEEDED',projected
    else:
        error=incoming.get('error','CONNECTOR_ERROR')
        row.status,row.error_code='FAILED',error if isinstance(error,str) and ERROR_CODE.fullmatch(error) else 'CONNECTOR_ERROR'
    row.finished_at=now
